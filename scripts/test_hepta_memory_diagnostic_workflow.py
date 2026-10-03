"""Execute the workflow recorder with fixture commands, without compiling Rust."""

import json
import os
from pathlib import Path
import shutil
import shlex
import subprocess
import tempfile
import unittest

from hepta_inference_artifact_acceptor import EXPECTED

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/hepta-inference-readonly-matrix.yml"


class MemoryDiagnosticWorkflowTests(unittest.TestCase):
    def test_protected_command_contract_is_unchanged(self):
        workflow = WORKFLOW.read_text()
        protected = workflow.split("record_dir=memory-diagnostics", 1)[0]
        commands = {}
        for line in protected.splitlines():
            words = (
                shlex.split(line.strip()) if line.strip().startswith("record ") else []
            )
            if words:
                commands[words[1]] = words[3:]
        self.assertEqual(commands, EXPECTED)

    def execute(
        self,
        *,
        prior_failure=False,
        zero_selection=False,
        lint_failure=False,
        empty_filter="test(local_lease_outbox_tests)",
    ):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = root / "repo"
            (repo / "scripts").mkdir(parents=True)
            shutil.copy(
                ROOT / "scripts/hepta_ci_exec.py", repo / "scripts/hepta_ci_exec.py"
            )
            for args in [
                ("init", "-q"),
                ("config", "user.name", "fixture"),
                ("config", "user.email", "fixture@example.invalid"),
                ("add", "."),
                ("commit", "-qm", "fixture"),
            ]:
                subprocess.run(
                    ["git", *args], cwd=repo, check=True, capture_output=True
                )
            sha = subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=repo, text=True
            ).strip()
            binaries = root / "bin"
            binaries.mkdir()
            fake = """#!/usr/bin/env python3
import os, sys
if sys.argv[0].endswith('just'):
    empty = os.environ['ZERO_SELECTION'] == '1' and os.environ['EMPTY_FILTER'] in sys.argv
    print('Summary [ 0.001s] 0 tests run: 0 passed, 50 skipped' if empty else 'Summary [ 0.001s] 2 tests run: 2 passed, 50 skipped')
else:
    raise SystemExit(int(os.environ['LINT_FAILURE']))
"""
            for name in ("just", "cargo"):
                path = binaries / name
                path.write_text(fake)
                path.chmod(0o755)
            workflow = WORKFLOW.read_text()
            block = workflow.split(
                "      - name: Execute all required commands without hiding earlier failures\n",
                1,
            )[1].split("      - name:", 1)[0]
            script = "\n".join(
                line[10:] for line in block.split("        run: |\n", 1)[1].splitlines()
            )
            prefix = script.split("record 01-state", 1)[0]
            suffix = script[script.index("record_dir=memory-diagnostics") :]
            prior = (
                'record prior-metadata 0 python3 -c "raise SystemExit(1)"\n'
                if prior_failure
                else ""
            )
            out = root / "records"
            result = subprocess.run(
                ["bash", "-c", prefix + prior + suffix],
                cwd=repo,
                capture_output=True,
                text=True,
                timeout=20,
                env={
                    **os.environ,
                    "PATH": str(binaries) + os.pathsep + os.environ["PATH"],
                    "RECORDS_DIR": str(out),
                    "SOURCE_SHA": sha,
                    "TESTED_SHA": sha,
                    "BASE_SHA": sha,
                    "HEPTA_CI_LANE": "source-head",
                    "ZERO_SELECTION": str(int(zero_selection)),
                    "EMPTY_FILTER": empty_filter,
                    "LINT_FAILURE": str(int(lint_failure)),
                },
            )
            records = {
                path.stem: json.loads(path.read_text())
                for path in (out / "memory-diagnostics").glob("*.json")
            }
            self.assertEqual(
                set(records),
                {
                    "12-memory-correction",
                    "13-memory-outbox",
                    "14-memory-production",
                    "15-memory-lib-clippy",
                    "16-memory-exact-recovery",
                    "17-agentd-recovery-product",
                },
            )
            for record in records.values():
                self.assertEqual(record["before"], record["after"])
                self.assertEqual(record["tested_sha"], sha)
                self.assertFalse(record["after"]["dirty"])
            protected = list((out / "commands").glob("*.json"))
            self.assertEqual(
                [path.stem for path in protected],
                ["prior-metadata"] if prior_failure else [],
            )
            return result.returncode, records

    def test_prior_failure_survives_passing_memory_diagnostics(self):
        code, records = self.execute(prior_failure=True)
        self.assertEqual(code, 1)
        self.assertTrue(
            all(record["status"] == "passed" for record in records.values())
        )

    def test_zero_selection_fails_and_later_diagnostics_still_run(self):
        code, records = self.execute(zero_selection=True)
        self.assertEqual(code, 1)
        self.assertEqual(records["13-memory-outbox"]["observed_passed_tests"], 0)
        self.assertEqual(records["13-memory-outbox"]["status"], "failed")
        self.assertEqual(records["14-memory-production"]["observed_passed_tests"], 2)

    def test_strict_lint_failure_remains_failure(self):
        code, records = self.execute(lint_failure=True)
        self.assertEqual(code, 1)
        self.assertEqual(records["15-memory-lib-clippy"]["status"], "failed")

    def test_scoped_success_records_every_test_group(self):
        code, records = self.execute()
        self.assertEqual(code, 0)
        self.assertEqual(
            [records[name]["observed_passed_tests"] for name in sorted(records)],
            [2, 2, 2, 0, 2, 2],
        )

    def test_each_exact_recovery_case_rejects_zero_selection(self):
        for name, selector in (
            (
                "16-memory-exact-recovery",
                "test(=cognitive_store::recovery::tests::exact_current_cut_recovers_writable_generation_and_persists_activation)",
            ),
            (
                "17-agentd-recovery-product",
                "test(=agentd_product_host_recovers_exact_cut_into_fenced_writer_generation)",
            ),
        ):
            with self.subTest(name=name):
                code, records = self.execute(zero_selection=True, empty_filter=selector)
                self.assertEqual(code, 1)
                self.assertEqual(records[name]["observed_passed_tests"], 0)
                self.assertEqual(records[name]["status"], "failed")
                self.assertIn("--no-tests=fail", records[name]["command"])


if __name__ == "__main__":
    unittest.main()
