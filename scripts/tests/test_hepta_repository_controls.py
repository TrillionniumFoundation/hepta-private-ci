from copy import deepcopy
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import hepta_repository_controls as controls

SHA = "1" * 40
APP = 123456
REPO = "TrillionniumFoundation/hepta-private-ci"


def fixture():
    branch = {"name": "main", "protected": True, "commit": {"sha": SHA}}
    protection = {
        "enforce_admins": {"enabled": True},
        "allow_force_pushes": {"enabled": False}, "allow_deletions": {"enabled": False},
        "required_pull_request_reviews": {"required_approving_review_count": 1,
            "dismiss_stale_reviews": True, "require_last_push_approval": True,
            "bypass_pull_request_allowances": {"users": [], "teams": [], "apps": []}},
        "required_status_checks": {"strict": True, "contexts": ["blocking-ci"], "checks": [
            {"context": "blocking-ci", "app_id": 9999},
            {"context": controls.EVALUATION_CONTEXT, "app_id": APP}]},
    }
    checks = [
        {"id": 100, "name": "blocking-ci", "head_sha": SHA,
         "status": "completed", "conclusion": "success", "app": {"id": 9999, "slug": "github-actions"}},
        {"id": 200, "name": controls.EVALUATION_CONTEXT, "head_sha": SHA,
         "status": "completed", "conclusion": "success", "app": {"id": APP, "slug": "independent-fixture-app"}},
    ]
    return branch, protection, checks


class RepositoryControlTests(unittest.TestCase):
    def setUp(self):
        self.branch, self.protection, self.checks = fixture()

    def validate(self):
        return controls.validate_observation(self.branch, self.protection, self.checks,
                                             expected_sha=SHA, evaluator_app=APP)

    def test_strict_observed_profile(self):
        self.assertEqual(self.validate(), [100, 200])

    def test_main_unprotected(self):
        self.branch["protected"] = False
        with self.assertRaises(controls.ControlError): self.validate()

    def test_old_main_head(self):
        self.branch["commit"]["sha"] = "2" * 40
        with self.assertRaises(controls.ControlError): self.validate()

    def test_unknown_admin_enforcement(self):
        del self.protection["enforce_admins"]
        with self.assertRaises(controls.ControlError): self.validate()

    def test_admin_bypass(self):
        self.protection["enforce_admins"]["enabled"] = False
        with self.assertRaises(controls.ControlError): self.validate()

    def test_force_push_enabled(self):
        self.protection["allow_force_pushes"]["enabled"] = True
        with self.assertRaises(controls.ControlError): self.validate()

    def test_unknown_force_push_policy(self):
        del self.protection["allow_force_pushes"]
        with self.assertRaises(controls.ControlError): self.validate()

    def test_no_reviews_required(self):
        self.protection["required_pull_request_reviews"]["required_approving_review_count"] = 0
        with self.assertRaises(controls.ControlError): self.validate()

    def test_boolean_does_not_count_as_one_review(self):
        self.protection["required_pull_request_reviews"]["required_approving_review_count"] = True
        with self.assertRaises(controls.ControlError): self.validate()

    def test_stale_reviews_allowed(self):
        self.protection["required_pull_request_reviews"]["dismiss_stale_reviews"] = False
        with self.assertRaises(controls.ControlError): self.validate()

    def test_last_push_can_be_self_approved(self):
        self.protection["required_pull_request_reviews"]["require_last_push_approval"] = False
        with self.assertRaises(controls.ControlError): self.validate()

    def test_user_review_bypass(self):
        self.protection["required_pull_request_reviews"]["bypass_pull_request_allowances"]["users"] = [{"id": 1}]
        with self.assertRaises(controls.ControlError): self.validate()

    def test_app_review_bypass(self):
        self.protection["required_pull_request_reviews"]["bypass_pull_request_allowances"]["apps"] = [{"id": APP}]
        with self.assertRaises(controls.ControlError): self.validate()

    def test_stale_base_allowed(self):
        self.protection["required_status_checks"]["strict"] = False
        with self.assertRaises(controls.ControlError): self.validate()

    def test_context_name_alone_is_not_an_independent_identity(self):
        self.protection["required_status_checks"]["checks"][1]["app_id"] = None
        with self.assertRaises(controls.ControlError): self.validate()

    def test_any_app_cannot_sign_evaluation(self):
        self.protection["required_status_checks"]["checks"][1]["app_id"] = -1
        with self.assertRaises(controls.ControlError): self.validate()

    def test_wrong_trusted_app(self):
        self.checks[1]["app"]["id"] += 1
        with self.assertRaises(controls.ControlError): self.validate()

    def test_shared_actions_identity_is_not_independent(self):
        self.checks[1]["app"]["slug"] = "github-actions"
        with self.assertRaises(controls.ControlError): self.validate()

    def test_wrong_sha_check_not_reused(self):
        self.checks[1]["head_sha"] = "2" * 40
        with self.assertRaises(controls.ControlError): self.validate()

    def test_new_pending_invalidates_old_success(self):
        latest = deepcopy(self.checks[1]); latest.update(id=201, status="queued", conclusion=None)
        self.checks.append(latest)
        with self.assertRaises(controls.ControlError): self.validate()

    def test_skipped_is_not_success(self):
        self.checks[1]["conclusion"] = "skipped"
        with self.assertRaises(controls.ControlError): self.validate()

    def test_neutral_is_not_success(self):
        self.checks[1]["conclusion"] = "neutral"
        with self.assertRaises(controls.ControlError): self.validate()

    def test_untrusted_success_cannot_replace_trusted_failure(self):
        self.checks[1]["conclusion"] = "failure"
        forged = deepcopy(self.checks[1]); forged.update(id=999, conclusion="success")
        forged["app"]["id"] = APP + 1
        self.checks.append(forged)
        with self.assertRaises(controls.ControlError): self.validate()

    def test_missing_extra_required_gate_fails(self):
        self.protection["required_status_checks"]["checks"].append({"context": "extra-required", "app_id": 9999})
        with self.assertRaises(controls.ControlError): self.validate()

    def test_activation_is_not_self_authorized(self):
        responses = [self.branch, self.protection, {"check_runs": self.checks}, self.branch, self.protection]
        with patch.object(controls, "api", side_effect=responses):
            result = controls.observe(REPO, SHA, APP)
        self.assertTrue(result["repository_control_profile_passed"])
        self.assertIs(result["activation_authorized"], False)

    def test_policy_drift_during_observation_fails(self):
        after = deepcopy(self.protection); after["enforce_admins"]["enabled"] = False
        with patch.object(controls, "api", side_effect=[self.branch, self.protection,
                                                      {"check_runs": self.checks}, self.branch, after]):
            with self.assertRaises(controls.ControlError): controls.observe(REPO, SHA, APP)

    def test_main_drift_during_observation_fails(self):
        after = deepcopy(self.branch); after["commit"]["sha"] = "3" * 40
        with patch.object(controls, "api", side_effect=[self.branch, self.protection,
                                                      {"check_runs": self.checks}, after, self.protection]):
            with self.assertRaises(controls.ControlError): controls.observe(REPO, SHA, APP)

    def test_api_denial_cannot_be_replaced_with_source_policy(self):
        with patch.object(controls, "api", side_effect=subprocess.CalledProcessError(1, ["gh", "api"])):
            with self.assertRaises(subprocess.CalledProcessError): controls.observe(REPO, SHA, APP)

    def test_pagination_reads_beyond_first_page(self):
        first = [{"id": i} for i in range(100)]
        with patch.object(controls, "api", side_effect=[{"check_runs": first}, {"check_runs": [{"id": 101}]}]) as api:
            result = controls.collect_checks(REPO, SHA)
        self.assertEqual(len(result), 101)
        self.assertIn("page=2", api.call_args_list[1].args[0])

    def test_unbounded_pagination_fails_instead_of_certifying_prefix(self):
        with patch.object(controls, "api", return_value={"check_runs": [{}] * 100}):
            with self.assertRaises(controls.ControlError): controls.collect_checks(REPO, SHA)


if __name__ == "__main__":
    unittest.main()
