"""Tests for bounded and predictable BODYLINE simulation speed scaling."""
import unittest

from src.speed_control import (
    DEFAULT_SPEED_PERCENT,
    MAX_SPEED_PERCENT,
    MIN_SPEED_PERCENT,
    normalize_speed_percent,
    scaled_inter_body_pause_seconds,
    scaled_publish_delay_ms,
)


class SpeedControlTests(unittest.TestCase):
    def test_default_is_original_speed(self):
        self.assertEqual(DEFAULT_SPEED_PERCENT, 100)
        self.assertEqual(scaled_publish_delay_ms(90, DEFAULT_SPEED_PERCENT), 90.0)
        self.assertEqual(scaled_inter_body_pause_seconds(10, DEFAULT_SPEED_PERCENT), 10.0)

    def test_maximum_speed_scales_publish_delay_and_inter_body_pause(self):
        self.assertEqual(MAX_SPEED_PERCENT, 10_000)
        self.assertAlmostEqual(scaled_publish_delay_ms(90, MAX_SPEED_PERCENT), 0.9)
        self.assertAlmostEqual(scaled_inter_body_pause_seconds(10, MAX_SPEED_PERCENT), 0.1)

    def test_speed_never_normalizes_below_minimum_or_above_maximum(self):
        self.assertEqual(normalize_speed_percent(-50), MIN_SPEED_PERCENT)
        self.assertEqual(normalize_speed_percent(99), MIN_SPEED_PERCENT)
        self.assertEqual(normalize_speed_percent(10_001), MAX_SPEED_PERCENT)
        self.assertEqual(normalize_speed_percent(50_000), MAX_SPEED_PERCENT)

    def test_speed_accepts_number_input_values(self):
        self.assertEqual(normalize_speed_percent("1500"), 1500)
        self.assertEqual(normalize_speed_percent(1234.4), 1234)
        self.assertEqual(normalize_speed_percent(1234.6), 1235)

    def test_invalid_speed_input_raises_clear_error(self):
        with self.assertRaisesRegex(ValueError, "számnak kell lennie"):
            normalize_speed_percent("gyors")
        with self.assertRaisesRegex(ValueError, "véges számnak kell lennie"):
            normalize_speed_percent(float("nan"))

    def test_negative_base_delays_are_rejected(self):
        with self.assertRaises(ValueError):
            scaled_publish_delay_ms(-1, 100)
        with self.assertRaises(ValueError):
            scaled_inter_body_pause_seconds(-1, 100)


if __name__ == "__main__":
    unittest.main()
