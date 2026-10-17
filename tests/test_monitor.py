"""Integration tests for Excel-driven monitoring and automatic rework routing."""
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from src.catalog import list_configurations
from src.simulator import generate_body_events
from src.monitor import (
    REWORK_DONE, REWORK_IN_PROGRESS, REWORK_WAITING, connect_db, process_event,
)


CONFIG = list_configurations()[0]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def body_start(body_id="BODY-TEST", config=CONFIG):
    return {"event_type": "body_start", "body_id": body_id, "config_id": config["config_id"],
            "timestamp": now_iso()}


def weld(body_id, point, config=CONFIG, current=None):
    return {"event_type": "weld_result", "body_id": body_id, "config_id": config["config_id"],
            "weld_id": point["weld_id"],
            "current_ka": current if current is not None else point["nominal_current_ka"],
            "weld_time_ms": point["nominal_weld_time_ms"],
            "electrode_force_kn": point["nominal_electrode_force_kn"], "timestamp": now_iso()}


def complete(body_id="BODY-TEST", config=CONFIG):
    return {"event_type": "body_complete", "body_id": body_id, "config_id": config["config_id"],
            "timestamp": now_iso()}


class MonitorIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.conn = connect_db(Path(self.tmp.name) / "test.db")
        self.config = CONFIG
        self.points = self.config["points"]

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def test_duplicate_point_routes_sidewall_to_rework(self):
        process_event(self.conn, body_start())
        process_event(self.conn, weld("BODY-TEST", self.points[0]))
        process_event(self.conn, weld("BODY-TEST", self.points[0]))
        for point in self.points[1:]:
            process_event(self.conn, weld("BODY-TEST", point))
        process_event(self.conn, complete())

        body = self.conn.execute("SELECT status, duplicate_ids_json FROM bodies WHERE body_id='BODY-TEST'").fetchone()
        queue = self.conn.execute("SELECT status, reason FROM rework_queue WHERE body_id='BODY-TEST'").fetchone()
        self.assertEqual(body["status"], "SELEJT / UTÓMUNKÁRA KÜLDVE")
        self.assertEqual(json.loads(body["duplicate_ids_json"]), [self.points[0]["weld_id"]])
        self.assertEqual(queue["status"], REWORK_WAITING)
        self.assertIn("Duplikált pontok", queue["reason"])

    def test_missing_point_routes_sidewall_to_rework(self):
        process_event(self.conn, body_start())
        for point in self.points[1:]:
            process_event(self.conn, weld("BODY-TEST", point))
        process_event(self.conn, complete())
        body = self.conn.execute("SELECT status, missing_ids_json FROM bodies WHERE body_id='BODY-TEST'").fetchone()
        queue = self.conn.execute("SELECT body_id FROM rework_queue").fetchone()
        self.assertEqual(body["status"], "SELEJT / UTÓMUNKÁRA KÜLDVE")
        self.assertEqual(json.loads(body["missing_ids_json"]), [self.points[0]["weld_id"]])
        self.assertEqual(queue["body_id"], "BODY-TEST")

    def test_out_of_range_parameter_routes_sidewall_to_rework(self):
        process_event(self.conn, body_start())
        high_current = self.config["limits"].current_max + 2
        process_event(self.conn, weld("BODY-TEST", self.points[0], current=high_current))
        for point in self.points[1:]:
            process_event(self.conn, weld("BODY-TEST", point))
        process_event(self.conn, complete())
        body = self.conn.execute("SELECT status, parameter_errors FROM bodies WHERE body_id='BODY-TEST'").fetchone()
        self.assertEqual(body["status"], "SELEJT / UTÓMUNKÁRA KÜLDVE")
        self.assertGreater(body["parameter_errors"], 0)

    def test_fault_free_cycles_for_all_models_pass_without_rework(self):
        configs = list_configurations()
        for config in configs:
            body_id, events = generate_body_events(config["config_id"], fault_rate=0.0, seed=123, non_wear_defect_probability=0.0)
            for event in events:
                process_event(self.conn, event)
            row = self.conn.execute(
                "SELECT status FROM bodies WHERE body_id=?", (body_id,)
            ).fetchone()
            queue = self.conn.execute(
                "SELECT body_id FROM rework_queue WHERE body_id=?", (body_id,)
            ).fetchone()
            self.assertEqual(row["status"], "MEGFELELŐ", msg=config["label"])
            self.assertIsNone(queue, msg=config["label"])

    def test_good_sidewall_does_not_enter_rework(self):
        process_event(self.conn, body_start())
        for point in self.points:
            process_event(self.conn, weld("BODY-TEST", point))
        process_event(self.conn, complete())
        body = self.conn.execute("SELECT status FROM bodies WHERE body_id='BODY-TEST'").fetchone()
        queue = self.conn.execute("SELECT body_id FROM rework_queue").fetchone()
        self.assertEqual(body["status"], "MEGFELELŐ")
        self.assertIsNone(queue)

    def test_completed_cycle_writes_per_run_statistics_log(self):
        log_dir = Path(self.tmp.name) / "logs"
        body_id = "BODY-LOG-TEST"
        process_event(self.conn, body_start(body_id))
        for point in self.points:
            process_event(self.conn, weld(body_id, point))
        process_event(self.conn, complete(body_id), log_dir=log_dir)

        files = list(log_dir.glob("run_*.json"))
        self.assertEqual(len(files), 1)
        report = json.loads(files[0].read_text(encoding="utf-8"))
        self.assertEqual(report["body_id"], body_id)
        self.assertEqual(report["status"], "MEGFELELŐ")
        self.assertEqual(report["expected_weld_points"], self.config["expected_count"])
        self.assertEqual(report["received_unique_expected_points"], self.config["expected_count"])
        self.assertEqual(report["point_completeness_percent"], 100.0)
        self.assertFalse(report["rework_required"])
        self.assertIsNotNone(report["duration_seconds"])
        self.assertLess(report["duration_seconds"], 20.0)
        self.assertTrue(report["within_20_second_target"])
        self.assertTrue((log_dir / "production_summary.json").exists())
        self.assertEqual(len(list(log_dir.glob("production_*.jsonl"))), 1)

    def test_rework_state_transitions_are_logged(self):
        process_event(self.conn, body_start())
        for point in self.points[1:]:
            process_event(self.conn, weld("BODY-TEST", point))
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
