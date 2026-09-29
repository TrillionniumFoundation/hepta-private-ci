"""Hermetic tests: synthetic receipts below are NOT qualification evidence."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

import agentd_exact_head as q

SHA = "a" * 40


class ReceiptTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.paths = []
        for os_name in q.OSES:
            for suite in q.SUITES:
                folder = self.root / f"{os_name}-{suite}"
                folder.mkdir()
                commands = []
                for index, argv in enumerate(q.cargo_commands(suite)):
                    log = folder / f"command-{index}.log"
                    log.write_text("SYNTHETIC UNIT TEST FIXTURE\n")
                    commands.append({"argv": argv, "exit_code": 0, "elapsed_seconds": 0.25,
                                     "log": log.name, "log_sha256": q.sha256(log)})
                data = {"schema": q.SCHEMA, "source_sha": SHA, "expected_sha": SHA,
                        "run_id": "123", "attempt": "1", "os": os_name, "suite": suite,
                        "result": "success", "errors": [], "commands": commands,
                        "production_activation": False, "rustc": "SYNTHETIC",
                        "lock_sha256": "b" * 64, "runner_sha256": "d" * 64, "workflow_sha256": "e" * 64,
                        "host_system": "Linux" if os_name == "ubuntu-latest" else "Darwin", "host_arch": "synthetic",
                        "binary_evidence": "digest-only-not-a-release-artifact",
                        "binaries": {name: {"path": "/synthetic/fixture", "size": 1,
                                            "sha256": "c" * 64} for name in q.ALIASES}}
                path = folder / "receipt.json"
                q.atomic_json(path, data)
                self.paths.append(path)

    def verify(self):
        return q.verify(self.root, SHA, "123", "1")

    def mutate(self, edit):
        path = self.paths[0]
        data = q.read_json(path)
        edit(data)
        q.atomic_json(path, data)

    def test_complete_synthetic_matrix_keeps_activation_disabled(self):
        result = self.verify()
        self.assertEqual(len(result["receipt_sha256"]), 14)
        self.assertIs(result["production_activation"], False)
        self.assertIn("independent-security-acceptance", result["unproven"])

    def test_reject_invalid_context_and_claims(self):
        cases = {"schema": 2, "source_sha": "d" * 40, "expected_sha": "d" * 40,
                 "run_id": "124", "attempt": "2", "os": "windows-latest",
                 "suite": "unknown", "result": "skipped", "errors": ["failure"],
                 "production_activation": True, "rustc": "", "lock_sha256": "bad",
                 "binary_evidence": "verified-release-artifact", "commands": [],
                 "binaries": {}, "host_system": "Windows", "host_arch": "",
                 "runner_sha256": "bad", "workflow_sha256": "bad"}
        original = q.read_json(self.paths[0])
        for key, value in cases.items():
            with self.subTest(field=key):
                changed = copy.deepcopy(original)
                changed[key] = value
                q.atomic_json(self.paths[0], changed)
                with self.assertRaises(ValueError):
                    self.verify()
        q.atomic_json(self.paths[0], original)

    def test_reject_bad_command_evidence(self):
        original = q.read_json(self.paths[0])
        for key, value in (("exit_code", 1), ("exit_code", False),
                           ("elapsed_seconds", -1), ("elapsed_seconds", True),
                           ("log", "../command-0.log"), ("log", "/etc/passwd"),
                           ("argv", ["true"]), ("log_sha256", "d" * 64)):
            with self.subTest(field=key, value=value):
                changed = copy.deepcopy(original)
                changed["commands"][0][key] = value
                q.atomic_json(self.paths[0], changed)
                with self.assertRaises(ValueError):
                    self.verify()

    def test_missing_receipt(self):
        self.paths[0].unlink()
        with self.assertRaisesRegex(ValueError, "missing required"):
            self.verify()

    def test_duplicate_receipt(self):
        extra = self.root / "duplicate"
        extra.mkdir()
        q.atomic_json(extra / "receipt.json", q.read_json(self.paths[0]))
        # Duplicate may sort first; copying logs avoids testing missing logs.
        for log in self.paths[0].parent.glob("*.log"):
            (extra / log.name).write_bytes(log.read_bytes())
        with self.assertRaisesRegex(ValueError, "duplicate"):
            self.verify()

    def test_tampered_log(self):
        (self.paths[0].parent / "command-0.log").write_text("tampered")
        with self.assertRaisesRegex(ValueError, "digest mismatch"):
            self.verify()

    def test_missing_log(self):
        (self.paths[0].parent / "command-0.log").unlink()
        with self.assertRaisesRegex(ValueError, "missing command log"):
            self.verify()

    def test_symlink(self):
        (self.root / "unsafe").symlink_to(self.paths[0])
        with self.assertRaisesRegex(ValueError, "symlinks"):
            self.verify()

    def test_malformed_duplicate_and_nonfinite_json(self):
        for text in ("{", '{"schema":1,"schema":1}', '{"duration":NaN}',
                     '{"duration":Infinity}'):
            with self.subTest(text=text):
                self.paths[0].write_text(text)
                with self.assertRaises(ValueError):
                    self.verify()

    def test_oversized_receipt(self):
        self.paths[0].write_bytes(b" " * (1024 * 1024 + 1))
        with self.assertRaisesRegex(ValueError, "too large"):
            self.verify()

    def test_source_digest_drift(self):
        self.mutate(lambda d: d.update(runner_sha256="f" * 64))
        with self.assertRaisesRegex(ValueError, "inconsistent source digests"):
            self.verify()

    def test_failed_job_cannot_leave_success_summary(self):
        import subprocess
        import sys
        summary = self.root / "summary.json"
        q.atomic_json(summary, {"engineering_result": "success"})
        proc = subprocess.run([sys.executable, str(Path(q.__file__)), "verify",
                               "--sha", SHA, "--run-id", "123", "--attempt", "1",
                               "--output", str(summary), "--evidence", str(self.root),
                               "--contract-result", "failure", "--suite-result", "success"],
                              capture_output=True)
        self.assertEqual(proc.returncode, 1)
        self.assertEqual(q.read_json(summary)["engineering_result"], "failure")

    def test_command_plan_has_locked_and_no_filtered_tests(self):
        for suite in q.SUITES:
            for argv in q.cargo_commands(suite):
                self.assertIn("--locked", argv)
                self.assertNotIn("--ignored", argv)
                self.assertNotIn("--skip", argv)

    def test_all_fixture_roles_must_resolve_from_cargo_artifacts(self):
        log = self.root / "cargo.jsonl"
        env = {}
        lines = []
        for role, names in q.ALIASES.items():
            executable = self.root / names[0]
            executable.write_text("synthetic-not-executed")
            executable.chmod(0o700)
            lines.append(json.dumps({"reason": "compiler-artifact", "target": {"name": names[0]},
                                     "executable": str(executable)}))
        log.write_text("\n".join(lines))
        result = q.fixture_environment(log, env)
        self.assertEqual(set(result), set(q.ALIASES))
        self.assertEqual(env["CODEX_EXE_PATH"], env["HEPTA_CODEX_BIN"])
        self.assertEqual(env["AGENTD_EXE_PATH"], env["HEPTA_AGENTD_BIN"])
        self.assertEqual(env["SUPERVISOR_EXE_PATH"], env["HEPTA_SUPERVISOR_BIN"])
        log.write_text("{}\n")
        with self.assertRaisesRegex(ValueError, "missing"):
            q.fixture_environment(log, {})

    def test_failed_command_has_actual_exit_and_log(self):
        import os
        import sys
        command = q.execute([sys.executable, "-c", "raise SystemExit(7)"], self.root,
                            dict(os.environ), self.root, 99, 10)
        self.assertEqual(command["exit_code"], 7)
        self.assertEqual(command["log_sha256"], q.sha256(self.root / command["log"]))

    def test_timeout_terminates_process_group(self):
        import os
        import sys
        command = q.execute([sys.executable, "-c", "import time; time.sleep(60)"], self.root,
                            dict(os.environ), self.root, 99, 1)
        self.assertEqual(command["exit_code"], 124)
        self.assertIn("timed out", (self.root / command["log"]).read_text())


if __name__ == "__main__":
    unittest.main()
