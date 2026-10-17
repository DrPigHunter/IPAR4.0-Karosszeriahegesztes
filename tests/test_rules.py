import unittest

from src.rules import evaluate_body, validate_event


class ValidationTests(unittest.TestCase):
    def test_valid_parameters(self):
        event = {"current_ka": 9.0, "weld_time_ms": 250, "electrode_force_kn": 3.5}
        self.assertEqual(validate_event(event), [])

    def test_out_of_range_parameters(self):
        event = {"current_ka": 13.5, "weld_time_ms": 250, "electrode_force_kn": 3.5}
        self.assertEqual(len(validate_event(event)), 1)

    def test_missing_weld_point(self):
        result = evaluate_body(["W001", "W002"], ["W001"], 0)
        self.assertEqual(result["missing_ids"], ["W002"])
        self.assertNotEqual(result["status"], "MEGFELELŐ")

    def test_duplicate_weld_point(self):
        result = evaluate_body(["W001"], ["W001", "W001"], 0)
        self.assertEqual(result["duplicate_ids"], ["W001"])
        self.assertNotEqual(result["status"], "MEGFELELŐ")

    def test_clean_body(self):
        result = evaluate_body(["W001", "W002"], ["W001", "W002"], 0)
        self.assertEqual(result["status"], "MEGFELELŐ")


if __name__ == "__main__":
    unittest.main()
