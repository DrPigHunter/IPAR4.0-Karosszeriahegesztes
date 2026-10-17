"""Integration tests for MQTT monitor event handling and rework routing."""
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from src.monitor import (
    REWORK_DONE, REWORK_IN_PROGRESS, REWORK_WAITING, connect_db, process_event,
)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def body_start(body_id="BODY-TEST"):
    return {"event_type": "body_start", "body_id": body_id, "body_type": "Compact",
            "expected_weld_ids": ["W001", "W002"], "timestamp": now_iso()}


def weld(body_id, weld_id, current=9.0):
    return {"event_type": "weld_result", "body_id": body_id, "body_type": "Compact",
            "weld_id": weld_id, "current_ka": current, "weld_time_ms": 250.0,
            "electrode_force_kn": 3.5, "timestamp": now_iso()}


def complete(body_id="BODY-TEST"):
    return {"event_type": "body_complete", "body_id": body_id, "body_type": "Compact",
            "expected_weld_ids": ["W001", "W002"], "timestamp": now_iso()}


class MonitorIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.conn = connect_db(Path(self.tmp.name) / "test.db")

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def test_duplicate_point_routes_body_to_rework(self):
        process_event(self.conn, body_start())
        process_event(self.conn, weld("BODY-TEST", "W001"))
        process_event(self.conn, weld("BODY-TEST", "W001"))
        process_event(self.conn, weld("BODY-TEST", "W002"))
        process_event(self.conn, complete())

        body = self.conn.execute("SELECT status, duplicate_ids_json FROM bodies WHERE body_id='BODY-TEST'").fetchone()
        queue = self.conn.execute("SELECT status, reason FROM rework_queue WHERE body_id='BODY-TEST'").fetchone()
        self.assertEqual(body["status"], "SELEJT / UTÓMUNKÁRA KÜLDVE")
        self.assertEqual(json.loads(body["duplicate_ids_json"]), ["W001"])
        self.assertEqual(queue["status"], REWORK_WAITING)
        self.assertIn("Duplikált pontok", queue["reason"])

    def test_missing_point_routes_body_to_rework(self):
        process_event(self.conn, body_start())
        process_event(self.conn, weld("BODY-TEST", "W001"))
        process_event(self.conn, complete())
        body = self.conn.execute("SELECT status, missing_ids_json FROM bodies WHERE body_id='BODY-TEST'").fetchone()
        queue = self.conn.execute("SELECT body_id FROM rework_queue").fetchone()
        self.assertEqual(body["status"], "SELEJT / UTÓMUNKÁRA KÜLDVE")
        self.assertEqual(json.loads(body["missing_ids_json"]), ["W002"])
        self.assertEqual(queue["body_id"], "BODY-TEST")

    def test_out_of_range_parameter_routes_body_to_rework(self):
        process_event(self.conn, body_start())
        process_event(self.conn, weld("BODY-TEST", "W001", current=13.5))
        process_event(self.conn, weld("BODY-TEST", "W002"))
        process_event(self.conn, complete())
        body = self.conn.execute("SELECT status, parameter_errors FROM bodies WHERE body_id='BODY-TEST'").fetchone()
        self.assertEqual(body["status"], "SELEJT / UTÓMUNKÁRA KÜLDVE")
        self.assertGreater(body["parameter_errors"], 0)

    def test_good_body_does_not_enter_rework(self):
        process_event(self.conn, body_start())
        process_event(self.conn, weld("BODY-TEST", "W001"))
        process_event(self.conn, weld("BODY-TEST", "W002"))
        process_event(self.conn, complete())
        body = self.conn.execute("SELECT status FROM bodies WHERE body_id='BODY-TEST'").fetchone()
        queue = self.conn.execute("SELECT body_id FROM rework_queue").fetchone()
        self.assertEqual(body["status"], "MEGFELELŐ")
        self.assertIsNone(queue)

    def test_rework_state_transitions_are_logged(self):
        process_event(self.conn, body_start())
        process_event(self.conn, weld("BODY-TEST", "W001"))
        process_event(self.conn, complete())
        process_event(self.conn, {"event_type": "rework_action", "body_id": "BODY-TEST",
                                  "action": "START", "note": "Elkezdve", "timestamp": now_iso()})
        row = self.conn.execute("SELECT status FROM rework_queue WHERE body_id='BODY-TEST'").fetchone()
        self.assertEqual(row["status"], REWORK_IN_PROGRESS)
        process_event(self.conn, {"event_type": "rework_action", "body_id": "BODY-TEST",
                                  "action": "COMPLETE", "note": "Javítás kész", "timestamp": now_iso()})
        row = self.conn.execute("SELECT status, resolution_note FROM rework_queue WHERE body_id='BODY-TEST'").fetchone()
        actions = self.conn.execute("SELECT COUNT(*) FROM rework_actions").fetchone()[0]
        self.assertEqual(row["status"], REWORK_DONE)
        self.assertEqual(row["resolution_note"], "Javítás kész")
        self.assertEqual(actions, 2)

    def test_unknown_event_type_is_logged(self):
        process_event(self.conn, {"event_type": "mystery", "body_id": "BODY-TEST"})
        error = self.conn.execute("SELECT category FROM system_errors").fetchone()
        self.assertEqual(error["category"], "ISMERETLEN ESEMÉNYTÍPUS")


if __name__ == "__main__":
    unittest.main()
