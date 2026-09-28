import unittest

from scripts.hepta_repository_surface import forbidden_additions


class RepositorySurfaceTests(unittest.TestCase):
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
