"""Independent reader controls. No original product code or binary is executed."""
import json
import unittest

from verify_original_followups import CORE, RESTART, checked_junit, compiled_inventory


def listing(package="codex-core", kind="lib", names=None):
    if names is None:
        names = set(CORE) | {"not_selected", "original_ignored"}
    cases = {name: {"ignored": name == "original_ignored",
                    "filter-match": {"status": "mismatch", "reason": "ignored"}
                    if name == "original_ignored" else {"status": "matches"}}
             for name in sorted(names)}
    return json.dumps({"test-count": len(cases), "rust-suites": {
        "exact_binary": {"package-name": package, "kind": kind, "status": "listed",
                         "binary-path": "original-binary", "testcases": cases}}}).encode()


def xml(names, extra="", count=None):
    names = list(names)
    count = len(names) if count is None else count
    return ('<testsuites><testsuite tests="' + str(count) + '" failures="0" errors="0" skipped="0">'
            + ''.join('<testcase name="' + name + '">' + extra + '</testcase>' for name in names)
            + '</testsuite></testsuites>').encode()


class FocusedReaderControls(unittest.TestCase):
    def test_core_selection_does_not_count_unselected_inventory(self):
        value = compiled_inventory(listing(), "codex-core", "lib", CORE, False)
        self.assertEqual(len(value["all_cases"]), 4)
        self.assertEqual(value["qualification_filtered_cases"], ["not_selected"])
        self.assertEqual(checked_junit(xml(sorted(CORE)), value)["passed"], 2)

    def test_complete_supervisor_case(self):
        value = compiled_inventory(listing("codex-hepta-supervisor", "test", RESTART),
                                   "codex-hepta-supervisor", "test", RESTART, True)
        self.assertEqual(checked_junit(xml(RESTART), value)["passed"], 1)

    def test_missing_required_compiled_case_rejected(self):
        with self.assertRaises(RuntimeError):
            compiled_inventory(listing(names={next(iter(CORE))}), "codex-core", "lib", CORE, False)

    def test_changed_supervisor_universe_rejected(self):
        with self.assertRaises(RuntimeError):
            compiled_inventory(listing("codex-hepta-supervisor", "test", RESTART | {"extra"}),
                               "codex-hepta-supervisor", "test", RESTART, True)

    def test_wrong_package_rejected(self):
        with self.assertRaises(RuntimeError):
            compiled_inventory(listing(package="other"), "codex-core", "lib", CORE, False)

    def test_selected_inventory_filter_rejected(self):
        value = json.loads(listing())
        value["rust-suites"]["exact_binary"]["testcases"][sorted(CORE)[0]]["filter-match"] = {
            "status": "mismatch", "reason": "expression"}
        with self.assertRaises(RuntimeError):
            compiled_inventory(json.dumps(value).encode(), "codex-core", "lib", CORE, False)

    def test_missing_duplicate_or_extra_execution_rejected(self):
        value = compiled_inventory(listing(), "codex-core", "lib", CORE, False)
        names = sorted(CORE)
        for executed in (names[:1], [names[0], names[0]], names + ["not_selected"]):
            with self.subTest(executed=executed), self.assertRaises(RuntimeError):
                checked_junit(xml(executed), value)

    def test_skip_retry_failure_rejected(self):
        value = compiled_inventory(listing(), "codex-core", "lib", CORE, False)
        for tag in ("skipped", "failure", "error", "rerunFailure", "flakyFailure"):
            with self.subTest(tag=tag), self.assertRaises(RuntimeError):
                checked_junit(xml(CORE, "<" + tag + "/>"), value)

    def test_inconsistent_junit_counter_rejected(self):
        value = compiled_inventory(listing(), "codex-core", "lib", CORE, False)
        with self.assertRaises(RuntimeError):
            checked_junit(xml(CORE, count=3), value)

    def test_duplicate_json_key_rejected(self):
        raw = listing().replace(b'"test-count": 4', b'"test-count": 4, "test-count": 4')
        with self.assertRaises(RuntimeError):
            compiled_inventory(raw, "codex-core", "lib", CORE, False)


if __name__ == "__main__":
    unittest.main()
