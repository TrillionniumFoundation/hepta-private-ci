#!/usr/bin/env python3
"""Controls for rejecting incomplete evidence; these are not product test passes."""
import copy
import json
import unittest

from run_native import inventory, validate_junit
from run_bazel import test_counts


class EvidenceReaderTests(unittest.TestCase):
    def setUp(self):
        self.document = {"test-count": 2, "rust-suites": {"package": {
            "package-name": "package", "kind": "lib", "status": "listed",
            "binary-path": "/not-executed/test",
            "testcases": {name: {"kind": "test", "ignored": False, "filter-match": {"status": "matches"}}
                          for name in ("first", "second")}}}}
        self.listed = inventory(json.dumps(self.document), "package", [])
        self.xml = '<testsuites><testsuite tests="2" failures="0" errors="0"><testcase name="first"/><testcase name="second"/></testsuite></testsuites>'

    def test_complete_inventory_and_junit(self):
        self.assertEqual(validate_junit(self.xml, self.listed)["passed"], 2)

    def test_incomplete_junit_rejected(self):
        with self.assertRaises(RuntimeError):
            validate_junit(self.xml.replace('<testcase name="second"/>', ''), self.listed)

    def test_duplicate_case_rejected(self):
        with self.assertRaises(RuntimeError):
            validate_junit(self.xml.replace('name="second"', 'name="first"'), self.listed)

    def test_unknown_case_rejected(self):
        with self.assertRaises(RuntimeError):
            validate_junit(self.xml.replace('name="second"', 'name="other"'), self.listed)

    def test_failure_skip_and_retry_rejected(self):
        for tag in ("failure", "error", "skipped", "rerunFailure", "rerunError", "flakyFailure", "flakyError"):
            with self.subTest(tag=tag), self.assertRaises(RuntimeError):
                validate_junit(self.xml.replace('<testcase name="second"/>',
                              '<testcase name="second"><' + tag + '/></testcase>'), self.listed)

    def test_zero_run_rejected(self):
        with self.assertRaises(RuntimeError):
            validate_junit('<testsuites><testsuite tests="0"/></testsuites>', self.listed)

    def test_counters_rejected(self):
        with self.assertRaises(RuntimeError):
            validate_junit(self.xml.replace('tests="2"', 'tests="9"'), self.listed)

    def test_filter_is_not_an_ignore(self):
        row = self.document["rust-suites"]["package"]["testcases"]["second"]
        row["filter-match"] = {"status": "mismatch", "reason": "expression"}
        with self.assertRaises(RuntimeError):
            inventory(json.dumps(self.document), "package", [])

    def test_exact_original_ignored_set(self):
        row = self.document["rust-suites"]["package"]["testcases"]["second"]
        row.update({"ignored": True, "filter-match": {"status": "mismatch", "reason": "ignored"}})
        with self.assertRaises(RuntimeError):
            inventory(json.dumps(self.document), "package", [])
        listed = inventory(json.dumps(self.document), "package", ["second"])
        self.assertEqual(listed["expected"], ["first"])
        self.assertEqual(listed["original_ignored"], ["second"])

    def test_wrong_or_unlisted_library_rejected(self):
        for field, value in (("status", "skipped"), ("kind", "test"), ("package-name", "other")):
            doc = copy.deepcopy(self.document)
            doc["rust-suites"]["package"][field] = value
            with self.subTest(field=field), self.assertRaises(RuntimeError):
                inventory(json.dumps(doc), "package", [])

    def test_duplicate_json_key_rejected(self):
        with self.assertRaises(RuntimeError):
            inventory('{"test-count":2,"test-count":2}', "package", [])

    def test_bazel_complete_and_incomplete_results(self):
        good = b"test first ... ok\ntest result: ok. 1 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out;\n"
        self.assertEqual(test_counts(good, [])["passed"], 1)
        for bad in (b"running 2 tests\ntest first ... ok\n",
                    good.replace(b"1 passed", b"0 passed"),
                    good.replace(b"0 filtered", b"1 filtered"),
                    good + b"test result: FAILED. 1 passed; 1 failed; 0 ignored; 0 measured; 0 filtered out;\n"):
            with self.subTest(raw=bad), self.assertRaises(RuntimeError):
                test_counts(bad, [])

    def test_bazel_only_original_ignored_names(self):
        log = b"test probe ... ignored\n" + b"test result: ok. 1 passed; 0 failed; 1 ignored; 0 measured; 0 filtered out;\n"
        self.assertEqual(test_counts(log, ["probe"])["original_ignored"], ["probe"])
        with self.assertRaises(RuntimeError):
            test_counts(log, [])


if __name__ == "__main__":
    unittest.main()
