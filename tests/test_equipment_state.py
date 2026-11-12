"""Durable equipment-state tests."""
import tempfile
import unittest
from pathlib import Path

from src.equipment_state import load_equipment_state, save_equipment_state


# Ezek a tesztek a kopási és elektródaállapot fájlba mentését, majd újratöltését vizsgálják.
class EquipmentStateTests(unittest.TestCase):
    # Újratöltés után is ugyanazt a kopást és beállításokat várom vissza.
    def test_tool_wear_and_settings_survive_reload(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "data" / "equipment_state.json"
            state = {
                "wear_state": {
                    "wear_percent": 41.25,
                    "current_tool_number": 3,
                    "tool_change_count": 2,
                    "bodies_since_tool_change": 17,
                    "tool_change_pending": True,
                    "pending_tool_change_body_id": "BODY-17",
                },
                "wear_per_point_percent": 0.005,
                "auto_tool_change_enabled": True,
                "tool_change_interval_bodies": 100,
                "tool_change_duration_seconds": 5.0,
                "coolant_flow_l_min": 6.0,
                "coolant_inlet_temp_c": 20.0,
                "coolant_outlet_temp_c": 30.0,
                "do_not_persist_this": "dashboard-session-only",
            }
            saved = save_equipment_state(state, path)
            loaded = load_equipment_state(path)
            self.assertEqual(saved, path)
            self.assertEqual(loaded["wear_state"]["wear_percent"], 41.25)
            self.assertEqual(loaded["wear_state"]["current_tool_number"], 3)
            self.assertTrue(loaded["wear_state"]["tool_change_pending"])
            self.assertEqual(loaded["wear_state"]["pending_tool_change_body_id"], "BODY-17")
            self.assertEqual(loaded["tool_change_interval_bodies"], 100)
            self.assertEqual(loaded["coolant_flow_l_min"], 6.0)
            self.assertNotIn("do_not_persist_this", loaded)

    # Hiányzó vagy sérült fájlnál a betöltés biztonságos alapállapotra essen vissza.
    def test_missing_or_malformed_state_file_falls_back_to_empty_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "missing.json"
            self.assertEqual(load_equipment_state(path), {})
            path.write_text("{not-json", encoding="utf-8")
            self.assertEqual(load_equipment_state(path), {})

    # A hibás belső állapotot ne vegyük át érvényes kopási adatként.
    def test_invalid_nested_wear_state_is_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "equipment_state.json"
            path.write_text('{"wear_state": "broken", "tool_change_interval_bodies": 22}', encoding="utf-8")
            loaded = load_equipment_state(path)
            self.assertNotIn("wear_state", loaded)
            self.assertEqual(loaded["tool_change_interval_bodies"], 22)


if __name__ == "__main__":
    unittest.main()
