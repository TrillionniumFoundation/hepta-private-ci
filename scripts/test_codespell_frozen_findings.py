"""Exercise exact historical classification and real full-tree checker coverage."""

from collections import Counter
import copy
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from contextlib import redirect_stderr

import check_codespell_frozen_findings as gate


TOKEN = bytes.fromhex("726573746f726561626c65").decode()
TOKEN_SHA = gate.digest(TOKEN.encode())
DIAGNOSTIC = f"./evidence.txt:1: {TOKEN} ==> restorable\n"
DIAGNOSTIC_SHA = gate.digest(DIAGNOSTIC.rstrip("\n").encode())
EXPECTED = Counter({("evidence.txt", 1, TOKEN_SHA, DIAGNOSTIC_SHA): 1})


class OutputTests(unittest.TestCase):
    def test_exact_observation_keeps_raw_failure_visible(self):
        result = gate.classify(DIAGNOSTIC, "1\n", 65, EXPECTED)
        self.assertEqual(
            {
                key: result[key]
                for key in (
                    "raw_lint_findings",
                    "frozen_historical_findings",
                    "new_findings",
                    "missing_frozen_findings",
                    "raw_lint_clean",
                    "policy_passed",
                    "raw_exit_code",
                )
            },
            {
                "raw_lint_findings": 1,
                "frozen_historical_findings": 1,
                "new_findings": 0,
                "missing_frozen_findings": 0,
                "raw_lint_clean": False,
                "policy_passed": True,
                "raw_exit_code": 65,
            },
        )

    def test_new_changed_duplicate_and_missing_observations_fail(self):
        cases = [
            (DIAGNOSTIC.replace("evidence.txt", "new.txt"), "1\n", 65),
            (DIAGNOSTIC.replace(":1:", ":2:"), "1\n", 65),
            (DIAGNOSTIC.replace(TOKEN, TOKEN.upper()), "1\n", 65),
            (DIAGNOSTIC.replace("restorable", "different suggestion"), "1\n", 65),
            (DIAGNOSTIC * 2, "2\n", 65),
            ("", "0\n", 0),
        ]
        for stdout, stderr, status in cases:
            with self.subTest(stdout=stdout):
                self.assertFalse(
                    gate.classify(stdout, stderr, status, EXPECTED)["policy_passed"]
                )

    def test_unknown_diagnostics_and_inconsistent_tool_results_fail(self):
        cases = [
            (DIAGNOSTIC + "unexpected warning\n", "1\n", 65),
            (DIAGNOSTIC.replace("./evidence", "../evidence"), "1\n", 65),
            (DIAGNOSTIC.replace("./evidence", "./../evidence"), "1\n", 65),
            (DIAGNOSTIC, "warning\n1\n", 65),
            (DIAGNOSTIC, "0\n", 65),
            (DIAGNOSTIC, "1\n", 0),
            (DIAGNOSTIC, "1\n", 2),
            (DIAGNOSTIC, "1", 65),
        ]
        for stdout, stderr, status in cases:
            with self.subTest(stdout=stdout, stderr=stderr, status=status):
                with self.assertRaises(gate.PolicyError):
                    gate.classify(stdout, stderr, status, EXPECTED)


class RepositoryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="hepta-spelling-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.run_git("init", "--quiet")
        (self.root / ".codespellrc").write_text(
            "[codespell]\nskip = .git*\ncheck-hidden = true\n"
        )
        (self.root / ".codespellignore").write_text("legitimate\n")
        (self.root / "evidence.txt").write_text(TOKEN + "\n")
        self.run_git("add", ".")
        self.run_git(
            "-c",
            "user.name=Policy Tests",
            "-c",
            "user.email=policy@example.invalid",
            "-c",
            "commit.gpgsign=false",
            "commit",
            "--quiet",
            "-m",
            "Freeze evidence",
        )
        self.commit = self.run_git("rev-parse", "HEAD").strip()
        source_patch = patch.object(gate, "SOURCE_COMMIT", self.commit)
        source_patch.start()
        self.addCleanup(source_patch.stop)
        self.policy = {
            "schema_version": 1,
            "source_commit": self.commit,
            "codespell_version": gate.VERSION,
            "configuration": [self.record(path) for path in sorted(gate.CONFIGURATION)],
            "absent_configuration": sorted(gate.ABSENT_CONFIGURATION),
            "files": [
                {
                    **self.record("evidence.txt"),
                    "findings": [
                        {
                            "line": 1,
                            "token_sha256": TOKEN_SHA,
                            "diagnostic_sha256": DIAGNOSTIC_SHA,
                        }
                    ],
                }
            ],
        }
        (self.root / "scripts").mkdir()
        self.write_policy(self.policy)
        inventory_patch = patch.object(
            gate, "AUTHORIZED_POLICY_SHA256", gate.policy_identity(self.policy)
        )
        inventory_patch.start()
        self.addCleanup(inventory_patch.stop)

    def run_git(self, *arguments):
        return subprocess.run(
            ["git", *arguments],
            cwd=self.root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout

    def record(self, relative):
        data = (self.root / relative).read_bytes()
        return {"path": relative, "bytes": len(data), "sha256": gate.digest(data)}

    def write_policy(self, policy):
        (self.root / gate.POLICY_PATH).write_text(json.dumps(policy) + "\n")

    def test_real_checker_accepts_only_the_frozen_observation(self):
        report = gate.evaluate(self.root)
        self.assertTrue(report["policy_passed"])
        self.assertEqual(
            (
                report["raw_lint_findings"],
                report["frozen_historical_findings"],
                report["new_findings"],
                report["tracked_files_checked"],
            ),
            (1, 1, 0, 3),
        )

    def test_same_word_in_new_file_is_not_globally_ignored(self):
        (self.root / "new.txt").write_text(TOKEN + "\n")
        with redirect_stderr(io.StringIO()):
            report = gate.evaluate(self.root)
        self.assertEqual(
            (
                report["policy_passed"],
                report["raw_lint_findings"],
                report["frozen_historical_findings"],
                report["new_findings"],
            ),
            (False, 2, 1, 1),
        )

    def test_any_frozen_byte_change_fails(self):
        (self.root / "evidence.txt").write_text(TOKEN + "\ncorrect spelling\n")
        with self.assertRaisesRegex(gate.PolicyError, "bytes changed"):
            gate.evaluate(self.root)

    def test_rebinding_changed_bytes_cannot_replace_historical_provenance(self):
        (self.root / "evidence.txt").write_text(TOKEN + "\ncorrect spelling\n")
        self.policy["files"][0].update(self.record("evidence.txt"))
        self.write_policy(self.policy)
        with patch.object(
            gate, "AUTHORIZED_POLICY_SHA256", gate.policy_identity(self.policy)
        ):
            with self.assertRaisesRegex(gate.PolicyError, "provenance mismatch"):
                gate.evaluate(self.root)

    def test_new_file_cannot_be_registered_as_historical(self):
        (self.root / "new.txt").write_text(TOKEN + "\n")
        entry = copy.deepcopy(self.policy["files"][0])
        entry.update(self.record("new.txt"))
        self.policy["files"].append(entry)
        self.write_policy(self.policy)
        with patch.object(
            gate, "AUTHORIZED_POLICY_SHA256", gate.policy_identity(self.policy)
        ):
            with self.assertRaisesRegex(gate.PolicyError, "Git verification failed"):
                gate.evaluate(self.root)

    def test_removing_historical_inventory_and_changing_source_cannot_pass(self):
        second = self.root / "second.txt"
        second.write_text(TOKEN + "\n")
        self.run_git("add", "second.txt")
        self.run_git(
            "-c",
            "user.name=Policy Tests",
            "-c",
            "user.email=policy@example.invalid",
            "-c",
            "commit.gpgsign=false",
            "commit",
            "--quiet",
            "-m",
            "Freeze second evidence",
        )
        self.policy["source_commit"] = self.run_git("rev-parse", "HEAD").strip()
        entry = copy.deepcopy(self.policy["files"][0])
        entry.update(self.record("second.txt"))
        entry["findings"][0]["diagnostic_sha256"] = gate.digest(
            DIAGNOSTIC.replace("evidence.txt", "second.txt").rstrip("\n").encode()
        )
        self.policy["files"].append(entry)
        identity = gate.policy_identity(self.policy)
        with (
            patch.object(gate, "SOURCE_COMMIT", self.policy["source_commit"]),
            patch.object(gate, "AUTHORIZED_POLICY_SHA256", identity),
        ):
            self.policy["files"].pop()
            second.write_text("restorable\n")
            self.write_policy(self.policy)
            with self.assertRaisesRegex(gate.PolicyError, "inventory changed"):
                gate.evaluate(self.root)

    def test_changed_global_configuration_fails(self):
        (self.root / ".codespellignore").write_text(TOKEN + "\n")
        with self.assertRaisesRegex(gate.PolicyError, "bytes changed"):
            gate.evaluate(self.root)

    def test_new_automatic_configuration_fails(self):
        (self.root / "setup.cfg").write_text("[codespell]\nquiet-level = 3\n")
        with self.assertRaisesRegex(gate.PolicyError, "automatic configuration"):
            gate.evaluate(self.root)

    def test_missing_tracked_file_fails(self):
        (self.root / "evidence.txt").unlink()
        with self.assertRaisesRegex(gate.PolicyError, "Tracked source is missing"):
            gate.evaluate(self.root)

    def test_sparse_checkout_fails(self):
        self.run_git("update-index", "--skip-worktree", "evidence.txt")
        with self.assertRaisesRegex(gate.PolicyError, "Sparse checkout"):
            gate.evaluate(self.root)

    def test_source_symlink_fails(self):
        source = self.root / "evidence.txt"
        source.rename(self.root / "original.txt")
        try:
            source.symlink_to(self.root / "original.txt")
        except OSError:
            self.skipTest("Creating symlinks is not available on this host")
        with self.assertRaisesRegex(gate.PolicyError, "Symlink"):
            gate.evaluate(self.root)

    def test_changed_checker_version_fails(self):
        wrong_version = subprocess.CompletedProcess([], 0, "0.0.0\n", "")
        with (
            patch.object(gate, "verify_checkout", return_value=3),
            patch.object(gate.subprocess, "run", return_value=wrong_version),
        ):
            with self.assertRaisesRegex(gate.PolicyError, "exact registered"):
                gate.evaluate(self.root)

    def test_source_change_during_checker_execution_fails(self):
        real_run = subprocess.run

        def mutate_after_scan(arguments, **kwargs):
            result = real_run(arguments, **kwargs)
            if "--count" in arguments:
                (self.root / "evidence.txt").write_text(TOKEN + "\ncorrect spelling\n")
            return result

        with patch.object(gate.subprocess, "run", side_effect=mutate_after_scan):
            with self.assertRaisesRegex(gate.PolicyError, "bytes changed"):
                gate.evaluate(self.root)

    def test_duplicate_and_unknown_json_fields_fail(self):
        for value in ['{"schema_version":1,"schema_version":1}', '{"unknown":1}']:
            with self.subTest(value=value):
                (self.root / gate.POLICY_PATH).write_text(value)
                with self.assertRaises(gate.PolicyError):
                    gate.load_policy(self.root)

    def test_invalid_manifest_bindings_fail(self):
        cases = []
        for key, value in [
            ("path", "../evidence.txt"),
            ("path", "/evidence.txt"),
            ("path", "folder\\evidence.txt"),
            ("bytes", True),
            ("sha256", "invalid"),
        ]:
            policy = copy.deepcopy(self.policy)
            policy["files"][0][key] = value
            cases.append(policy)
        for key, value in [
            ("line", True),
            ("line", 0),
            ("token_sha256", "invalid"),
            ("diagnostic_sha256", "invalid"),
        ]:
            policy = copy.deepcopy(self.policy)
            policy["files"][0]["findings"][0][key] = value
            cases.append(policy)
        duplicate = copy.deepcopy(self.policy)
        duplicate["files"][0]["findings"] *= 2
        cases.append(duplicate)
        changed_commit = copy.deepcopy(self.policy)
        changed_commit["source_commit"] = "0" * 40
        cases.append(changed_commit)
        for policy in cases:
            with self.subTest(policy=policy):
                self.write_policy(policy)
                with self.assertRaises(gate.PolicyError):
                    gate.load_policy(self.root)


if __name__ == "__main__":
    unittest.main()
