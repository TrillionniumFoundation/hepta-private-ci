"""Keep the governed source/merge commands and receipt admission in agreement."""

from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re
import shlex
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import kernel_evidence_record_validation as validation


ROOT = Path(__file__).resolve().parents[2]
PRODUCT_TARGETS = (
    "kernel_evidence_product",
    "kernel_evidence_profile",
    "kernel_evidence_paging_product",
    "kernel_evidence_publication_cli",
)


class QualificationCommandCoverageTests(unittest.TestCase):
    def test_every_native_qualification_plan_preserves_locked_dependencies(self):
        for name in validation.TEST_RECORDS:
            with self.subTest(name=name):
                command = validation.EXPECTED_COMMANDS[name]
                self.assertEqual(command[:2], ["bash", "-lc"])
                self.assertIn("--locked", shlex.split(command[2]))

    def test_product_plan_runs_library_and_every_registered_integration_target(self):
        tokens = shlex.split(
            validation.EXPECTED_COMMANDS["agentd-product-test.json"][2]
        )
        self.assertEqual(tokens.count("--lib"), 1)
        observed = [
            tokens[i + 1] for i, token in enumerate(tokens) if token == "--test"
        ]
        self.assertEqual(observed, list(PRODUCT_TARGETS))

    def test_both_workflow_lanes_execute_the_admitted_commands(self):
        workflow = ROOT / ".github/workflows/hepta-kernel-evidence-qualification.yml"
        commands = re.findall(
            r"bash -lc '([^'\n]+)'", workflow.read_text(encoding="utf-8")
        )
        for name in validation.TEST_RECORDS:
            with self.subTest(name=name):
                expected = validation.EXPECTED_COMMANDS[name][2]
                self.assertEqual(commands.count(expected), 2)
        self.assertEqual(len(commands), 4)

    def test_old_and_weakened_product_commands_cannot_reuse_successful_logs(self):
        name = "agentd-product-test.json"
        current = validation.EXPECTED_COMMANDS[name]
        weakened = [
            "cd codex-rs && cargo test -p codex-hepta-agentd "
            "--test kernel_evidence_product --test kernel_evidence_profile",
            current[2].replace(" --locked", "", 1),
            current[2].replace(" --lib", "", 1),
        ]
        weakened.extend(
            current[2].replace(f" --test {target}", "", 1) for target in PRODUCT_TARGETS
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            log = b"test result: ok. 7 passed; 0 failed; 0 ignored;\n"
            (root / "execution.log").write_bytes(log)
            expected = {
                "source_sha": "a" * 40,
                "tested_sha": "a" * 40,
                "base_sha": "b" * 40,
                "lane": "source-head",
                "run_id": "100",
                "run_attempt": "2",
                "job": "source-head",
            }
            identity = {
                "commit": "a" * 40,
                "tree": "c" * 40,
                "parents": ["b" * 40],
                "dirty": False,
            }
            now = datetime.now(timezone.utc)
            record = {
                "schema_version": 1,
                **expected,
                "command": current,
                "working_directory": directory,
                "before": identity,
                "after": identity,
                "status": "passed",
                "error": None,
                "exit_code": 0,
                "command_exit_code": 0,
                "returncode": 0,
                "timed_out": False,
                "output_limit_exceeded": False,
                "observed_passed_tests": 7,
                "observed_failed_tests": 0,
                "started_at": (now - timedelta(seconds=1)).isoformat(),
                "finished_at": now.isoformat(),
                "elapsed_seconds": 1.0,
                "log_file": "execution.log",
                "log_bytes": len(log),
                "log_sha256": hashlib.sha256(log).hexdigest(),
            }

            def inspect(command):
                record["command"] = command
                (root / name).write_text(json.dumps(record), encoding="utf-8")
                return validation.inspect_execution_record(
                    root,
                    name,
                    expected=expected,
                    identity=identity,
                    working_directory=directory,
                )

            accepted = inspect(current)
            self.assertTrue(accepted["passed"], accepted)
            for command in weakened:
                with self.subTest(command=command):
                    result = inspect(["bash", "-lc", command])
                    self.assertFalse(result["passed"], result)
                    self.assertIn("required command", result["error"])


if __name__ == "__main__":
    unittest.main()
