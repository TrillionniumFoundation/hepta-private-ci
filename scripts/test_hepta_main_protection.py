"""Operator-policy tests with a fake GitHub API; not live enforcement evidence."""
import copy
from pathlib import Path
import tempfile
import unittest

from hepta_main_protection import (
    API, GATE, RULESET_NAME, WORKFLOW, ProtectionError,
    desired_ruleset, execute, verified_gate_app, verify_ruleset,
)

HEAD = "a" * 40
APP = 99


def evidence():
    check = {"id": 1, "name": GATE, "head_sha": HEAD, "status": "completed",
             "conclusion": "success", "app": {"slug": "github-actions", "id": APP},
             "check_suite": {"id": 42}}
    run = {"head_sha": HEAD, "check_suite_id": 42, "status": "completed",
           "conclusion": "success", "path": ".github/workflows/" + WORKFLOW}
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


def review(value):
    return next(row for row in value["rules"] if row["type"] == "pull_request")["parameters"]


class ProtectionTests(unittest.TestCase):
    def test_requires_observed_app_id(self):
        for value in (None, 0, -1, True, "99"):
            with self.subTest(value=value), self.assertRaises(ProtectionError):
                desired_ruleset(value)

    def test_no_bypass_and_independent_review_rules(self):
        value = desired_ruleset(APP)
        verify_ruleset(value, APP)
        self.assertEqual(value["bypass_actors"], [])
        self.assertEqual(review(value)["required_approving_review_count"], 1)
        self.assertEqual((GATE, WORKFLOW), ("CI required", "blocking-ci.yml"))

    def test_every_review_control_is_checked_on_readback(self):
        fields = ("dismiss_stale_reviews_on_push", "require_code_owner_review",
                  "require_last_push_approval", "required_review_thread_resolution")
        for field in fields:
            for replacement in (False, None, 1, "true"):
                value = desired_ruleset(APP)
                review(value)[field] = replacement
                with self.subTest(field=field, replacement=replacement):
                    with self.assertRaises(ProtectionError):
                        verify_ruleset(value, APP)

    def test_zero_missing_and_boolean_review_counts_are_rejected(self):
        for count in (None, 0, -1, True, "1"):
            value = desired_ruleset(APP)
            review(value)["required_approving_review_count"] = count
            with self.subTest(count=count), self.assertRaises(ProtectionError):
                verify_ruleset(value, APP)

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
        replacements = {"head_sha": "b" * 40, "app": {"slug": "other", "id": APP},
                        "check_suite": {"id": 123}}
        for field, replacement in replacements.items():
            checks, runs = evidence()
            checks[0][field] = replacement
            with self.subTest(field=field), self.assertRaises(ProtectionError):
                verified_gate_app(checks, runs, HEAD)

    def test_missing_suite_cannot_match_another_missing_suite(self):
        checks, runs = evidence()
        checks[0].pop("check_suite")
        runs[0].pop("check_suite_id")
        with self.assertRaises(ProtectionError):
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

    def test_duplicate_rules_rejected(self):
        value = desired_ruleset(APP)
        value["rules"].append(copy.deepcopy(value["rules"][0]))
        with self.assertRaises(ProtectionError):
            verify_ruleset(value, APP)

    def test_dry_run_cannot_write(self):
        api = FakeAPI()
        with tempfile.TemporaryDirectory() as tmp:
            result = execute(api, HEAD, Path(tmp), False)
            self.assertEqual(result["mode"], "read-only")
            self.assertFalse(api.writes)

    def test_weak_existing_rules_rejected_even_in_dry_run(self):
        for apply in (False, True):
            api = FakeAPI()
            api.ruleset = {**desired_ruleset(APP), "id": 7}
            review(api.ruleset)["required_approving_review_count"] = 0
            with tempfile.TemporaryDirectory() as tmp, self.assertRaises(ProtectionError):
                execute(api, HEAD, Path(tmp), apply)
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
        review(api.ruleset)["required_approving_review_count"] = 2
        with tempfile.TemporaryDirectory() as tmp:
            execute(api, HEAD, Path(tmp), True)
        self.assertFalse(api.writes)
        self.assertEqual(review(api.ruleset)["required_approving_review_count"], 2)

    def test_main_race_prevents_write(self):
        class MovingMain(FakeAPI):
            def pages(self, path, key=None):
                value = super().pages(path, key)
                if path.startswith("actions/"):
                    self.head = "b" * 40
                return value
        api = MovingMain()
        with tempfile.TemporaryDirectory() as tmp, self.assertRaises(ProtectionError):
            execute(api, HEAD, Path(tmp), True)
        self.assertFalse(api.writes)

    def test_weakened_write_readback_is_not_success(self):
        class WeakReadback(FakeAPI):
            def call(self, method, path, body=None):
                value = super().call(method, path, body)
                if method == "POST":
                    review(self.ruleset)["require_last_push_approval"] = False
                return value
        api = WeakReadback()
        with tempfile.TemporaryDirectory() as tmp, self.assertRaises(ProtectionError):
            execute(api, HEAD, Path(tmp), True)
        self.assertEqual(len(api.writes), 1)

    def test_pagination_never_accepts_a_truncated_policy(self):
        class Endless(API):
            def call(self, method, path, body=None):
                return [{}] * 100
        with self.assertRaises(ProtectionError):
            Endless().pages("rulesets")


if __name__ == "__main__":
    unittest.main()
