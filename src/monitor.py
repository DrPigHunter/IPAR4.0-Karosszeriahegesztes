"""MQTT monitor: validate welding events, persist them, and route rejects to rework."""
from __future__ import annotations

import json
import sqlite3
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import paho.mqtt.client as mqtt

from src.rules import evaluate_body, validate_event

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "welding.db"
BROKER_HOST, BROKER_PORT, TOPIC = "127.0.0.1", 1883, "welding/events"

REWORK_WAITING = "UTÓMUNKÁRA VÁR"
REWORK_IN_PROGRESS = "UTÓMUNKA FOLYAMATBAN"
REWORK_DONE = "UTÓMUNKA ELVÉGEZVE – ÚJRAELLENŐRZÉS SZÜKSÉGES"


def connect_db(db_path: str | Path | None = None) -> sqlite3.Connection:
    """Open the application database; accepting a path makes integration tests isolated."""
    target = Path(db_path) if db_path is not None else DB_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(target), timeout=10, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript("""
      CREATE TABLE IF NOT EXISTS bodies (
        body_id TEXT PRIMARY KEY, body_type TEXT NOT NULL, expected_count INTEGER NOT NULL DEFAULT 0,
        expected_ids_json TEXT NOT NULL DEFAULT '[]', status TEXT NOT NULL DEFAULT 'FOLYAMATBAN',
        missing_ids_json TEXT NOT NULL DEFAULT '[]', unexpected_ids_json TEXT NOT NULL DEFAULT '[]',
        duplicate_ids_json TEXT NOT NULL DEFAULT '[]', parameter_errors INTEGER NOT NULL DEFAULT 0,
        event_count INTEGER NOT NULL DEFAULT 0, started_at TEXT NOT NULL, completed_at TEXT,
        latency_ms REAL
      );
      CREATE TABLE IF NOT EXISTS weld_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT, body_id TEXT NOT NULL, weld_id TEXT NOT NULL,
        current_ka REAL, weld_time_ms REAL, electrode_force_kn REAL, timestamp TEXT NOT NULL,
        received_at REAL NOT NULL, errors_json TEXT NOT NULL, duplicate INTEGER NOT NULL DEFAULT 0,
        raw_json TEXT NOT NULL
      );
      CREATE INDEX IF NOT EXISTS idx_weld_events_body ON weld_events(body_id, id);
      CREATE TABLE IF NOT EXISTS rework_queue (
        body_id TEXT PRIMARY KEY, reason TEXT NOT NULL, status TEXT NOT NULL,
        created_at TEXT NOT NULL, updated_at TEXT NOT NULL, resolved_at TEXT, resolution_note TEXT
      );
      CREATE TABLE IF NOT EXISTS rework_actions (
        id INTEGER PRIMARY KEY AUTOINCREMENT, body_id TEXT NOT NULL,
        action TEXT NOT NULL, note TEXT NOT NULL DEFAULT '', timestamp TEXT NOT NULL
      );
      CREATE TABLE IF NOT EXISTS system_errors (
        id INTEGER PRIMARY KEY AUTOINCREMENT, category TEXT NOT NULL,
        detail TEXT NOT NULL, raw_payload TEXT NOT NULL DEFAULT '', received_at TEXT NOT NULL
      );
    """)
    # Forward-compatible migration for databases created by earlier project versions.
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(bodies)").fetchall()}
    if "unexpected_ids_json" not in columns:
        conn.execute("ALTER TABLE bodies ADD COLUMN unexpected_ids_json TEXT NOT NULL DEFAULT '[]'")
    conn.commit()
    return conn


def log_processing_error(
    conn: sqlite3.Connection, category: str, detail: str, raw_payload: str = ""
) -> None:
    """Keep malformed and unsupported messages visible instead of silently dropping them."""
    conn.execute(
        "INSERT INTO system_errors(category,detail,raw_payload,received_at) VALUES(?,?,?,?)",
        (category, detail[:2000], raw_payload[:10000], datetime.now().astimezone().isoformat()),
    )
    conn.commit()


def _ensure_body(conn: sqlite3.Connection, body_id: str, body_type: str, timestamp: str) -> None:
    conn.execute(
        """INSERT OR IGNORE INTO bodies(body_id,body_type,expected_count,expected_ids_json,started_at)
           VALUES(?,?,0,'[]',?)""",
        (body_id, body_type, timestamp),
    )


def process_event(
    conn: sqlite3.Connection, event: dict[str, Any], received_at: float | None = None
) -> None:
    """Process a decoded MQTT message. Duplicate deliveries remain visible and make the body fail."""
    received_at = time.time() if received_at is None else received_at
    if not isinstance(event, dict):
        log_processing_error(conn, "ÉRVÉNYTELEN ÜZENET", "Az MQTT-üzenet gyökéreleme nem objektum.")
        return

    body_id = event.get("body_id")
    event_type = event.get("event_type")
    timestamp = str(event.get("timestamp") or datetime.now().astimezone().isoformat())
    if not isinstance(body_id, str) or not body_id.strip():
        log_processing_error(conn, "HIÁNYZÓ AZONOSÍTÓ", "Az esemény nem tartalmaz érvényes body_id mezőt.", json.dumps(event, ensure_ascii=False))
        return

    if event_type == "body_start":
        body_type = str(event.get("body_type", "Ismeretlen"))
        expected_ids = event.get("expected_weld_ids", [])
        if not isinstance(expected_ids, list) or not all(isinstance(item, str) for item in expected_ids):
            log_processing_error(conn, "ÉRVÉNYTELEN INDÍTÁS", "Az expected_weld_ids mezőnek szöveges azonosítók listájának kell lennie.", json.dumps(event, ensure_ascii=False))
            return
        _ensure_body(conn, body_id, body_type, timestamp)
        conn.execute(
            """UPDATE bodies SET body_type=?,expected_count=?,expected_ids_json=?
               WHERE body_id=? AND status='FOLYAMATBAN'""",
            (body_type, len(expected_ids), json.dumps(expected_ids, ensure_ascii=False), body_id),
        )
        conn.commit()
        return

    if event_type == "weld_result":
        weld_id = event.get("weld_id")
        if not isinstance(weld_id, str) or not weld_id.strip():
            log_processing_error(conn, "HIÁNYZÓ HEGESZTÉSI PONT", "A weld_result eseményből hiányzik a weld_id.", json.dumps(event, ensure_ascii=False))
            return
        body_type = str(event.get("body_type", "Ismeretlen"))
        errors = validate_event(event)
        _ensure_body(conn, body_id, body_type, timestamp)
        exists = conn.execute(
            "SELECT 1 FROM weld_events WHERE body_id=? AND weld_id=? LIMIT 1",
            (body_id, weld_id),
        ).fetchone()
        duplicate = exists is not None
        if duplicate:
            errors = [*errors, "Duplikált üzenet: ez a hegesztési pont korábban már beérkezett."]
        conn.execute(
            """INSERT INTO weld_events(body_id,weld_id,current_ka,weld_time_ms,electrode_force_kn,
               timestamp,received_at,errors_json,duplicate,raw_json) VALUES(?,?,?,?,?,?,?,?,?,?)""",
            (body_id, weld_id, event.get("current_ka"), event.get("weld_time_ms"),
             event.get("electrode_force_kn"), timestamp, received_at,
             json.dumps(errors, ensure_ascii=False), int(duplicate), json.dumps(event, ensure_ascii=False)),
        )
        conn.execute(
            "UPDATE bodies SET event_count=event_count+1,parameter_errors=parameter_errors+? WHERE body_id=?",
            (len([e for e in errors if not e.startswith("Duplikált üzenet:")]), body_id),
        )
        conn.commit()
        return

    if event_type == "body_complete":
        expected_ids = event.get("expected_weld_ids", [])
        if not isinstance(expected_ids, list) or not all(isinstance(item, str) for item in expected_ids):
            log_processing_error(conn, "ÉRVÉNYTELEN LEZÁRÁS", "Az expected_weld_ids mező hibás.", json.dumps(event, ensure_ascii=False))
            return
        body_type = str(event.get("body_type", "Ismeretlen"))
        _ensure_body(conn, body_id, body_type, timestamp)
        conn.execute(
            "UPDATE bodies SET body_type=?,expected_count=?,expected_ids_json=? WHERE body_id=?",
            (body_type, len(expected_ids), json.dumps(expected_ids, ensure_ascii=False), body_id),
        )
        rows = conn.execute(
            "SELECT weld_id,errors_json FROM weld_events WHERE body_id=? ORDER BY id", (body_id,)
        ).fetchall()
        received_ids = [str(row["weld_id"]) for row in rows]
        parameter_errors = sum(
            sum(not str(error).startswith("Duplikált üzenet:") for error in json.loads(row["errors_json"]))
            for row in rows
        )
        result = evaluate_body(expected_ids, received_ids, parameter_errors)
        try:
            sent_epoch = datetime.fromisoformat(timestamp).timestamp()
            latency_ms = max(0.0, (received_at - sent_epoch) * 1000.0)
        except (ValueError, OverflowError, OSError):
            latency_ms = None

        bad = result["status"] != "MEGFELELŐ"
        final_status = "SELEJT / UTÓMUNKÁRA KÜLDVE" if bad else "MEGFELELŐ"
        conn.execute(
            """UPDATE bodies SET status=?,missing_ids_json=?,unexpected_ids_json=?,duplicate_ids_json=?,
               parameter_errors=?,completed_at=?,latency_ms=? WHERE body_id=?""",
            (final_status, json.dumps(result["missing_ids"], ensure_ascii=False),
             json.dumps(result["unexpected_ids"], ensure_ascii=False),
             json.dumps(result["duplicate_ids"], ensure_ascii=False), parameter_errors,
             timestamp, latency_ms, body_id),
        )
        if bad:
            reason_parts: list[str] = []
            if result["missing_ids"]:
                reason_parts.append(f"Hiányzó pontok: {', '.join(result['missing_ids'])}")
            if result["unexpected_ids"]:
                reason_parts.append(f"Váratlan pontok: {', '.join(result['unexpected_ids'])}")
            if result["duplicate_ids"]:
                reason_parts.append(f"Duplikált pontok: {', '.join(result['duplicate_ids'])}")
            if parameter_errors:
                reason_parts.append(f"Paraméterhibák: {parameter_errors}")
            reason = "; ".join(reason_parts) or "A karosszéria nem felelt meg az ellenőrzésnek."
            conn.execute(
                """INSERT OR IGNORE INTO rework_queue(body_id,reason,status,created_at,updated_at)
                   VALUES(?,?,?,?,?)""",
                (body_id, reason, REWORK_WAITING, timestamp, timestamp),
            )
        conn.commit()
        return

    if event_type == "rework_action":
        action = event.get("action")
        note = str(event.get("note") or "")
        transitions = {
            "START": (REWORK_WAITING, REWORK_IN_PROGRESS),
            "COMPLETE": (REWORK_IN_PROGRESS, REWORK_DONE),
        }
        if action not in transitions:
            log_processing_error(conn, "ISMERETLEN UTÓMUNKA-MŰVELET", f"Nem támogatott művelet: {action}", json.dumps(event, ensure_ascii=False))
            return
        old_status, new_status = transitions[action]
        row = conn.execute("SELECT status FROM rework_queue WHERE body_id=?", (body_id,)).fetchone()
        if row is None:
            log_processing_error(conn, "ISMERETLEN UTÓMUNKA", f"Nincs utómunka-bejegyzés ehhez: {body_id}", json.dumps(event, ensure_ascii=False))
            return
        if row["status"] != old_status:
            log_processing_error(conn, "ÉRVÉNYTELEN ÁLLAPOTVÁLTÁS", f"{body_id}: {row['status']} állapotból nem hajtható végre a(z) {action} művelet.", json.dumps(event, ensure_ascii=False))
            return
        conn.execute(
            "UPDATE rework_queue SET status=?,updated_at=?,resolved_at=?,resolution_note=? WHERE body_id=?",
            (new_status, timestamp, timestamp if action == "COMPLETE" else None, note, body_id),
        )
        conn.execute(
            "INSERT INTO rework_actions(body_id,action,note,timestamp) VALUES(?,?,?,?)",
            (body_id, action, note, timestamp),
        )
        conn.commit()
        return

    log_processing_error(conn, "ISMERETLEN ESEMÉNYTÍPUS", f"Nem támogatott event_type: {event_type!r}", json.dumps(event, ensure_ascii=False))


def main() -> None:
    conn = connect_db()
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="welding-monitor")

    def on_connect(client: mqtt.Client, userdata: Any, flags: Any, reason_code: Any, properties: Any) -> None:
        if reason_code == 0:
            client.subscribe(TOPIC, qos=1)
            print(f"MQTT monitor csatlakozott; feliratkozva: {TOPIC}")
        else:
            print(f"MQTT csatlakozási hiba: {reason_code}")

    def on_message(client: mqtt.Client, userdata: Any, message: mqtt.MQTTMessage) -> None:
        raw = message.payload.decode("utf-8", errors="replace")
        try:
            process_event(conn, json.loads(raw))
        except (sqlite3.Error, TypeError, ValueError, KeyError) as exc:
            print(f"Üzenetfeldolgozási hiba: {exc}")
            try:
                log_processing_error(conn, "FELDOLGOZÁSI HIBA", str(exc), raw)
            except sqlite3.Error as db_exc:
                print(f"A hibanapló adatbázis-hibája: {db_exc}")

    client.on_connect, client.on_message = on_connect, on_message
    while True:
        try:
            client.connect(BROKER_HOST, BROKER_PORT, keepalive=30)
            client.loop_forever(retry_first_connection=True)
        except (OSError, mqtt.MQTTException) as exc:
            print(f"Broker még nem elérhető ({exc}); újrapróbálkozás 3 másodperc múlva.")
            time.sleep(3)


if __name__ == "__main__":
    main()
