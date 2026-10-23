"""Acceptance gate regressions, runnable without FFmpeg in lightweight CI."""
import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from run_codec_acceptance import require_tools, run_acceptance


class CodecAcceptanceTests(unittest.TestCase):
    def test_missing_tools_fail_the_actual_entrypoint(self):
        with tempfile.TemporaryDirectory() as empty_path:
            env = dict(os.environ, PATH=empty_path)
            result = subprocess.run(
                [sys.executable, str(Path(__file__).with_name("run_codec_acceptance.py"))],
                env=env, capture_output=True, text=True, timeout=30)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("required codec tool unavailable: ffmpeg", result.stderr)

    def test_each_tool_is_mandatory(self):
        for absent in ("ffmpeg", "ffprobe"):
            with self.subTest(absent=absent), patch(
                "run_codec_acceptance.shutil.which",
                side_effect=lambda name: None if name == absent else name,
            ), patch("run_codec_acceptance.subprocess.run"):
                with self.assertRaisesRegex(RuntimeError, absent):
                    require_tools()

    def test_broken_version_command_fails(self):
        with patch("run_codec_acceptance.shutil.which", return_value="codec"), patch(
            "run_codec_acceptance.subprocess.run",
            side_effect=subprocess.CalledProcessError(1, ["codec", "-version"]),
        ):
            with self.assertRaises(subprocess.CalledProcessError):
                require_tools()

    def test_zero_all_skipped_and_partial_skipped_suites_fail(self):
        def skipped():
            raise unittest.SkipTest("missing fixture capability")

        for callbacks in ((), (skipped,), (lambda: None, skipped)):
            with self.subTest(count=len(callbacks)):
                suite = unittest.TestSuite(unittest.FunctionTestCase(fn) for fn in callbacks)
                self.assertEqual(run_acceptance(suite, io.StringIO()), 1)

    def test_failed_test_is_not_accepted(self):
        def failing():
            raise AssertionError("rejected media")

        suite = unittest.TestSuite([unittest.FunctionTestCase(failing)])
        self.assertEqual(run_acceptance(suite, io.StringIO()), 1)

    def test_executed_success_is_accepted(self):
        suite = unittest.TestSuite([unittest.FunctionTestCase(lambda: None)])
        self.assertEqual(run_acceptance(suite, io.StringIO()), 0)


if __name__ == "__main__":
    unittest.main()
