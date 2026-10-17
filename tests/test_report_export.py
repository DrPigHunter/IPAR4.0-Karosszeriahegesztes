"""Regression tests for dated Excel evaluation exports and complete log capture."""
import tempfile
import time
import unittest
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path

import pandas as pd
from openpyxl import load_workbook

from src.catalog import list_configurations
from src.monitor import connect_db, process_event
from src.report_export import append_application_log, export_production_report
from src.simulator import generate_body_events


class ReportExportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db_path = self.root / "data" / "test.db"
        self.log_dir = self.root / "logs"
        self.conn = connect_db(self.db_path)

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def _record_one_cycle(self):
        config = list_configurations()[0]
        _, events = generate_body_events(config["config_id"], fault_rate=0.0, seed=123)
        for event in events:
            process_event(self.conn, event, log_dir=self.log_dir)
        return config

    def test_export_contains_evaluation_metrics_all_tables_and_logs(self):
        config = self._record_one_cycle()
        append_application_log(
            "test_operator_action",
            {"purpose": "verify complete workbook export", "selected_fault_mode": "outside_limits"},
            log_dir=self.log_dir,
        )
        timestamp = datetime(2026, 10, 17, 18, 40, 20, tzinfo=timezone.utc)
        path, data, info = export_production_report(
            session_started_at=time.time() - 120,
            fault_rate_percent=0.1,
            fault_mode="outside_limits",
            automatic_worker_stopped=True,
            speed_percent=10_000,
            db_path=self.db_path,
            log_dir=self.log_dir,
            export_timestamp=timestamp,
        )

        self.assertTrue(path.is_file())
        self.assertEqual(path.name, "BODYLINE_jelentes_2026-10-17_18-40-20.xlsx")
        self.assertEqual(path.read_bytes(), data)
        self.assertEqual(info["session_body_count"], 1)
        self.assertEqual(info["session_pass_count"], 1)
        self.assertEqual(info["session_scrap_count"], 0)
        self.assertEqual(info["speed_percent"], 10_000)

        workbook = load_workbook(BytesIO(data), read_only=True, data_only=True)
        required_sheets = {
            "Összesítő", "Modellenként", "Karosszériák", "Hegesztési adatok",
            "Utómunka sor", "Utómunka műveletek", "Rendszerhibák",
            "Futásnaplók", "Napi JSONL", "Összesített JSON", "Alkalmazás-napló",
            "Konzolnapló", "Beállítások",
        }
        self.assertTrue(required_sheets.issubset(set(workbook.sheetnames)))
        self.assertEqual(workbook["Karosszériák"].max_row, 2)
        self.assertEqual(workbook["Hegesztési adatok"].max_row, config["expected_count"] + 1)

        summary = pd.read_excel(BytesIO(data), sheet_name="Összesítő")
        metrics = dict(zip(summary["Mutató"], summary["Érték"]))
        self.assertEqual(metrics["Megfelelt darab (db)"], 1)
        self.assertEqual(metrics["Selejtes / utómunkás darab (db)"], 0)
        self.assertEqual(metrics["Pont-eltérés valószínűsége (%)"], 0.1)
        self.assertEqual(metrics["Eltérés módja"], "outside_limits")
        self.assertEqual(metrics["Szimulációs sebesség (%)"], 10_000)

        logs = pd.read_excel(BytesIO(data), sheet_name="Alkalmazás-napló")
        self.assertIn("test_operator_action", set(logs["event"]))
        run_logs = pd.read_excel(BytesIO(data), sheet_name="Futásnaplók")
        self.assertIn("body_id", run_logs.columns)
        workbook.close()

    def test_export_is_created_even_when_database_does_not_exist(self):
        missing_db = self.root / "not-created-yet.db"
        path, data, info = export_production_report(
            session_started_at=time.time(),
            fault_rate_percent=0.0,
            fault_mode="within_limits",
            automatic_worker_stopped=False,
            db_path=missing_db,
            log_dir=self.log_dir,
            export_timestamp=datetime(2026, 10, 17, 18, 41, 0, tzinfo=timezone.utc),
        )
        self.assertTrue(path.exists())
        self.assertTrue(data.startswith(b"PK"))
        self.assertEqual(info["session_body_count"], 0)
        workbook = load_workbook(BytesIO(data), read_only=True)
        self.assertIn("Hegesztési adatok", workbook.sheetnames)
        workbook.close()


if __name__ == "__main__":
    unittest.main()
