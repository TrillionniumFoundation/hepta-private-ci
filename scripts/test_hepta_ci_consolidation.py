from __future__ import annotations

import tomllib
import unittest
from pathlib import Path

from scripts.hepta_workflow_commands import (
    load_workflow,
    workflow_events,
    declared_commands,
)
from scripts.hepta_ci_risk import project
from scripts.hepta_ci_scope import select

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github/workflows"
AUTOMATIC = {
    "blocking-ci.yml",
    "hepta-architecture-convergence.yml",
}
DEEP_PATTERNS = (
    "hepta-*.yml",
    "hnmf-qualification.yml",
    "lane-a-foundation.yml",
    "memory-federation-v2-final-verify.yml",
    "openbao-compatibility.yml",
)


class HeptaCiConsolidationTests(unittest.TestCase):
    def test_product_fixture_group_does_not_change_workload_deadlines_or_retries(self):
        config = tomllib.loads((ROOT / "codex-rs/.config/nextest.toml").read_text())
        self.assertEqual(
            config["test-groups"]["hepta_product_lifecycle"], {"max-threads": 1}
        )
        overrides = config["profile"]["default"]["overrides"]
        group = [
            item
            for item in overrides
            if item.get("test-group") == "hepta_product_lifecycle"
        ]
        self.assertEqual(len(group), 1)
        # The scheduling expression is owned by Nextest, not duplicated here.
        # This override may change which fixtures share a resource, but cannot
        # quietly override their deadlines, retry policy or thread weights.
        self.assertEqual(set(group[0]), {"filter", "test-group"})
        self.assertIsInstance(group[0]["filter"], str)
        self.assertTrue(group[0]["filter"].strip())
        soak = [
            item
            for item in overrides
            if "normal_product_bounded_evolution_under_concurrent_load"
            in item["filter"]
        ]
        self.assertEqual(len(soak), 1)
        self.assertEqual(
            soak[0]["slow-timeout"], {"period": "60s", "terminate-after": 4}
        )
        self.assertNotIn("retries", soak[0])
        self.assertEqual(
            config["profile"]["default"]["slow-timeout"],
            {"period": "30s", "terminate-after": 2},
        )

    def test_only_two_aggregate_workflows_automatically_run_for_pull_requests(
        self,
    ) -> None:
        candidates: set[Path] = set()
        for pattern in DEEP_PATTERNS:
            candidates.update(WORKFLOWS.glob(pattern))
        candidates.add(WORKFLOWS / "blocking-ci.yml")
        observed = {
            path.name
            for path in candidates
            if "pull_request" in workflow_events(load_workflow(path.read_text()))
        }
        self.assertEqual(observed, AUTOMATIC)

    def test_deep_entries_remain_manually_runnable(self) -> None:
        candidates: set[Path] = set()
        for pattern in DEEP_PATTERNS:
            candidates.update(WORKFLOWS.glob(pattern))
        for path in candidates:
            if path.name in AUTOMATIC or path.name == "hepta-contract-gate.yml":
                continue
            events = workflow_events(load_workflow(path.read_text()))
            self.assertTrue({"workflow_call", "workflow_dispatch"} <= events, path.name)

    def test_risk_and_qualification_select_behavior_not_source_spelling(self):
        scope = select([])
        for risk in ("ordinary", "stateful", "effect", "release"):
            for qualified in (False, True):
                with self.subTest(risk=risk, qualified=qualified):
                    result = project(
                        scope, change_risk=risk, qualification_requested=qualified
                    )
                    expected = (
                        ["source-head"]
                        if risk == "ordinary" and not qualified
                        else ["source-head", "base-merge"]
                    )
                    self.assertEqual(result["lanes"], expected)
                    self.assertEqual(result["require_exact_source"], qualified)
        with self.assertRaises(ValueError):
            project(scope, qualification_requested="true")

    def test_learning_lane_executes_independent_reference_workspaces(self):
        workflow = load_workflow(
            (WORKFLOWS / "hepta-architecture-convergence.yml").read_text()
        )
        commands = declared_commands(
            (WORKFLOWS / "hepta-architecture-convergence.yml").read_text(), ROOT
        )
        for package in (
            "hnmf-reference",
            "hnmf-contract-reference",
            "hnmf-adversarial-reference",
        ):
            manifest = "../qualification/" + package + "/Cargo.toml"
            matching = [command for command in commands if manifest in command]
            self.assertEqual(len(matching), 1)
            command = matching[0]
            self.assertIn("--locked", command)
            position = command.index("just")
            self.assertEqual(command[position + 1], "test")
            self.assertEqual(command[command.index("--manifest-path") + 1], manifest)
            self.assertEqual(command[command.index("--profile") + 1], "default")
        self.assertIn("qualification", workflow["jobs"])

    def test_aggregators_use_stable_required_job_names(self):
        for filename, name in (
            ("blocking-ci.yml", "CI required"),
            ("hepta-architecture-convergence.yml", "Architecture required"),
        ):
            workflow = load_workflow((WORKFLOWS / filename).read_text())
            matches = [
                job for job in workflow["jobs"].values() if job.get("name") == name
            ]
            self.assertEqual(len(matches), 1)
            self.assertTrue(matches[0].get("needs"))


if __name__ == "__main__":
    unittest.main()
