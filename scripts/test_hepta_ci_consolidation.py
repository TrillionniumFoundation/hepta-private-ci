from __future__ import annotations

import copy
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
        overrides = config["profile"]["default"]["overrides"]
        group = [
            item
            for item in overrides
            if item.get("test-group") == "hepta_product_lifecycle"
        ]
        self.assertTrue(group)
        # The scheduling expression is owned by Nextest, not duplicated here.
        # The base entry only schedules fixtures. Specific multi-process
        # experiments may retain their bounded total harness time while their
        # original request deadlines stay in the owning product tests.
        self.assertTrue(any(set(item) == {"filter", "test-group"} for item in group))
        for item in group:
            self.assertNotIn("threads-required", item)
            if "retries" in item:
                self.assertEqual(item["retries"], 0)
            self.assertIsInstance(item["filter"], str)
            self.assertTrue(item["filter"].strip())
        soak = [
            item
            for item in overrides
            if "normal_product_bounded_evolution_under_concurrent_load"
            in item["filter"]
        ]
        self.assertEqual(len(soak), 1)
        # Time and concurrency budgets have one owner: the Nextest profile.
        # Keep checking that isolation does not smuggle in retry overrides.
        self.assertNotIn("retries", soak[0])

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

    def assert_process_lane(self, workflow):
        jobs = workflow["jobs"]
        product = jobs["product_process"]
        library = jobs["qualification"]
        required = jobs["required"]
        self.assertIn("product_process", required["needs"])
        gate = required["steps"][0]
        self.assertEqual(
            gate["env"]["PRODUCT_PROCESS_RESULT"], "${{ needs.product_process.result }}"
        )
        self.assertIn('test "$PRODUCT_PROCESS_RESULT" = success', gate["run"])
        self.assertEqual(product["strategy"]["matrix"], library["strategy"]["matrix"])
        self.assertEqual(int(product["timeout-minutes"]), 60)
        # Both jobs recompute the exact same source/prospective merge and scope.
        for name in [
            "Check out exact candidate",
            "Fetch exact qualification history",
            "Verify GitHub prospective merge ref matches this exact candidate",
            "Construct the canonical prospective merge",
            "Bind tested identity",
            "Select exact-tree execution tier",
            "Select affected architecture boundaries",
        ]:
            self.assertEqual(
                next(step for step in product["steps"] if step.get("name") == name),
                next(step for step in library["steps"] if step.get("name") == name),
            )
        commands = [
            step
            for step in product["steps"]
            if "agentd-selection-product.json" in step.get("run", "")
        ]
        self.assertEqual(len(commands), 1)
        step = commands[0]
        self.assertEqual(
            step["if"],
            "steps.execution.outputs.run_native == 'true' && steps.scope.outputs.lifecycle == 'true'",
        )
        self.assertIn(
            "--minimum-tests 6 -- just test --locked --cargo-profile hepta-product -p codex-hepta-agentd --test module_selection_product --test-threads=1 --retries=0",
            step["run"],
        )
        self.assertFalse(
            any(
                "module_selection_product" in step.get("run", "")
                for step in library["steps"]
            )
        )
        cache = next(
            step
            for step in product["steps"]
            if step.get("name") == "Cache public Cargo sources"
        )
        self.assertEqual(
            set(cache["with"]["path"].splitlines()),
            {
                "~/.cargo/registry/cache",
                "~/.cargo/registry/index",
                "~/.cargo/registry/src",
                "~/.cargo/git/db",
            },
        )

    def test_cold_product_profile_has_its_own_budget_without_duplicate_or_skipped_coverage(
        self,
    ):
        self.assert_process_lane(
            load_workflow(
                (WORKFLOWS / "hepta-architecture-convergence.yml").read_text()
            )
        )

    def test_process_lane_failure_cannot_be_omitted_from_the_required_gate(self):
        original = load_workflow(
            (WORKFLOWS / "hepta-architecture-convergence.yml").read_text()
        )
        for mutation in ("needs", "result", "shell-gate"):
            workflow = copy.deepcopy(original)
            required = workflow["jobs"]["required"]
            if mutation == "needs":
                required["needs"].remove("product_process")
            elif mutation == "result":
                required["steps"][0]["env"]["PRODUCT_PROCESS_RESULT"] = "success"
            else:
                required["steps"][0]["run"] = required["steps"][0]["run"].replace(
                    'test "$PRODUCT_PROCESS_RESULT" = success', "true"
                )
            with self.subTest(mutation=mutation), self.assertRaises(AssertionError):
                self.assert_process_lane(workflow)

    def test_process_job_rejects_other_candidate_or_weakened_native_coverage(self):
        original = load_workflow(
            (WORKFLOWS / "hepta-architecture-convergence.yml").read_text()
        )
        for mutation in ("candidate", "profile", "count", "retry"):
            workflow = copy.deepcopy(original)
            steps = workflow["jobs"]["product_process"]["steps"]
            if mutation == "candidate":
                next(
                    step
                    for step in steps
                    if step.get("name") == "Check out exact candidate"
                )["with"]["ref"] = "main"
            else:
                step = next(
                    step
                    for step in steps
                    if "module_selection_product" in step.get("run", "")
                )
                before, after = {
                    "profile": (
                        "--cargo-profile hepta-product",
                        "--cargo-profile dev-small",
                    ),
                    "count": ("--minimum-tests 6", "--minimum-tests 0"),
                    "retry": ("--retries=0", "--retries=1"),
                }[mutation]
                step["run"] = step["run"].replace(before, after)
            with self.subTest(mutation=mutation), self.assertRaises(AssertionError):
                self.assert_process_lane(workflow)

    def test_source_cache_cannot_include_credentials_or_native_test_state(self):
        original = load_workflow(
            (WORKFLOWS / "hepta-architecture-convergence.yml").read_text()
        )
        for extra in (
            "~/.cargo/config.toml",
            "~/.cargo/credentials.toml",
            "codex-rs/target",
        ):
            workflow = copy.deepcopy(original)
            cache = next(
                step
                for step in workflow["jobs"]["product_process"]["steps"]
                if step.get("name") == "Cache public Cargo sources"
            )
            cache["with"]["path"] += "\n" + extra
            with self.subTest(extra=extra), self.assertRaises(AssertionError):
                self.assert_process_lane(workflow)


if __name__ == "__main__":
    unittest.main()
