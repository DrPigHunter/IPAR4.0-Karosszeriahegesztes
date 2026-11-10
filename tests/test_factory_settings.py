"""Tests for operator-locked factory settings."""
import unittest

from src.factory_settings import (
    DEFAULT_NON_WEAR_DEFECT_PROBABILITY,
    FACTORY_EQUIPMENT_SETTINGS,
    SHIFT_BREAK_APPROX_WELD_POINTS,
    SHIFT_BREAK_INTERVAL_BODIES,
    apply_factory_settings,
)


# A gyári demonstrációs beállítások tesztjei az operátor által nem módosítható alapértékeket ellenőrzik.
class FactorySettingsTests(unittest.TestCase):
    # Ellenőrzöm, hogy az elektródacsere üteme a kódban rögzített műszakhatárhoz kapcsolódjon.
    def test_head_change_is_code_defined_at_simulated_shift_break(self):
        self.assertEqual(SHIFT_BREAK_INTERVAL_BODIES, 100)
        self.assertEqual(SHIFT_BREAK_APPROX_WELD_POINTS, 14_000)
        self.assertEqual(FACTORY_EQUIPMENT_SETTINGS["tool_change_interval_bodies"], 100)

    # A kopástól független háttérhiba valószínűsége alacsony és alapból rögzített legyen.
    def test_non_wear_defect_probability_is_low_and_locked_by_default(self):
        self.assertEqual(DEFAULT_NON_WEAR_DEFECT_PROBABILITY, 0.0001)
        self.assertEqual(FACTORY_EQUIPMENT_SETTINGS["non_wear_defect_probability"], 0.0001)

    # A mentett kezelői érték ne írja felül a kódban rögzített demonstrációs paramétereket.
    def test_saved_settings_are_overridden_by_factory_defaults(self):
        state = {
            "fault_rate": 0.1,
            "non_wear_defect_probability": 0.4,
            "fault_mode": "outside_limits",
            "wear_enabled": False,
            "wear_per_point_percent": 0.04,
            "auto_correct_wear": False,
            "auto_tool_change_enabled": False,
            "tool_change_interval_bodies": 1,
            "tool_change_duration_seconds": 99.0,
            "coolant_flow_l_min": 0.0,
            "coolant_inlet_temp_c": 80.0,
            "coolant_outlet_temp_c": 90.0,
            "speed_percent": 750,
            "wear_state": {"wear_percent": 12.3},
        }

        apply_factory_settings(state)

        for key, value in FACTORY_EQUIPMENT_SETTINGS.items():
            self.assertEqual(state[key], value)
        self.assertEqual(state["speed_percent"], 750)
        self.assertEqual(state["wear_state"], {"wear_percent": 12.3})

    # Csak a kijelölt alapbeállításokat állítsa vissza a konfiguráció.
    def test_only_declared_factory_parameters_are_overwritten(self):
        state = {"speed_percent": 250, "completed_cycles": 42, "body_id": "BODY-1"}
        apply_factory_settings(state)
        self.assertEqual(state["speed_percent"], 250)
        self.assertEqual(state["completed_cycles"], 42)
        self.assertEqual(state["body_id"], "BODY-1")


if __name__ == "__main__":
    unittest.main()
