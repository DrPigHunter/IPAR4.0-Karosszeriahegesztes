"""Tests for monitor-side completion waiting used to pace automatic production."""
import sqlite3
import tempfile
import threading
import time
import unittest
from pathlib import Path

from src.monitor import connect_db
from src.monitor_wait import MonitorCompletionTimeout, wait_for_body_completion


# A várakozási tesztek azt biztosítják, hogy a publisher ne tekintse lezártnak a ciklust a monitor végső SQLite-státusza előtt.
class MonitorWaitTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "welding.db"
        conn = connect_db(self.db_path)
        conn.execute(
            """INSERT INTO bodies(body_id,body_type,config_id,started_at,status)
               VALUES(?,?,?,?,?)""",
            ("BODY-WAIT", "Test model", "TEST", "2026-10-17T18:00:00+00:00", "FOLYAMATBAN"),
        )
        conn.commit()
        conn.close()

    def tearDown(self):
        self.tmp.cleanup()

    # A várakozás addig tartson, amíg a monitor végleges állapotot nem ment.
    def test_waits_until_monitor_persists_terminal_status(self):
        def finish_body():
            time.sleep(0.05)
            with sqlite3.connect(self.db_path, timeout=2) as conn:
                conn.execute(
                    "UPDATE bodies SET status=?,completed_at=?,duration_seconds=? WHERE body_id=?",
                    ("MEGFELELŐ", "2026-10-17T18:00:12+00:00", 12.0, "BODY-WAIT"),
                )
                conn.commit()

        thread = threading.Thread(target=finish_body, daemon=True)
        thread.start()
        result = wait_for_body_completion("BODY-WAIT", self.db_path, timeout_seconds=2, poll_interval_seconds=0.005)
        thread.join(timeout=1)
        self.assertEqual(result["status"], "MEGFELELŐ")
        self.assertEqual(result["duration_seconds"], 12.0)
        self.assertEqual(result["body_id"], "BODY-WAIT")

    # Már lezárt oldalfalnál ne legyen felesleges várakozás.
    def test_returns_immediately_if_monitor_already_finalized_body(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE bodies SET status=?,completed_at=?,duration_seconds=? WHERE body_id=?",
                ("SELEJT / UTÓMUNKÁRA KÜLDVE", "2026-10-17T18:00:12+00:00", 12.0, "BODY-WAIT"),
            )
            conn.commit()
        result = wait_for_body_completion("BODY-WAIT", self.db_path, timeout_seconds=0.5)
        self.assertEqual(result["status"], "SELEJT / UTÓMUNKÁRA KÜLDVE")

    # Elmaradt monitorválasznál egyértelmű időtúllépést kapjak.
    def test_timeout_is_raised_for_missing_monitor_result(self):
        missing_db = Path(self.tmp.name) / "missing.db"
        started = time.monotonic()
        with self.assertRaises(MonitorCompletionTimeout):
            wait_for_body_completion("BODY-MISSING", missing_db, timeout_seconds=0.04, poll_interval_seconds=0.005)
        self.assertLess(time.monotonic() - started, 0.5)

    # Érvénytelen határidőt és lekérdezési időközt utasítson el.
    def test_invalid_wait_parameters_are_rejected(self):
        with self.assertRaises(ValueError):
            wait_for_body_completion("BODY-WAIT", self.db_path, timeout_seconds=0)
        with self.assertRaises(ValueError):
            wait_for_body_completion("BODY-WAIT", self.db_path, poll_interval_seconds=0)
        with self.assertRaises(ValueError):
            wait_for_body_completion("   ", self.db_path)


if __name__ == "__main__":
    unittest.main()
