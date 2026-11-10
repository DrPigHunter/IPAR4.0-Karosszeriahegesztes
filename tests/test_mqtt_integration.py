"""Real MQTT -> monitor -> SQLite integration tests.

Run explicitly with RUN_MQTT_INTEGRATION=1 and a live Mosquitto broker/monitor.
The normal unit-test suite skips these tests when that environment flag is absent.
"""
from __future__ import annotations

import os
import sqlite3
import unittest

from src.catalog import list_configurations
from src.monitor import DB_PATH, REWORK_WAITING
from src.monitor_wait import wait_for_body_completion
from src.simulator import generate_body_events, publish_events


@unittest.skipUnless(
    os.environ.get("RUN_MQTT_INTEGRATION") == "1",
    "Requires a live MQTT broker and monitor; run via the mqtt-integration CI job.",
)
# Ezek az integrációs tesztek az élő Mosquitto broker és a monitor közötti teljes adatutat ellenőrzik.
class MqttEndToEndTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not DB_PATH.exists():
            raise RuntimeError(f"Monitor adatbázisa nem jött létre: {DB_PATH}")

    # Egy komplett oldalfal eseménysorát küldöm el a broker felé, opcionálisan szándékos határérték-túllépéssel.
    def publish_cycle(self, inject_out_of_range_parameter: bool = False) -> tuple[str, dict]:
        config = list_configurations()[0]
        body_id, events = generate_body_events(config["config_id"], fault_rate=0.0, seed=731, non_wear_defect_probability=0.0)
        if inject_out_of_range_parameter:
            limits = config["limits"]
            weld_event = next(event for event in events if event.get("event_type") == "weld_result")
            weld_event["current_ka"] = limits.current_max + 1.0

        publish_events(events, delay_ms=0.0)
        result = wait_for_body_completion(body_id, DB_PATH, timeout_seconds=20.0, poll_interval_seconds=0.02)
        return body_id, result

    # Hibátlan adatsor MQTT-n keresztül is megfelelő státuszba jusson.
    def test_good_sidewall_flows_through_mqtt_and_monitor_as_acceptable(self):
        body_id, result = self.publish_cycle()
        self.assertEqual(result["body_id"], body_id)
        self.assertEqual(result["status"], "MEGFELELŐ")
        with sqlite3.connect(DB_PATH, timeout=5) as conn:
            row = conn.execute(
                "SELECT expected_count,event_count,status,parameter_errors FROM bodies WHERE body_id=?",
                (body_id,),
            ).fetchone()
        self.assertIsNotNone(row)
        expected_count, event_count, status, parameter_errors = row
        self.assertGreater(expected_count, 0)
        self.assertEqual(event_count, expected_count)
        self.assertEqual(status, "MEGFELELŐ")
        self.assertEqual(parameter_errors, 0)

    # Határérték-túllépés után az utómunka-sor automatikusan kapjon bejegyzést.
    def test_out_of_range_measurement_flows_to_automatic_rework_queue(self):
        body_id, result = self.publish_cycle(inject_out_of_range_parameter=True)
        self.assertEqual(result["body_id"], body_id)
        self.assertTrue(result["status"].startswith("SELEJT"))
        with sqlite3.connect(DB_PATH, timeout=5) as conn:
            body = conn.execute(
                "SELECT status,parameter_errors FROM bodies WHERE body_id=?",
                (body_id,),
            ).fetchone()
            rework = conn.execute(
                "SELECT reason,status FROM rework_queue WHERE body_id=?",
                (body_id,),
            ).fetchone()
        self.assertIsNotNone(body)
        self.assertGreater(body[1], 0)
        self.assertIsNotNone(rework)
        self.assertIn("Paraméterhibák", rework[0])
        self.assertEqual(rework[1], REWORK_WAITING)


if __name__ == "__main__":
    unittest.main()
