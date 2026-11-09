"""Rejection controls for observer accounting; these are not native Rust tests."""

import copy
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET

import windows_operator_bazel as observer


class Accounting(unittest.TestCase):
    def setUp(self):
        self.names = ["trust::exact_namespace", "trust::wrong_namespace"]
        self.execution = {"startedUnix": 100.0, "finishedUnix": 120.0}
        self.result = {
            "testAttemptStartMillisEpoch": "110000",
            "status": "PASSED",
            "executionInfo": {"strategy": "local"},
        }
        self.events = [
            {
                "id": {
                    "testResult": {
                        "label": observer.TARGET,
                        "run": 1,
                        "shard": 0,
                        "attempt": 1,
                    }
                },
                "testResult": self.result,
            },
            {
                "id": {"testSummary": {"label": observer.TARGET}},
                "testSummary": {"overallStatus": "PASSED", "totalRunCount": 1},
            },
        ]

    def log(self, states=("ok", "ok")):
        rows = [f"test {name} ... {state}" for name, state in zip(self.names, states)]
        passed, failed, ignored = (
            states.count(value) for value in ("ok", "FAILED", "ignored")
        )
        status = "FAILED" if failed else "ok"
        rows.append(
            f"test result: {status}. {passed} passed; {failed} failed; {ignored} ignored; 0 measured; 0 filtered out; finished in 0.01s"
        )
        return "\n".join(rows) + "\n"

    def test_complete_discovery_is_only_a_list(self):
        listed = "".join(f"{name}: test\n" for name in self.names)
        self.assertEqual(observer.discovery_names(listed, self.names), self.names)
        with self.assertRaises(ValueError):
            observer.libtest_result(listed, self.names)

    def test_final_source_drift_cannot_leave_a_passed_status(self):
        receipt = {"passed": True, "status": "original_target_passed_without_retry"}
        observer.finalize_status(receipt, False)
        self.assertFalse(receipt["passed"])
        self.assertFalse(receipt["sourceUnchanged"])
        self.assertEqual(receipt["status"], "failed_or_incomplete")
        observer.finalize_status(receipt, True)
        self.assertFalse(receipt["passed"])
        self.assertEqual(receipt["status"], "failed_or_incomplete")

    def test_missing_foreign_and_duplicate_discovery_rejected(self):
        for names in (
            self.names[:1],
            [self.names[0], "other::case"],
            self.names + self.names[:1],
        ):
            with self.subTest(names=names), self.assertRaises(ValueError):
                observer.discovery_names(
                    "".join(f"{name}: test\n" for name in names), self.names
                )

    def test_original_case_rows_and_summary_pass_together(self):
        result = observer.libtest_result(self.log(), self.names)
        self.assertTrue(result["passed"])
        self.assertEqual(result["executed"], 2)

    def test_failed_or_ignored_case_cannot_pass(self):
        for state in ("FAILED", "ignored"):
            with self.subTest(state=state):
                self.assertFalse(
                    observer.libtest_result(self.log(("ok", state)), self.names)[
                        "passed"
                    ]
                )

    def test_missing_duplicate_and_false_count_results_rejected(self):
        for text in (
            self.log().replace(f"test {self.names[1]} ... ok\n", ""),
            self.log() + f"test {self.names[0]} ... ok\n",
            self.log().replace("2 passed", "3 passed"),
        ):
            with self.subTest(text=text), self.assertRaises(ValueError):
                observer.libtest_result(text, self.names)

    def test_bep_requires_the_original_wrapper_target(self):
        events = copy.deepcopy(self.events)
        events[0]["id"]["testResult"]["label"] += "-bin"
        with self.assertRaises(ValueError):
            observer.test_events(events)

    def test_retry_attempts_remain_separate_even_if_summary_passes(self):
        events = copy.deepcopy(self.events)
        retry = copy.deepcopy(events[0])
        retry["id"]["testResult"]["attempt"] = 2
        events.insert(1, retry)
        results, _ = observer.test_events(events)
        self.assertEqual(
            [row["id"]["testResult"]["attempt"] for row in results], [1, 2]
        )

    def test_duplicate_attempt_identity_rejected(self):
        with self.assertRaises(ValueError):
            observer.test_events(self.events + self.events[:1])

    def test_local_remote_and_old_cache_cannot_be_fresh(self):
        self.assertTrue(observer.freshness(self.result, self.execution))
        for change in (
            {"cachedLocally": True},
            {"executionInfo": {"cachedRemotely": True}},
            {"testAttemptStartMillisEpoch": "99000"},
        ):
            with self.subTest(change=change):
                self.assertFalse(
                    observer.freshness({**self.result, **change}, self.execution)
                )

    def test_xml_aggregate_is_not_promoted_to_two_native_cases(self):
        result = observer.xml_observation(
            b'<testsuite tests="1"><testcase name="wrapper"/></testsuite>',
            ET.TreeBuilder,
        )
        self.assertTrue(result["passed"])
        self.assertEqual(result["testcaseCount"], 1)
        self.assertEqual(
            result["granularity"], "original_Bazel_XML_not_assumed_per_Rust_case"
        )

    def test_negative_xml_children_attributes_and_declarations(self):
        for child in (
            "failure",
            "error",
            "skipped",
            "rerunFailure",
            "rerunError",
            "flakyFailure",
            "flakyError",
        ):
            data = f'<testsuite><testcase name="wrapper"><{child}/></testcase></testsuite>'.encode()
            with self.subTest(child=child):
                self.assertFalse(
                    observer.xml_observation(data, ET.TreeBuilder)["passed"]
                )
        self.assertFalse(
            observer.xml_observation(
                b'<testsuite failures="1"><testcase name="wrapper"/></testsuite>',
                ET.TreeBuilder,
            )["passed"]
        )
        with self.assertRaises(ValueError):
            observer.xml_observation(b"<!DOCTYPE x><testsuite/>", ET.TreeBuilder)

    def test_old_output_cannot_be_reused(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "test.xml"
            path.write_text("<testsuite/>", encoding="utf-8")
            with self.assertRaises(ValueError):
                observer.bounded(path, self.execution)

    def test_foreign_bep_uri_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            with self.assertRaises(ValueError):
                observer.local_output("https://example.invalid/test.log", root)
            with self.assertRaises(ValueError):
                observer.local_output("file://foreign-host/test.log", root)

    def test_only_discovery_receives_list_flags_and_target_is_never_inner(self):
        for mode in ("discovery", "execution"):
            command = observer.bazel_command("a" * 40, Path("records") / mode, mode)
            self.assertEqual(command[-1], observer.TARGET)
            self.assertIn("--nocache_test_results", command)
            self.assertEqual("--test_arg=--list" in command, mode == "discovery")
            self.assertEqual(
                "--test_arg=--format=terse" in command, mode == "discovery"
            )
            self.assertFalse(
                any(
                    arg.startswith(
                        (
                            "--test_env=",
                            "--runs_per_test=",
                            "--flaky_test_attempts=",
                            "--test_timeout=",
                        )
                    )
                    for arg in command
                )
            )


if __name__ == "__main__":
    unittest.main()
