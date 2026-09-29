"""Guard ordinary candidate qualification from live permission probes."""

from __future__ import annotations

import itertools
import os
from pathlib import Path
import subprocess
import unittest

from scripts.hepta_workflow_commands import declared_commands
from scripts.hepta_workflow_commands import load_workflow
from scripts.hepta_workflow_commands import run_scalar_commands
from scripts.hepta_workflow_commands import workflow_events
from scripts.hepta_workflow_commands import workflow_expression_references

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/hepta-architecture-convergence.yml"
ACTIVATION = ROOT / ".github/workflows/hepta-self-iteration-activation.yml"


def command_lines(step: dict) -> list[str]:
    return [" ".join(command) for command in run_scalar_commands(step.get("run", ""))]


def step_with_command(job: dict, needle: str) -> tuple[int, dict]:
    matches = [
        (index, step)
        for index, step in enumerate(job.get("steps", []))
        if any(needle in line for line in command_lines(step))
    ]
    if len(matches) != 1:
        raise AssertionError(
            f"expected one step containing {needle!r}, found {len(matches)}"
        )
    return matches[0]


def contains_key(value: object, key: str) -> bool:
    if isinstance(value, dict):
        return key in value or any(contains_key(item, key) for item in value.values())
    if isinstance(value, list):
        return any(contains_key(item, key) for item in value)
    return False


class CandidateTransportWorkflowTests(unittest.TestCase):
    def architecture(self) -> dict:
        return load_workflow(WORKFLOW.read_text(encoding="utf-8"))

    def test_ordinary_qualification_uses_local_contract_tests_only(self):
        qualification = self.architecture()["jobs"]["qualification"]
        _, step = step_with_command(
            qualification, "scripts.test_hepta_candidate_transport_workflow"
        )
        lines = command_lines(step)
        self.assertTrue(
            any(
                "python3 -m unittest -v scripts.test_hepta_candidate_transport_workflow"
                in line
                for line in lines
            )
        )
        self.assertTrue(any("--minimum-tests 1" in line for line in lines))
        self.assertNotIn("GH_TOKEN", step.get("env", {}))
        forbidden = ("observe_write_transport_denial", "git-receive-pack", "gh api")
        self.assertFalse(any(token in line for token in forbidden for line in lines))

    def test_external_repository_observation_remains_activation_only(self):
        architecture_commands = [
            " ".join(command)
            for command in declared_commands(WORKFLOW.read_text(), ROOT)
        ]
        self.assertFalse(
            any(
                token in line
                for token in ("--probe-write-denial", "git-receive-pack")
                for line in architecture_commands
            )
        )

        activation = load_workflow(ACTIVATION.read_text(encoding="utf-8"))
        self.assertEqual(
            workflow_events(activation), {"workflow_call", "workflow_dispatch"}
        )
        self.assertTrue(
            all(
                value in {"read", "none"}
                for value in activation["permissions"].values()
            )
        )
        job = activation["jobs"]["repository-control"]
        _, step = step_with_command(job, "scripts/hepta_repository_controls.py")
        lines = command_lines(step)
        self.assertTrue(any("--probe-write-denial" in line for line in lines))
        self.assertIn(
            "github.token", workflow_expression_references(step.get("env", {}))
        )

    def test_native_and_lifecycle_work_precedes_transport_contract(self):
        job = self.architecture()["jobs"]["qualification"]
        transport, _ = step_with_command(
            job, "scripts.test_hepta_candidate_transport_workflow"
        )
        for needle in (
            "-p codex-hepta-infer-core",
            "repeated_read_only_add_replace_retire_preserves_dispatch_and_generation_fences",
            "new_generation_candidate_changes_behavior_and_explicit_predecessor_reload_restores_it",
        ):
            with self.subTest(needle=needle):
                index, _ = step_with_command(job, needle)
                self.assertLess(index, transport)

    def test_required_fan_in_still_rejects_every_unsuccessful_lane(self):
        required = self.architecture()["jobs"]["required"]
        needs = required["needs"]
        self.assertEqual(
            set(needs if isinstance(needs, list) else [needs]),
            {"plan", "qualification"},
        )
        refs = workflow_expression_references(required.get("steps", []))
        self.assertTrue(
            {
                "needs.plan.result",
                "needs.qualification.result",
                "needs.plan.outputs.risk",
                "needs.plan.outputs.lanes",
            }
            <= refs
        )
        self.assertFalse(contains_key(required, "continue-on-error"))
        script = required["steps"][0]["run"]
        states = (
            "success",
            "failure",
            "skipped",
            "cancelled",
            "timed_out",
            "action_required",
        )
        for plan, qualification in itertools.product(states, repeat=2):
            with self.subTest(plan=plan, qualification=qualification):
                process = subprocess.run(
                    ["bash", "--noprofile", "--norc", "-eo", "pipefail", "-c", script],
                    env={
                        **os.environ,
                        "PLAN_RESULT": plan,
                        "QUALIFICATION_RESULT": qualification,
                        "RISK": "ordinary",
                        "LANES": "source-head",
                    },
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                self.assertEqual(
                    process.returncode == 0, plan == qualification == "success"
                )


if __name__ == "__main__":
    unittest.main()
