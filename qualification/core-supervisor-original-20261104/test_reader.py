"""Reject false passes in the focused original-case evidence reader."""
import json
import unittest

from run_original_native import CORE_CASES, RESTART_CASES, SCOPES, inventory, validate_junit


def listing(scope):
    names = set(scope["required"])
    if not scope["complete_target"]:
        names |= {"unselected::control", "original::ignored"}
    cases = {
        name: {"ignored": name == "original::ignored",
               "filter-match": {"status": "mismatch", "reason": "ignored"}
               if name == "original::ignored" else {"status": "matches"}}
        for name in sorted(names)
    }
    return {"test-count": len(cases), "rust-suites": {
        scope["package"]: {"package-name": scope["package"], "kind": scope["kind"],
                           "status": "listed", "binary-path": "/unused/compiled-test",
                           "testcases": cases}}}


def xml(names, extra="", tests=None):
    count = len(names) if tests is None else tests
    body = "".join('<testcase name="' + name + '">' + extra + "</testcase>" for name in names)
    return ('<testsuites><testsuite tests="' + str(count) +
            '" failures="0" errors="0" skipped="0">' + body + "</testsuite></testsuites>").encode()


class EvidenceControls(unittest.TestCase):
    def test_exact_core_subset_is_explicit(self):
        result = inventory(json.dumps(listing(SCOPES[0])), SCOPES[0])
        self.assertEqual(set(result["expected"]), CORE_CASES)
        self.assertEqual(result["qualification_filtered_cases"], ["unselected::control"])
        self.assertEqual(result["original_ignored"], ["original::ignored"])
        self.assertFalse(result["complete_target"])

    def test_complete_original_restart_target(self):
        result = inventory(json.dumps(listing(SCOPES[1])), SCOPES[1])
        self.assertEqual(set(result["expected"]), RESTART_CASES)
        self.assertTrue(result["complete_target"])
        self.assertEqual(validate_junit(xml(result["expected"]), result)["passed"], 1)

    def test_required_case_cannot_be_ignored(self):
        value = listing(SCOPES[0])
        case = value["rust-suites"]["codex-core"]["testcases"][next(iter(CORE_CASES))]
        case.update({"ignored": True, "filter-match": {"status": "mismatch", "reason": "ignored"}})
        with self.assertRaises(RuntimeError):
            inventory(json.dumps(value), SCOPES[0])

    def test_wrong_binary_kind_is_rejected(self):
        value = listing(SCOPES[0])
        value["rust-suites"]["codex-core"]["kind"] = "test"
        with self.assertRaises(RuntimeError):
            inventory(json.dumps(value), SCOPES[0])

    def test_inventory_filter_is_rejected(self):
        value = listing(SCOPES[0])
        case = value["rust-suites"]["codex-core"]["testcases"]["unselected::control"]
        case["filter-match"] = {"status": "mismatch", "reason": "expression"}
        with self.assertRaises(RuntimeError):
            inventory(json.dumps(value), SCOPES[0])

    def test_duplicate_json_key_is_rejected(self):
        value = json.dumps(listing(SCOPES[0]))
        value = value.replace('"test-count": 4', '"test-count": 4, "test-count": 4')
        with self.assertRaises(RuntimeError):
            inventory(value, SCOPES[0])

    def test_complete_target_cannot_hide_extra_case(self):
        value = listing(SCOPES[1])
        suite = value["rust-suites"][SCOPES[1]["package"]]
        suite["testcases"]["unselected::control"] = {"ignored": False, "filter-match": {"status": "matches"}}
        value["test-count"] += 1
        with self.assertRaises(RuntimeError):
            inventory(json.dumps(value), SCOPES[1])

    def test_fresh_complete_core_report(self):
        value = {"expected": sorted(CORE_CASES), "original_ignored": []}
        self.assertEqual(validate_junit(xml(value["expected"]), value)["passed"], 2)

    def test_missing_duplicate_and_extra_results_are_rejected(self):
        value = {"expected": sorted(CORE_CASES), "original_ignored": []}
        names = value["expected"]
        for invalid in (names[:1], [names[0], names[0]], [*names, "extra"]):
            with self.subTest(names=invalid), self.assertRaises(RuntimeError):
                validate_junit(xml(invalid), value)

    def test_failures_skips_and_retries_are_rejected(self):
        value = {"expected": sorted(CORE_CASES), "original_ignored": []}
        for tag in ("failure", "error", "skipped", "rerunFailure", "rerunError", "flakyFailure", "flakyError"):
            with self.subTest(tag=tag), self.assertRaises(RuntimeError):
                validate_junit(xml(value["expected"], "<" + tag + "/>"), value)

    def test_counter_mismatch_is_rejected(self):
        value = {"expected": sorted(CORE_CASES), "original_ignored": []}
        with self.assertRaises(RuntimeError):
            validate_junit(xml(value["expected"], tests=3), value)


if __name__ == "__main__":
    unittest.main()
