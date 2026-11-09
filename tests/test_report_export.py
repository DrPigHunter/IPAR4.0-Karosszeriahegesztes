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
from src.report_export import append_application_log, export_production_report, split_long_sheets
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
        _, events = generate_body_events(config["config_id"], fault_rate=0.0, seed=123, non_wear_defect_probability=0.0)
        for event in events:
            process_event(self.conn, event, log_dir=self.log_dir)
        return config

    def test_large_tables_are_split_without_losing_rows(self):
        source = pd.DataFrame({"row_id": list(range(7)), "payload": [f"row-{i}" for i in range(7)]})
        sheets = split_long_sheets({"Hegesztési adatok": source}, max_data_rows=3)

        self.assertEqual(list(sheets), [
            "Hegesztési adatok 1", "Hegesztési adatok 2", "Hegesztési adatok 3"
        ])
        self.assertEqual([len(frame) for frame in sheets.values()], [3, 3, 1])
        self.assertTrue(all(len(name) <= 31 for name in sheets))
        combined = pd.concat(sheets.values(), ignore_index=True)
        pd.testing.assert_frame_equal(combined, source)

    def test_short_tables_keep_original_sheet_name(self):
        source = pd.DataFrame({"row_id": [1, 2]})
        sheets = split_long_sheets({"Karosszériák": source}, max_data_rows=3)
        self.assertEqual(list(sheets), ["Karosszériák"])
        pd.testing.assert_frame_equal(sheets["Karosszériák"], source)

    def test_sheet_split_rejects_non_positive_row_limit(self):
        with self.assertRaises(ValueError):
            split_long_sheets({"rows": pd.DataFrame({"x": [1]})}, max_data_rows=0)

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
        self.assertEqual(path.name, "BODYLINE_jelentes_2026-10-17_18-40-20_000000.xlsx")
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
            "Konzolnapló", "Beállítások", "Kopás és önkorrekció", "Eszközcsere-napló", "Paraméter-audit", "Források",
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
        self.assertIn("Információ", run_logs.columns)
        self.assertTrue(run_logs["Információ"].str.contains("Nincs rögzített adat").any())
        sources = pd.read_excel(BytesIO(data), sheet_name="Források")
        self.assertTrue(sources["URL"].str.contains("twi-global.com").any())
        self.assertTrue(sources["URL"].str.contains("springer.com").any())
        workbook.close()

    def test_electrode_wear_summary_and_settings_are_exported(self):
        config = list_configurations()[0]
        wear_state = {"wear_percent": 10.0}
        body_id, events = generate_body_events(
            config["config_id"], seed=55, wear_state=wear_state, non_wear_defect_probability=0.0,
            wear_per_point_percent=0.03, wear_enabled=True, auto_correct_wear=True,
        )
        for event in events:
            process_event(self.conn, event, log_dir=self.log_dir)
        append_application_log(
            "electrode_tool_replaced",
            {
                "change_mode": "AUTO",
                "completed_body_id": body_id,
                "previous_tool_number": 1,
                "new_tool_number": 2,
                "tool_change_number": 1,
                "wear_percent_before_reset": 18.5,
                "replacement_interval_bodies": 2,
                "bodies_since_previous_change": 2,
                "tool_weld_points_before_reset": config["expected_count"],
                "tool_corrected_points_before_reset": 12,
                "tool_uncorrectable_points_before_reset": 1,
            },
            log_dir=self.log_dir,
        )

        path, data, _ = export_production_report(
            session_started_at=time.time() - 120,
            fault_rate_percent=0.0,
            fault_mode="within_limits",
            automatic_worker_stopped=True,
            db_path=self.db_path,
            log_dir=self.log_dir,
            export_timestamp=datetime(2026, 10, 17, 18, 44, 0, tzinfo=timezone.utc),
            wear_enabled=True,
            wear_per_point_percent=0.03,
            auto_correct_wear=True,
            auto_tool_change_enabled=True,
            tool_change_interval_bodies=2,
        )
        self.assertTrue(path.exists())
        workbook = load_workbook(BytesIO(data), read_only=True, data_only=True)
        self.assertIn("Kopás és önkorrekció", workbook.sheetnames)
        workbook.close()

        wear_summary = pd.read_excel(BytesIO(data), sheet_name="Kopás és önkorrekció")
        total = wear_summary[wear_summary["Modellazonosító"] == "ÖSSZESEN"].iloc[0]
        self.assertEqual(int(total["Hegesztési pontok"]), config["expected_count"])
        self.assertGreaterEqual(float(total["Legnagyobb kopás (%)"]), 10.0)
        settings = pd.read_excel(BytesIO(data), sheet_name="Beállítások")
        setting_values = dict(zip(settings["Beállítás"], settings["Érték"]))
        self.assertEqual(setting_values["Elektródakopás modellezése"], True)
        self.assertEqual(setting_values["Kopás hegesztési pontonként (%)"], 0.03)
        self.assertEqual(setting_values["Automatikus önkorrekció"], True)
        self.assertEqual(setting_values["Automatikus eszközcsere"], True)
        self.assertEqual(setting_values["Eszközcsere minden X oldalfalciklus után"], 2)
        self.assertEqual(setting_values["Kopástól független alapfolyamat-hiba / pont (%)"], 0.01)

        tool_changes = pd.read_excel(BytesIO(data), sheet_name="Eszközcsere-napló")
        self.assertEqual(len(tool_changes), 1)
        self.assertEqual(tool_changes.iloc[0]["Csere módja"], "AUTO")
        self.assertEqual(tool_changes.iloc[0]["Előző eszköz"], 1)
        self.assertEqual(tool_changes.iloc[0]["Új eszköz"], 2)
        self.assertEqual(tool_changes.iloc[0]["Karosszéria-intervallum"], 2)
        self.assertAlmostEqual(tool_changes.iloc[0]["Csere előtti kopás (%)"], 18.5)

    def test_two_exports_with_same_second_keep_distinct_files(self):
        timestamp = datetime(2026, 10, 17, 18, 42, 0, tzinfo=timezone.utc)
        first_path, _, _ = export_production_report(
            session_started_at=time.time(),
            fault_rate_percent=0.0,
            fault_mode="within_limits",
            automatic_worker_stopped=True,
            db_path=self.db_path,
            log_dir=self.log_dir,
            export_timestamp=timestamp,
        )
        second_path, _, _ = export_production_report(
            session_started_at=time.time(),
            fault_rate_percent=0.0,
            fault_mode="within_limits",
            automatic_worker_stopped=True,
            db_path=self.db_path,
            log_dir=self.log_dir,
            export_timestamp=timestamp.replace(microsecond=1),
        )
        self.assertNotEqual(first_path, second_path)
        self.assertTrue(first_path.exists())
        self.assertTrue(second_path.exists())

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
