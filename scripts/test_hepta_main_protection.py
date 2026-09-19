import copy
from pathlib import Path
import tempfile
import unittest

from hepta_main_protection import (GATE, RULESET_NAME, WORKFLOW, ProtectionError,
                                  desired_ruleset, execute, verified_gate_app, verify_ruleset)

HEAD = "a" * 40
APP = 99


def evidence():
    check = {"id": 1, "name": GATE, "head_sha": HEAD, "status": "completed", "conclusion": "success",
             "app": {"slug": "github-actions", "id": APP}, "check_suite": {"id": 42}}
    run = {"head_sha": HEAD, "check_suite_id": 42, "status": "completed", "conclusion": "success",
           "path": ".github/workflows/" + WORKFLOW}
    return [check], [run]


class FakeAPI:
    def __init__(self):
        self.head = HEAD
        self.ruleset = None
        self.writes = []
        self.checks, self.runs = evidence()

    def call(self, method, path, body=None):
        if method == "GET" and path == "branches/main":
            return {"commit": {"sha": self.head}}
        if method == "GET" and path == "rulesets/7":
            return copy.deepcopy(self.ruleset)
        if method == "POST" and path == "rulesets":
            self.writes.append((method, path))
            self.ruleset = {**copy.deepcopy(body), "id": 7}
            return copy.deepcopy(self.ruleset)
        raise AssertionError((method, path))

    def pages(self, path, key=None):
        if path.startswith("rulesets?"):
            return [] if self.ruleset is None else [{"id": 7, "name": RULESET_NAME}]
        if path.startswith("commits/"):
            return copy.deepcopy(self.checks)
        if path.startswith("actions/"):
            return copy.deepcopy(self.runs)
        raise AssertionError(path)


class ProtectionTests(unittest.TestCase):
    def test_requires_observed_app_id(self):
        for value in (None, 0, -1, True, "99"):
            with self.subTest(value=value), self.assertRaises(ProtectionError):
                desired_ruleset(value)

    def test_minimal_no_bypass_rules(self):
        value = desired_ruleset(APP)
        verify_ruleset(value, APP)
        self.assertEqual(value["bypass_actors"], [])
        review = next(r for r in value["rules"] if r["type"] == "pull_request")
        self.assertEqual(review["parameters"]["required_approving_review_count"], 0)

    def test_green_gate_must_be_from_named_workflow(self):
        checks, runs = evidence()
        self.assertEqual(verified_gate_app(checks, runs, HEAD), APP)
        runs[0]["path"] = ".github/workflows/unrelated.yml"
        with self.assertRaises(ProtectionError):
            verified_gate_app(checks, runs, HEAD)

    def test_old_green_cannot_hide_latest_red(self):
        checks, runs = evidence()
        checks.append({**copy.deepcopy(checks[0]), "id": 2, "conclusion": "failure"})
        with self.assertRaises(ProtectionError):
            verified_gate_app(checks, runs, HEAD)

    def test_wrong_commit_app_or_suite_rejected(self):
        for field in ("head_sha", "app", "check_suite"):
            checks, runs = evidence()
            checks[0][field] = {"head_sha": "b" * 40, "app": {"slug": "other", "id": APP}, "check_suite": {"id": 123}}[field]
            with self.subTest(field=field), self.assertRaises(ProtectionError):
                verified_gate_app(checks, runs, HEAD)

    def test_bypass_and_missing_check_rejected(self):
        value = desired_ruleset(APP)
        value["bypass_actors"] = [{"actor_type": "OrganizationAdmin", "bypass_mode": "always"}]
        with self.assertRaises(ProtectionError):
            verify_ruleset(value, APP)
        value = desired_ruleset(APP)
        value["rules"].pop()
        with self.assertRaises(ProtectionError):
            verify_ruleset(value, APP)

    def test_dry_run_cannot_write(self):
        api = FakeAPI()
        with tempfile.TemporaryDirectory() as tmp:
            result = execute(api, HEAD, Path(tmp), False)
            self.assertEqual(result["mode"], "read-only")
            self.assertFalse(api.writes)

    def test_apply_writes_once_and_reads_back(self):
        api = FakeAPI()
        with tempfile.TemporaryDirectory() as tmp:
            result = execute(api, HEAD, Path(tmp), True)
            self.assertEqual(result["mode"], "applied-and-read-back")
            self.assertEqual(api.writes, [("POST", "rulesets")])
            self.assertTrue((Path(tmp) / "before.json").is_file())
            self.assertTrue((Path(tmp) / "after.json").is_file())
            execute(api, HEAD, Path(tmp), True)
            self.assertEqual(len(api.writes), 1)

    def test_wrong_baseline_never_writes(self):
        api = FakeAPI()
        with tempfile.TemporaryDirectory() as tmp, self.assertRaises(ProtectionError):
            execute(api, "b" * 40, Path(tmp), True)
        self.assertFalse(api.writes)

    def test_failed_gate_never_writes(self):
        api = FakeAPI()
        api.checks[0]["conclusion"] = "failure"
        with tempfile.TemporaryDirectory() as tmp, self.assertRaises(ProtectionError):
            execute(api, HEAD, Path(tmp), True)
        self.assertFalse(api.writes)

    def test_existing_stronger_review_not_weakened(self):
        api = FakeAPI()
        api.ruleset = {**desired_ruleset(APP), "id": 7}
        next(r for r in api.ruleset["rules"] if r["type"] == "pull_request")["parameters"]["required_approving_review_count"] = 2
        with tempfile.TemporaryDirectory() as tmp:
            execute(api, HEAD, Path(tmp), True)
        self.assertFalse(api.writes)
        self.assertEqual(next(r for r in api.ruleset["rules"] if r["type"] == "pull_request")["parameters"]["required_approving_review_count"], 2)


if __name__ == "__main__":
    unittest.main()
