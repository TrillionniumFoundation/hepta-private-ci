"""Negative controls for retained original schema evidence; no product code runs."""
import json
import unittest

from verify_schema_original import IGNORED, REQUIRED, PACKAGE, complete_native, identity


def listing():
    names = sorted(REQUIRED | {"unrelated_original_case", IGNORED})
    cases = {name: {"ignored": name == IGNORED,
                    "filter-match": {"status": "mismatch", "reason": "ignored"}
                    if name == IGNORED else {"status": "matches"}} for name in names}
    return json.dumps({"test-count": len(cases), "rust-suites": {"original-library": {
        "package-name": PACKAGE, "kind": "lib", "status": "listed", "testcases": cases}}}).encode()


def xml(names, skip=None, tag=None, count=None):
    names = list(names)
    body = "".join('<testcase name="' + name + '">' +
                   ("<skipped/>" if name == skip else "<" + tag + "/>" if tag else "") +
                   "</testcase>" for name in names)
    return ('<testsuites><testsuite tests="' + str(len(names) if count is None else count)
            + '" failures="0" errors="0" skipped="' + str(1 if skip else 0) + '">'
            + body + "</testsuite></testsuites>").encode()


class SchemaReaderControls(unittest.TestCase):
    def setUp(self):
        self.names = sorted(REQUIRED | {"unrelated_original_case"})

    def test_complete_library_counts_more_than_required_schema_four(self):
        result = complete_native(listing(), xml(self.names))
        self.assertEqual(result["passed"], 5)
        self.assertEqual(result["original_ignored_cases"], [IGNORED])
        self.assertEqual(result["junit_skipped_cases"], [])

    def test_original_ignored_generator_may_be_reported_skipped(self):
        result = complete_native(listing(), xml(self.names + [IGNORED], skip=IGNORED))
        self.assertEqual(result["passed"], 5)
        self.assertEqual(result["junit_skipped_cases"], [IGNORED])

    def test_missing_duplicate_extra_case_rejected(self):
        for names in (self.names[:-1], self.names + [self.names[0]], self.names + ["extra"]):
            with self.subTest(names=names), self.assertRaises(RuntimeError):
                complete_native(listing(), xml(names))

    def test_runnable_skip_rejected(self):
        with self.assertRaises(RuntimeError):
            complete_native(listing(), xml(self.names, skip=self.names[0]))

    def test_failure_and_all_retry_nodes_rejected(self):
        for tag in ("failure", "error", "rerunFailure", "rerunError", "flakyFailure", "flakyError"):
            with self.subTest(tag=tag), self.assertRaises(RuntimeError):
                complete_native(listing(), xml(self.names, tag=tag))

    def test_wrong_compiled_package_and_filter_rejected(self):
        data = json.loads(listing())
        for replacement in ("package", "filter"):
            changed = json.loads(json.dumps(data))
            suite = changed["rust-suites"]["original-library"]
            if replacement == "package":
                suite["package-name"] = "another-package"
            else:
                suite["testcases"][self.names[0]]["filter-match"] = {"status": "mismatch", "reason": "expression"}
            with self.subTest(replacement=replacement), self.assertRaises(RuntimeError):
                complete_native(json.dumps(changed).encode(), xml(self.names))

    def test_ignored_helper_cannot_become_new_ignored_case(self):
        data = json.loads(listing())
        suite = data["rust-suites"]["original-library"]
        suite["testcases"]["unrelated_original_case"]["ignored"] = True
        suite["testcases"]["unrelated_original_case"]["filter-match"] = {"status": "mismatch", "reason": "ignored"}
        with self.assertRaises(RuntimeError):
            complete_native(json.dumps(data).encode(), xml(self.names))

    def test_duplicate_json_key_rejected(self):
        raw = listing().replace(b'"test-count": 6', b'"test-count": 6, "test-count": 6')
        self.assertNotEqual(raw, listing())
        with self.assertRaises(RuntimeError):
            complete_native(raw, xml(self.names))

    def test_inconsistent_junit_counter_rejected(self):
        with self.assertRaises(RuntimeError):
            complete_native(listing(), xml(self.names, count=4))

    def test_raw_identity_binds_length_sha256_and_git_object(self):
        self.assertEqual(identity(b""), {
            "bytes": 0, "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
            "git_blob": "e69de29bb2d1d6434b8b29ae775ad8c2e48c5391"})
        self.assertNotEqual(identity(b"x"), identity(b"x\n"))


if __name__ == "__main__":
    unittest.main()
