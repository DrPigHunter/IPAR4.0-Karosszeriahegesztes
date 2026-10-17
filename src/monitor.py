"""MQTT subscriber, event validator, and SQLite result store."""
from __future__ import annotations
import json, sqlite3, time
from datetime import datetime
from pathlib import Path
from typing import Any
import paho.mqtt.client as mqtt
from src.rules import evaluate_body, validate_event

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "welding.db"
BROKER_HOST, BROKER_PORT, TOPIC = "127.0.0.1", 1883, "welding/events"

def connect_db() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript('''CREATE TABLE IF NOT EXISTS bodies (
      body_id TEXT PRIMARY KEY, body_type TEXT NOT NULL, expected_count INTEGER NOT NULL,
      expected_ids_json TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'FOLYAMATBAN',
      missing_ids_json TEXT NOT NULL DEFAULT '[]', duplicate_ids_json TEXT NOT NULL DEFAULT '[]',
      parameter_errors INTEGER NOT NULL DEFAULT 0, event_count INTEGER NOT NULL DEFAULT 0,
      started_at TEXT NOT NULL, completed_at TEXT, latency_ms REAL);
      CREATE TABLE IF NOT EXISTS weld_events (
      id INTEGER PRIMARY KEY AUTOINCREMENT, body_id TEXT NOT NULL, weld_id TEXT NOT NULL,
      current_ka REAL, weld_time_ms REAL, electrode_force_kn REAL, timestamp TEXT NOT NULL,
      received_at REAL NOT NULL, errors_json TEXT NOT NULL, duplicate INTEGER NOT NULL DEFAULT 0, raw_json TEXT NOT NULL);''')
    conn.commit(); return conn

def process_event(conn: sqlite3.Connection, event: dict[str, Any], received_at: float | None = None) -> None:
    """Process one decoded MQTT event; separated for deterministic tests."""
    received_at = time.time() if received_at is None else received_at
    body_id = event.get("body_id")
    if not body_id: return
    if event.get("event_type") == "weld_result":
        body_type = str(event.get("body_type", "Ismeretlen")); errors = validate_event(event)
        conn.execute("INSERT OR IGNORE INTO bodies(body_id,body_type,expected_count,expected_ids_json,started_at) VALUES(?,?,0,'[]',?)", (body_id, body_type, str(event.get("timestamp", ""))))
        exists = conn.execute("SELECT 1 FROM weld_events WHERE body_id=? AND weld_id=? LIMIT 1", (body_id, str(event.get("weld_id", "")))).fetchone()
        duplicate = exists is not None
        conn.execute('''INSERT INTO weld_events(body_id,weld_id,current_ka,weld_time_ms,electrode_force_kn,timestamp,received_at,errors_json,duplicate,raw_json)
          VALUES(?,?,?,?,?,?,?,?,?,?)''', (body_id, str(event.get("weld_id", "")), event.get("current_ka"), event.get("weld_time_ms"), event.get("electrode_force_kn"), str(event.get("timestamp", "")), received_at, json.dumps(errors, ensure_ascii=False), int(duplicate), json.dumps(event, ensure_ascii=False)))
        conn.execute("UPDATE bodies SET event_count=event_count+1, parameter_errors=parameter_errors+? WHERE body_id=?", (len(errors), body_id)); conn.commit()
    elif event.get("event_type") == "body_complete":
        expected_ids = list(event.get("expected_weld_ids", [])); body_type = str(event.get("body_type", "Ismeretlen"))
        conn.execute("INSERT OR IGNORE INTO bodies(body_id,body_type,expected_count,expected_ids_json,started_at) VALUES(?,?,?,?,?)", (body_id, body_type, len(expected_ids), json.dumps(expected_ids), str(event.get("timestamp", ""))))
        conn.execute("UPDATE bodies SET expected_count=?, expected_ids_json=? WHERE body_id=?", (len(expected_ids), json.dumps(expected_ids), body_id))
        rows = conn.execute("SELECT weld_id,errors_json FROM weld_events WHERE body_id=? ORDER BY id", (body_id,)).fetchall()
        received_ids = [str(row["weld_id"]) for row in rows]
        parameter_errors = sum(len(json.loads(row["errors_json"])) for row in rows)
        result = evaluate_body(expected_ids, received_ids, parameter_errors)
        sent_at = str(event.get("timestamp", ""))
        try:
            sent_epoch = datetime.fromisoformat(sent_at).timestamp()
            latency_ms = max(0.0, (received_at - sent_epoch) * 1000.0)
        except (ValueError, OverflowError):
            latency_ms = None
        conn.execute("UPDATE bodies SET status=?,missing_ids_json=?,duplicate_ids_json=?,parameter_errors=?,completed_at=?,latency_ms=? WHERE body_id=?", (result["status"], json.dumps(result["missing_ids"]), json.dumps(result["duplicate_ids"]), parameter_errors, sent_at, latency_ms, body_id))
        conn.commit()

def main() -> None:
    conn = connect_db(); client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="welding-monitor")
    def on_connect(client: mqtt.Client, userdata: Any, flags: Any, reason_code: Any, properties: Any) -> None:
        if reason_code == 0:
            client.subscribe(TOPIC, qos=1); print(f"MQTT monitor csatlakozott; feliratkozva: {TOPIC}")
        else: print(f"MQTT csatlakozási hiba: {reason_code}")
    def on_message(client: mqtt.Client, userdata: Any, message: mqtt.MQTTMessage) -> None:
        try: process_event(conn, json.loads(message.payload.decode("utf-8")))
        except (UnicodeDecodeError, json.JSONDecodeError, sqlite3.Error, TypeError, ValueError) as exc: print(f"Üzenetfeldolgozási hiba: {exc}")
    client.on_connect, client.on_message = on_connect, on_message
    while True:
        try: client.connect(BROKER_HOST, BROKER_PORT, keepalive=30); client.loop_forever(retry_first_connection=True)
        except (OSError, mqtt.MQTTException) as exc: print(f"Broker még nem elérhető ({exc}); újrapróbálkozás 3 másodperc múlva."); time.sleep(3)

if __name__ == "__main__": main()
