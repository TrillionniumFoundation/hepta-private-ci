"""Adversarial tests for the native evidence collector; no live credentials."""
from __future__ import annotations

import copy
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location(
    "native_evidence", Path(__file__).with_name("hepta_ui_native_evidence.py")
)
evidence = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(evidence)


class RustInventoryTests(unittest.TestCase):
    def test_comments_and_string_literals_are_not_exports(self):
        source = '''// pub fn fake() {}
/* outer /* pub struct False; */ pub enum Hidden {} */
const S: &str = r###"pub fn fabricated() {}"###;
const C: char = '"';
pub async fn real() {}
'''
        api, _ = evidence.declarations("x.rs", source)
        self.assertEqual([x["name"] for x in api], ["real"])
        self.assertEqual(api[0]["line"], 5)

    def test_restricted_visibility_is_not_claimed_public(self):
        api, _ = evidence.declarations("x.rs", "pub(crate) fn internal() {}\npub struct Exposed;")
        self.assertEqual([x["visibility"] for x in api], ["restricted", "public"])

    def test_multiline_public_declarations(self):
        api, _ = evidence.declarations("x.rs", "pub\nunsafe fn real() {}\npub const LIMIT: u64 = 1;")
        self.assertEqual([x["name"] for x in api], ["real", "LIMIT"])

    def test_test_inventory_is_not_test_execution(self):
        _, cases = evidence.declarations("x.rs", "#[test]\n#[ignore]\nfn needs_host() {}")
        self.assertEqual(cases[0]["name"], "needs_host")
        self.assertFalse(cases[0]["executionProved"])

    def test_tokio_test_attributes(self):
        _, cases = evidence.declarations("x.rs", '#[tokio::test(flavor = "current_thread")]\nasync fn real() {}')
        self.assertEqual(cases[0]["name"], "real")

    def test_unterminated_comment_refused(self):
        with self.assertRaises(ValueError):
            evidence.masked_rust("/* x")

    def test_unterminated_raw_string_refused(self):
        with self.assertRaises(ValueError):
            evidence.masked_rust('r##"x')

    def test_lifetime_is_not_a_character(self):
        api, _ = evidence.declarations("x.rs", "pub fn live<'a>(v: &'a str) {}")
        self.assertEqual(api[0]["name"], "live")


class CheckValidationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.subject = {"sourceSha": "a" * 40, "sourceTreeSha": "b" * 40}
        self.checks = []
        for label in evidence.REQUIRED:
            log = self.root / f"{label}.log"
            log.write_bytes(b"retained command output\n")
            self.checks.append({"schema": "hepta.ui.native.check.v1", **self.subject,
                                "label": label, "exitCode": 0, "timedOut": False,
                                "sourceUnchanged": True, "command": ["test-command"],
                                "startedAt": "2026-09-27T00:00:00+00:00",
                                "finishedAt": "2026-09-27T00:00:01+00:00",
                                "log": log.name, "logSha256": evidence.sha256(log.read_bytes())})

    def validate(self):
        evidence.validate_checks(self.checks, self.root, self.subject, "macOS")

    def test_complete_matrix_checks_accepted(self):
        self.validate()

    def test_missing_check_refused(self):
        self.checks.pop()
        with self.assertRaises(ValueError): self.validate()

    def test_duplicate_check_refused(self):
        self.checks[-1] = copy.deepcopy(self.checks[0])
        with self.assertRaises(ValueError): self.validate()

    def test_boolean_exit_status_not_zero(self):
        self.checks[0]["exitCode"] = False
        with self.assertRaises(ValueError): self.validate()

    def test_failure_refused(self):
        self.checks[0]["exitCode"] = 1
        with self.assertRaises(ValueError): self.validate()

    def test_timeout_refused(self):
        self.checks[0]["timedOut"] = True
        with self.assertRaises(ValueError): self.validate()

    def test_dirty_source_refused(self):
        self.checks[0]["sourceUnchanged"] = False
        with self.assertRaises(ValueError): self.validate()

    def test_foreign_head_refused(self):
        self.checks[0]["sourceSha"] = "c" * 40
        with self.assertRaises(ValueError): self.validate()

    def test_foreign_tree_refused(self):
        self.checks[0]["sourceTreeSha"] = "c" * 40
        with self.assertRaises(ValueError): self.validate()

    def test_modified_log_refused(self):
        (self.root / self.checks[0]["log"]).write_bytes(b"changed")
        with self.assertRaises(ValueError): self.validate()

    def test_missing_log_refused(self):
        (self.root / self.checks[0]["log"]).unlink()
        with self.assertRaises(ValueError): self.validate()

    def test_path_traversal_refused(self):
        self.checks[0]["log"] = "../identity.log"
        with self.assertRaises(ValueError): self.validate()

    def test_command_missing_refused(self):
        self.checks[0]["command"] = []
        with self.assertRaises(ValueError): self.validate()

    def test_clock_without_timezone_refused(self):
        self.checks[0]["startedAt"] = "2026-09-27T00:00:00"
        with self.assertRaises(ValueError): self.validate()

    def test_negative_clock_interval_refused(self):
        self.checks[0]["finishedAt"] = "2026-09-26T00:00:00+00:00"
        with self.assertRaises(ValueError): self.validate()

    def test_linux_requires_installed_product_test(self):
        with self.assertRaises(ValueError):
            evidence.validate_checks(self.checks, self.root, self.subject, "Linux")

    def test_unknown_platform_refused(self):
        with self.assertRaises(ValueError):
            evidence.validate_checks(self.checks, self.root, self.subject, "other")


class ActualCommandTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "repo"
        self.root.mkdir()
        self.out = Path(self.temp.name) / "external-evidence"
        self.git("init", "--quiet")
        self.git("config", "user.email", "fixture@example.invalid")
        self.git("config", "user.name", "fixture")
        self.model = self.root / "apps/hepta-native/src/model.rs"
        self.model.parent.mkdir(parents=True)
        self.model.write_text("pub enum PlatformAction { OpenPath, CopyText }\n")
        self.git("add", ".")
        self.git("commit", "--quiet", "-m", "fixture")

    def git(self, *args):
        return subprocess.check_output(["git", *args], cwd=self.root, stderr=subprocess.STDOUT)

    def run_check(self, command, timeout=10):
        with patch.dict(os.environ, {"NATIVE_EXPECTED_HEAD": evidence.git(self.root, "rev-parse", "HEAD")}):
            return evidence.run_check(self.root, self.out, "app_tests", command, timeout)

    def test_real_success_writes_bound_receipt_outside_repository(self):
        self.assertEqual(self.run_check([sys.executable, "-c", "print('executed')"]), 0)
        report = json.loads((self.out / "app_tests.json").read_text())
        self.assertEqual(report["sourceSha"], evidence.git(self.root, "rev-parse", "HEAD"))
        self.assertIn(b"executed", (self.out / "app_tests.log").read_bytes())

    def test_real_failure_is_not_hidden(self):
        self.assertEqual(self.run_check([sys.executable, "-c", "raise SystemExit(7)"]), 1)
        self.assertEqual(json.loads((self.out / "app_tests.json").read_text())["exitCode"], 7)

    def test_missing_executable_records_failure(self):
        self.assertEqual(self.run_check([str(self.root / "does-not-exist")]), 1)
        self.assertEqual(json.loads((self.out / "app_tests.json").read_text())["exitCode"], 127)

    def test_actual_timeout_fails(self):
        self.assertEqual(self.run_check([sys.executable, "-c", "import time; time.sleep(5)"], 1), 1)
        self.assertTrue(json.loads((self.out / "app_tests.json").read_text())["timedOut"])

    def test_mutated_source_cannot_get_success(self):
        code = "from pathlib import Path; Path('apps/hepta-native/src/model.rs').write_text('changed')"
        self.assertEqual(self.run_check([sys.executable, "-c", code]), 1)
        self.assertFalse(json.loads((self.out / "app_tests.json").read_text())["sourceUnchanged"])

    def test_second_observation_does_not_overwrite_first(self):
        self.run_check([sys.executable, "-c", "print('first')"])
        with self.assertRaises(FileExistsError):
            self.run_check([sys.executable, "-c", "print('second')"])
        self.assertIn(b"first", (self.out / "app_tests.log").read_bytes())

    def test_inventory_changes_when_committed_source_changes(self):
        before = evidence.inventory(self.root)
        self.model.write_text(self.model.read_text() + "pub fn added() {}\n#[test]\nfn actual_test() {}\n")
        with self.assertRaises(ValueError): evidence.inventory(self.root)
        self.git("add", ".")
        self.git("commit", "--quiet", "-m", "new source")
        after = evidence.inventory(self.root)
        self.assertNotEqual(before["inventorySha256"], after["inventorySha256"])
        self.assertNotEqual(before["sourceSha"], after["sourceSha"])
        self.assertEqual(after["tests"][0]["name"], "actual_test")
        self.assertFalse(after["releaseAuthorized"])


if __name__ == "__main__":
    unittest.main()
