"""Real shell, count parser and evidence builder; native commands remain stand-ins."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_CHECK_COUNT = 24
TEST_CHECKS = (
    "manifest-rust",
    "types-tests",
    "wire-tests",
    "ndu-tests",
    "prompt-producer",
    "prompt-ledger",
    "topology-consumer",
    "manifest-owners",
)


class ConsumerExecutionTests(unittest.TestCase):
    def execute(self, failure: str):
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            root = work / "source"
            (root / "scripts").mkdir(parents=True)
            for name in (
                "run_platform_types_consumer_qualification.sh",
                "platform_types_nonempty_tests.py",
                "platform_types_consumer_evidence.py",
            ):
                shutil.copyfile(ROOT / "scripts" / name, root / "scripts" / name)
            vector = root / "codex-rs/hepta-types/conformance/verify_vectors.ts"
            vector.parent.mkdir(parents=True)
            vector.write_text("// Synthetic runner input; node is a stand-in.\n")
            (root / ".gitignore").write_text("__pycache__/\n")

            def git(*args):
                return subprocess.check_output(
                    ["git", *args], cwd=root, text=True
                ).strip()

            git("init", "-q")
            git("config", "user.name", "Consumer runner fixture")
            git("config", "user.email", "consumer@example.invalid")
            git("config", "core.hooksPath", "/dev/null")
            git("add", ".")
            git("-c", "commit.gpgsign=false", "commit", "-qm", "fixture")
            self.fixture_head = git("rev-parse", "HEAD")
            tools = work / "bin"
            tools.mkdir()
            for name in ("cargo", "just", "python3", "node"):
                tool = tools / name
                tool.write_text(
                    "#!/bin/sh\n"
                    'name="${0##*/}"\n'
                    'printf "%s\\n" "$name $*" >> "$TEST_COMMAND_LOG"\n'
                    'if [ "$name" = python3 ]; then\n'
                    '  case "$1" in\n'
                    '    scripts/platform_types_nonempty_tests.py)\n'
                    '      if [ "$TEST_FAILURE" = count-tamper ]; then printf \'{"executedTests":999}\\n\'; exit 0; fi;;\n'
                    '  esac\n'
                    '  case "$1" in\n'
                    '    scripts/platform_types_nonempty_tests.py|scripts/platform_types_consumer_evidence.py)\n'
                    f'      exec {shlex.quote(sys.executable)} -S "$@";;\n'
                    '  esac\n'
                    'fi\n'
                    'if [ "$name" = cargo ] && [ "$1" = check ] && [ "$TEST_FAILURE" = compile ]; then exit 19; fi\n'
                    'if [ "$name" = cargo ] && [ "$1" = test ]; then\n'
                    '  case "$*" in\n'
                    '    *topology_candidate*)\n'
                    '      if [ "$TEST_FAILURE" = empty ]; then\n'
                    '        printf "%s\\n" "running 0 tests"\n'
                    '        printf "%s\\n" "test result: ok. 0 passed; 0 failed; 0 ignored; 0 measured; 9 filtered out; finished in 0.00s"\n'
                    '        exit 0\n'
                    '      fi\n'
                    '      if [ "$TEST_FAILURE" = orphan-summary ]; then\n'
                    '        printf "%s\\n" "test result: ok. 2 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 0.01s"\n'
                    '        exit 0\n'
                    '      fi\n'
                    '      if [ "$TEST_FAILURE" = compile-only ]; then printf "%s\\n" "Finished test profile; no tests executed"; exit 0; fi;;\n'
                    '  esac\n'
                    '  printf "%s\\n" "running 2 tests"\n'
                    '  printf "%s\\n" "test result: ok. 2 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 0.01s"\n'
                    'fi\nexit 0\n'
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
                    f'exec {shlex.quote(real_git)} "$@"\n'
                )
                git_tool.chmod(0o755)
            evidence = work / "evidence"
            evidence.mkdir()
            (evidence / "topology-consumer-count.json").write_text(
                '{"executedTests":99}'
            )
            env = dict(
                os.environ,
                PATH=str(tools) + os.path.sep + os.environ["PATH"],
                HEPTA_TYPES_EVIDENCE_DIR=str(evidence),
                TEST_COMMAND_LOG=str(work / "commands.log"),
                TEST_FAILURE=failure,
                PYTHONDONTWRITEBYTECODE="1",
            )
            process = subprocess.run(
                [
                    "bash",
                    str(root / "scripts/run_platform_types_consumer_qualification.sh"),
                ],
                cwd=work,
                env=env,
                capture_output=True,
                text=True,
                timeout=90,
            )
            self.assertTrue(
                (evidence / "execution.json").is_file(),
                process.stdout + process.stderr,
            )
            record = json.loads((evidence / "execution.json").read_text())
            for row in record["checks"]:
                self.assertTrue((evidence / row["log"]).is_file())
                self.assertEqual(len(row["logSha256"]), 64)
                if "testCountLog" in row:
                    self.assertTrue((evidence / row["testCountLog"]).is_file())
                    self.assertEqual(len(row["testCountSha256"]), 64)
            self.assertFalse(any(evidence.glob("*-count.json.tmp")))
            count_files = {path.name for path in evidence.glob("*-count.json")}
            return process, record, (work / "commands.log").read_text(), count_files

    def test_compile_failure_keeps_every_later_consumer_and_stays_red(self):
        process, record, commands, _ = self.execute("compile")
        self.assertNotEqual(process.returncode, 0)
        self.assertFalse(record["checksPassed"])
        self.assertFalse(record["qualified"])
        checks = {row["name"]: row["exitCode"] for row in record["checks"]}
        self.assertEqual(len(checks), EXPECTED_CHECK_COUNT)
        self.assertEqual(checks["consumer-compile"], 19)
        for name in (
            "manifest-rust",
            "wire-tests",
            "topology-consumer",
            "manifest-owners",
            "wire-lint",
            "ndu-lint",
        ):
            self.assertEqual(checks[name], 0)
        for name in (
            "verify_manifest_vectors.py",
            "verify_platform_wire_vectors.py",
            "manifest_protocol_consumer",
            "codex-hepta-wire",
            "codex-hepta-learning-ledger",
        ):
            self.assertIn(name, commands)

    def test_empty_or_orphan_focused_suite_is_not_success(self):
        for failure in ("empty", "orphan-summary"):
            with self.subTest(failure=failure):
                process, record, _, count_files = self.execute(failure)
                self.assertNotEqual(process.returncode, 0)
                self.assertFalse(record["checksPassed"])
                self.assertFalse(record["qualified"])
                checks = {
                    row["name"]: row["exitCode"] for row in record["checks"]
                }
                self.assertEqual(len(checks), EXPECTED_CHECK_COUNT)
                self.assertEqual(checks["topology-consumer"], 4)
                self.assertEqual(checks["manifest-owners"], 0)
                self.assertEqual(checks["ndu-lint"], 0)
                self.assertNotIn("topology-consumer-count.json", count_files)

    def test_success_requires_all_checks_and_retains_exact_source(self):
        process, record, _, count_files = self.execute("")
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        self.assertTrue(record["checksPassed"])
        self.assertTrue(record["qualified"])
        self.assertEqual(len(record["checks"]), EXPECTED_CHECK_COUNT)
        self.assertEqual(record["sourceHead"], self.fixture_head)
        self.assertTrue(record["sourceUnchanged"])
        self.assertFalse(record["productActivation"])
        self.assertFalse(record["independentAcceptance"])
        self.assertEqual(sum("executedTests" in row for row in record["checks"]), 8)
        for name in TEST_CHECKS:
            self.assertIn(f"{name}-count.json", count_files)

    def test_source_change_cannot_turn_successful_commands_into_qualification(self):
        process, record, _, _ = self.execute("drift")
        self.assertNotEqual(process.returncode, 0)
        self.assertTrue(record["checksPassed"])
        self.assertFalse(record["sourceUnchanged"])
        self.assertFalse(record["qualified"])

    def test_compile_only_and_forged_count_cannot_qualify(self):
        for failure in ("compile-only", "count-tamper"):
            with self.subTest(failure=failure):
                process, record, _, _ = self.execute(failure)
                self.assertNotEqual(process.returncode, 0)
                self.assertFalse(record["qualified"])
                self.assertEqual(len(record["checks"]), EXPECTED_CHECK_COUNT)

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
