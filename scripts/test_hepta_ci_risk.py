import json
import tempfile
import unittest
from pathlib import Path

from scripts.hepta_ci_risk import classify
from scripts.hepta_ci_risk import project
from scripts.hepta_ci_scope import GROUPS
from scripts.hepta_ci_scope import generated_package_groups


ROOT = Path(__file__).resolve().parents[1]


class CiRiskTests(unittest.TestCase):
    def scope(self, **values):
        scope = {group: False for group in GROUPS}
        scope.update(native=False, derived=False, full_repo=False)
        scope.update(values)
        return scope

    def test_risk_order_matches_execution_boundary(self):
        self.assertEqual(classify(self.scope()), "ordinary")
        self.assertEqual(classify(self.scope(inference=True, native=True)), "ordinary")
        self.assertEqual(classify(self.scope(lifecycle=True, native=True)), "stateful")
        self.assertEqual(classify(self.scope(effects=True, native=True)), "effect")
        self.assertEqual(classify(self.scope(full_repo=True)), "release")

    def test_execution_policy_keeps_ordinary_feedback_bounded(self):
        ordinary = project(self.scope(inference=True, native=True))
        self.assertEqual(ordinary["lanes"], ["source-head"])
        self.assertFalse(ordinary["require_exact_source"])
        self.assertEqual(ordinary["ordinary_feedback_target_minutes"], 10)
        self.assertEqual(ordinary["scoped_timeout_minutes"], 15)
        self.assertEqual(ordinary["architecture_timeout_minutes"], 15)

        stateful = project(self.scope(lifecycle=True, native=True))
        self.assertEqual(stateful["lanes"], ["source-head", "base-merge"])
        self.assertTrue(stateful["require_exact_source"])
        self.assertEqual(stateful["scoped_timeout_minutes"], 40)
        self.assertEqual(stateful["architecture_timeout_minutes"], 60)

    def test_required_workflows_consume_risk_projection(self):
        architecture = (
            ROOT / ".github/workflows/hepta-architecture-convergence.yml"
        ).read_text(encoding="utf-8")
        blocking = (ROOT / ".github/workflows/blocking-ci.yml").read_text(
            encoding="utf-8"
        )

        self.assertIn(
            "lane: ${{ fromJSON(needs.plan.outputs.lanes) }}", architecture
        )
        self.assertNotIn(
            "github.event_name == 'pull_request' && '[\"source-head\",\"base-merge\"]'",
            architecture,
        )
        self.assertIn("RISK: ${{ needs.plan.outputs.risk }}", architecture)
        self.assertIn("run_native=false", architecture)
        self.assertIn(
            "timeout-minutes: ${{ fromJSON(needs.plan.outputs.timeout_minutes) }}",
            architecture,
        )
        self.assertIn(".architecture_timeout_minutes", architecture)

        self.assertIn(
            "scoped_timeout_minutes: ${{ steps.scope.outputs.scoped_timeout_minutes }}",
            blocking,
        )
        scoped = blocking.split("  hepta-scoped:", 1)[1].split(
            "  lightweight:", 1
        )[0]
        self.assertIn(
            "timeout-minutes: ${{ fromJSON(needs.scope.outputs.scoped_timeout_minutes) }}",
            scoped,
        )
        self.assertNotIn("timeout-minutes: 40", scoped)

    def test_package_groups_are_loaded_only_from_generated_matrix(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "docs/modules/CI_MATRIX.json"
            target.parent.mkdir(parents=True)
            target.write_text(
                json.dumps(
                    {
                        "schema": "hepta.module-ci-matrix.v1",
                        "groups": sorted(GROUPS),
                        "packages": [
                            {
                                "packagePath": "codex-rs/hepta-sample",
                                "packageName": "codex-hepta-sample",
                                "module": "sample.module",
                                "ciGroups": ["lifecycle"],
                                "compileLayer": 1,
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            self.assertEqual(
                generated_package_groups(root), {"hepta-sample": {"lifecycle"}}
            )


if __name__ == "__main__":
    unittest.main()
