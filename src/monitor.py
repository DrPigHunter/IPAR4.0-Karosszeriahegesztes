"""MQTT subscriber: validates events against the version-controlled Excel catalog and records run history."""
from __future__ import annotations

import json
import sqlite3
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import paho.mqtt.client as mqtt

from src.catalog import CatalogError, get_configuration
from src.rules import evaluate_body, validate_event

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "welding.db"
LOG_DIR = ROOT / "logs"
BROKER_HOST, BROKER_PORT, TOPIC = "127.0.0.1", 1883, "welding/events"

REWORK_WAITING = "UTÓMUNKÁRA VÁR"
REWORK_IN_PROGRESS = "UTÓMUNKA FOLYAMATBAN"
REWORK_DONE = "UTÓMUNKA ELVÉGEZVE – ÚJRAELLENŐRZÉS SZÜKSÉGES"


def connect_db(db_path: str | Path | None = None) -> sqlite3.Connection:
    """Runtime DB stores observations, run history, and rework only—not reference recipes."""
    target = Path(db_path) if db_path is not None else DB_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(target), timeout=10, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript("""
      CREATE TABLE IF NOT EXISTS bodies (
        body_id TEXT PRIMARY KEY, body_type TEXT NOT NULL, config_id TEXT NOT NULL DEFAULT '',
        expected_count INTEGER NOT NULL DEFAULT 0, expected_ids_json TEXT NOT NULL DEFAULT '[]',
        status TEXT NOT NULL DEFAULT 'FOLYAMATBAN', missing_ids_json TEXT NOT NULL DEFAULT '[]',
        unexpected_ids_json TEXT NOT NULL DEFAULT '[]', duplicate_ids_json TEXT NOT NULL DEFAULT '[]',
        parameter_errors INTEGER NOT NULL DEFAULT 0, event_count INTEGER NOT NULL DEFAULT 0,
        started_at TEXT NOT NULL, started_received_at REAL, completed_at TEXT, latency_ms REAL,
        duration_seconds REAL
      );
      CREATE TABLE IF NOT EXISTS weld_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT, body_id TEXT NOT NULL, config_id TEXT NOT NULL DEFAULT '',
        weld_id TEXT NOT NULL, current_ka REAL, weld_time_ms REAL, electrode_force_kn REAL,
        timestamp TEXT NOT NULL, received_at REAL NOT NULL, errors_json TEXT NOT NULL,
        duplicate INTEGER NOT NULL DEFAULT 0, raw_json TEXT NOT NULL
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
    # Migrate databases from earlier prototype versions.
    for table, column, declaration in (
        ("bodies", "config_id", "TEXT NOT NULL DEFAULT ''"),
        ("weld_events", "config_id", "TEXT NOT NULL DEFAULT ''"),
        ("bodies", "unexpected_ids_json", "TEXT NOT NULL DEFAULT '[]'"),
        ("bodies", "started_received_at", "REAL"),
        ("bodies", "duration_seconds", "REAL"),
    ):
        columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        if column not in columns:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {declaration}")
    conn.commit()
    return conn


def log_processing_error(
    conn: sqlite3.Connection, category: str, detail: str, raw_payload: str = ""
) -> None:
    """Persist malformed messages and processing failures so operators can see them."""
    conn.execute(
        "INSERT INTO system_errors(category,detail,raw_payload,received_at) VALUES(?,?,?,?)",
        (category, detail[:2000], raw_payload[:10000], datetime.now().astimezone().isoformat()),
    )
    conn.commit()


def _ensure_body(
    conn: sqlite3.Connection, body_id: str, config_id: str,
    config: dict[str, Any], timestamp: str,
) -> None:
    """Snapshot config identity and expected IDs for this run; recipe remains in Excel."""
    conn.execute(
        """INSERT OR IGNORE INTO bodies(body_id,body_type,config_id,expected_count,expected_ids_json,started_at)
           VALUES(?,?,?,?,?,?)""",
        (body_id, config["label"], config_id, len(config["expected_weld_ids"]),
         json.dumps(config["expected_weld_ids"], ensure_ascii=False), timestamp),
    )


def _resolve_config(conn: sqlite3.Connection, event: dict[str, Any], body_id: str) -> tuple[str, dict[str, Any]] | None:
    """Resolve config from event, falling back to the already registered body run."""
    config_id = str(event.get("config_id") or "").strip()
    if not config_id:
        row = conn.execute("SELECT config_id FROM bodies WHERE body_id=?", (body_id,)).fetchone()
        config_id = str(row["config_id"] or "") if row else ""
    if not config_id:
        log_processing_error(conn, "HIÁNYZÓ KONFIGURÁCIÓ", f"{body_id}: nincs config_id.", json.dumps(event, ensure_ascii=False))
        return None
    try:
        config = get_configuration(config_id)
    except CatalogError as exc:
        log_processing_error(conn, "ISMERETLEN EXCEL-KONFIGURÁCIÓ", str(exc), json.dumps(event, ensure_ascii=False))
        return None
    row = conn.execute("SELECT config_id FROM bodies WHERE body_id=?", (body_id,)).fetchone()
    if row and row["config_id"] and row["config_id"] != config_id:
        log_processing_error(
            conn, "KONFIGURÁCIÓ-ELTÉRÉS",
            f"{body_id}: a futás konfigurációja {row['config_id']}, de az esemény {config_id} értéket küldött.",
            json.dumps(event, ensure_ascii=False),
        )
        return None
    return config_id, config


def process_event(
    conn: sqlite3.Connection, event: dict[str, Any], received_at: float | None = None,
    log_dir: str | Path | None = None,
) -> None:
    """Process one MQTT event. Parameter limits and required points always come from the XLSX catalog."""
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
        resolved = _resolve_config(conn, event, body_id)
        if not resolved:
            return
        config_id, config = resolved
        _ensure_body(conn, body_id, config_id, config, timestamp)
        conn.execute(
            "UPDATE bodies SET started_received_at=COALESCE(started_received_at, ?) WHERE body_id=?",
            (received_at, body_id),
        )
        conn.commit()
        if log_dir is not None:
            try:
                from src.run_logger import write_part_loaded_log
                write_part_loaded_log(log_dir, body_id, config, timestamp)
            except (OSError, TypeError, ValueError) as exc:
                print(f"WARNING: could not write part-load TXT log: {exc}")
        return

    if event_type == "weld_result":
        resolved = _resolve_config(conn, event, body_id)
        if not resolved:
            return
        config_id, config = resolved
        weld_id = event.get("weld_id")
        if not isinstance(weld_id, str) or not weld_id.strip():
            log_processing_error(conn, "HIÁNYZÓ HEGESZTÉSI PONT", f"{body_id}: a weld_result eseményből hiányzik a weld_id.", json.dumps(event, ensure_ascii=False))
            return
        _ensure_body(conn, body_id, config_id, config, timestamp)
        errors = validate_event(event, limits=config["limits"])
        if event.get("process_quality_ok") is False:
            errors.append(
                "Elektródakopás miatti minőségi eltérés: az automatikus korrekció nem érte el a "
                "szimulált célértéket a megengedett határokon belül."
            )
        if weld_id not in config["expected_weld_ids"]:
            errors.append("Váratlan hegesztési pont: nem szerepel a GitHubon verziózott Excel-katalógus pontlistájában.")
        exists = conn.execute(
            "SELECT 1 FROM weld_events WHERE body_id=? AND weld_id=? LIMIT 1", (body_id, weld_id)
        ).fetchone()
        duplicate = exists is not None
        if duplicate:
            errors.append("Duplikált üzenet: ez a hegesztési pont korábban már beérkezett.")
        conn.execute(
            """INSERT INTO weld_events(body_id,config_id,weld_id,current_ka,weld_time_ms,electrode_force_kn,
               timestamp,received_at,errors_json,duplicate,raw_json) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
            (body_id, config_id, weld_id, event.get("current_ka"), event.get("weld_time_ms"),
             event.get("electrode_force_kn"), timestamp, received_at,
             json.dumps(errors, ensure_ascii=False), int(duplicate), json.dumps(event, ensure_ascii=False)),
        )
        param_error_count = len([
            err for err in errors
            if not err.startswith("Duplikált üzenet:") and not err.startswith("Váratlan hegesztési pont:")
        ])
        conn.execute(
            "UPDATE bodies SET event_count=event_count+1,parameter_errors=parameter_errors+? WHERE body_id=?",
            (param_error_count, body_id),
        )
        conn.commit()
        if errors and log_dir is not None:
            try:
                from src.run_logger import write_weld_error_log
                write_weld_error_log(log_dir, event, errors)
            except (OSError, TypeError, ValueError) as exc:
                print(f"WARNING: could not write weld-fault TXT log: {exc}")
        return

    if event_type == "body_complete":
        resolved = _resolve_config(conn, event, body_id)
        if not resolved:
            return
        config_id, config = resolved
        _ensure_body(conn, body_id, config_id, config, timestamp)
        expected_ids = list(config["expected_weld_ids"])
        conn.execute(
            "UPDATE bodies SET expected_count=?,expected_ids_json=? WHERE body_id=?",
            (len(expected_ids), json.dumps(expected_ids, ensure_ascii=False), body_id),
        )
        rows = conn.execute(
            "SELECT weld_id,errors_json FROM weld_events WHERE body_id=? ORDER BY id", (body_id,)
        ).fetchall()
        received_ids = [str(row["weld_id"]) for row in rows]
        parameter_errors = sum(
            sum(
                not str(error).startswith(("Duplikált üzenet:", "Váratlan hegesztési pont:"))
                for error in json.loads(row["errors_json"])
            )
            for row in rows
        )
        wear_failed_ids = [
            str(row["weld_id"])
            for row in rows
            if any(
                "Elektródakopás miatti minőségi eltérés" in str(error)
                for error in json.loads(row["errors_json"])
            )
        ]
        result = evaluate_body(expected_ids, received_ids, parameter_errors)
        start_row = conn.execute(
            "SELECT started_received_at FROM bodies WHERE body_id=?", (body_id,)
        ).fetchone()
        started_received_at = start_row["started_received_at"] if start_row else None
        duration_seconds = (
            round(max(0.0, received_at - float(started_received_at)), 3)
            if started_received_at is not None else None
        )
        try:
            sent_epoch = datetime.fromisoformat(timestamp).timestamp()
            latency_ms = max(0.0, (received_at - sent_epoch) * 1000.0)
        except (ValueError, OverflowError, OSError):
            latency_ms = None

        bad = result["status"] != "MEGFELELŐ"
        final_status = "SELEJT / UTÓMUNKÁRA KÜLDVE" if bad else "MEGFELELŐ"
        conn.execute(
            """UPDATE bodies SET status=?,missing_ids_json=?,unexpected_ids_json=?,duplicate_ids_json=?,
               parameter_errors=?,completed_at=?,latency_ms=?,duration_seconds=? WHERE body_id=?""",
            (final_status, json.dumps(result["missing_ids"], ensure_ascii=False),
             json.dumps(result["unexpected_ids"], ensure_ascii=False),
             json.dumps(result["duplicate_ids"], ensure_ascii=False), parameter_errors,
             timestamp, latency_ms, duration_seconds, body_id),
        )
        if bad:
            reason_parts: list[str] = []
            if result["missing_ids"]:
                reason_parts.append(f"Hiányzó pontok: {', '.join(result['missing_ids'])}")
            if result["unexpected_ids"]:
                reason_parts.append(f"Váratlan pontok: {', '.join(result['unexpected_ids'])}")
            if result["duplicate_ids"]:
                reason_parts.append(f"Duplikált pontok: {', '.join(result['duplicate_ids'])}")
            if wear_failed_ids:
                sample_ids = ", ".join(wear_failed_ids[:10])
                suffix = " …" if len(wear_failed_ids) > 10 else ""
                reason_parts.append(
                    f"Elektródakopás miatti sikertelen korrekció: {len(wear_failed_ids)} pont "
                    f"(például: {sample_ids}{suffix})"
                )
            if parameter_errors:
                reason_parts.append(f"Paraméterhibák: {parameter_errors}")
            reason = "; ".join(reason_parts) or "A karosszéria nem felelt meg az ellenőrzésnek."
            conn.execute(
                """INSERT OR IGNORE INTO rework_queue(body_id,reason,status,created_at,updated_at)
                   VALUES(?,?,?,?,?)""",
                (body_id, reason, REWORK_WAITING, timestamp, timestamp),
            )
        conn.commit()
        if log_dir is not None:
            try:
                from src.run_logger import write_run_log
                path = write_run_log(
                    conn, body_id, config, expected_ids, received_ids, result,
                    parameter_errors, duration_seconds, log_dir,
                )
                print(f"Production TXT log updated: {path}")
            except (OSError, sqlite3.Error, TypeError, ValueError) as exc:
                print(f"WARNING: could not write completed-part TXT log: {exc}")
        return

    if event_type == "rework_action":
        action, note = event.get("action"), str(event.get("note") or "")
        transitions = {"START": (REWORK_WAITING, REWORK_IN_PROGRESS),
                       "COMPLETE": (REWORK_IN_PROGRESS, REWORK_DONE)}
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
        if log_dir is not None:
            try:
                from src.run_logger import write_rework_action_log
                write_rework_action_log(log_dir, body_id, str(action), timestamp)
            except (OSError, TypeError, ValueError) as exc:
                print(f"WARNING: could not write rework TXT log: {exc}")
        return

    log_processing_error(conn, "ISMERETLEN ESEMÉNYTÍPUS", f"Nem támogatott event_type: {event_type!r}", json.dumps(event, ensure_ascii=False))


def main() -> None:
    conn = connect_db()
    try:
        from src.catalog import list_configurations
        all_configs = list_configurations()
        print(f"Excel katalógus betöltve: {len(all_configs)} modell–alkatrész konfiguráció.")
    except CatalogError as exc:
        print(f"KRITIKUS KONFIGURÁCIÓS HIBA: {exc}")
        raise

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
            process_event(conn, json.loads(raw), log_dir=LOG_DIR)
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
