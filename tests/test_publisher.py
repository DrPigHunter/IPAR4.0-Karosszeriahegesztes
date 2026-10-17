"""Unit tests for reliable, pipelined MQTT event publishing."""
import json
import unittest
from unittest.mock import patch

from src import simulator


class FakePublishInfo:
    def __init__(self, owner, rc=0):
        self.owner = owner
        self.rc = rc
        self.published = False

    def wait_for_publish(self, timeout=None):
        # This assertion ensures the publisher queues the complete cycle before
        # synchronously waiting for acknowledgements one by one.
        self.owner.wait_calls.append((self, timeout, len(self.owner.published_payloads)))
        self.published = self.rc == 0

    def is_published(self):
        return self.published


class FakeMqttClient:
    def __init__(self, rc=0):
        self.rc = rc
        self.published_payloads = []
        self.inflight_limits = []
        self.queue_limits = []
        self.wait_calls = []
        self.connected = False
        self.loop_running = False
        self.disconnected = False

    def max_inflight_messages_set(self, value):
        self.inflight_limits.append(value)

    def max_queued_messages_set(self, value):
        self.queue_limits.append(value)

    def connect(self, host, port, keepalive=30):
        self.connected = (host, port, keepalive)

    def loop_start(self):
        self.loop_running = True

    def publish(self, topic, payload, qos=0):
        self.published_payloads.append((topic, json.loads(payload), qos))
        return FakePublishInfo(self, self.rc)

    def loop_stop(self):
        self.loop_running = False

    def disconnect(self):
        self.disconnected = True


class PublisherTests(unittest.TestCase):
    def test_queues_all_ordered_events_then_checks_qos1_acknowledgements(self):
        client = FakeMqttClient()
        events = [
            {"event_type": "body_start", "body_id": "BODY-1"},
            {"event_type": "weld_result", "body_id": "BODY-1", "weld_id": "W001"},
            {"event_type": "body_complete", "body_id": "BODY-1"},
        ]
        with patch("src.simulator.mqtt.Client", return_value=client), patch("src.simulator.time.sleep") as sleep:
            simulator.publish_events(events, host="localhost", port=1883, delay_ms=0.9)

        self.assertEqual(client.inflight_limits, [1000])
        self.assertEqual(client.queue_limits, [0])
        self.assertEqual([item[1]["event_type"] for item in client.published_payloads],
                         ["body_start", "weld_result", "body_complete"])
        self.assertTrue(all(item[2] == 1 for item in client.published_payloads))
        self.assertTrue(all("timestamp" in item[1] for item in client.published_payloads))
        self.assertEqual(len(client.wait_calls), len(events))
        self.assertTrue(all(call[2] == len(events) for call in client.wait_calls))
        self.assertEqual(sleep.call_count, len(events))
        self.assertFalse(client.loop_running)
        self.assertTrue(client.disconnected)

    def test_negative_delay_is_rejected_before_connect(self):
        client = FakeMqttClient()
        with patch("src.simulator.mqtt.Client", return_value=client):
            with self.assertRaisesRegex(ValueError, "nem lehet negatív"):
                simulator.publish_events([{"event_type": "body_start"}], delay_ms=-0.1)
        self.assertFalse(client.connected)

    def test_publish_failure_still_stops_network_loop_and_disconnects(self):
        client = FakeMqttClient(rc=1)
        with patch("src.simulator.mqtt.Client", return_value=client), patch("src.simulator.time.sleep"):
            with self.assertRaisesRegex(RuntimeError, "sorba állításkor"):
                simulator.publish_events([{"event_type": "body_start"}], delay_ms=0)
        self.assertFalse(client.loop_running)
        self.assertTrue(client.disconnected)


if __name__ == "__main__":
    unittest.main()
