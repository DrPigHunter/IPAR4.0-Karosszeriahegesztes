"""Tests for the source-informed but deliberately non-certifying recipe plausibility audit."""
import unittest
from copy import deepcopy
from dataclasses import replace

from src.catalog import list_configurations
from src.parameter_audit import build_parameter_audit


class ParameterAuditTests(unittest.TestCase):
    def test_catalog_audit_returns_each_model_and_marks_screening_not_certification(self):
        configs = list_configurations()
        rows = build_parameter_audit(configs)
        self.assertEqual(len(rows), len(configs))
        self.assertEqual(len({row["Konfiguráció"] for row in rows}), len(configs))
        self.assertTrue(all(row["Pontok száma"] > 0 for row in rows))
        self.assertTrue(all(row["Áramhatár min (kA)"] > 0 for row in rows))
        self.assertTrue(all(row["Időhatár min (ms)"] > 0 for row in rows))
        self.assertTrue(all(row["Erőhatár min (kN)"] > 0 for row in rows))
        self.assertTrue(all(row["Referencia-ellenőrzés"] in {
            "FELÜLVIZSGÁLAT", "PLAUZIBILIS, NEM IGAZOLT"
        } for row in rows))

    def test_audit_flags_out_of_envelope_current_and_force_without_rewriting_recipe(self):
        original = list_configurations()[0]
        altered = deepcopy(original)
        altered["limits"] = replace(
            original["limits"], current_max=16.0, force_max=6.5
        )
        original_current_max = float(original["limits"].current_max)
        result = build_parameter_audit([altered])[0]
        self.assertEqual(result["Referencia-ellenőrzés"], "FELÜLVIZSGÁLAT")
        self.assertIn("15.0 kA", result["Megjegyzések"])
        self.assertIn("6.0 kN", result["Megjegyzések"])
        self.assertEqual(float(original["limits"].current_max), original_current_max)


if __name__ == "__main__":
    unittest.main()
