"""Smoke test that the Streamlit dashboard renders its main tab content."""
from pathlib import Path
import unittest

from streamlit.testing.v1 import AppTest


ROOT = Path(__file__).resolve().parents[1]


class DashboardRenderTests(unittest.TestCase):
    def test_dashboard_renders_main_tabs_without_streamlit_exception(self):
        app = AppTest.from_file(str(ROOT / "src" / "dashboard.py"), default_timeout=30).run()
        self.assertEqual(
            len(app.exception),
            0,
            msg="Dashboard raised a Streamlit exception: "
            + "; ".join(str(item.value) for item in app.exception),
        )

        rendered_markdown = "\n".join(item.value for item in app.markdown)
        rendered_titles = "\n".join(item.value for item in app.title)
        rendered_subheaders = "\n".join(item.value for item in app.subheader)

        visible_text = "\n".join((rendered_markdown, rendered_titles, rendered_subheaders))
        self.assertIn("Gyártócella élő nézete", visible_text)
        self.assertIn("Production log", visible_text)


if __name__ == "__main__":
    unittest.main()
