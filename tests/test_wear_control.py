"""Tests for cumulative electrode wear, bounded correction, and monitor rework routing."""
import json
import tempfile
import unittest
from pathlib import Path

from src.catalog import list_configurations
from src.monitor import connect_db, process_event
from src.simulator import generate_body_events
from src.wear_control import (
    DEFAULT_TOOL_CHANGE_INTERVAL_BODIES,
    QUALITY_TARGET_PERCENT,
    apply_electrode_wear,
    ensure_wear_state,
    register_completed_body_for_tool,
    replace_electrode_tool,
    replace_tool_if_due,
)

CONFIG = list_configurations()[0]


class ElectrodeWearTests(unittest.TestCase):
    def test_wear_accumulates_and_controller_corrects_inside_catalog_limits(self):
        state = {"wear_percent": 20.0}
        _, events = generate_body_events(
            CONFIG["config_id"],
            fault_rate=0.0,
            seed=27,
            wear_state=state,
            wear_per_point_percent=0.0,
            wear_enabled=True,
            auto_correct_wear=True,
        )
        points = [event for event in events if event.get("event_type") == "weld_result"]
        self.assertTrue(points)
        self.assertGreaterEqual(state["wear_percent"], 20.0)
        self.assertTrue(any(event["auto_correction_applied"] for event in points))
        self.assertTrue(all(event["simulated_quality_index_percent"] >= QUALITY_TARGET_PERCENT
                            for event in points))
        limits = CONFIG["limits"]
        self.assertTrue(all(limits.current_min <= event["current_ka"] <= limits.current_max
                            for event in points))
        self.assertTrue(all(limits.weld_time_min <= event["weld_time_ms"] <= limits.weld_time_max
                            for event in points))
        self.assertTrue(all(event["process_quality_ok"] for event in points))

    def test_deliberately_injected_limit_fault_is_not_hidden_by_controller(self):
        point = CONFIG["points"][0]
        event = {
            "event_type": "weld_result",
            "weld_id": point["weld_id"],
            "current_ka": CONFIG["limits"].current_min - 0.01,
            "weld_time_ms": point["nominal_weld_time_ms"],
            "electrode_force_kn": point["nominal_electrode_force_kn"],
            "simulated_variation": "OUTSIDE_ACCEPTED_LIMITS",
        }
        apply_electrode_wear(
            [event], CONFIG, {"wear_percent": 0.0},
            wear_per_point_percent=0.0, wear_enabled=True, auto_correct=True,
        )
        self.assertLess(event["current_ka"], CONFIG["limits"].current_min)
        self.assertFalse(event["process_quality_ok"])
        self.assertEqual(event["auto_correction_steps"], 0)

    def test_wear_accumulates_between_calls(self):
        state = {}
        _, first = generate_body_events(
            CONFIG["config_id"], seed=7, wear_state=state,
            wear_enabled=True, auto_correct_wear=False, wear_per_point_percent=0.02,
        )
        first_wear = state["wear_percent"]
        _, second = generate_body_events(
            CONFIG["config_id"], seed=8, wear_state=state,
            wear_enabled=True, auto_correct_wear=False, wear_per_point_percent=0.02,
        )
        self.assertGreater(first_wear, 0.0)
        self.assertGreater(state["wear_percent"], first_wear)
        second_points = [e for e in second if e.get("event_type") == "weld_result"]
        self.assertTrue(all(e["electrode_wear_enabled"] for e in second_points))

    def test_disabled_wear_does_not_change_quality_or_measurements(self):
        base_id, base_events = generate_body_events(CONFIG["config_id"], seed=99)
        _, wear_events = generate_body_events(
            CONFIG["config_id"], seed=99, wear_state={"wear_percent": 80.0},
            wear_enabled=False, auto_correct_wear=True, wear_per_point_percent=0.03,
        )
        base_points = [e for e in base_events if e.get("event_type") == "weld_result"]
        wear_points = [e for e in wear_events if e.get("event_type") == "weld_result"]
        self.assertEqual([e["current_ka"] for e in base_points],
                         [e["current_ka"] for e in wear_points])
        self.assertEqual([e["weld_time_ms"] for e in base_points],
                         [e["weld_time_ms"] for e in wear_points])
        self.assertTrue(all(e["process_quality_ok"] for e in wear_points))

    def test_uncorrectable_wear_quality_is_detected_and_routed_to_rework(self):
        state = {"wear_percent": 100.0}
        body_id, events = generate_body_events(
            CONFIG["config_id"], seed=12, wear_state=state,
            wear_enabled=True, auto_correct_wear=False, wear_per_point_percent=0.0,
        )
        points = [e for e in events if e.get("event_type") == "weld_result"]
        self.assertTrue(points)
        self.assertTrue(all(e["process_quality_ok"] is False for e in points))

        with tempfile.TemporaryDirectory() as tmp:
            conn = connect_db(Path(tmp) / "wear-test.db")
            try:
                for event in events:
                    process_event(conn, event)
                row = conn.execute(
                    "SELECT status, parameter_errors FROM bodies WHERE body_id=?", (body_id,)
                ).fetchone()
                rework = conn.execute(
                    "SELECT reason FROM rework_queue WHERE body_id=?", (body_id,)
                ).fetchone()
                self.assertEqual(row["status"], "SELEJT / UTÓMUNKÁRA KÜLDVE")
                self.assertGreater(row["parameter_errors"], 0)
                self.assertIsNotNone(rework)
                self.assertIn("Elektródakopás", rework["reason"])
            finally:
                conn.close()

    def test_automatic_tool_replacement_after_configured_number_of_completed_bodies(self):
        state = ensure_wear_state({
            "wear_percent": 37.5,
            "total_weld_points": 300,
            "tool_weld_points": 60,
            "tool_corrected_points": 9,
        })
        self.assertEqual(DEFAULT_TOOL_CHANGE_INTERVAL_BODIES, 100)

        for body_number in (1, 2):
            change = register_completed_body_for_tool(
                state, interval_bodies=3, enabled=True, body_id=f"BODY-{body_number}"
            )
            self.assertIsNone(change)
            self.assertEqual(state["current_tool_number"], 1)

        change = register_completed_body_for_tool(
            state, interval_bodies=3, enabled=True, body_id="BODY-3"
        )
        self.assertIsNotNone(change)
        self.assertEqual(change["change_mode"], "AUTO")
        self.assertEqual(change["previous_tool_number"], 1)
        self.assertEqual(change["new_tool_number"], 2)
        self.assertEqual(change["tool_change_number"], 1)
        self.assertEqual(change["bodies_since_previous_change"], 3)
        self.assertAlmostEqual(change["wear_percent_before_reset"], 37.5)
        self.assertEqual(state["wear_percent"], 0.0)
        self.assertEqual(state["current_tool_number"], 2)
        self.assertEqual(state["tool_change_count"], 1)
        self.assertEqual(state["bodies_since_tool_change"], 0)
        self.assertEqual(state["tool_weld_points"], 0)
        self.assertEqual(state["tool_corrected_points"], 0)
        # Lifetime metrics remain available; only counters for the replaced tool reset.
        self.assertEqual(state["total_weld_points"], 300)

    def test_disabled_auto_replacement_can_be_enabled_after_tool_life_limit(self):
        state = ensure_wear_state({"wear_percent": 12.0})
        for body_number in range(1, 4):
            change = register_completed_body_for_tool(
                state, interval_bodies=3, enabled=False, body_id=f"BODY-{body_number}"
            )
            self.assertIsNone(change)
        self.assertEqual(state["bodies_since_tool_change"], 3)
        self.assertEqual(state["current_tool_number"], 1)

        change = replace_tool_if_due(
            state, interval_bodies=3, enabled=True, body_id="BODY-3"
        )
        self.assertIsNotNone(change)
        self.assertEqual(change["change_mode"], "AUTO")
        self.assertEqual(state["wear_percent"], 0.0)
        self.assertEqual(state["current_tool_number"], 2)
        self.assertEqual(state["bodies_since_tool_change"], 0)

    def test_manual_tool_replacement_resets_current_wear_but_preserves_lifetime_counts(self):
        state = ensure_wear_state({
            "wear_percent": 55.0,
            "total_weld_points": 900,
            "corrected_points": 120,
            "bodies_since_tool_change": 8,
            "tool_weld_points": 240,
            "tool_corrected_points": 30,
        })
        change = replace_electrode_tool(state, reason="MANUAL", body_id="BODY-LAST")
        self.assertEqual(change["change_mode"], "MANUAL")
        self.assertEqual(change["completed_body_id"], "BODY-LAST")
        self.assertEqual(change["wear_percent_before_reset"], 55.0)
        self.assertEqual(state["wear_percent"], 0.0)
        self.assertEqual(state["current_tool_number"], 2)
        self.assertEqual(state["bodies_since_tool_change"], 0)
        self.assertEqual(state["total_weld_points"], 900)
        self.assertEqual(state["corrected_points"], 120)
        self.assertEqual(state["tool_weld_points"], 0)
        self.assertEqual(state["tool_corrected_points"], 0)

    def test_tool_change_interval_validation(self):
        state = ensure_wear_state({})
        with self.assertRaises(ValueError):
            register_completed_body_for_tool(state, interval_bodies=0)
        with self.assertRaises(ValueError):
            replace_tool_if_due(state, interval_bodies=10_001)

    def test_wear_rate_validation(self):
        state = {}
        with self.assertRaises(ValueError):
            apply_electrode_wear([], CONFIG, state, wear_per_point_percent=1.01)


if __name__ == "__main__":
    unittest.main()
