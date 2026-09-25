"""Behavioral regressions for repository-control observations; no live authority."""
from copy import deepcopy
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import sys
import unittest
from unittest.mock import patch

import hepta_repository_controls as controls

SHA = "1" * 40
APP = 123456
REPO = "TrillionniumFoundation/hepta-private-ci"


def fixture():
    branch = {"name": "main", "protected": True, "commit": {"sha": SHA}}
    protection = {
        "enforce_admins": {"enabled": True},
        "allow_force_pushes": {"enabled": False}, "allow_deletions": {"enabled": False},
        "required_conversation_resolution": {"enabled": True},
        "required_pull_request_reviews": {"required_approving_review_count": 1,
            "dismiss_stale_reviews": True, "require_last_push_approval": True,
            "require_code_owner_reviews": True,
            "bypass_pull_request_allowances": {"users": [], "teams": [], "apps": []}},
        "required_status_checks": {"strict": True, "contexts": [controls.BLOCKING_CONTEXT], "checks": [
            {"context": controls.BLOCKING_CONTEXT, "app_id": 9999},
            {"context": controls.EVALUATION_CONTEXT, "app_id": APP}]},
    }
    checks = [
        {"id": 100, "name": controls.BLOCKING_CONTEXT, "head_sha": SHA,
         "status": "completed", "conclusion": "success", "app": {"id": 9999, "slug": "github-actions"}},
        {"id": 200, "name": controls.EVALUATION_CONTEXT, "head_sha": SHA,
         "status": "completed", "conclusion": "success", "app": {"id": APP, "slug": "independent-fixture-app"}},
    ]
    return branch, protection, checks


class CheckSourceTests(unittest.TestCase):
    def setUp(self):
        self.branch, self.protection, self.checks = fixture()

    def validate(self):
        return controls.validate_observation(self.branch, self.protection, self.checks,
                                             expected_sha=SHA, evaluator_app=APP)

    def test_valid_distinct_pinned_sources(self):
        self.assertEqual(self.validate(), [100, 200])

    def test_owner_and_conversation_controls_cannot_be_inferred_from_fixture(self):
        for field in ("owner", "conversation"):
            for value in (None, False, 1, "true"):
                self.branch, self.protection, self.checks = fixture()
                if field == "owner":
                    self.protection["required_pull_request_reviews"]["require_code_owner_reviews"] = value
                else:
                    self.protection["required_conversation_resolution"]["enabled"] = value
                with self.subTest(field=field, value=value), self.assertRaises(controls.ControlError):
                    self.validate()

    def test_unpinned_blocking_context_rejected(self):
        for value in (None, -1):
            with self.subTest(app_id=value):
                self.protection["required_status_checks"]["checks"][0]["app_id"] = value
                with self.assertRaises(controls.ControlError): self.validate()

    def test_evaluator_cannot_also_publish_blocking_check(self):
        self.protection["required_status_checks"]["checks"][0]["app_id"] = APP
        self.checks[0]["app"] = deepcopy(self.checks[1]["app"])
        with self.assertRaises(controls.ControlError): self.validate()

    def test_extra_required_context_must_pin_its_source(self):
        self.protection["required_status_checks"]["contexts"].append("unbound-extra")
        extra = deepcopy(self.checks[0]); extra.update(id=300, name="unbound-extra")
        self.checks.append(extra)
        with self.assertRaises(controls.ControlError): self.validate()

    def test_boolean_observed_identity_is_not_app_one(self):
        self.protection["required_status_checks"]["checks"][0]["app_id"] = 1
        self.checks[0]["app"]["id"] = True
        with self.assertRaises(controls.ControlError): self.validate()

    def test_wrong_branch_fails_before_collecting_checks(self):
        self.branch["commit"]["sha"] = "2" * 40
        with patch.object(controls, "api", side_effect=[self.branch, self.protection]), \
             patch.object(controls, "collect_checks") as collect:
            with self.assertRaises(controls.ControlError): controls.observe(REPO, SHA, APP)
        collect.assert_not_called()

    def test_oversized_check_page_rejected(self):
        with patch.object(controls, "api", side_effect=[{"check_runs": [{}] * 101}, {"check_runs": []}]):
            with self.assertRaises(controls.ControlError): controls.collect_checks(REPO, SHA)

    def test_api_has_a_request_timeout(self):
        result = subprocess.CompletedProcess(["gh"], 0, stdout="{}", stderr="")
        with patch.object(controls.subprocess, "run", return_value=result) as run:
            self.assertEqual(controls.api("repos/owner/repository"), {})
        self.assertGreater(run.call_args.kwargs.get("timeout", 0), 0)
        self.assertLessEqual(run.call_args.kwargs["timeout"], 60)

    def test_api_timeout_never_emits_success(self):
        with patch.object(sys, "argv", ["controls", "--repo", REPO, "--expected-sha", SHA]), \
             patch.dict(controls.os.environ, {"HEPTA_EVALUATOR_APP_ID": str(APP)}), \
             patch.object(controls, "api", side_effect=subprocess.TimeoutExpired(["gh"], 30)), \
             patch("sys.stdout", new_callable=io.StringIO) as out, \
             patch("sys.stderr", new_callable=io.StringIO):
            self.assertEqual(controls.main(), 1)
        self.assertEqual(out.getvalue(), "")


class RepositoryPermissionObservationTests(unittest.TestCase):
    @staticmethod
    def payload(**overrides):
        permissions = {
            "admin": False,
            "maintain": False,
            "push": False,
            "triage": False,
            "pull": True,
        }
        permissions.update(overrides)
        return {"full_name": REPO, "id": 1, "permissions": permissions}

    def observe(self, status=200, payload=None):
        body = json.dumps(payload if payload is not None else self.payload()).encode()
        with patch.object(controls.http.client, "HTTPSConnection") as connect:
            connection = connect.return_value
            connection.getresponse.return_value.status = status
            connection.getresponse.return_value.read.return_value = body
            result = controls.observe_repository_push_denial(REPO, "fixture-token")
        connection.close.assert_called_once()
        connect.assert_called_once()
        self.assertEqual(connect.call_args.args, ("api.github.com",))
        self.assertIsNotNone(connect.call_args.kwargs["context"])
        args, kwargs = connection.request.call_args
        self.assertEqual(args[:2], ("GET", f"/repos/{REPO}"))
        self.assertIsNone(kwargs.get("body"))
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer fixture-token")
        return result

    def test_exact_read_only_repository_role_denial_is_narrow_observation(self):
        result = self.observe()
        self.assertIs(result["repository_push_permission_denied"], True)
        self.assertIs(result["activation_authorized"], False)
        self.assertIs(result["credential_separation_proven"], False)

    def test_allowed_or_unknown_repository_write_roles_fail_closed(self):
        cases = [
            self.payload(push=True),
            self.payload(admin=True),
            self.payload(maintain=True),
            self.payload(push=None),
            self.payload(push=0),
            {"full_name": REPO, "id": 1},
        ]
        for payload in cases:
            with self.subTest(payload=payload):
                with self.assertRaises(controls.ControlError):
                    self.observe(payload=payload)

    def test_http_and_payload_failures_are_not_permission_denial(self):
        cases = [
            (401, self.payload()),
            (403, self.payload()),
            (404, self.payload()),
            (429, self.payload()),
            (500, self.payload()),
            (200, []),
            (200, {"full_name": "other/repository", "id": 1, "permissions": {}}),
            (200, {"full_name": REPO, "id": 0, "permissions": {}}),
        ]
        for status, payload in cases:
            with self.subTest(status=status, payload=payload):
                with self.assertRaises(controls.ControlError):
                    self.observe(status=status, payload=payload)

    def test_timeout_is_unknown_and_closes_connection(self):
        with patch.object(controls.http.client, "HTTPSConnection") as connect:
            connect.return_value.getresponse.side_effect = TimeoutError("timed out")
            with self.assertRaises(controls.ControlError):
                controls.observe_repository_push_denial(REPO, "fixture-token")
        connect.return_value.close.assert_called_once()

    def test_response_size_is_bounded(self):
        with patch.object(controls.http.client, "HTTPSConnection") as connect:
            connection = connect.return_value
            connection.getresponse.return_value.status = 200
            connection.getresponse.return_value.read.return_value = b"x" * 65537
            with self.assertRaises(controls.ControlError):
                controls.observe_repository_push_denial(REPO, "fixture-token")
        connection.close.assert_called_once()

    def test_missing_token_and_bad_repository_never_access_network(self):
        for repo, token in [(REPO, ""), ("../repository", "fixture"), ("a/b/c", "fixture")]:
            with self.subTest(repo=repo), patch.object(
                controls.http.client, "HTTPSConnection"
            ) as connect:
                with self.assertRaises(controls.ControlError):
                    controls.observe_repository_push_denial(repo, token)
                connect.assert_not_called()

    def test_cli_discards_control_success_when_permission_is_unknown(self):
        with patch.object(
            sys,
            "argv",
            ["controls", "--repo", REPO, "--expected-sha", SHA, "--probe-write-denial"],
        ), patch.dict(
            controls.os.environ,
            {"HEPTA_EVALUATOR_APP_ID": str(APP), "GH_TOKEN": "fixture-token"},
        ), patch.object(
            controls, "observe", return_value={"repository_control_profile_passed": True}
        ), patch.object(
            controls,
            "observe_repository_push_denial",
            side_effect=controls.ControlError("unknown"),
        ), patch("sys.stdout", new_callable=io.StringIO) as out, patch(
            "sys.stderr", new_callable=io.StringIO
        ):
            self.assertEqual(controls.main(), 1)
        self.assertEqual(out.getvalue(), "")

class FormattingCommandTests(unittest.TestCase):
    def run_format_step(self, exit_code):
        # Execute the actual workflow shell, using a stand-in cargo process.
        # This exercises exit propagation and diagnostics, not Rust formatting.
        path = Path(__file__).resolve().parents[1] / ".github/workflows/hepta-converged-learning.yml"
        block = path.read_text().split("      - name: Formatting without tested-source mutation\n", 1)[1]
        block = block.split("      - name:", 1)[0]
        script = "\n".join(line[10:] for line in block.split("        run: |\n", 1)[1].splitlines())
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            cargo = root / "cargo"
            cargo.write_text(f"#!/bin/sh\nprintf '%s\\n' 'format diagnostic' >&2\nexit {exit_code}\n")
            cargo.chmod(0o700)
            environment = dict(os.environ, RUNNER_TEMP=temporary,
                               PATH=str(root) + os.pathsep + os.environ["PATH"])
            result = subprocess.run(["bash", "-c", script], cwd=root, env=environment,
                                    capture_output=True, text=True, timeout=10, check=False)
            diagnostic = (root / "hepta-learning-rustfmt.txt").read_text()
        self.assertEqual(result.returncode, exit_code)
        self.assertEqual(result.stdout, diagnostic)
        self.assertEqual(diagnostic, "format diagnostic\n")

    def test_format_failure_is_retained_and_not_swallowed(self):
        self.run_format_step(7)

    def test_format_success_does_not_become_failure(self):
        self.run_format_step(0)


if __name__ == "__main__":
    unittest.main()
