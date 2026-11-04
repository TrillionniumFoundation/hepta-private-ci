"""Controls for exact selected cases and complete provider-library evidence."""
import copy
import json
import unittest
from unittest.mock import patch

from run_native import inventory, validate_junit

SUBSET = {"package": "codex-core", "kind": "lib", "required": ["a", "b"], "complete_target": False}
FULL = {"package": "codex-model-provider-info", "kind": "lib",
        "required": ["a"], "complete_target": True}


def listing(scope, names=("a", "b", "other"), ignored=()):
    return {"test-count": len(names), "rust-suites": {scope["package"]: {
        "package-name": scope["package"], "kind": scope["kind"], "status": "listed",
        "binary-path": "/unused/compiled-tests",
        "testcases": {name: {"ignored": name in ignored,
                            "filter-match": {"status": "mismatch", "reason": "ignored"}
                            if name in ignored else {"status": "matches"}} for name in names},
    }}}


def xml(names, bad="", count=None):
    n = len(names) if count is None else count
    return ('<testsuites><testsuite tests="' + str(n)
            + '" failures="0" errors="0" skipped="0">'
            + "".join('<testcase name="' + name + '">' + bad + "</testcase>" for name in names)
            + "</testsuite></testsuites>").encode()


class EvidenceControls(unittest.TestCase):
    def test_subset_preserves_filtered_denominator(self):
        scope = copy.deepcopy(SUBSET)
        value = inventory(json.dumps(listing(scope)), scope)
        self.assertEqual(value["expected"], ["a", "b"])
        self.assertEqual(value["qualification_filtered_cases"], ["other"])
        self.assertEqual(value["all_runnable_count"], 3)
        self.assertFalse(value["complete_target"])

    def test_complete_library_uses_every_compiled_case(self):
        value = inventory(json.dumps(listing(FULL)), FULL)
        self.assertEqual(value["expected"], ["a", "b", "other"])
        self.assertEqual(value["qualification_filtered_cases"], [])
        self.assertEqual(validate_junit(xml(value["expected"]), value)["passed"], 3)

    def test_required_case_cannot_be_missing(self):
        with self.assertRaises(RuntimeError):
            inventory(json.dumps(listing(SUBSET, ("a", "other"))), SUBSET)

    def test_required_case_cannot_be_ignored(self):
        with self.assertRaises(RuntimeError):
            inventory(json.dumps(listing(SUBSET, ignored=("b",))), SUBSET)

    def test_complete_library_cannot_add_an_ignore(self):
        with self.assertRaises(RuntimeError):
            inventory(json.dumps(listing(FULL, ignored=("other",))), FULL)

    def test_filtered_inventory_is_rejected(self):
        data = listing(SUBSET)
        data["rust-suites"]["codex-core"]["testcases"]["other"]["filter-match"] = {
            "status": "mismatch", "reason": "expression"}
        with self.assertRaises(RuntimeError):
            inventory(json.dumps(data), SUBSET)

    def test_duplicate_inventory_keys_are_rejected(self):
        value = json.dumps(listing(SUBSET))
        value = value.replace('"test-count": 3', '"test-count": 3, "test-count": 3')
        with self.assertRaises(RuntimeError):
            inventory(value, SUBSET)

    def test_wrong_package_and_kind_are_rejected(self):
        for field, value in (("package-name", "other-package"), ("kind", "test")):
            data = listing(SUBSET)
            data["rust-suites"]["codex-core"][field] = value
            with self.subTest(field=field), self.assertRaises(RuntimeError):
                inventory(json.dumps(data), SUBSET)

    def test_known_platform_case_must_actually_be_absent(self):
        scope = dict(SUBSET, platform_exclusions={"Windows": ["b"]})
        with patch("run_native.platform.system", return_value="Windows"):
            value = inventory(json.dumps(listing(scope, ("a", "other"))), scope)
            self.assertEqual(value["expected"], ["a"])
            self.assertEqual(value["platform_excluded"], ["b"])
            with self.assertRaises(RuntimeError):
                inventory(json.dumps(listing(scope)), scope)

    def test_platform_exclusion_cannot_hide_an_unrequired_case(self):
        scope = dict(SUBSET, platform_exclusions={"Windows": ["other"]})
        with patch("run_native.platform.system", return_value="Windows"):
            with self.assertRaises(RuntimeError):
                inventory(json.dumps(listing(scope, ("a", "b"))), scope)

    def test_missing_duplicate_and_extra_junit_cases_are_rejected(self):
        listed = {"expected": ["a", "b"], "original_ignored": []}
        for names in (["a"], ["a", "a"], ["a", "b", "extra"]):
            with self.subTest(names=names), self.assertRaises(RuntimeError):
                validate_junit(xml(names), listed)

    def test_failure_skip_and_retry_nodes_are_rejected(self):
        listed = {"expected": ["a", "b"], "original_ignored": []}
        for tag in ("failure", "error", "skipped", "rerunFailure", "rerunError", "flakyFailure", "flakyError"):
            with self.subTest(tag=tag), self.assertRaises(RuntimeError):
                validate_junit(xml(["a", "b"], "<" + tag + "/>"), listed)

    def test_junit_counter_mismatch_is_rejected(self):
        with self.assertRaises(RuntimeError):
            validate_junit(xml(["a", "b"], count=3), {"expected": ["a", "b"], "original_ignored": []})


if __name__ == "__main__":
    unittest.main()
