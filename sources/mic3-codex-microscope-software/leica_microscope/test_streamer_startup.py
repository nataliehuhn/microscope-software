"""Startup regressions; no camera or microscope connection is required."""
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from leica_microscope import streamer


class StreamerStartupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(
            prefix="streamer-test-", dir=str(Path(__file__).resolve().parent)
        )
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.definition = self.base / "camera.xml"
        self.buffer = self.base / "camera.mmap"
        self.reader = streamer.MemmapReader.__new__(streamer.MemmapReader)
        self.worker = Mock()
        self.worker.poll.return_value = None
        for name, value in (
            ("memmap_def", self.definition),
            ("memmap_file", self.buffer),
        ):
            patcher = patch.object(streamer, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = patch.object(streamer, "MemMap")
        self.map_type = patcher.start()
        self.addCleanup(patcher.stop)
        patcher = patch.object(streamer.subprocess, "Popen")
        self.popen = patcher.start()
        self.addCleanup(patcher.stop)

    def publish_definition(self, *args, **kwargs):
        self.definition.write_text("ready")
        return self.worker

    def test_start_uses_current_interpreter_and_absolute_worker_path(self):
        self.popen.side_effect = self.publish_definition
        self.reader.start_streamer()
        self.popen.assert_called_once_with(
            [sys.executable, "-u", str(streamer.base_dir / "streamer.py")],
            cwd=str(streamer.base_dir),
        )
        self.map_type.assert_called_once_with(self.definition)

    def test_only_removes_the_buffer_for_this_checkout(self):
        other = self.base / "other"
        (other / "includes").mkdir(parents=True)
        unrelated_buffer = other / "includes" / "camera.mmap"
        unrelated_buffer.write_bytes(b"keep")
        self.buffer.write_bytes(b"stale")
        self.popen.side_effect = self.publish_definition
        previous = Path.cwd()
        try:
            os.chdir(other)
            self.reader.start_streamer()
        finally:
            os.chdir(previous)
        self.assertFalse(self.buffer.exists())
        self.assertEqual(unrelated_buffer.read_bytes(), b"keep")

    def test_failed_worker_reports_error_without_waiting_forever(self):
        self.worker.poll.return_value = 1
        self.popen.return_value = self.worker
        with self.assertRaisesRegex(RuntimeError, "exited with code 1"):
            self.reader.start_streamer()
        self.map_type.assert_not_called()

    def test_stalled_worker_is_stopped_and_reports_timeout(self):
        self.reader.startup_timeout = 0
        self.popen.return_value = self.worker
        with self.assertRaisesRegex(RuntimeError, "did not start within"):
            self.reader.start_streamer()
        self.worker.kill.assert_called_once_with()
        self.worker.wait.assert_called_once_with()
        self.map_type.assert_not_called()

    def test_stale_definition_cannot_count_as_successful_startup(self):
        self.definition.write_text("stale")
        self.worker.poll.return_value = 1
        self.popen.return_value = self.worker
        with self.assertRaisesRegex(RuntimeError, "exited with code 1"):
            self.reader.start_streamer()
        self.assertFalse(self.definition.exists())


if __name__ == "__main__":
    unittest.main()
