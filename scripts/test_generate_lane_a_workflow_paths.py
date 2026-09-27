from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

import generate_lane_a_workflow_paths as subject


class LaneAWorkflowPathGenerationTests(unittest.TestCase):
    def inventory(self) -> dict[str, object]:
        return {
            "modules": [
                {
                    "id": "platform.types",
                    "rootBindings": [{"path": "codex-rs/hepta-types"}],
                    "sourceEvidenceRoots": ["codex-rs/hepta-types"],
                    "technicalDocument": "docs/modules/platform.types/TECHNICAL.md",
                },
                {
                    "id": "platform.wire",
                    "rootBindings": [{"path": "codex-rs/hepta-wire"}],
                    "sourceEvidenceRoots": ["codex-rs/hepta-wire", "codex-rs/wire-fixtures"],
                    "technicalDocument": "docs/modules/platform.wire/TECHNICAL.md",
                },
            ]
        }

    def test_paths_are_deterministic_deduplicated_and_module_ordered(self) -> None:
        paths = subject.module_owned_paths(
            self.inventory(), expected_modules=["platform.types", "platform.wire"]
        )
        self.assertEqual(
            paths,
            [
                "codex-rs/hepta-types/**",
                "docs/modules/platform.types/**",
                "codex-rs/hepta-wire/**",
                "codex-rs/wire-fixtures/**",
                "docs/modules/platform.wire/**",
            ],
        )

    def test_missing_closed_world_module_rejects(self) -> None:
        with self.assertRaisesRegex(subject.GenerationError, "missing from inventory"):
            subject.module_owned_paths(self.inventory(), expected_modules=["kernel.authority"])

    def test_duplicate_module_ids_reject(self) -> None:
        inventory = self.inventory()
        modules = inventory["modules"]
        assert isinstance(modules, list)
        modules.append(copy.deepcopy(modules[0]))
        with self.assertRaisesRegex(subject.GenerationError, "duplicate module id"):
            subject.module_owned_paths(inventory, expected_modules=["platform.types"])

    def test_repository_escape_and_glob_in_manifest_reject(self) -> None:
        for unsafe in ["../outside", "/absolute", "codex-rs/hepta-*", "a/./b"]:
            with self.subTest(unsafe=unsafe):
                inventory = self.inventory()
                modules = inventory["modules"]
                assert isinstance(modules, list)
                modules[0]["rootBindings"][0]["path"] = unsafe
                with self.assertRaises(subject.GenerationError):
                    subject.module_owned_paths(inventory, expected_modules=["platform.types"])

    def test_check_detects_and_write_repairs_stale_block(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inventory_path = root / "MODULES.json"
            workflow_path = root / "workflow.yml"
            inventory_path.write_text(json.dumps(self.inventory()), encoding="utf-8")
            workflow_path.write_text(
                "paths:\n"
                f"{subject.BEGIN_MARKER}\n"
                '      - "stale/**"\n'
                f"{subject.END_MARKER}\n"
                '      - "fixed/**"\n',
                encoding="utf-8",
            )
            with self.assertRaisesRegex(subject.GenerationError, "stale"):
                subject.check(
                    inventory_path,
                    workflow_path,
                    expected_modules=["platform.types", "platform.wire"],
                )
            subject.write(
                inventory_path,
                workflow_path,
                expected_modules=["platform.types", "platform.wire"],
            )
            subject.check(
                inventory_path,
                workflow_path,
                expected_modules=["platform.types", "platform.wire"],
            )
            rendered = workflow_path.read_text(encoding="utf-8")
            self.assertIn('      - "codex-rs/hepta-wire/**"', rendered)
            self.assertIn('      - "fixed/**"', rendered)

    def test_marker_multiplicity_rejects(self) -> None:
        with self.assertRaisesRegex(subject.GenerationError, "exactly one"):
            subject.replace_generated_block("paths:\n", "generated")

    def test_repository_workflow_matches_current_inventory(self) -> None:
        subject.check()

    def test_reversed_markers_reject_as_generation_error(self) -> None:
        with self.assertRaisesRegex(subject.GenerationError, "reversed"):
            subject.replace_generated_block(subject.END_MARKER + "\n" + subject.BEGIN_MARKER, "x")

    def test_root_and_control_character_paths_reject(self) -> None:
        for path in [".", "a\x00b", "a\x1fb"]:
            with self.assertRaises(subject.GenerationError):
                subject._safe_repo_path(path, field="path", module_id="platform.wire")

    def test_quoted_paths_cannot_escape_the_generated_yaml_string(self) -> None:
        import json
        path = 'docs/a"b/**'
        line = subject.render_generated_block([path]).splitlines()[1].strip()
        self.assertEqual(json.loads(line[2:]), path)


if __name__ == "__main__":
    unittest.main()
