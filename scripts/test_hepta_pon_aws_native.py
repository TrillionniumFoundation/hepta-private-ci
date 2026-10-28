"""Parser and failure controls only. Every native command is mocked or forbidden."""

import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import hepta_pon_aws_native as native


SHA = "a" * 40


def listing():
    return {
        "test-count": 3,
        "rust-suites": {
            "aws-config": {
                "status": "listed",
                "testcases": {
                    "first": {"ignored": False, "filter-match": {"status": "matches"}},
                    "second": {"ignored": False, "filter-match": {"status": "matches"}},
                    "ignored": {
                        "ignored": True,
                        "filter-match": {"status": "mismatch", "reason": "ignored"},
                    },
                },
            }
        },
    }


def junit(second="", omit_second=False):
    tail = (
        ""
        if omit_second
        else f'<testcase classname="aws-config" name="second" time="0.02">{second}</testcase>'
    )
    return (
        '<testsuites><testsuite name="aws-config"><testcase classname="aws-config" name="first" time="0.01"/>'
        + tail
        + "</testsuite></testsuites>"
    ).encode()


class NativeObserverControls(unittest.TestCase):
    def test_discovery_keeps_ignored_and_exact_selected_identities(self):
        cases = native.discovery(json.dumps(listing()))
        result = native.reconcile(cases, junit())
        self.assertEqual(
            (
                result["discovered"],
                result["ignored"],
                result["selected"],
                result["observed"],
            ),
            (3, 1, 2, 2),
        )
        self.assertTrue(result["all_selected_passed"])

    def test_failure_timeout_missing_and_absent_junit_cannot_reduce_the_denominator(
        self,
    ):
        cases = native.discovery(json.dumps(listing()))
        for raw in [
            junit('<failure type="test timeout"/>'),
            junit('<error type="failed to start"/>'),
            junit("<skipped/>"),
            junit(omit_second=True),
            None,
        ]:
            with self.subTest(raw=raw):
                result = native.reconcile(cases, raw)
                self.assertEqual(result["selected"], 2)
                self.assertFalse(result["all_selected_passed"])
        self.assertEqual(len(native.reconcile(cases, None)["unobserved"]), 2)

    def test_forged_duplicate_retry_and_undeclared_junit_results_are_rejected(self):
        cases = native.discovery(json.dumps(listing()))
        for raw in [
            junit().replace(b'name="second"', b'name="first"'),
            junit().replace(b'name="second"', b'name="ignored"'),
            junit().replace(b'classname="aws-config"', b'classname="other"'),
            junit("<rerunFailure/>"),
            junit("<failure><rerunFailure/></failure>"),
            junit("<failure/><error/>"),
            b'<!DOCTYPE data [<!ENTITY x SYSTEM "file:///etc/passwd">]>' + junit(),
        ]:
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                native.reconcile(cases, raw)

    def test_incomplete_or_inconsistent_discovery_is_unknown(self):
        bad = []
        changed = listing()
        changed["test-count"] = 2
        bad.append(changed)
        changed = listing()
        changed["rust-suites"]["aws-config"]["status"] = "skipped"
        bad.append(changed)
        for field, value in [("ignored", None), ("filter-match", {"status": "future"})]:
            changed = listing()
            changed["rust-suites"]["aws-config"]["testcases"]["first"][field] = value
            bad.append(changed)
        changed = listing()
        changed["rust-suites"]["aws-config"]["testcases"] = {}
        changed["test-count"] = 0
        bad.append(changed)
        for data in bad:
            with self.subTest(data=data), self.assertRaises(ValueError):
                native.discovery(json.dumps(data))

    def test_local_execution_is_rejected_before_any_native_command(self):
        with (
            TemporaryDirectory() as temporary,
            patch.dict(os.environ, {}, clear=True),
            patch.object(native.subprocess, "run") as run,
        ):
            with self.assertRaisesRegex(
                ValueError, "restricted to the declared hosted workflow"
            ):
                native.run(Path(temporary), SHA)
            run.assert_not_called()

    def test_command_failure_preserves_all_later_stages_and_raw_failure(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / "evidence"
            state = {"commit": SHA, "tree": "b" * 40, "parents": [], "dirty": False}
            with patch.object(native, "source_state", return_value=state):
                native.prepare(output, SHA, "provider-default")

                def failed(_command, **kwargs):
                    kwargs["stderr"].write(b"synthetic native launch failure control\n")
                    return SimpleNamespace(returncode=23)

                with (
                    patch.dict(
                        os.environ,
                        {
                            "CARGO_TARGET_DIR": str(root / "target"),
                            "RUNNER_TEMP": str(root),
                        },
                    ),
                    patch.object(native.subprocess, "run", side_effect=failed) as run,
                ):
                    self.assertEqual(native.run(output, SHA), 23)
                    run.assert_called_once()
            record = json.loads((output / "record.json").read_text())
            self.assertEqual(record["stages"][0]["exit_code"], 23)
            self.assertEqual(
                [s["state"] for s in record["stages"][1:]], ["not_started"] * 6
            )
            self.assertIsNone(record["test_inventory"])
            self.assertEqual(
                (output / "logs/rustc-version.stderr.txt").read_bytes(),
                b"synthetic native launch failure control\n",
            )
            self.assertFalse(record["native_scenario_passed"])

    def test_finalizer_keeps_interrupted_outcome_and_unobserved_cases(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / "evidence"
            state = {"commit": SHA, "tree": "b" * 40, "parents": [], "dirty": False}
            with patch.object(native, "source_state", return_value=state):
                native.prepare(output, SHA, "provider-default")
                record = json.loads((output / "record.json").read_text())
                record["state"] = "running"
                record["stages"][-1]["state"] = "running"
                record["test_inventory"] = native.discovery(json.dumps(listing()))
                native.write_json(output / "record.json", record)
                with patch.dict(
                    os.environ,
                    {
                        "CARGO_TARGET_DIR": str(root / "target"),
                        "NATIVE_STEP_OUTCOME": "cancelled",
                    },
                ):
                    self.assertEqual(native.finalize(output, SHA), 1)
            record = json.loads((output / "record.json").read_text())
            self.assertEqual(record["stages"][-1]["state"], "interrupted_or_unknown")
            self.assertIsNone(record["stages"][-1]["exit_code"])
            self.assertEqual(len(record["terminal_cases"]["unobserved"]), 2)
            self.assertFalse(record["native_scenario_passed"])
            self.assertFalse(record["bigint_blocker_closed"])

    def test_stale_junit_is_rejected_before_any_native_command(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / "evidence"
            state = {"commit": SHA, "tree": "b" * 40, "parents": [], "dirty": False}
            with patch.object(native, "source_state", return_value=state):
                native.prepare(output, SHA, "auth-default")
                result = root / "target/nextest/local/junit.xml"
                result.parent.mkdir(parents=True)
                result.write_bytes(junit())
                with (
                    patch.dict(
                        os.environ,
                        {
                            "CARGO_TARGET_DIR": str(root / "target"),
                            "RUNNER_TEMP": str(root),
                        },
                    ),
                    patch.object(native.subprocess, "run") as run,
                ):
                    with self.assertRaisesRegex(ValueError, "stale JUnit"):
                        native.run(output, SHA)
                    run.assert_not_called()

    def setUp(self):
        self.environment = patch.dict(
            os.environ,
            {
                "GITHUB_RUN_ID": "synthetic-control",
                "GITHUB_RUN_ATTEMPT": "1",
                "GITHUB_EVENT_NAME": "pull_request",
                "GITHUB_SHA": "c" * 40,
            },
        )
        self.environment.start()
        self.addCleanup(self.environment.stop)


if __name__ == "__main__":
    unittest.main()
