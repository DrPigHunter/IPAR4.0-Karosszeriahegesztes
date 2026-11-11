"""A konfigurálható helyi vagy LAN MQTT-végpont bemeneti ellenőrzései."""
import unittest

from src.network_config import load_mqtt_config


class NetworkConfigTests(unittest.TestCase):
    def test_defaults_keep_existing_local_setup(self):
        config = load_mqtt_config({})
        self.assertEqual(config.host, "127.0.0.1")
        self.assertEqual(config.port, 1883)
        self.assertEqual(config.topic, "welding/events")

    def test_private_lan_endpoint_can_be_configured(self):
        config = load_mqtt_config({
            "BODYLINE_MQTT_HOST": "192.168.1.50",
            "BODYLINE_MQTT_PORT": "1884",
            "BODYLINE_MQTT_TOPIC": "bodyline/production",
        })
        self.assertEqual(config.host, "192.168.1.50")
        self.assertEqual(config.port, 1884)
        self.assertEqual(config.topic, "bodyline/production")

    def test_empty_host_or_topic_is_rejected(self):
        for values in (
            {"BODYLINE_MQTT_HOST": " "},
            {"BODYLINE_MQTT_TOPIC": ""},
        ):
            with self.subTest(values=values), self.assertRaises(ValueError):
                load_mqtt_config(values)

    def test_invalid_port_is_rejected(self):
        for value in ("0", "65536", "not-a-port"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                load_mqtt_config({"BODYLINE_MQTT_PORT": value})


if __name__ == "__main__":
    unittest.main()
