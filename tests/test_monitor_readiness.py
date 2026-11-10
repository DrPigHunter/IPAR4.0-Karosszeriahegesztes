"""Tests for the atomic readiness signal consumed by the Windows launcher."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.monitor import clear_monitor_ready, signal_monitor_ready


# A monitor readiness tesztjei az indító szkript felé küldött kész/kapcsolatvesztési jelzéseket ellenőrzik.
class MonitorReadinessTests(unittest.TestCase):
    # Sikeres MQTT-kapcsolat után atomikusan jelenjen meg a ready fájl.
    def test_successful_connection_writes_atomic_ready_file(self):
        with tempfile.TemporaryDirectory() as folder:
            ready_file = Path(folder) / "monitor.ready"
            with patch.dict(os.environ, {"BODYLINE_READY_FILE": str(ready_file)}):
                signal_monitor_ready()

            self.assertTrue(ready_file.is_file())
            content = ready_file.read_text(encoding="utf-8")
            self.assertIn("status=connected", content)
            self.assertIn("timestamp=", content)
            self.assertEqual(len(content.splitlines()), 2)
            self.assertFalse(ready_file.with_suffix(".ready.tmp").exists())

    # Kapcsolatvesztéskor a ready fájl tűnjön el.
    def test_disconnect_removes_ready_file(self):
        with tempfile.TemporaryDirectory() as folder:
            ready_file = Path(folder) / "monitor.ready"
            ready_file.write_text("status=connected\n", encoding="utf-8")
            with patch.dict(os.environ, {"BODYLINE_READY_FILE": str(ready_file)}):
                clear_monitor_ready()

            self.assertFalse(ready_file.exists())

    # Közvetlen tesztfuttatáskor ne legyen kötelező a launcher környezet.
    def test_readiness_signal_is_optional_outside_launcher(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch.dict(os.environ, {}, clear=True):
                signal_monitor_ready()
                clear_monitor_ready()
            self.assertEqual(list(Path(folder).iterdir()), [])


if __name__ == "__main__":
    unittest.main()
