"""Tests for bounded and predictable BODYLINE simulation speed scaling."""
import unittest

from src.speed_control import (
    CYCLE_TARGET_SECONDS,
    DEFAULT_SPEED_PERCENT,
    DEFAULT_TARGET_CYCLE_SECONDS,
    MAX_SPEED_PERCENT,
    MIN_SPEED_PERCENT,
    base_publish_delay_ms,
    normalize_speed_percent,
    scaled_inter_body_pause_seconds,
    scaled_publish_delay_ms,
)


# A sebességtesztek a névleges ciklusidő számítását és a 100–10 000%-os skálázást ellenőrzik.
class SpeedControlTests(unittest.TestCase):
    # Alapsebességen 95 másodperces cél és 100 másodperces KPI-határ legyen.
    def test_default_speed_targets_a_95_second_cycle_and_100_second_limit(self):
        self.assertEqual(DEFAULT_SPEED_PERCENT, 100)
        self.assertEqual(DEFAULT_TARGET_CYCLE_SECONDS, 95.0)
        self.assertEqual(CYCLE_TARGET_SECONDS, 100)
        for event_count in (117, 120, 144):
            delay_ms = base_publish_delay_ms(event_count)
            self.assertAlmostEqual(delay_ms * event_count / 1000.0, 95.0)
        self.assertEqual(scaled_inter_body_pause_seconds(10, DEFAULT_SPEED_PERCENT), 10.0)

    # Érvénytelen pontszám vagy célidő esetén a késleltetés-számítás utasítsa el a bemenetet.
    def test_targeted_publish_delay_rejects_invalid_cycle_inputs(self):
        with self.assertRaisesRegex(ValueError, "pozitív egész"):
            base_publish_delay_ms(0)
        with self.assertRaisesRegex(ValueError, "pozitív, véges"):
            base_publish_delay_ms(120, 0)
        with self.assertRaisesRegex(ValueError, "pozitív, véges"):
            base_publish_delay_ms(120, float("inf"))

    # Maximális sebességen mind a pontközi, mind a ciklusközi várakozás csökkenjen.
    def test_maximum_speed_scales_publish_delay_and_inter_body_pause(self):
        self.assertEqual(MAX_SPEED_PERCENT, 10_000)
        self.assertAlmostEqual(scaled_publish_delay_ms(90, MAX_SPEED_PERCENT), 0.9)
        self.assertAlmostEqual(scaled_inter_body_pause_seconds(10, MAX_SPEED_PERCENT), 0.1)

    # A sebesség maradjon a megengedett határok között.
    def test_speed_never_normalizes_below_minimum_or_above_maximum(self):
        self.assertEqual(normalize_speed_percent(-50), MIN_SPEED_PERCENT)
        self.assertEqual(normalize_speed_percent(99), MIN_SPEED_PERCENT)
        self.assertEqual(normalize_speed_percent(10_001), MAX_SPEED_PERCENT)
        self.assertEqual(normalize_speed_percent(50_000), MAX_SPEED_PERCENT)

    # Egész és lebegőpontos sebességértéket is fogadjon el.
    def test_speed_accepts_number_input_values(self):
        self.assertEqual(normalize_speed_percent("1500"), 1500)
        self.assertEqual(normalize_speed_percent(1234.4), 1234)
        self.assertEqual(normalize_speed_percent(1234.6), 1235)

    # Nem számszerű bemenetre érthető hibát várok.
    def test_invalid_speed_input_raises_clear_error(self):
        with self.assertRaisesRegex(ValueError, "számnak kell lennie"):
            normalize_speed_percent("gyors")
        with self.assertRaisesRegex(ValueError, "véges számnak kell lennie"):
            normalize_speed_percent(float("nan"))

    # Negatív várakozási idő ne kerülhessen a szimulátorba.
    def test_negative_base_delays_are_rejected(self):
        with self.assertRaises(ValueError):
            scaled_publish_delay_ms(-1, 100)
        with self.assertRaises(ValueError):
            scaled_inter_body_pause_seconds(-1, 100)


if __name__ == "__main__":
    unittest.main()
