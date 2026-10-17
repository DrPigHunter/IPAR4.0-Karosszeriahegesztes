"""Unit tests for catalogue-driven simulation event generation."""
import unittest

from src.catalog import list_configurations
from src.simulator import generate_body_events


class SimulatorTests(unittest.TestCase):
    def test_fault_free_cycle_has_all_model_specific_welds(self):
        config = list_configurations()[0]
        body_id, events = generate_body_events(config["config_id"], fault_rate=0.0, seed=7)

        self.assertTrue(body_id.startswith("BODY-"))
        self.assertEqual(events[0]["event_type"], "body_start")
        self.assertEqual(events[-1]["event_type"], "body_complete")
        weld_events = [event for event in events if event["event_type"] == "weld_result"]
        self.assertEqual(len(weld_events), config["expected_count"])
        self.assertEqual(
            [event["weld_id"] for event in weld_events],
            config["expected_weld_ids"],
        )
        self.assertTrue(all(not event.get("duplicate_simulated") for event in weld_events))
        self.assertTrue(all(not event.get("unexpected_simulated") for event in events))

    def test_default_fault_rate_is_low(self):
        import inspect
        parameter = inspect.signature(generate_body_events).parameters["fault_rate"]
        self.assertEqual(parameter.default, 0.0)


if __name__ == "__main__":
    unittest.main()
