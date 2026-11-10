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


# A monitor tesztjei ideiglenes adatbázisban vizsgálják a pontellenőrzést, a minősítést és az utómunka útvonalát.
class MonitorIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.conn = connect_db(Path(self.tmp.name) / "test.db")
        self.config = CONFIG
        self.points = self.config["points"]

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    # Ismételt pontazonosító esetén az oldalfal kerüljön utómunkára.
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

    # Hiányzó hegesztési pont esetén ne legyen megfelelő a ciklus.
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

    # Határértéken kívüli mérésnél hibát naplózzon, és indítsa el az utómunka-ágat.
    def test_welding_fault_is_logged_in_english_and_part_is_sent_to_rework(self):
        log_dir = Path(self.tmp.name) / "logs"
        process_event(self.conn, body_start(), log_dir=log_dir)
        high_current = self.config["limits"].current_max + 2
        process_event(self.conn, weld("BODY-TEST", self.points[0], current=high_current), log_dir=log_dir)
        for point in self.points[1:]:
            process_event(self.conn, weld("BODY-TEST", point), log_dir=log_dir)
        process_event(self.conn, complete(), log_dir=log_dir)

        body = self.conn.execute("SELECT status, parameter_errors FROM bodies WHERE body_id='BODY-TEST'").fetchone()
        self.assertEqual(body["status"], "SELEJT / UTÓMUNKÁRA KÜLDVE")
        self.assertGreater(body["parameter_errors"], 0)

        lines = (log_dir / "production_log.txt").read_text(encoding="utf-8").splitlines()
        self.assertEqual(sum(" | WELDING FAULT | " in line for line in lines), 1)
        self.assertTrue(any("Current:" in line and "WELDING FAULT" in line for line in lines))
        self.assertTrue(any("SENT TO REWORK" in line and "PART REMOVED FROM LINE" in line for line in lines))
        self.assertFalse(any("Áramerősség" in line or "Hegesztési idő" in line for line in lines))

    # Mindegyik katalógusmodell hibátlan pontsorával megfelelő eredményt várok.
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

    # Hibátlan oldalfal ne kerüljön az utómunka-sorba.
    def test_good_sidewall_does_not_enter_rework(self):
        process_event(self.conn, body_start())
        for point in self.points:
            process_event(self.conn, weld("BODY-TEST", point))
        process_event(self.conn, complete())
        body = self.conn.execute("SELECT status FROM bodies WHERE body_id='BODY-TEST'").fetchone()
        queue = self.conn.execute("SELECT body_id FROM rework_queue").fetchone()
        self.assertEqual(body["status"], "MEGFELELŐ")
        self.assertIsNone(queue)

    # Ellenőrzöm, hogy a betöltés és a pont-hiba a ciklus lezárása előtt is megjelenik a naplóban.
    def test_part_load_and_weld_fault_are_logged_before_part_completion(self):
        log_dir = Path(self.tmp.name) / "logs"
        log_path = log_dir / "production_log.txt"
        body_id = "BODY-LIVE-LOG-TEST"

        process_event(self.conn, body_start(body_id), log_dir=log_dir)
        self.assertTrue(log_path.exists())
        lines_after_load = log_path.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines_after_load), 1)
        self.assertIn("NEW PART LOADED SUCCESSFULLY", lines_after_load[0])

        high_current = self.config["limits"].current_max + 2
        process_event(self.conn, weld(body_id, self.points[0], current=high_current), log_dir=log_dir)
        lines_after_fault = log_path.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines_after_fault), 2)
        self.assertIn("WELDING FAULT", lines_after_fault[1])
        self.assertIn(self.points[0]["weld_id"], lines_after_fault[1])

        # No body_complete event has been published yet; both records are already durable.
        self.assertEqual(
            self.conn.execute("SELECT status FROM bodies WHERE body_id=?", (body_id,)).fetchone()["status"],
            "FOLYAMATBAN",
        )

    # A lezárt ciklushoz rövid, ember által olvasható TXT összesítő készüljön.
    def test_completed_cycle_writes_compact_english_txt_lifecycle_log(self):
        log_dir = Path(self.tmp.name) / "logs"
        body_id = "BODY-LOG-TEST"
        process_event(self.conn, body_start(body_id), log_dir=log_dir)
        for point in self.points:
            process_event(self.conn, weld(body_id, point), log_dir=log_dir)
        process_event(self.conn, complete(body_id), log_dir=log_dir)

        log_path = log_dir / "production_log.txt"
        self.assertTrue(log_path.exists())
        lines = log_path.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 2)
        self.assertIn("NEW PART LOADED SUCCESSFULLY", lines[0])
        self.assertIn(body_id, lines[0])
        self.assertIn("PART REMOVED FROM LINE", lines[1])
        self.assertIn("WELDING COMPLETED SUCCESSFULLY", lines[1])
        self.assertIn(f"Welded points: {self.config['expected_count']}/{self.config['expected_count']}", lines[1])
        self.assertNotIn("Áramerősség", log_path.read_text(encoding="utf-8"))
        self.assertEqual(list(log_dir.glob("run_*.json")), [])
        self.assertEqual(list(log_dir.glob("production_*.jsonl")), [])

    # Az utómunka START és COMPLETE átmenetei külön is legyenek naplózva.
    def test_rework_state_transitions_are_logged(self):
        log_dir = Path(self.tmp.name) / "logs"
        process_event(self.conn, body_start(), log_dir=log_dir)
        for point in self.points[1:]:
            process_event(self.conn, weld("BODY-TEST", point), log_dir=log_dir)
        process_event(self.conn, complete(), log_dir=log_dir)
        process_event(self.conn, {"event_type": "rework_action", "body_id": "BODY-TEST",
                                  "action": "START", "note": "Elkezdve", "timestamp": now_iso()},
                      log_dir=log_dir)
        row = self.conn.execute("SELECT status FROM rework_queue WHERE body_id='BODY-TEST'").fetchone()
        self.assertEqual(row["status"], REWORK_IN_PROGRESS)
        process_event(self.conn, {"event_type": "rework_action", "body_id": "BODY-TEST",
                                  "action": "COMPLETE", "note": "Javítás kész", "timestamp": now_iso()},
                      log_dir=log_dir)
        row = self.conn.execute("SELECT status, resolution_note FROM rework_queue WHERE body_id='BODY-TEST'").fetchone()
        actions = self.conn.execute("SELECT COUNT(*) FROM rework_actions").fetchone()[0]
        self.assertEqual(row["status"], REWORK_DONE)
        self.assertEqual(row["resolution_note"], "Javítás kész")
        self.assertEqual(actions, 2)
        log_text = (log_dir / "production_log.txt").read_text(encoding="utf-8")
        self.assertIn("REWORK STARTED", log_text)
        self.assertIn("REWORK COMPLETED | READY FOR RE-INSPECTION", log_text)
        self.assertNotIn("Elkezdve", log_text)
        self.assertNotIn("Javítás kész", log_text)

    # Ismeretlen eseménytípusnál rendszerhibát várok, nem csendes eldobást.
    def test_unknown_event_type_is_logged(self):
        process_event(self.conn, {"event_type": "mystery", "body_id": "BODY-TEST"})
        error = self.conn.execute("SELECT category FROM system_errors").fetchone()
        self.assertEqual(error["category"], "ISMERETLEN ESEMÉNYTÍPUS")


if __name__ == "__main__":
    unittest.main()
