"""Unit tests for complete cycles and controllable per-point variation."""
import inspect
import random
import unittest
from unittest.mock import patch

from src.catalog import list_configurations
from src.factory_settings import DEFAULT_NON_WEAR_DEFECT_PROBABILITY
from src.simulator import (
    _apply_non_wear_process_defect,
    _apply_point_variation,
    generate_body_events,
    MAX_FAULT_PROBABILITY,
    MAX_NON_WEAR_DEFECT_PROBABILITY,
)


class SimulatorTests(unittest.TestCase):
    def test_fault_free_cycle_has_all_model_specific_welds(self):
        for config in list_configurations():
            body_id, events = generate_body_events(config["config_id"], fault_rate=0.0, seed=7, non_wear_defect_probability=0.0)
            self.assertTrue(body_id.startswith("BODY-"))
            self.assertEqual(events[0]["event_type"], "body_start")
            self.assertEqual(events[-1]["event_type"], "body_complete")
            weld_events = [event for event in events if event["event_type"] == "weld_result"]
            self.assertEqual(len(weld_events), config["expected_count"])
            self.assertEqual([event["weld_id"] for event in weld_events], config["expected_weld_ids"])
            self.assertTrue(all("simulated_variation" not in event for event in weld_events))
            self.assertEqual(len({event["weld_id"] for event in weld_events}), config["expected_count"])

    def test_zero_probability_means_no_injected_measurements(self):
        config = list_configurations()[0]
        _, events = generate_body_events(config["config_id"], fault_rate=0.0, seed=19, non_wear_defect_probability=0.0)
        self.assertFalse(any("simulated_variation" in event for event in events))

    def test_within_limits_variation_remains_acceptable(self):
        config = list_configurations()[0]
        limits = config["limits"]
        event = {
            "current_ka": config["points"][0]["nominal_current_ka"],
            "weld_time_ms": config["points"][0]["nominal_weld_time_ms"],
            "electrode_force_kn": config["points"][0]["nominal_electrode_force_kn"],
        }
        _apply_point_variation(event, limits, random.Random(31), "within_limits")
        self.assertEqual(event["simulated_variation"], "WITHIN_ACCEPTED_LIMITS")
        self.assertTrue(limits.current_min <= event["current_ka"] <= limits.current_max)
        self.assertTrue(limits.weld_time_min <= event["weld_time_ms"] <= limits.weld_time_max)
        self.assertTrue(limits.force_min <= event["electrode_force_kn"] <= limits.force_max)

    def test_outside_limits_variation_exceeds_exactly_one_limit(self):
        config = list_configurations()[0]
        limits = config["limits"]
        event = {
            "current_ka": config["points"][0]["nominal_current_ka"],
            "weld_time_ms": config["points"][0]["nominal_weld_time_ms"],
            "electrode_force_kn": config["points"][0]["nominal_electrode_force_kn"],
        }
        _apply_point_variation(event, limits, random.Random(31), "outside_limits")
        self.assertEqual(event["simulated_variation"], "OUTSIDE_ACCEPTED_LIMITS")
        invalid = [
            not limits.current_min <= event["current_ka"] <= limits.current_max,
            not limits.weld_time_min <= event["weld_time_ms"] <= limits.weld_time_max,
            not limits.force_min <= event["electrode_force_kn"] <= limits.force_max,
        ]
        self.assertEqual(sum(invalid), 1)

    def test_probability_is_limited_to_0_1_percent_per_point(self):
        self.assertEqual(MAX_FAULT_PROBABILITY, 0.001)
        with self.assertRaises(ValueError):
            generate_body_events(list_configurations()[0]["config_id"], fault_rate=0.00101)

    def test_default_fault_rate_is_zero(self):
        self.assertEqual(DEFAULT_NON_WEAR_DEFECT_PROBABILITY, 0.0001)
        self.assertEqual(MAX_NON_WEAR_DEFECT_PROBABILITY, 0.001)
        parameter = inspect.signature(generate_body_events).parameters["fault_rate"]
        self.assertEqual(parameter.default, 0.0)
        background_parameter = inspect.signature(generate_body_events).parameters["non_wear_defect_probability"]
        self.assertEqual(background_parameter.default, DEFAULT_NON_WEAR_DEFECT_PROBABILITY)


    def test_background_defect_probability_creates_non_wear_limit_breach(self):
        config = list_configurations()[0]

        class AlwaysTriggerRng:
            @staticmethod
            def random():
                return 0.0

            @staticmethod
            def uniform(a, b):
                return (a + b) / 2.0

            @staticmethod
            def choice(values):
                return values[0]

        with patch("src.simulator.random.Random", return_value=AlwaysTriggerRng()):
            _, events = generate_body_events(
                config["config_id"], fault_rate=0.0, seed=1,
                non_wear_defect_probability=DEFAULT_NON_WEAR_DEFECT_PROBABILITY,
            )

        points = [event for event in events if event.get("event_type") == "weld_result"]
        self.assertTrue(points)
        self.assertTrue(all(event["simulated_variation"] == "BACKGROUND_PROCESS_DEFECT" for event in points))
        self.assertTrue(all(event["non_wear_process_defect"] is True for event in points))
        self.assertTrue(all(event["simulated_failure_source"] == "NON_WEAR_PROCESS_VARIATION" for event in points))
        self.assertTrue(all(event["simulated_failure_cause_hypothesis"] for event in points))
        limits = config["limits"]
        self.assertTrue(any(event["current_ka"] > limits.current_max for event in points))

    def test_background_defect_probability_is_validated(self):
        config = list_configurations()[0]
        with self.assertRaises(ValueError):
            generate_body_events(config["config_id"], non_wear_defect_probability=0.00101)


if __name__ == "__main__":
    unittest.main()
