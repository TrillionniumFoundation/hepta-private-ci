"""Regression tests for native-host exact-identity execution records."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

RUNNER = Path(__file__).with_name("hepta_ci_exec.py").resolve()


class NativeHostExecutionRecordTests(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory(prefix="hepta-native-host-exec-")
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self.git("init", "-q")
        self.git("config", "user.name", "native-host-test")
        self.git("config", "user.email", "native-host-test@example.invalid")
        (self.repo / "input").write_text("exact source\n", encoding="utf-8")
        self.git("add", ".")
        self.git("commit", "-qm", "source")
        self.source = self.git("rev-parse", "HEAD")
        self.result = self.root / "record.json"
        self.marker = self.root / "effect"

    def git(self, *args: str) -> str:
        return subprocess.check_output(
            ["git", "-C", str(self.repo), *args],
            text=True,
            stderr=subprocess.PIPE,
        ).strip()

    def execute(self, *, source_sha: str | None = None, tested_sha: str | None = None):
        code = (
            "from pathlib import Path; "
            f"Path({str(self.marker)!r}).write_text('executed', encoding='utf-8')"
        )
        return subprocess.run(
            [
                sys.executable,
                str(RUNNER),
                "--output",
                str(self.result),
                "--",
                sys.executable,
                "-c",
                code,
            ],
            cwd=self.repo,
            env={
                **os.environ,
                "PYTHONDONTWRITEBYTECODE": "1",
                "SOURCE_SHA": source_sha or self.source,
                "TESTED_SHA": tested_sha or self.source,
                "BASE_SHA": "0" * 40,
                "HEPTA_CI_LANE": "native-host",
            },
            text=True,
            capture_output=True,
            timeout=10,
        )

    def receipt(self) -> dict:
        return json.loads(self.result.read_text(encoding="utf-8"))

    def test_native_host_executes_only_the_exact_source_head(self) -> None:
        result = self.execute()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.marker.read_text(encoding="utf-8"), "executed")
        receipt = self.receipt()
        self.assertEqual(receipt["lane"], "native-host")
        self.assertEqual(receipt["source_sha"], self.source)
        self.assertEqual(receipt["tested_sha"], self.source)
        self.assertEqual(receipt["status"], "passed")
        self.assertEqual(receipt["command_exit_code"], 0)

    def test_native_host_rejects_source_relabelling_before_dispatch(self) -> None:
        result = self.execute(source_sha="f" * 40)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertFalse(self.marker.exists())
        receipt = self.receipt()
        self.assertEqual(receipt["status"], "rejected")
        self.assertIsNone(receipt["command_exit_code"])
        self.assertIn("exact source SHA", receipt["error"])


if __name__ == "__main__":
    unittest.main()
