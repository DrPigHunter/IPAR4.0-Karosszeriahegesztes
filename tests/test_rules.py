import unittest
from src.rules import evaluate_body, validate_event

# A szabálytesztek a paraméterhatárokat, pontteljességet és duplikációt ellenőrzik.
class ValidationTests(unittest.TestCase):
    # Határértéken belüli paramétereknél ne jelezzen hibát.
    def test_valid_parameters(self):
        self.assertEqual(validate_event({"current_ka":9.0,"weld_time_ms":250,"electrode_force_kn":3.5}), [])
    # Határértéken kívüli áram-, idő- vagy erőértéknél jelezzen eltérést.
    def test_out_of_range_parameters(self):
        self.assertEqual(len(validate_event({"current_ka":13.5,"weld_time_ms":250,"electrode_force_kn":3.5})), 1)
    # Hiányzó pont esetén az oldalfal ne legyen megfelelő.
    def test_missing_weld_point(self):
        result=evaluate_body(["W001","W002"],["W001"],0); self.assertEqual(result["missing_ids"],["W002"]); self.assertNotEqual(result["status"],"MEGFELELŐ")
    # Duplikált pontazonosító esetén legyen hiba.
    def test_duplicate_weld_point(self):
        result=evaluate_body(["W001"],["W001","W001"],0); self.assertEqual(result["duplicate_ids"],["W001"]); self.assertNotEqual(result["status"],"MEGFELELŐ")
    # Teljes, hibamentes pontlista esetén MEGFELELŐ státuszt várok.
    def test_clean_body(self): self.assertEqual(evaluate_body(["W001","W002"],["W001","W002"],0)["status"],"MEGFELELŐ")

if __name__ == "__main__": unittest.main()
