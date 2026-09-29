"""Execution-path checks for local actions, and real Git merge behavior."""

import os
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from hepta_workflow_commands import (
    declared_commands,
    verify_synthetic_merge,
    verify_owner_self_tests,
    workflow_commands,
    workflow_contains_key,
    workflow_events,
    workflow_expression_functions,
    workflow_expression_references,
    workflow_job,
    workflow_literal_collection_values,
    workflow_needs,
    workflow_run,
    workflow_step,
    workflow_step_by_id,
    workflow_steps,
    load_workflow,
)

ROOT = Path(__file__).resolve().parents[1]


class WorkflowCommandTests(unittest.TestCase):
    def test_only_run_scalars_are_commands(self):
        self.assertEqual(
            workflow_commands("""name: cargo test
steps:
  - run: >-
      just test --locked
      -p example
  - run: |
      # cargo test --locked -p misleading
      echo cargo test
      python3 scripts/check.py verify
"""),
            [
                ["just", "test", "--locked", "-p", "example"],
                ["echo", "cargo", "test"],
                ["python3", "scripts/check.py", "verify"],
            ],
        )

    def test_equivalent_yaml_encodings_share_executable_meaning(self):
        expected = [["python3", "scripts/check.py", "verify"]]
        for text in (
            'steps: [{run: "python3 scripts/check.py verify"}]',
            '"steps": [{"run": "python3 scripts/check.py verify"}]',
            "steps:\n  - run: &command >-\n      python3 scripts/check.py\n      verify\n",
            'env: {run: "echo not-a-step"}\njobs: {check: {steps: [{run: "python3 scripts/check.py verify"}]}}',
        ):
            with self.subTest(text=text):
                self.assertEqual(workflow_commands(text), expected)

    def test_quoted_inline_composite_reference_resolves_without_source_spelling(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            action = root / "local action"
            action.mkdir()
            (action / "action.yaml").write_text(
                'runs: {using: "composite", steps: [{"run": "python3 owner.py self-test"}]}'
            )
            text = 'steps: [{"uses": "./local action"}]'
            self.assertEqual(
                declared_commands(text, root), [["python3", "owner.py", "self-test"]]
            )
            with self.assertRaisesRegex(ValueError, "both run and use"):
                declared_commands(
                    'steps: [{run: "echo one", uses: "./local action"}]', root
                )

    def test_commands_in_environment_data_are_not_steps(self):
        self.assertEqual(workflow_commands('env: {run: "git commit-tree forged"}'), [])
        self.assertEqual(
            workflow_commands(
                'jobs: {job: {env: {run: "git commit-tree forged"}, steps: [{run: "echo actual"}]}}'
            ),
            [["echo", "actual"]],
        )

    def test_expression_references_follow_data_flow_not_labels_or_quoted_text(self):
        value = {
            "timeout": "${{ fromJSON(needs.plan.outputs.timeout_minutes) }}",
            "nested": [
                "plain needs.fake.output",
                "${{ env.FLAG == 'needs.quoted.output' && steps.scope.outputs.native }}",
                "${{ matrix.lane }}",
            ],
        }
        self.assertEqual(
            workflow_expression_references(value),
            {
                "needs.plan.outputs.timeout_minutes",
                "env.FLAG",
                "steps.scope.outputs.native",
                "matrix.lane",
            },
        )
        self.assertEqual(
            workflow_expression_references("needs.plan.outputs.lanes"), set()
        )
        self.assertEqual(
            workflow_expression_references(
                "needs.plan.outputs.lanes == 'ignored.literal'", implicit=True
            ),
            {"needs.plan.outputs.lanes"},
        )

    def test_literal_collection_values_accept_yaml_lists_and_json_expressions(self):
        self.assertEqual(
            workflow_literal_collection_values(["source-head", "base-merge"]),
            {"source-head", "base-merge"},
        )
        self.assertEqual(
            workflow_literal_collection_values(
                "${{ fromJSON(github.event_name == 'pull_request' && "
                '\'["source-head","base-merge"]\' || '
                "'[\"source-head\"]') }}"
            ),
            {"source-head", "base-merge"},
        )
        self.assertEqual(
            workflow_literal_collection_values("${{ fromJSON(inputs.dynamic) }}"),
            set(),
        )

    def test_structured_workflow_helpers_ignore_yaml_presentation(self):
        document = load_workflow(
            """on: {workflow_dispatch: {}}
jobs:
  verify:
    needs: [plan, source]
    steps:
      - id: candidate
        name: Check candidate
        if: ${{ !cancelled() && needs.plan.result == 'success' }}
        run: echo verified
"""
        )
        self.assertEqual(workflow_events(document), {"workflow_dispatch"})
        self.assertEqual(
            workflow_needs(workflow_job(document, "verify")), {"plan", "source"}
        )
        self.assertEqual(len(workflow_steps(document, "verify")), 1)
        by_name = workflow_step(document, "verify", "Check candidate")
        self.assertIs(by_name, workflow_step_by_id(document, "verify", "candidate"))
        self.assertEqual(workflow_run(by_name), "echo verified\n")
        self.assertEqual(workflow_expression_functions(by_name["if"]), {"cancelled"})
        self.assertEqual(
            workflow_expression_references(by_name["if"]), {"needs.plan.result"}
        )
        self.assertFalse(workflow_contains_key(document, "continue-on-error"))

    def test_structured_workflow_helpers_reject_ambiguous_or_missing_shape(self):
        duplicate = load_workflow(
            """on: workflow_dispatch
jobs:
  verify:
    steps:
      - {name: Same, run: echo one}
      - {name: Same, run: echo two}
"""
        )
        with self.assertRaisesRegex(ValueError, "requires one step"):
            workflow_step(duplicate, "verify", "Same")
        with self.assertRaisesRegex(ValueError, "missing workflow job"):
            workflow_job(duplicate, "missing")
        with self.assertRaisesRegex(ValueError, "no executable run"):
            workflow_run({"uses": "actions/checkout@" + "a" * 40})
        with self.assertRaisesRegex(ValueError, "needs"):
            workflow_needs({"needs": {"dynamic": True}})

    def test_owner_self_test_is_executable_and_not_required_twice(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workflow = root / "owner.yml"
            registry = [
                {
                    "validator": "python3 scripts/owner.py verify",
                    "workflow": "owner.yml",
                }
            ]
            workflow.write_text("steps:\n  - run: python3 scripts/owner.py self-test\n")
            verify_owner_self_tests(registry, root)
            for line in (
                "# python3 scripts/owner.py self-test",
                "echo python3 scripts/owner.py self-test",
                "python3 scripts/owner.py verify",
            ):
                with (
                    self.subTest(line=line),
                    self.assertRaisesRegex(ValueError, "must invoke"),
                ):
                    workflow.write_text(f"steps:\n  - run: |\n      {line}\n")
                    verify_owner_self_tests(registry, root)

    def test_real_subordinate_workflows_own_their_self_tests(self):
        import json

        registry = json.loads(
            (ROOT / "docs/governance/DOCUMENT_SYSTEM.json").read_text()
        )
        verify_owner_self_tests(registry["subordinateRegistries"], ROOT)

    def test_real_workflow_resolves_composite_action(self):
        text = (ROOT / ".github/workflows/hepta-development-docs.yml").read_text()
        verify_synthetic_merge(text, ROOT)
        document = load_workflow(text)
        for job in document["jobs"].values():
            job["steps"] = [
                step
                for step in job.get("steps", [])
                if step.get("uses") != "./.github/actions/hepta-synthetic-merge"
            ]
        with self.assertRaisesRegex(ValueError, "missing executable"):
            verify_synthetic_merge(json.dumps(document), ROOT)

    def test_comment_or_echo_cannot_stand_in_for_merge(self):
        for line in (
            "# git merge-tree --write-tree base source",
            "echo git merge-tree --write-tree base source",
        ):
            with self.subTest(line=line), self.assertRaises(ValueError):
                verify_synthetic_merge(
                    f"run: |\n  {line}\n  echo git commit-tree tree\n", ROOT
                )

    def test_shell_payload_does_not_register_a_local_action(self):
        text = "run: |\n  cat <<END\n  uses: ./missing\n  END\n"
        declared_commands(text, ROOT)

    def test_local_action_path_and_cycle_reject(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            action = root / "a"
            action.mkdir()
            (action / "action.yml").write_text(
                "runs:\n  using: composite\n  steps:\n    - uses: ./a\n"
            )
            for target in ("./a", "./../outside", "./missing"):
                with self.subTest(target=target), self.assertRaises(ValueError):
                    declared_commands(f"steps:\n  - uses: {target}\n", root)


class SyntheticMergeExecutionTests(unittest.TestCase):
    def test_shared_action_builds_ordered_repeatable_candidate(self):
        action = load_workflow(
            (ROOT / ".github/actions/hepta-synthetic-merge/action.yml").read_text()
        )
        steps = action.get("runs", {}).get("steps", [])
        matches = [step for step in steps if step.get("id") == "merge"]
        self.assertEqual(len(matches), 1)
        script = workflow_run(matches[0])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)

            def git(*args):
                return subprocess.check_output(
                    ["git", "-C", str(root), *args], text=True, stderr=subprocess.PIPE
                ).strip()

            git("init", "-q")
            git("config", "user.name", "test")
            git("config", "user.email", "test@example.invalid")
            (root / "base").write_text("base\n")
            git("add", ".")
            git("commit", "-qm", "initial")
            initial = git("rev-parse", "HEAD")
            (root / "source").write_text("source\n")
            git("add", ".")
            git("commit", "-qm", "source")
            source = git("rev-parse", "HEAD")
            git("checkout", "--detach", initial)
            (root / "target").write_text("target\n")
            git("add", ".")
            git("commit", "-qm", "target")
            base = git("rev-parse", "HEAD")
            outputs = []
            for number in range(2):
                git("checkout", "--detach", source)
                output = root / f"output-{number}"
                environment = {
                    **os.environ,
                    "BASE_SHA": base,
                    "SOURCE_SHA": source,
                    "PR_NUMBER": "1",
                    "AUTHOR_NAME": "test",
                    "AUTHOR_EMAIL": "test@example.invalid",
                    "MESSAGE": "test merge",
                    "GITHUB_OUTPUT": str(output),
                }
                result = subprocess.run(
                    ["bash", "-c", script],
                    cwd=root,
                    env=environment,
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                outputs.append(
                    dict(line.split("=", 1) for line in output.read_text().splitlines())
                )
                self.assertEqual(
                    git("rev-list", "--parents", "-n", "1", "HEAD"),
                    f"{outputs[-1]['sha']} {base} {source}",
                )
                self.assertEqual((root / "source").read_text(), "source\n")
                self.assertEqual((root / "target").read_text(), "target\n")
            self.assertEqual(outputs[0], outputs[1])
            git("checkout", "--detach", base)
            result = subprocess.run(
                ["bash", "-c", script],
                cwd=root,
                env=environment,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(
                result.returncode, 0, "incorrect checked-out source must fail"
            )


if __name__ == "__main__":
    unittest.main()
