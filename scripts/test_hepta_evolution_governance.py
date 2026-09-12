"""Governance observations never turn absent evidence into activation authority."""

import copy
import unittest
import urllib.error
from unittest import mock

import verify_hepta_evolution_governance as governance


def protected_configuration():
    return {
        "enforce_admins": {"enabled": True},
        "required_conversation_resolution": {"enabled": True},
        "allow_force_pushes": {"enabled": False},
        "allow_deletions": {"enabled": False},
        "required_pull_request_reviews": {
            "required_approving_review_count": 1,
            "dismiss_stale_reviews": True,
            "require_code_owner_reviews": True,
            "require_last_push_approval": True,
            "bypass_pull_request_allowances": {"users": [], "teams": [], "apps": []},
        },
        "required_status_checks": {
            "strict": True,
            "checks": [
                {"context": context, "app_id": governance.GITHUB_ACTIONS_APP_ID}
                for context in governance.REQUIRED_CHECKS
            ],
        },
    }


class GovernanceTests(unittest.TestCase):
    def test_complete_configuration_is_only_configuration_evidence(self):
        branch = {"name": "main", "protected": True}
        with mock.patch.object(governance, "read_json", side_effect=[branch, protected_configuration()]):
            result = governance.observe("example/repository", None)
        self.assertEqual(result["status"], "CONFIGURATION_VERIFIED")
        self.assertEqual(result["gaps"], [])
        self.assertFalse(result["productionAuthorized"])
        self.assertFalse(result["independentAcceptance"])

    def test_missing_malformed_and_weakened_policies_fail_closed(self):
        branch = {"name": "main", "protected": True}
        base = protected_configuration()
        for field in base:
            changed = copy.deepcopy(base)
            del changed[field]
            with self.subTest(missing=field):
                self.assertTrue(governance.protection_gaps(branch, changed))
        for field in ("dismiss_stale_reviews", "require_code_owner_reviews", "require_last_push_approval"):
            changed = copy.deepcopy(base)
            changed["required_pull_request_reviews"][field] = False
            with self.subTest(weakened=field):
                self.assertIn(f"invalid_{field}", governance.protection_gaps(branch, changed))
        for count in (0, True, "1", None):
            changed = copy.deepcopy(base)
            changed["required_pull_request_reviews"]["required_approving_review_count"] = count
            self.assertIn("independent_review_not_required", governance.protection_gaps(branch, changed))
        for kind in ("users", "teams", "apps"):
            changed = copy.deepcopy(base)
            changed["required_pull_request_reviews"]["bypass_pull_request_allowances"][kind] = ["actor"]
            self.assertIn("review_bypass_not_proven_disabled", governance.protection_gaps(branch, changed))
        for value in (None, [], "protected", True):
            self.assertTrue(governance.protection_gaps(value, value))

    def test_required_check_names_without_pinned_issuers_do_not_suffice(self):
        for app_id in (-1, None, 123):
            changed = protected_configuration()
            changed["required_status_checks"]["checks"][0]["app_id"] = app_id
            self.assertTrue(governance.protection_gaps({"name": "main", "protected": True}, changed))
        changed = protected_configuration()
        changed["required_status_checks"]["checks"].append(copy.deepcopy(changed["required_status_checks"]["checks"][0]))
        self.assertTrue(governance.protection_gaps({"name": "main", "protected": True}, changed))

    def test_unprotected_branch_is_blocked_without_administration_access(self):
        with mock.patch.object(governance, "read_json", return_value={"name": "main", "protected": False}) as read:
            result = governance.observe("example/repository", None)
        self.assertEqual(result["gaps"], ["main_not_protected"])
        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual(read.call_count, 1)

    def test_api_denial_is_not_configuration_verification(self):
        denied = urllib.error.HTTPError("https://api.github.com/", 403, "denied", None, None)
        with (
            mock.patch("sys.argv", ["governance"]),
            mock.patch.object(governance, "observe", side_effect=denied),
            mock.patch("builtins.print") as output,
        ):
            self.assertEqual(governance.main(), 1)
        self.assertIn("configuration_unverifiable:403", output.call_args.args[0])
        self.assertNotIn("CONFIGURATION_VERIFIED", output.call_args.args[0])

    def test_repository_identity_cannot_inject_an_endpoint(self):
        for repository in ("../other", "owner/../repos", "owner/repo?token=value", "https://host/"):
            with mock.patch.object(governance, "read_json") as read:
                with self.assertRaises(ValueError):
                    governance.observe(repository, "never-used-token")
                read.assert_not_called()


if __name__ == "__main__":
    unittest.main()
