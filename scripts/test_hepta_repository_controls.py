"""Behavioral regressions for the read-only repository-control observer.

Fixtures never establish live protection or independent evaluator credentials.
"""
from __future__ import annotations

import copy
import subprocess
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import hepta_repository_controls as controls

REPO = "TrillionniumFoundation/hepta-private-ci"
SHA = "a" * 40
EVALUATOR = 4242


def fixture():
    branch = {"name": "main", "protected": True, "commit": {"sha": SHA}}
    protection = {
        "enforce_admins": {"enabled": True},
        "allow_force_pushes": {"enabled": False},
        "allow_deletions": {"enabled": False},
        "required_pull_request_reviews": {
            "required_approving_review_count": 1,
            "dismiss_stale_reviews": True,
            "require_last_push_approval": True,
            "bypass_pull_request_allowances": {"users": [], "teams": [], "apps": []},
        },
        "required_status_checks": {
            "strict": True,
            "checks": [
                {"context": controls.BLOCKING_CONTEXT, "app_id": 15368},
                {"context": controls.EVALUATION_CONTEXT, "app_id": EVALUATOR},
            ],
            "contexts": [controls.BLOCKING_CONTEXT, controls.EVALUATION_CONTEXT],
        },
    }
    checks = [
        {"id": 1, "name": controls.BLOCKING_CONTEXT, "head_sha": SHA,
         "status": "completed", "conclusion": "success",
         "app": {"id": 15368, "slug": "github-actions"}},
        {"id": 2, "name": controls.EVALUATION_CONTEXT, "head_sha": SHA,
         "status": "completed", "conclusion": "success",
         "app": {"id": EVALUATOR, "slug": "trusted-evaluator"}},
    ]
    return branch, protection, checks


class RepositoryControlTests(unittest.TestCase):
    def validate(self, branch, protection, checks):
        return controls.validate_observation(
            branch, protection, checks, expected_sha=SHA, evaluator_app=EVALUATOR)

    def test_exact_head_and_source_are_accepted(self):
        self.assertEqual(self.validate(*fixture()), [1, 2])

    def test_newer_non_success_invalidates_historical_green(self):
        for status, conclusion in [
            ("queued", None), ("in_progress", None), ("completed", "failure"),
            ("completed", "cancelled"), ("completed", "skipped"),
            ("completed", "neutral"), ("completed", "timed_out"),
        ]:
            with self.subTest(status=status, conclusion=conclusion):
                branch, protection, checks = fixture()
                latest = copy.deepcopy(checks[1])
                latest.update(id=3, status=status, conclusion=conclusion)
                checks.append(latest)
                with self.assertRaises(controls.ControlError):
                    self.validate(branch, protection, checks)

    def test_wrong_app_or_wrong_head_cannot_supply_independent_evidence(self):
        for change in ("app", "head"):
            branch, protection, checks = fixture()
            if change == "app":
                checks[1]["app"]["id"] += 1
            else:
                checks[1]["head_sha"] = "b" * 40
            with self.subTest(change=change), self.assertRaises(controls.ControlError):
                self.validate(branch, protection, checks)

    def test_repository_actions_cannot_impersonate_independent_evaluator(self):
        branch, protection, checks = fixture()
        checks[1]["app"]["slug"] = "github-actions"
        with self.assertRaises(controls.ControlError):
            self.validate(branch, protection, checks)

    def test_legacy_context_does_not_bind_evaluator_app(self):
        branch, protection, checks = fixture()
        protection["required_status_checks"]["checks"].pop()
        with self.assertRaises(controls.ControlError):
            self.validate(branch, protection, checks)

    def test_review_bypass_and_disabled_enforcement_fail_closed(self):
        for kind in ("users", "teams", "apps"):
            branch, protection, checks = fixture()
            reviews = protection["required_pull_request_reviews"]
            reviews["bypass_pull_request_allowances"][kind] = [{"id": 1}]
            with self.subTest(kind=kind), self.assertRaises(controls.ControlError):
                self.validate(branch, protection, checks)
        branch, protection, checks = fixture()
        protection["enforce_admins"]["enabled"] = False
        with self.assertRaises(controls.ControlError):
            self.validate(branch, protection, checks)

    def test_observation_does_not_authorize_activation(self):
        branch, protection, checks = fixture()
        responses = [branch, protection, {"check_runs": checks}, branch, protection]
        with patch.object(controls, "api", side_effect=responses) as api:
            result = controls.observe(REPO, SHA, EVALUATOR)
        self.assertTrue(result["repository_control_profile_passed"])
        self.assertFalse(result["activation_authorized"])
        self.assertEqual(api.call_count, 5)

    def test_branch_or_protection_change_during_observation_is_rejected(self):
        for change in ("head", "protection"):
            branch, protection, checks = fixture()
            after, current = copy.deepcopy(branch), copy.deepcopy(protection)
            if change == "head":
                after["commit"]["sha"] = "b" * 40
            else:
                current["required_status_checks"]["strict"] = False
            responses = [branch, protection, {"check_runs": checks}, after, current]
            with patch.object(controls, "api", side_effect=responses):
                with self.subTest(change=change), self.assertRaises(controls.ControlError):
                    controls.observe(REPO, SHA, EVALUATOR)

    def test_unavailable_administration_does_not_turn_into_default_success(self):
        branch, _, _ = fixture()
        denied = subprocess.CalledProcessError(1, ["gh", "api"], stderr="HTTP 403")
        with patch.object(controls, "api", side_effect=[branch, denied]):
            with self.assertRaises(subprocess.CalledProcessError):
                controls.observe(REPO, SHA, EVALUATOR)

    def test_pagination_bound_cannot_accept_a_truncated_observation(self):
        with patch.object(controls, "api", return_value={"check_runs": [{}] * 100}) as api:
            with self.assertRaises(controls.ControlError):
                controls.collect_checks(REPO, SHA)
            self.assertEqual(api.call_count, 100)

    def test_invalid_scope_and_evaluator_never_call_github(self):
        for repo, sha, evaluator in [
            ("../repo", SHA, EVALUATOR), (REPO, "not-a-sha", EVALUATOR),
            (REPO, SHA, True), (REPO, SHA, 0),
        ]:
            with patch.object(controls, "api") as api:
                with self.subTest(repo=repo, sha=sha, evaluator=evaluator):
                    with self.assertRaises(controls.ControlError):
                        controls.observe(repo, sha, evaluator)
                    api.assert_not_called()

    def test_transport_uses_only_read_method(self):
        with patch.object(controls.subprocess, "run",
                          return_value=SimpleNamespace(stdout='{"ok": true}')) as run:
            self.assertEqual(controls.api("repos/owner/repo/branches/main"), {"ok": True})
        self.assertEqual(run.call_args.args[0][:4], ["gh", "api", "--method", "GET"])


if __name__ == "__main__":
    unittest.main()
