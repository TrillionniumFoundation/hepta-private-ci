"""Behavioral admission tests for repository extensions and CI cost policy."""

import copy
import json
import tempfile
import unittest
from pathlib import Path
from scripts.hepta_repository_surface import (
    POLICY_PATH,
    ROOT,
    forbidden_additions,
    load_policy,
)
from scripts.hepta_workflow_commands import load_workflow, validate_manual_workflow

MANUAL = """name: Local diagnostics
on: {workflow_dispatch: {}, workflow_call: {}}
permissions: {contents: read}
jobs:
  inspect:
    runs-on: ubuntu-24.04
    timeout-minutes: 10
    steps:
      - run: echo 'diagnostic output'
"""


class RepositorySurfaceTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.policy_text = (ROOT / POLICY_PATH).read_text()
        self.write(POLICY_PATH, self.policy_text)

    def write(self, path, text):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)
        return target

    def forbidden(self, paths):
        return forbidden_additions(paths, root=self.root)

    def test_reviewed_budget_changes_are_consumed_without_fixed_number_gates(self):
        text = self.policy_text.replace(
            "ordinaryFeedbackTargetMinutes = 10", "ordinaryFeedbackTargetMinutes = 8"
        )
        text = text.replace(
            "ordinaryWorkflowTimeoutMinutes = 15", "ordinaryWorkflowTimeoutMinutes = 18"
        )
        self.write(POLICY_PATH, text)
        policy = load_policy(self.root)
        self.assertEqual(policy["ordinaryFeedbackTargetMinutes"], 8)
        self.assertEqual(policy["ordinaryWorkflowTimeoutMinutes"], 18)
        self.assertEqual(policy["maximumActiveConvergencePrsPerCapability"], 1)

    def test_budget_values_reject_aliases_unbounded_or_inverted_tiers(self):
        for value in ("true", "0", "361", "1.5", '"15"', "50"):
            with self.subTest(value=value):
                self.write(
                    POLICY_PATH,
                    self.policy_text.replace(
                        "ordinaryWorkflowTimeoutMinutes = 15",
                        f"ordinaryWorkflowTimeoutMinutes = {value}",
                    ),
                )
                with self.assertRaises(ValueError):
                    load_policy(self.root)

    def test_authority_and_duplicate_registry_policy_cannot_be_widened(self):
        for original, replacement in [
            (
                "selfIterationReleaseAllowed = false",
                "selfIterationReleaseAllowed = true",
            ),
            (
                "newPullRequestWorkflowFilesAllowed = false",
                "newPullRequestWorkflowFilesAllowed = true",
            ),
            (
                '  "docs/modules/registry.toml",',
                '  "docs/modules/registry.toml",\n  "docs/modules/SECOND.json",',
            ),
        ]:
            self.write(POLICY_PATH, self.policy_text.replace(original, replacement))
            with self.subTest(replacement=replacement), self.assertRaises(ValueError):
                load_policy(self.root)

    def test_explanation_and_single_module_manifest_are_allowed(self):
        self.assertEqual(
            self.forbidden(
                [
                    "docs/modules/EXTENSION_GUIDE.md",
                    "docs/modules/example.readonly/module.toml",
                    "docs/modules/example.readonly/TECHNICAL.md",
                ]
            ),
            [],
        )

    def test_schema_allowed_but_registry_payload_or_duplicate_keys_rejected(self):
        path = "docs/modules/example.readonly/schema.json"
        schema = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "properties": {"generation": {"type": "integer"}},
        }
        self.write(path, json.dumps(schema))
        self.assertEqual(self.forbidden([path]), [])
        for changed in (
            {**schema, "modules": []},
            {**schema, "authorityFlags": {}},
            {"schema": "parallel-registry", "modules": []},
        ):
            self.write(path, json.dumps(changed))
            self.assertEqual(self.forbidden([path]), [path])
        self.write(path, '{"$schema":"x", "$schema":"y"}')
        self.assertEqual(self.forbidden([path]), [path])
        self.assertEqual(
            self.forbidden(["docs/modules/SECOND.toml"]), ["docs/modules/SECOND.toml"]
        )

    def test_manual_workflow_admission_reads_content_not_its_name(self):
        path = ".github/workflows/manual-memory-diagnostics.yml"
        self.write(path, MANUAL)
        self.assertEqual(self.forbidden([path]), [])
        self.write(
            path,
            MANUAL.replace(
                "on: {workflow_dispatch: {}, workflow_call: {}}",
                "on: [push, workflow_dispatch]",
            ),
        )
        self.assertEqual(self.forbidden([path]), [path])

    def test_equivalent_yaml_reordering_quotes_and_comments_are_accepted(self):
        document = load_workflow(MANUAL)
        # JSON is a valid YAML representation of the identical workflow.
        validate_manual_workflow(json.dumps(dict(reversed(list(document.items())))), 60)
        validate_manual_workflow(
            MANUAL.replace("\non:", "\n'on':").replace(
                "contents: read", "'contents': 'read'"
            )
            + "\n# permissions: write-all\n",
            60,
        )

    def test_privileged_or_opaque_diagnostics_fail(self):
        baseline = load_workflow(MANUAL)
        variants = []
        for field, value in (
            ("permissions", {"contents": "write"}),
            ("runs-on", "self-hosted"),
            ("runs-on", "${{ inputs.runner }}"),
            ("environment", "production"),
            ("timeout-minutes", "61"),
            ("timeout-minutes", ""),
            ("uses", "owner/repo/.github/workflows/hidden.yml@main"),
        ):
            candidate = copy.deepcopy(baseline)
            candidate["jobs"]["inspect"][field] = value
            variants.append(candidate)
        candidate = copy.deepcopy(baseline)
        candidate["permissions"] = "write-all"
        variants.append(candidate)
        candidate = copy.deepcopy(baseline)
        candidate["jobs"]["inspect"]["steps"][0]["env"] = {
            "TOKEN": "${{ secrets['TOKEN'] }}"
        }
        variants.append(candidate)
        for candidate in variants:
            with self.subTest(candidate=candidate), self.assertRaises(ValueError):
                validate_manual_workflow(json.dumps(candidate), 60)

    def test_secret_context_is_rejected_in_functions_not_only_dot_access(self):
        baseline = load_workflow(MANUAL)
        for expression in (
            "${{ toJSON(secrets) }}",
            "${{ SECRETS.KEY }}",
            "${{ secrets['KEY'] }}",
        ):
            candidate = copy.deepcopy(baseline)
            candidate["jobs"]["inspect"]["steps"][0]["run"] = "echo " + expression
            with self.subTest(expression=expression), self.assertRaises(ValueError):
                validate_manual_workflow(json.dumps(candidate), 60)
        candidate = copy.deepcopy(baseline)
        candidate["jobs"]["inspect"]["steps"][0]["run"] = (
            "echo 'secrets are not referenced'"
        )
        validate_manual_workflow(json.dumps(candidate), 60)

    def test_missing_duplicate_and_recursive_workflow_data_fail(self):
        for text in (
            "",
            MANUAL + "permissions: write-all\n",
            "a: &loop [*loop]",
            "!!python/object:example {}",
        ):
            with self.subTest(text=text[:30]), self.assertRaises(ValueError):
                validate_manual_workflow(text, 60)

    def test_new_workflow_symlink_escape_and_missing_inputs_fail(self):
        path = ".github/workflows/manual.yml"
        self.assertEqual(self.forbidden([path]), [path])
        with tempfile.TemporaryDirectory() as outside:
            source = Path(outside) / "outside.yml"
            source.write_text(MANUAL)
            target = self.root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.symlink_to(source)
            self.assertEqual(self.forbidden([path]), [path])
        with self.assertRaises(ValueError):
            self.forbidden(["docs/modules/../outside.md"])

    def test_existing_manual_diagnostic_cannot_escape_its_admission_on_edit(self):
        import subprocess
        from scripts.hepta_repository_surface import extension_paths

        def git(*args):
            return subprocess.check_output(
                ["git", *args], cwd=self.root, text=True
            ).strip()

        git("init", "-q")
        git("config", "user.name", "Policy Test")
        git("config", "user.email", "policy@localhost")
        path = ".github/workflows/manual diagnostic.yml"
        self.write(path, MANUAL)
        legacy = ".github/workflows/existing-integration.yml"
        self.write(legacy, MANUAL.replace("workflow_dispatch", "push"))
        git("add", ".")
        git("commit", "-qm", "admitted baseline")
        base = git("rev-parse", "HEAD")
        self.write(path, MANUAL.replace("workflow_dispatch", "pull_request"))
        self.write(
            legacy,
            MANUAL.replace("workflow_dispatch", "push").replace(
                "diagnostic output", "different output"
            ),
        )
        git("add", ".")
        git("commit", "-qm", "workflow edits")
        selected = extension_paths(base, git("rev-parse", "HEAD"), self.root)
        self.assertEqual(selected, [path])
        self.assertEqual(self.forbidden(selected), [path])
        self.write(path, MANUAL.replace("diagnostic output", "renamed diagnostic"))
        git("add", ".")
        git("commit", "-qm", "equivalent diagnostic")
        selected = extension_paths(base, git("rev-parse", "HEAD"), self.root)
        self.assertEqual(self.forbidden(selected), [])

    def test_manual_matrix_budget_counts_expanded_jobs_not_yaml_job_entries(self):
        document = load_workflow(MANUAL)
        job = document["jobs"]["inspect"]
        job["strategy"] = {"matrix": {"version": ["a", "b"], "mode": ["x", "y"]}}
        validate_manual_workflow(json.dumps(document), 60)
        job["strategy"]["matrix"]["include"] = [{"note": "metadata only"}]
        validate_manual_workflow(json.dumps(document), 60)
        for matrix in (
            "${{ fromJSON(inputs.matrix) }}",
            {"version": [str(i) for i in range(17)]},
            {"include": [{"item": str(i)} for i in range(17)]},
            {"version": ["${{ inputs.version }}"]},
            {"version": []},
        ):
            job["strategy"] = {"matrix": matrix}
            with self.subTest(matrix=matrix), self.assertRaises(ValueError):
                validate_manual_workflow(json.dumps(document), 60)
        job["strategy"] = {"matrix": {"version": [str(i) for i in range(9)]}}
        document["jobs"]["second"] = copy.deepcopy(job)
        with self.assertRaisesRegex(ValueError, "expanded job budget"):
            validate_manual_workflow(json.dumps(document), 60)

    def test_changed_schema_cannot_become_a_parallel_registry(self):
        import subprocess
        from scripts.hepta_repository_surface import extension_paths

        def git(*args):
            return subprocess.check_output(
                ["git", *args], cwd=self.root, text=True
            ).strip()

        git("init", "-q")
        git("config", "user.name", "Schema Test")
        git("config", "user.email", "schema@localhost")
        path = "docs/modules/example.readonly/schema.json"
        schema = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
        }
        self.write(path, json.dumps(schema))
        git("add", ".")
        git("commit", "-qm", "schema baseline")
        base = git("rev-parse", "HEAD")
        self.write(path, json.dumps({**schema, "modules": []}))
        unusual = "docs/modules/说明\nsecond line.md"
        self.write(unusual, "# explanation")
        git("add", ".")
        git("commit", "-qm", "changed schema and literal path")
        selected = extension_paths(base, git("rev-parse", "HEAD"), self.root)
        self.assertEqual(selected, sorted([path, unusual]))
        self.assertEqual(self.forbidden(selected), [path])


if __name__ == "__main__":
    unittest.main()
