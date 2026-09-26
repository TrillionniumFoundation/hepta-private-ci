"""Exercise failure isolation through the real qualification shell entrypoint."""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class ConsumerExecutionTests(unittest.TestCase):
    def execute(self, failure: str):
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            tools = work / "bin"
            tools.mkdir()
            for name in ("cargo", "just", "python3", "node"):
                tool = tools / name
                tool.write_text(
                    "#!/bin/sh\n"
                    f'if [ "${{0##*/}}" = python3 ] && [ "$1" = - ]; then exec {sys.executable} "$@"; fi\n'
                    'printf "%s\\n" "$0 $*" >> "$TEST_COMMAND_LOG"\n'
                    'case "$0 $*" in\n'
                    '  */cargo\\ check*) test "$TEST_FAILURE" != compile || exit 19;;\n'
                    '  *codex-hepta-supervisor*topology_candidate*) test "$TEST_FAILURE" != empty || exit 4;;\n'
                    "esac\nexit 0\n"
                )
                tool.chmod(0o755)
            if failure == "drift":
                git_tool = tools / "git"
                real_git = shutil.which("git")
                self.assertIsNotNone(real_git)
                marker = work / "head-reads"
                git_tool.write_text(
                    "#!/bin/sh\n"
                    'if [ "$1" = rev-parse ] && [ "$2" = HEAD ]; then\n'
                    f'  if [ -f "{marker}" ]; then printf "%040d\\n" 1; exit 0; fi\n'
                    f'  : > "{marker}"\n'
                    'fi\n'
                    f'exec "{real_git}" "$@"\n'
                )
                git_tool.chmod(0o755)
            evidence = work / "evidence"
            env = dict(
                os.environ,
                PATH=str(tools) + os.pathsep + os.environ["PATH"],
                HEPTA_TYPES_EVIDENCE_DIR=str(evidence),
                TEST_COMMAND_LOG=str(work / "commands.log"),
                TEST_FAILURE=failure,
            )
            process = subprocess.run(
                [
                    "bash",
                    str(ROOT / "scripts/run_platform_types_consumer_qualification.sh"),
                ],
                cwd=work,
                env=env,
                capture_output=True,
                text=True,
                timeout=90,
            )
            self.assertTrue(
                (evidence / "execution.json").is_file(), process.stdout + process.stderr
            )
            record = json.loads((evidence / "execution.json").read_text())
            for row in record["checks"]:
                self.assertTrue((evidence / row["log"]).is_file())
                self.assertEqual(len(row["logSha256"]), 64)
            return process, record, (work / "commands.log").read_text()

    def test_compile_failure_keeps_every_later_consumer_and_stays_red(self):
        process, record, commands = self.execute("compile")
        self.assertNotEqual(process.returncode, 0)
        self.assertFalse(record["checksPassed"])
        self.assertFalse(record["qualified"])
        checks = {row["name"]: row["exitCode"] for row in record["checks"]}
        self.assertEqual(len(checks), 19)
        self.assertEqual(checks["consumer-compile"], 19)
        self.assertEqual(checks["manifest-rust"], 0)
        self.assertEqual(checks["topology-consumer"], 0)
        self.assertEqual(checks["ndu-lint"], 0)
        self.assertIn("verify_manifest_vectors.py", commands)
        self.assertIn("manifest_protocol_consumer", commands)
        self.assertIn("codex-hepta-learning-ledger", commands)

    def test_empty_focused_suite_is_not_success(self):
        process, record, _ = self.execute("empty")
        self.assertNotEqual(process.returncode, 0)
        self.assertFalse(record["checksPassed"])
        self.assertFalse(record["qualified"])

    def test_success_requires_all_checks_and_retains_exact_source(self):
        process, record, _ = self.execute("")
        self.assertEqual(
            process.returncode,
            0 if record["cleanWorktree"] else 1,
            process.stdout + process.stderr,
        )
        self.assertTrue(record["checksPassed"])
        self.assertEqual(len(record["checks"]), 19)
        self.assertEqual(
            record["sourceHead"],
            subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
            ).strip(),
        )
        self.assertTrue(record["sourceUnchanged"])
        self.assertFalse(record["productActivation"])
        self.assertFalse(record["independentAcceptance"])

    def test_source_change_cannot_turn_successful_commands_into_qualification(self):
        process, record, _ = self.execute("drift")
        self.assertNotEqual(process.returncode, 0)
        self.assertTrue(record["checksPassed"])
        self.assertFalse(record["sourceUnchanged"])
        self.assertFalse(record["qualified"])

    def test_each_lane_requires_independent_consumer_outcome(self):
        import yaml

        workflow = yaml.safe_load(
            (ROOT / ".github/workflows/lane-a-foundation.yml").read_text()
        )
        for job in workflow["jobs"].values():
            steps = job["steps"]
            consumers = next(
                step for step in steps if step.get("id", "").endswith("_consumers")
            )
            self.assertEqual(consumers["if"], "${{ !cancelled() }}")
            receipt = next(
                step for step in steps if step.get("id", "").endswith("_receipts")
            )
            self.assertIn(consumers["id"] + ".outcome == 'success'", receipt["if"])
            final = steps[-1]
            self.assertIn("CONSUMER_OUTCOME", final["env"])
            self.assertIn('test "$CONSUMER_OUTCOME" = success', final["run"])


if __name__ == "__main__":
    unittest.main()
