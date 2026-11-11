"""A virtuális érzékelő-metaadatok és logikai beavatkozási pontok ellenőrzése."""
import unittest

from src.virtual_sensors import (
    actuator_catalog,
    attach_virtual_sensor_metadata,
    operator_interaction_catalog,
    sensor_catalog,
)


class VirtualSensorTests(unittest.TestCase):
    def test_three_measurement_channels_have_signal_units_and_sample_method(self):
        channels = sensor_catalog()
        self.assertEqual({item["signal"] for item in channels}, {
            "current_ka", "weld_time_ms", "electrode_force_kn"
        })
        self.assertTrue(all(item["unit"] for item in channels))
        self.assertTrue(all("egy érték minden hegesztési pontnál" in item["sampling"] for item in channels))

    def test_sensor_metadata_is_attached_only_to_weld_results(self):
        start = {"event_type": "body_start"}
        self.assertIs(attach_virtual_sensor_metadata(start), start)
        event = {"event_type": "weld_result", "current_ka": 8.5}
        result = attach_virtual_sensor_metadata(event)
        self.assertEqual(result["signal_origin"], "SIMULATED_VIRTUAL_SENSOR")
        self.assertEqual(result["sensor_sources"]["current_ka"], "VS-CURRENT-01")
        self.assertEqual(result["sampling_method"], "ONE_EVENT_SAMPLE_PER_WELD_POINT")

    def test_logical_actuators_are_explicitly_not_physical(self):
        actuators = actuator_catalog()
        self.assertGreaterEqual(len(actuators), 3)
        self.assertTrue(all(item["physical_output"] is False for item in actuators))

    def test_operator_interaction_points_are_described(self):
        points = operator_interaction_catalog()
        self.assertGreaterEqual(len(points), 4)
        self.assertTrue(any("indítása" in item["point"] for item in points))
        self.assertTrue(any("Utómunka" in item["point"] for item in points))


if __name__ == "__main__":
    unittest.main()
