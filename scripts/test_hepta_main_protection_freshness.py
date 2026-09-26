"""Exercise stale/racing GitHub evidence; fake API, not live enforcement."""

import copy
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from hepta_main_protection import API, GATE, ProtectionError, execute, verified_gate_app
from test_hepta_main_protection import APP, HEAD, FakeAPI, evidence


def complete_evidence():
    checks, runs = evidence()
    runs[0].update(
        id=100,
        run_attempt=1,
        head_branch="main",
        event="push",
        repository={"full_name": "TrillionniumFoundation/hepta-private-ci"},
    )
    return checks, runs


class CompleteAPI(FakeAPI):
    def __init__(self):
        super().__init__()
        self.checks, self.runs = complete_evidence()


class FreshnessTests(unittest.TestCase):
    def test_newer_pending_workflow_cannot_reuse_old_green_gate(self):
        checks, runs = complete_evidence()
        runs.append(
            {
                **copy.deepcopy(runs[0]),
                "id": 101,
                "check_suite_id": 43,
                "status": "in_progress",
                "conclusion": None,
            }
        )
        with self.assertRaises(ProtectionError):
            verified_gate_app(checks, runs, HEAD)

    def test_newer_failed_workflow_cannot_reuse_old_green_gate(self):
        checks, runs = complete_evidence()
        runs.append(
            {
                **copy.deepcopy(runs[0]),
                "id": 101,
                "check_suite_id": 43,
                "conclusion": "failure",
            }
        )
        with self.assertRaises(ProtectionError):
            verified_gate_app(checks, runs, HEAD)

    def test_successful_new_run_needs_its_own_gate(self):
        checks, runs = complete_evidence()
        runs.append({**copy.deepcopy(runs[0]), "id": 101, "check_suite_id": 43})
        with self.assertRaises(ProtectionError):
            verified_gate_app(checks, runs, HEAD)

    def test_latest_attempt_must_be_complete(self):
        checks, runs = complete_evidence()
        runs.append(
            {
                **copy.deepcopy(runs[0]),
                "run_attempt": 2,
                "status": "in_progress",
                "conclusion": None,
            }
        )
        with self.assertRaises(ProtectionError):
            verified_gate_app(checks, runs, HEAD)

    def test_pr_or_other_branch_cannot_attest_main_workflow(self):
        for field, value in (("event", "pull_request"), ("head_branch", "candidate")):
            checks, runs = complete_evidence()
            runs[0][field] = value
            with self.subTest(field=field), self.assertRaises(ProtectionError):
                verified_gate_app(checks, runs, HEAD)

    def test_foreign_repository_cannot_attest_main(self):
        checks, runs = complete_evidence()
        runs[0]["repository"] = {"full_name": "elsewhere/hepta-private-ci"}
        with self.assertRaises(ProtectionError):
            verified_gate_app(checks, runs, HEAD)

    def test_missing_and_noninteger_run_identity_fail_closed(self):
        for field in ("id", "run_attempt", "check_suite_id"):
            for value in (None, True, "100", -1, 0):
                checks, runs = complete_evidence()
                runs[0][field] = value
                with (
                    self.subTest(field=field, value=value),
                    self.assertRaises(ProtectionError),
                ):
                    verified_gate_app(checks, runs, HEAD)

    def test_null_app_is_an_explicit_failure(self):
        checks, runs = complete_evidence()
        checks[0]["app"] = None
        with self.assertRaises(ProtectionError):
            verified_gate_app(checks, runs, HEAD)

    def test_check_identity_is_not_boolean_or_missing(self):
        for value in (None, True, "1", 0, -1):
            checks, runs = complete_evidence()
            checks[0]["id"] = value
            with self.subTest(value=value), self.assertRaises(ProtectionError):
                verified_gate_app(checks, runs, HEAD)

    def test_unrelated_workflow_does_not_mask_valid_gate(self):
        checks, runs = complete_evidence()
        runs.append(
            {
                **copy.deepcopy(runs[0]),
                "id": 200,
                "path": ".github/workflows/other.yml",
                "conclusion": "failure",
            }
        )
        self.assertEqual(verified_gate_app(checks, runs, HEAD), APP)

    def test_gate_can_come_from_exact_main_manual_run(self):
        checks, runs = complete_evidence()
        runs[0]["event"] = "workflow_dispatch"
        self.assertEqual(verified_gate_app(checks, runs, HEAD), APP)

    def test_gate_race_before_write_performs_no_mutation(self):
        class Rerunning(CompleteAPI):
            calls = 0

            def pages(self, path, key=None):
                if path.startswith("actions/workflows/"):
                    self.calls += 1
                    if self.calls > 1:
                        self.runs[0].update(
                            status="in_progress", conclusion=None, run_attempt=2
                        )
                return super().pages(path, key)

        api = Rerunning()
        with tempfile.TemporaryDirectory() as tmp, self.assertRaises(ProtectionError):
            execute(api, HEAD, Path(tmp), True)
        self.assertEqual(api.writes, [])

    def test_new_green_attempt_still_invalidates_preflight_identity(self):
        class ChangedIdentity(CompleteAPI):
            calls = 0

            def pages(self, path, key=None):
                if path.startswith("actions/workflows/"):
                    self.calls += 1
                    if self.calls > 1:
                        self.runs[0]["run_attempt"] = 2
                return super().pages(path, key)

        api = ChangedIdentity()
        with tempfile.TemporaryDirectory() as tmp, self.assertRaises(ProtectionError):
            execute(api, HEAD, Path(tmp), True)
        self.assertEqual(api.writes, [])

    def test_failed_postwrite_gate_is_not_reported_as_success(self):
        class PostwriteFailure(CompleteAPI):
            def call(self, method, path, body=None):
                value = super().call(method, path, body)
                if method == "POST":
                    self.checks[0]["conclusion"] = "failure"
                return value

        api = PostwriteFailure()
        with tempfile.TemporaryDirectory() as tmp, self.assertRaises(ProtectionError):
            execute(api, HEAD, Path(tmp), True)
        # Keep the protection: failure must NOT trigger a rollback/delete.
        self.assertEqual(api.writes, [("POST", "rulesets")])
        self.assertIsNotNone(api.ruleset)

    def test_public_host_is_explicit_even_with_foreign_environment(self):
        with (
            patch.dict("os.environ", {"GH_HOST": "foreign.invalid"}),
            patch(
                "hepta_main_protection.subprocess.run",
                return_value=subprocess.CompletedProcess([], 0, "{}", ""),
            ) as run,
        ):
            API().call("GET", "branches/main")
        command = run.call_args.args[0]
        self.assertIn("--hostname", command)
        self.assertEqual(command[command.index("--hostname") + 1], "github.com")

    def test_rerun_cannot_reuse_previous_attempt_gate(self):
        api = CompleteAPI()
        api.runs[0]["run_attempt"] = 2
        with tempfile.TemporaryDirectory() as tmp, self.assertRaises(ProtectionError):
            execute(api, HEAD, Path(tmp), True)
        self.assertEqual(api.writes, [])

    def test_successful_attempt_requires_its_own_check_run_link(self):
        api = CompleteAPI()
        api.jobs[0]["check_run_url"] = api.jobs[0]["check_run_url"].replace("/1", "/2")
        with tempfile.TemporaryDirectory() as tmp, self.assertRaises(ProtectionError):
            execute(api, HEAD, Path(tmp), True)
        self.assertEqual(api.writes, [])

    def test_attempt_job_requires_exact_head_run_and_success(self):
        for field, value in (
            ("head_sha", "b" * 40),
            ("run_id", 101),
            ("conclusion", "skipped"),
            ("name", "not the gate"),
            ("id", True),
            ("run_attempt", True),
        ):
            api = CompleteAPI()
            api.jobs[0][field] = value
            with self.subTest(field=field), tempfile.TemporaryDirectory() as tmp:
                with self.assertRaises(ProtectionError):
                    execute(api, HEAD, Path(tmp), True)
            self.assertEqual(api.writes, [])

    def test_missing_or_ambiguous_attempt_gate_performs_no_write(self):
        for kind in ("missing", "duplicate", "malformed"):
            api = CompleteAPI()
            api.jobs = {"missing": [], "duplicate": api.jobs * 2, "malformed": [None]}[
                kind
            ]
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as tmp:
                with self.assertRaises(ProtectionError):
                    execute(api, HEAD, Path(tmp), True)
            self.assertEqual(api.writes, [])

    def test_attempt_endpoint_allows_rows_without_optional_attempt_field(self):
        api = CompleteAPI()
        api.jobs[0].pop("run_attempt")
        with tempfile.TemporaryDirectory() as tmp:
            execute(api, HEAD, Path(tmp), True)
        self.assertEqual(api.writes, [("POST", "rulesets")])

    def test_new_attempt_with_new_gate_is_valid_when_stable(self):
        api = CompleteAPI()
        api.runs[0]["run_attempt"] = 2
        api.checks[0]["id"] = 3
        api.jobs[0].update(
            id=3,
            run_attempt=2,
            check_run_url=api.jobs[0]["check_run_url"].replace("/1", "/3"),
        )
        with tempfile.TemporaryDirectory() as tmp:
            execute(api, HEAD, Path(tmp), True)
        self.assertEqual(api.writes, [("POST", "rulesets")])

    def test_changed_check_is_captured_in_prewrite_and_postwrite_audit(self):
        api = CompleteAPI()
        with tempfile.TemporaryDirectory() as tmp:
            execute(api, HEAD, Path(tmp), True)
            for name in ("gate-before.json", "gate-prewrite.json", "gate-after.json"):
                self.assertTrue((Path(tmp) / name).is_file(), name)


if __name__ == "__main__":
    unittest.main()
