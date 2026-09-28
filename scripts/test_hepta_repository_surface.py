import tempfile
import unittest
from pathlib import Path

from scripts.hepta_repository_surface import POLICY_PATH
from scripts.hepta_repository_surface import ROOT
from scripts.hepta_repository_surface import forbidden_additions
from scripts.hepta_repository_surface import load_policy


class RepositorySurfaceTests(unittest.TestCase):
    def test_canonical_convergence_policy_is_fail_closed(self):
        policy = load_policy()
        self.assertEqual(policy["maximumActiveConvergencePrsPerCapability"], 1)
        self.assertEqual(
            policy["allowedDispositions"],
            ["absorb", "reference", "reject", "supersede"],
        )
        self.assertFalse(policy["newPullRequestWorkflowFilesAllowed"])
        self.assertEqual(
            policy["allowedModuleLocalMachineFiles"], {"module.toml"}
        )
        self.assertIn(POLICY_PATH, policy["allowedRootModuleFiles"])

    def test_policy_cannot_allow_an_extra_root_registry(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / POLICY_PATH
            target.parent.mkdir(parents=True)
            text = (ROOT / POLICY_PATH).read_text(encoding="utf-8")
            target.write_text(
                text.replace(
                    '  "docs/modules/registry.toml",\n',
                    '  "docs/modules/registry.toml",\n'
                    '  "docs/modules/PARALLEL_REGISTRY.json",\n',
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "widened or drifted"):
                load_policy(root)

    def test_shared_manifest_and_generated_roots_are_allowed(self):
        self.assertEqual(
            forbidden_additions(
                [
                    "docs/modules/example.module/module.toml",
                    "docs/modules/example.module/TECHNICAL.md",
                    "docs/modules/CI_MATRIX.json",
                    "docs/modules/COMPILE_GRAPH.json",
                    "docs/modules/registry.toml",
                ]
            ),
            [],
        )

    def test_new_workflow_or_per_module_registry_is_rejected(self):
        paths = forbidden_additions(
            [
                ".github/workflows/example-module.yml",
                "docs/modules/example.module/IMPLEMENTATION_MAP.json",
                "docs/modules/example.module/EXTRA.toml",
            ]
        )
        self.assertEqual(
            paths,
            [
                ".github/workflows/example-module.yml",
                "docs/modules/example.module/EXTRA.toml",
                "docs/modules/example.module/IMPLEMENTATION_MAP.json",
            ],
        )


if __name__ == "__main__":
    unittest.main()
