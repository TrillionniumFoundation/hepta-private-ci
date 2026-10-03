"""Exercise the focused workflow's identity adapter with the real recorder."""

from pathlib import Path
import re

from test_hepta_ci_exec import GitExecutionFixture


WORKFLOW = (
    Path(__file__).resolve().parents[1]
    / ".github/workflows/automation-taskflow-focused.yml"
)
IDENTITY_KEYS = ("SOURCE_SHA", "TESTED_SHA", "BASE_SHA", "HEPTA_CI_LANE")


def resolve(value, context):
    if not value.startswith("${{"):
        return value
    for term in value.removeprefix("${{").removesuffix("}}").strip().split(" || "):
        if term == "''":
            return ""
        result = context
        for part in term.split("."):
            result = result.get(part, {}) if isinstance(result, dict) else {}
        if result:
            return result
    return ""


def workflow_identity(text, context):
    identity = dict.fromkeys(IDENTITY_KEYS, "")
    for key, value in re.findall(r"^      (\w+): (.+)$", text, re.MULTILINE):
        if key in identity:
            identity[key] = resolve(value, context)
    return identity


class TaskFlowOwnerWorkflowTests(GitExecutionFixture):
    def context(self, pull_request):
        github = {"sha": "f" * 40 if pull_request else self.source, "event": {}}
        if pull_request:
            github["event"]["pull_request"] = {
                "head": {"sha": self.source},
                "base": {"sha": "e" * 40},
            }
        return {"github": github}

    def test_workflow_pr_and_push_identity_dispatch_the_reviewed_source(self):
        text = WORKFLOW.read_text()
        for pull_request in (True, False):
            with self.subTest(pull_request=pull_request):
                self.result.unlink(missing_ok=True)
                self.marker.unlink(missing_ok=True)
                context = self.context(pull_request)
                checkout = re.search(r"^          ref: (.+)$", text, re.MULTILINE)
                self.assertIsNotNone(
                    checkout, "focused checkout must select a literal source"
                )
                self.assertEqual(resolve(checkout[1], context), self.source)
                result = self.execute(**workflow_identity(text, context))
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(self.marker.read_text(), "executed")
                self.assertEqual(self.receipt()["tested_sha"], self.source)
                self.assertEqual(self.receipt()["before"], self.receipt()["after"])

    def test_missing_workflow_identity_rejects_before_dispatch(self):
        text = re.sub(
            r"^      SOURCE_SHA: .+\n", "", WORKFLOW.read_text(), flags=re.MULTILINE
        )
        result = self.execute(**workflow_identity(text, self.context(True)))
        self.assertEqual(result.returncode, 2)
        self.assertEqual(self.receipt()["status"], "rejected")
        self.assertIsNone(self.receipt()["command_exit_code"])
        self.assertFalse(self.marker.exists())
