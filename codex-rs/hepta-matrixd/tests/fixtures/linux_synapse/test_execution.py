"""Exact nextest selection and fresh evidence parsing; no Docker/Rust qualification."""

import copy
from pathlib import Path
import tempfile
import unittest

from .contract import TEST_BINARY_ID, TEST_NAME
from .files import describe
from .receipts import junit
from .runtime import validate_test_listing


class ExecutionEvidence(unittest.TestCase):
    def test_full_inventory_selects_one_actual_frozen_path_and_rejects_tamper(self):
        with tempfile.TemporaryDirectory(prefix="hepta-test-inventory-") as temporary:
            root = Path(temporary).resolve()
            binary = root / "frozen-test"
            binary.write_bytes(
                b"actual bytes checked without invoking a model or test binary"
            )
            cases = {
                f"other_case_{index}": {
                    "ignored": False,
                    "filter-match": {"status": "mismatch"},
                }
                for index in range(8)
            }
            cases[TEST_NAME] = {"ignored": False, "filter-match": {"status": "matches"}}
            listing = {
                "rust-suites": {
                    TEST_BINARY_ID: {"binary-path": str(binary), "testcases": cases}
                }
            }
            build = {
                "binaries": {"test": {"path": str(binary), **describe(binary)}},
                "testcase_inventory": {
                    name: {"ignored": value["ignored"]} for name, value in cases.items()
                },
            }
            self.assertEqual(
                validate_test_listing(listing, build),
                {
                    "actual_binary_path": str(binary),
                    "total_cases_retained": 9,
                    "selected_cases": [TEST_NAME],
                },
            )
            for mode in (
                "extra_match",
                "no_match",
                "ignored",
                "missing_case",
                "unexpected_status",
                "wrong_path",
            ):
                changed = copy.deepcopy(listing)
                suite = changed["rust-suites"][TEST_BINARY_ID]
                if mode == "extra_match":
                    suite["testcases"]["other_case_0"]["filter-match"]["status"] = (
                        "matches"
                    )
                elif mode == "no_match":
                    suite["testcases"][TEST_NAME]["filter-match"]["status"] = "mismatch"
                elif mode == "ignored":
                    suite["testcases"][TEST_NAME]["ignored"] = True
                elif mode == "missing_case":
                    del suite["testcases"]["other_case_0"]
                elif mode == "unexpected_status":
                    suite["testcases"]["other_case_0"]["filter-match"]["status"] = (
                        "unknown"
                    )
                else:
                    alternate = root / "same-bytes-different-path"
                    alternate.write_bytes(binary.read_bytes())
                    suite["binary-path"] = str(alternate)
                with self.subTest(mode=mode), self.assertRaises(ValueError):
                    validate_test_listing(changed, build)
            binary.write_bytes(b"same path, changed executed bytes")
            with self.assertRaises(ValueError):
                validate_test_listing(listing, build)

    def test_junit_requires_one_success_and_no_hidden_skips_or_reruns(self):
        with tempfile.TemporaryDirectory(prefix="hepta-junit-") as temporary:
            root = Path(temporary).resolve()
            case = f'<testcase name="{TEST_NAME}" classname="{TEST_BINARY_ID}">{{body}}</testcase>'
            passing = (
                '<testsuites tests="1" failures="0" errors="0"><testsuite tests="1">'
                + case.format(body="")
                + "</testsuite></testsuites>"
            )
            path = root / "actual.xml"
            path.write_text(passing)
            self.assertEqual(junit(path)["passed"], 1)
            variants = [
                passing.replace(case.format(body=""), case.format(body=f"<{tag}/>"))
                for tag in ("failure", "error", "skipped", "flakyFailure", "rerunError")
            ]
            variants += [
                passing.replace(
                    'tests="1" failures="0" errors="0"',
                    'tests="1" failures="1" errors="0"',
                ),
                passing.replace("</testsuite>", case.format(body="") + "</testsuite>"),
                passing.replace(TEST_NAME, "a_different_test"),
                passing.replace(TEST_BINARY_ID, "unrelated_binary"),
            ]
            for index, text in enumerate(variants):
                path.write_text(text)
                with self.subTest(index=index), self.assertRaises(ValueError):
                    junit(path)


if __name__ == "__main__":
    unittest.main()
