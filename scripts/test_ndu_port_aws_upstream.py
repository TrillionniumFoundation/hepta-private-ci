"""Guard complete upstream execution, including failures and original skips."""

import json
from pathlib import Path
import tempfile
import unittest

from ndu_port_aws_upstream import suite_inventory
from ndu_port_aws_upstream import verify_suite_junit


class FullUpstreamEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.qualification = {
            "expected_total": 245,
            "expected_executed": 244,
            "expected_ignored": 1,
            "ignored_tests": ["ecs::test::real_dns_lookup"],
        }
        cases = {
            f"case_{index}": {"ignored": False, "filter-match": {"status": "matches"}}
            for index in range(244)
        }
        cases["ecs::test::real_dns_lookup"] = {
            "ignored": True,
            "filter-match": {"status": "mismatch"},
        }
        self.listing = {
            "test-count": 245,
            "rust-suites": {
                "aws-config": {
                    "package-name": "aws-config",
                    "status": "listed",
                    "binary-id": "aws-config",
                    "binary-path": "/fixture/binary",
                    "testcases": cases,
                }
            },
        }
        self.expected = {("aws-config", f"case_{index}") for index in range(244)}

    def test_actual_remote_inventory_retains_the_exact_original_ignore(self):
        fixture = (
            Path(__file__).resolve().parents[1]
            / "experiments/multimodal_output_portfolio/closure_v2_20261027/ci/port-remediation/evidence/AWS_UPSTREAM_V2_TEST_LIST.json"
        )
        listing = json.loads(fixture.read_text())
        executed, binaries = suite_inventory(listing, self.qualification)
        self.assertEqual(len(executed), 244)
        self.assertEqual(set(binaries), {"aws-config"})
        self.assertNotIn(("aws-config", "ecs::test::real_dns_lookup"), executed)
        wrong_original_name = {
            **self.qualification,
            "ignored_tests": ["ecs::tests::real_dns_lookup"],
        }
        with self.assertRaises(ValueError):
            suite_inventory(listing, wrong_original_name)

    def test_omitted_or_filtered_or_newly_ignored_tests_cannot_qualify(self):
        executed, binaries = suite_inventory(self.listing, self.qualification)
        self.assertEqual(executed, self.expected)
        self.assertEqual(binaries, {"aws-config": "/fixture/binary"})
        cases = self.listing["rust-suites"]["aws-config"]["testcases"]
        item = cases["case_7"]
        item["filter-match"]["status"] = "mismatch"
        with self.assertRaisesRegex(ValueError, "filtered"):
            suite_inventory(self.listing, self.qualification)
        item["filter-match"]["status"] = "matches"
        item["ignored"] = True
        with self.assertRaisesRegex(ValueError, "inventory"):
            suite_inventory(self.listing, self.qualification)
        del cases["case_7"]
        with self.assertRaisesRegex(ValueError, "inventory"):
            suite_inventory(self.listing, self.qualification)

    def test_full_junit_retains_flaky_attempts_but_rejects_failed_assertions_or_missing_cases(
        self,
    ):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "junit.xml"

            def report(extra="", count=244):
                cases = "".join(
                    f'<testcase classname="aws-config" name="case_{index}">{extra if index == 7 else ""}</testcase>'
                    for index in range(count)
                )
                path.write_text(
                    f'<testsuites tests="244" failures="0" errors="0"><testsuite>{cases}</testsuite></testsuites>'
                )

            report()
            self.assertEqual(verify_suite_junit(path, self.expected)["passed"], 244)
            report("<flakyFailure>original failed attempt is retained</flakyFailure>")
            self.assertEqual(
                verify_suite_junit(path, self.expected)["passed_after_retry"], 1
            )
            for extra in (
                "<failure>timeout assertion failed</failure>",
                "<error>aborted</error>",
                "<skipped/>",
            ):
                report(extra)
                with self.assertRaises(ValueError):
                    verify_suite_junit(path, self.expected)
            report(count=243)
            with self.assertRaisesRegex(ValueError, "every one"):
                verify_suite_junit(path, self.expected)


if __name__ == "__main__":
    unittest.main()
