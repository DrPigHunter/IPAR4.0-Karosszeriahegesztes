"""Smoke test that the Streamlit dashboard renders and reports its source version."""
import hashlib
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest


ROOT = Path(__file__).resolve().parents[1]


class DashboardRenderTests(unittest.TestCase):
    def test_dashboard_renders_main_tabs_and_signals_current_source(self):
        with tempfile.TemporaryDirectory() as folder:
            ready_file = Path(folder) / "dashboard.ready"
            expected_hash = hashlib.sha256((ROOT / "src" / "dashboard.py").read_bytes()).hexdigest()
            with patch.dict(os.environ, {"BODYLINE_DASHBOARD_READY_FILE": str(ready_file)}):
                app = AppTest.from_file(str(ROOT / "src" / "dashboard.py"), default_timeout=30).run()

            self.assertEqual(
                len(app.exception),
                0,
                msg="Dashboard raised a Streamlit exception: "
                + "; ".join(str(item.value) for item in app.exception),
            )

            rendered_markdown = "\\n".join(item.value for item in app.markdown)
            rendered_titles = "\\n".join(item.value for item in app.title)
            rendered_subheaders = "\\n".join(item.value for item in app.subheader)

            visible_text = "\\n".join((rendered_markdown, rendered_titles, rendered_subheaders))
            self.assertIn("Gyártócella élő nézete", visible_text)
            self.assertIn("Production log", visible_text)
            self.assertTrue(
                any(button.label == "⏻ Kilépés és minden leállítása" for button in app.button),
                "Dashboard shutdown button is not visible.",
            )
            self.assertTrue(ready_file.is_file(), "Dashboard did not write its readiness signal.")
            self.assertEqual(
                ready_file.read_text(encoding="utf-8").strip(),
                f"source_sha={expected_hash}",
            )


if __name__ == "__main__":
    unittest.main()
