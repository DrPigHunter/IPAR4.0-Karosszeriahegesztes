"""Validate structure and uniqueness of the checked-in vehicle sidewall catalogue."""
import unittest
from src.catalog import list_configurations


class CatalogTests(unittest.TestCase):
    def test_ten_model_part_configurations(self):
        configs = list_configurations()
        self.assertEqual(len(configs), 10)
        self.assertTrue(all(config["part"] == "Oldalfal (bal)" for config in configs))

    def test_each_model_has_own_spots_and_limits(self):
        configs = list_configurations()
        ids = [cfg["config_id"] for cfg in configs]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(len({tuple(cfg["expected_weld_ids"]) for cfg in configs}), 10)
        self.assertEqual(len({(cfg["limits"].current_min, cfg["limits"].current_max,
                               cfg["limits"].weld_time_min, cfg["limits"].weld_time_max,
                               cfg["limits"].force_min, cfg["limits"].force_max)
                              for cfg in configs}), 10)
        for cfg in configs:
            self.assertEqual(len(cfg["points"]), cfg["expected_count"])
            self.assertEqual(len(cfg["expected_weld_ids"]), len(set(cfg["expected_weld_ids"])))


if __name__ == "__main__":
    unittest.main()
