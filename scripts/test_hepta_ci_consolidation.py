from __future__ import annotations

import re
import tomllib
import unittest
from pathlib import Path

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


def event_block(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    match = re.search(r"(?ms)^on:\n(?P<body>.*?)(?=^[A-Za-z_.-]+:|\Z)", text)
    if match is None:
        raise AssertionError(f"missing event block: {path}")
    return match.group("body")


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
        self.assertEqual(
            group[0],
            {
                "filter": "package(codex-hepta-agentd) & test(automation_evolution::)",
                "test-group": "hepta_product_lifecycle",
            },
        )
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
            if re.search(r"(?m)^  pull_request(?:\s*:|:)\s*", event_block(path))
        }
        self.assertEqual(observed, AUTOMATIC)

    def test_deep_entries_remain_manually_runnable(self) -> None:
        candidates: set[Path] = set()
        for pattern in DEEP_PATTERNS:
            candidates.update(WORKFLOWS.glob(pattern))
        for path in candidates:
            if path.name in AUTOMATIC or path.name == "hepta-contract-gate.yml":
                continue
            block = event_block(path)
            self.assertIn("workflow_call:", block, path.name)
            self.assertIn("workflow_dispatch:", block, path.name)

    def test_exact_source_evidence_is_explicit_and_separate_from_native_risk(
        self,
    ) -> None:
        blocking = (WORKFLOWS / "blocking-ci.yml").read_text(encoding="utf-8")
        contract = (WORKFLOWS / "hepta-contract-gate.yml").read_text(encoding="utf-8")
        module_docs = (ROOT / "scripts/hepta-module-docs.py").read_text(
            encoding="utf-8"
        )
        risk = (ROOT / "scripts/hepta_ci_risk.py").read_text(encoding="utf-8")
        self.assertIn("require_exact_source:", blocking)
        self.assertIn("needs.scope.outputs.require_exact_source == 'true'", blocking)
        self.assertIn('return "ordinary"', risk)
        self.assertIn('return "effect"', risk)
        self.assertIn('ordinary = risk == "ordinary"', risk)
        self.assertIn("qualification_requested=args.qualification", risk)
        self.assertNotIn("--qualification", blocking)
        manual = contract.split("  workflow_dispatch:", 1)[1].split("permissions:", 1)[
            0
        ]
        self.assertIn("default: true", manual)
        self.assertIn("if: ${{ inputs.require_exact_source }}", contract)
        self.assertNotIn("scripts/hepta-implementation-maps.py", module_docs)

    def test_new_workflow_and_registry_infrastructure_is_frozen(self) -> None:
        blocking = (WORKFLOWS / "blocking-ci.yml").read_text(encoding="utf-8")
        freeze = (ROOT / "scripts/hepta_repository_surface.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("Freeze workflow and registry infrastructure", blocking)
        self.assertIn("hepta_repository_surface.py", blocking)
        self.assertIn('"--diff-filter=A"', freeze)
        self.assertIn('".github/workflows"', freeze)
        self.assertIn('"docs/modules"', freeze)
        self.assertIn('_REQUIRED_LOCAL_MACHINE_FILES = {"module.toml"}', freeze)
        self.assertIn("path.name not in allowed_local", freeze)
        self.assertIn("allowedRootModuleFiles widened or drifted", freeze)
        self.assertIn("new workflow or registry infrastructure is frozen", freeze)

    def test_aggregators_use_stable_required_job_names(self) -> None:
        blocking = (WORKFLOWS / "blocking-ci.yml").read_text(encoding="utf-8")
        architecture = (WORKFLOWS / "hepta-architecture-convergence.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn("name: CI required", blocking)
        self.assertIn("name: Architecture required", architecture)


if __name__ == "__main__":
    unittest.main()
