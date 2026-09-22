"""Regression coverage for non-recursive exact implementation-map source objects."""

import importlib.util
import unittest
from pathlib import Path
from unittest import mock


class ImplementationMapSourceObjectsTests(unittest.TestCase):
    def load_maps(self):
        spec = importlib.util.spec_from_file_location(
            "implementation_maps",
            Path(__file__).with_name("hepta-implementation-maps.py"),
        )
        maps = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(maps)
        return maps

    def test_tracks_native_tests_delegated_callees_and_product_callers(self):
        maps = self.load_maps()
        row = {
            "declaredRoots": ["codex-rs/hepta-prompt-optimizer"],
            "operations": [
                {
                    "sourcePath": "owner/src/canonical.rs",
                    "tests": [
                        "owner/src/canonical_tests.rs",
                        {"path": "owner/tests/product.rs"},
                    ],
                    "delegatedCallees": ["registry/src/v2.rs"],
                }
            ],
            "productCallers": [
                {
                    "sourcePath": "intelligence/src/prompt_pipeline.rs",
                    "tests": ["intelligence/src/prompt_pipeline_tests.rs"],
                }
            ],
        }
        self.assertEqual(
            maps.tracked_source_paths(row),
            [
                "intelligence/src/prompt_pipeline.rs",
                "intelligence/src/prompt_pipeline_tests.rs",
                "owner/src/canonical.rs",
                "owner/src/canonical_tests.rs",
                "owner/tests/product.rs",
                "registry/src/v2.rs",
            ],
        )
        self.assertNotIn(
            "codex-rs/hepta-prompt-optimizer",
            maps.tracked_source_paths(row),
        )

    def test_current_source_objects_bind_each_tracked_file_at_head(self):
        maps = self.load_maps()
        row = {
            "operations": [
                {
                    "sourcePath": "owner/src/canonical.rs",
                    "tests": ["owner/src/canonical_tests.rs"],
                    "delegatedCallees": [],
                }
            ],
            "productCallers": [],
        }

        def fake_git(*args):
            self.assertEqual(args[0], "rev-parse")
            return {
                "HEAD:owner/src/canonical.rs": "a" * 40,
                "HEAD:owner/src/canonical_tests.rs": "b" * 40,
            }[args[1]]

        with mock.patch.object(maps, "git", side_effect=fake_git):
            self.assertEqual(
                maps.current_source_objects(row),
                [
                    {"path": "owner/src/canonical.rs", "object": "a" * 40},
                    {"path": "owner/src/canonical_tests.rs", "object": "b" * 40},
                ],
            )


if __name__ == "__main__":
    unittest.main()
