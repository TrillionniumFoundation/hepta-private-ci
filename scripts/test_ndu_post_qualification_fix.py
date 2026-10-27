"""Exercise real small Git trees and executable tools, not Rust tests."""

import json
import unittest

import ndu_port_candidate_common as common
import ndu_post_qualification_fix as fix
from ndu_post_qualification_test_support import PostQualificationFixture
from ndu_post_qualification_test_support import git


class PostQualificationFixTests(PostQualificationFixture):
    def test_unchanged_source_keeps_original_identity(self):
        status, receipt, output = self.run_fix()
        self.assertEqual(status, 0)
        self.assertEqual(receipt["status"], "clippy_passed_source_unchanged")
        self.assertTrue(
            receipt["prior_behavioral_qualification_applies_to_after_source"]
        )
        self.assertEqual(receipt["before_tree"], receipt["after_tree"])
        self.assertEqual((output / "fix.patch").read_bytes(), b"")
        self.assertEqual((self.root / ".git/index").read_bytes(), self.index_before)
        self.assertEqual(
            json.loads(self.stamp.read_text()),
            [
                "fix",
                "--locked",
                "--profile",
                "ci-test",
                "-p",
                "codex-hepta-matrix-sdk",
                "-p",
                "codex-hepta-matrixd",
                "--features",
                "codex-hepta-matrixd/real-synapse-e2e",
            ],
        )

    def test_nonempty_matrix_delta_does_not_inherit_behavior_pass(self):
        status, receipt, output = self.run_fix(
            action={
                "writes": {str(self.root / self.source): "fixed candidate source\n"}
            }
        )
        self.assertEqual(status, 0)
        self.assertEqual(receipt["status"], "clippy_passed_review_required")
        self.assertFalse(
            receipt["prior_behavioral_qualification_applies_to_after_source"]
        )
        self.assertNotEqual(receipt["before_tree"], receipt["after_tree"])
        self.assertEqual(receipt["changed_paths"], [self.source])
        self.assertNotIn("Cargo.lock", (output / "fix.patch").read_text())
        self.assertEqual(
            (output / "before-source" / self.source).read_text(),
            "reviewed candidate source\n",
        )
        self.assertEqual(
            (output / "after-source" / self.source).read_text(),
            "fixed candidate source\n",
        )
        self.assertEqual((self.root / ".git/index").read_bytes(), self.index_before)

    def test_yaml_scope_has_five_packages_without_matrix_features(self):
        self.make_test_receipt("yaml")
        status, receipt, _ = self.run_fix(
            "yaml", action={"writes": {str(self.root / self.yaml): "fixed YAML\n"}}
        )
        self.assertEqual(status, 0)
        self.assertEqual(receipt["changed_paths"], [self.yaml])
        argv = json.loads(self.stamp.read_text())
        self.assertNotIn("--features", argv)
        self.assertEqual(
            [argv[i + 1] for i, item in enumerate(argv) if item == "-p"],
            list(fix.GROUPS["yaml"]["packages"]),
        )

    def test_failed_clippy_retains_partial_patch_and_original_result(self):
        before = (self.consumer / "RESULT.json").read_bytes()
        status, receipt, output = self.run_fix(
            action={
                "exit": 7,
                "writes": {str(self.root / self.source): "partial fix\n"},
            }
        )
        self.assertEqual(status, 1)
        self.assertEqual(receipt["clippy_exit_code"], 7)
        self.assertTrue((output / "fix.patch").stat().st_size)
        self.assertFalse(
            receipt["prior_behavioral_qualification_applies_to_after_source"]
        )
        self.assertEqual((output / "ORIGINAL_TEST_RESULT.json").read_bytes(), before)

    def test_protected_or_other_group_source_edits_are_rejected(self):
        for number, name in enumerate(
            (
                common.LOCKS[0],
                common.POLICIES[0],
                f"{self.vendor}/Cargo.toml",
                self.yaml,
            )
        ):
            with self.subTest(path=name):
                original = (self.root / name).read_bytes()
                status, receipt, output = self.run_fix(
                    name=f"scope-{number}",
                    action={"writes": {str(self.root / name): "forbidden edit\n"}},
                )
                self.assertEqual(status, 1)
                self.assertIn("outside", receipt["after_capture_error"])
                self.assertTrue((output / "fix.patch").stat().st_size)
                self.assertFalse(
                    receipt["prior_behavioral_qualification_applies_to_after_source"]
                )
                (self.root / name).write_bytes(original)

    def test_changed_original_evidence_is_rejected(self):
        log = self.consumer / self.test_record["commands"][0]["log"]
        status, receipt, _ = self.run_fix(
            action={"writes": {str(log): "overwritten original test log\n"}}
        )
        self.assertEqual(status, 1)
        self.assertIn("original test evidence", receipt["after_capture_error"])

    def test_wrong_version_prevents_fix(self):
        status, receipt, _ = self.run_fix(action={"version": "0.1.95"})
        self.assertEqual(status, 1)
        self.assertIn("version", receipt["error"])
        self.assertFalse(self.stamp.exists())

    def test_staged_mode_change_rejected_even_with_same_file_bytes(self):
        (self.root / self.source).chmod(0o755)
        git(self.root, "add", "--", self.source)
        before = (self.root / ".git/index").read_bytes()
        status, receipt, _ = self.run_fix()
        self.assertEqual(status, 1)
        self.assertIn("modes", receipt["error"])
        self.assertFalse(self.stamp.exists())
        self.assertEqual((self.root / ".git/index").read_bytes(), before)

    def test_ignored_extra_input_prevents_fix(self):
        self.put("ignored-override", "unexpected source input\n")
        status, receipt, _ = self.run_fix()
        self.assertEqual(status, 1)
        self.assertIn("extra files", receipt["error"])
        self.assertFalse(self.stamp.exists())

    def test_new_ignored_file_after_fix_is_rejected(self):
        status, receipt, _ = self.run_fix(
            action={"writes": {str(self.root / "ignored-new"): "unexpected\n"}}
        )
        self.assertEqual(status, 1)
        self.assertIn("ignored files", receipt["after_capture_error"])

    def test_wrong_receipt_or_old_reopen_cannot_authorize_fix(self):
        mutations = (
            lambda r: r.update(status="tests_failed"),
            lambda r: r.update(candidate_result_sha256="0" * 64),
            lambda r: r["test_results"].pop(),
            lambda r: r["old_fixture_input"].update(
                producer_fixture_unchanged_after_reopen=False
            ),
            lambda r: r["commands"][-1]["command"].__setitem__(-5, "test(=wrong)"),
        )
        original = json.dumps(self.test_record)
        for index, mutate in enumerate(mutations):
            with self.subTest(index=index):
                self.test_record = json.loads(original)
                mutate(self.test_record)
                self.write_receipt()
                status, receipt, _ = self.run_fix(name=f"receipt-{index}")
                self.assertEqual(status, 1)
                self.assertFalse(self.stamp.exists())
                self.assertFalse(
                    receipt["prior_behavioral_qualification_applies_to_after_source"]
                )

    def test_skipped_reopen_junit_prevents_fix(self):
        path = self.consumer / "reopen-junit.xml"
        path.write_text(
            path.read_text().replace(
                "/></testsuite>", "><skipped/></testcase></testsuite>"
            )
        )
        self.test_record["migration_phase"]["junit"]["sha256"] = common.checksum(path)
        self.write_receipt()
        status, receipt, _ = self.run_fix()
        self.assertEqual(status, 1)
        self.assertIn("Skipped", receipt["error"])
        self.assertFalse(self.stamp.exists())


if __name__ == "__main__":
    unittest.main()
