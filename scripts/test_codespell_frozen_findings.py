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

    def test_explicit_multiplicity_accepts_exactly_the_registered_count(self):
        expected = Counter({key: 2 for key in EXPECTED})
        for count in (0, 1, 2, 3):
            with self.subTest(count=count):
                report = gate.classify(
                    DIAGNOSTIC * count,
                    f"{count}\n",
                    65 if count else 0,
                    expected,
                )
                self.assertEqual(report["policy_passed"], count == 2)
                self.assertEqual(report["missing_frozen_findings"], max(2 - count, 0))
                self.assertEqual(report["new_findings"], max(count - 2, 0))

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
        (self.root / "historical-v2.txt").write_text(f"{TOKEN} {TOKEN}\n")
        self.run_git("add", "historical-v2.txt")
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
            "Freeze extension",
        )
        self.extension_commit = self.run_git("rev-parse", "HEAD").strip()
        sources_patch = patch.object(
            gate, "EXTENSION_SOURCE_COMMITS", (self.extension_commit,)
        )
        sources_patch.start()
        self.addCleanup(sources_patch.stop)
        self.extension = {
            "schema_version": 2,
            "codespell_version": gate.VERSION,
            "legacy_policy": {
                "path": gate.POLICY_PATH,
                "source_commit": self.commit,
                "canonical_sha256": gate.AUTHORIZED_POLICY_SHA256,
            },
            "sources": [
                {
                    "source_commit": self.extension_commit,
                    "files": [
                        {
                            **self.record("historical-v2.txt"),
                            "findings": [
                                {
                                    "line": 1,
                                    "token_sha256": TOKEN_SHA,
                                    "diagnostic_sha256": gate.digest(
                                        DIAGNOSTIC.replace(
                                            "evidence.txt", "historical-v2.txt"
                                        )
                                        .rstrip("\n")
                                        .encode()
                                    ),
                                    "count": 2,
                                }
                            ],
                        }
                    ],
                }
            ],
        }
        extension_patch = self.authorized_extension()
        extension_patch.start()
        self.addCleanup(extension_patch.stop)

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

    def authorized_extension(self):
        self.extension["legacy_policy"]["canonical_sha256"] = (
            gate.AUTHORIZED_POLICY_SHA256
        )
        (self.root / gate.EXTENSION_PATH).write_text(json.dumps(self.extension) + "\n")
        return patch.object(
            gate, "AUTHORIZED_EXTENSION_SHA256", gate.policy_identity(self.extension)
        )

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
            (3, 3, 0, 4),
        )
        self.assertEqual(report["source_commits"], [self.commit, self.extension_commit])

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
            (False, 4, 3, 1),
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
            with (
                self.authorized_extension(),
                self.assertRaisesRegex(gate.PolicyError, "provenance mismatch"),
            ):
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
            with (
                self.authorized_extension(),
                self.assertRaisesRegex(gate.PolicyError, "Git verification failed"),
            ):
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

    def test_extension_inventory_and_count_tampering_fails(self):
        original = copy.deepcopy(self.extension)
        for count in (True, 0, -1, 1, 3):
            with self.subTest(count=count):
                changed = copy.deepcopy(original)
                changed["sources"][0]["files"][0]["findings"][0]["count"] = count
                (self.root / gate.EXTENSION_PATH).write_text(json.dumps(changed))
                with self.assertRaises(gate.PolicyError):
                    gate.evaluate(self.root)
        for field, value in (("sources", []), ("legacy_policy", {})):
            with self.subTest(field=field):
                changed = copy.deepcopy(original)
                changed[field] = value
                (self.root / gate.EXTENSION_PATH).write_text(json.dumps(changed))
                with self.assertRaises(gate.PolicyError):
                    gate.evaluate(self.root)

    def test_extension_is_required_without_fallback_to_version_one(self):
        (self.root / gate.EXTENSION_PATH).unlink()
        with self.assertRaises(FileNotFoundError):
            gate.evaluate(self.root)

    def test_extension_rejects_duplicate_files_and_diagnostic_tuples(self):
        original = copy.deepcopy(self.extension)
        for group in ("files", "findings"):
            with self.subTest(group=group):
                self.extension = copy.deepcopy(original)
                source = self.extension["sources"][0]
                entries = (
                    source["files"]
                    if group == "files"
                    else source["files"][0]["findings"]
                )
                entries.append(copy.deepcopy(entries[0]))
                with (
                    self.authorized_extension(),
                    self.assertRaisesRegex(gate.PolicyError, "Duplicate"),
                ):
                    gate.evaluate(self.root)

    def test_extension_cannot_replace_an_original_file(self):
        self.extension["sources"][0]["files"][0]["path"] = "evidence.txt"
        with (
            self.authorized_extension(),
            self.assertRaisesRegex(gate.PolicyError, "Duplicate source path"),
        ):
            gate.evaluate(self.root)

    def test_extension_source_must_match_its_fixed_registration(self):
        self.extension["sources"][0]["source_commit"] = "f" * 40
        with (
            self.authorized_extension(),
            self.assertRaisesRegex(gate.PolicyError, "source commits changed"),
        ):
            gate.evaluate(self.root)

    def test_extension_source_must_be_an_ancestor(self):
        unrelated = self.run_git(
            "-c",
            "user.name=Policy Tests",
            "-c",
            "user.email=policy@example.invalid",
            "-c",
            "commit.gpgsign=false",
            "commit-tree",
            "HEAD^{tree}",
            "-m",
            "Other root",
        ).strip()
        self.extension["sources"][0]["source_commit"] = unrelated
        with (
            patch.object(gate, "EXTENSION_SOURCE_COMMITS", (unrelated,)),
            self.authorized_extension(),
            self.assertRaisesRegex(gate.PolicyError, "Git verification failed"),
        ):
            gate.evaluate(self.root)

    def test_extension_changed_bytes_cannot_replace_historical_provenance(self):
        (self.root / "historical-v2.txt").write_text(f"{TOKEN} {TOKEN}\ncorrect\n")
        self.extension["sources"][0]["files"][0].update(
            self.record("historical-v2.txt")
        )
        with (
            self.authorized_extension(),
            self.assertRaisesRegex(gate.PolicyError, "provenance mismatch"),
        ):
            gate.evaluate(self.root)

    def test_extension_cannot_register_a_new_file_as_historical(self):
        (self.root / "new.txt").write_text(f"{TOKEN} {TOKEN}\n")
        self.extension["sources"][0]["files"][0].update(self.record("new.txt"))
        with (
            self.authorized_extension(),
            self.assertRaisesRegex(gate.PolicyError, "Git verification failed"),
        ):
            gate.evaluate(self.root)

    def test_real_checker_rejects_a_missing_or_extra_registered_occurrence(self):
        finding = self.extension["sources"][0]["files"][0]["findings"][0]
        for count, missing, new in ((1, 0, 1), (3, 1, 0)):
            with self.subTest(count=count):
                finding["count"] = count
                with self.authorized_extension(), redirect_stderr(io.StringIO()):
                    report = gate.evaluate(self.root)
                self.assertEqual(
                    {
                        key: report[key]
                        for key in (
                            "policy_passed",
                            "raw_lint_findings",
                            "missing_frozen_findings",
                            "new_findings",
                        )
                    },
                    {
                        "policy_passed": False,
                        "raw_lint_findings": 3,
                        "missing_frozen_findings": missing,
                        "new_findings": new,
                    },
                )

    def test_extension_changes_during_scan_fail_even_for_json_whitespace(self):
        real_run = subprocess.run

        def mutate_after_scan(arguments, **kwargs):
            result = real_run(arguments, **kwargs)
            if "--count" in arguments:
                path = self.root / gate.EXTENSION_PATH
                path.write_bytes(path.read_bytes() + b"\n")
            return result

        with patch.object(gate.subprocess, "run", side_effect=mutate_after_scan):
            with self.assertRaisesRegex(
                gate.PolicyError, "Extension changed during scan"
            ):
                gate.evaluate(self.root)


if __name__ == "__main__":
    unittest.main()
