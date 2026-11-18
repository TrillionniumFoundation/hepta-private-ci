"""Adversarial source removal against real frozen and portable file closures."""

import copy
import hashlib
from pathlib import Path
import tempfile
import unittest

from hepta_cell_joint_worker import verify_candidate_source_closure
from package_hia_cell_candidate import git
from qualify_hia_cell_joint import capture_source_identity, execution_sources


class CandidateClosureControls(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.roots = {group: Path(self.temp.name) / group for group in ("cells", "hia")}
        for group, root in self.roots.items():
            root.mkdir()
            git(root, "init", "-q")
            names = (
                ("scripts/hepta_cells/model.py", "scripts/hepta_pred1/core.py")
                if group == "cells"
                else ("hepta/compiler.py",)
            )
            for name in names:
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("def operation():\n    return 1\n")
            git(root, "add", ".")
            git(
                root,
                "-c",
                "user.name=Closure fixture",
                "-c",
                "user.email=fixture@example.invalid",
                "commit",
                "-qm",
                "initial package source",
            )
        locations = execution_sources(self.roots["cells"], self.roots["hia"])
        for _, _, path in locations:
            if not path.exists():
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("# required source fixture\n")
        for root in self.roots.values():
            git(root, "add", ".")
            git(
                root,
                "-c",
                "user.name=Closure fixture",
                "-c",
                "user.email=fixture@example.invalid",
                "commit",
                "-qm",
                "frozen source",
            )
        self.value = {
            "files": [
                {
                    "root": group,
                    "path": str(path.relative_to(root)),
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                }
                for group, root, path in locations
            ],
            "source_identity": {
                group: capture_source_identity(
                    root,
                    [
                        str(path.relative_to(root))
                        for name, _, path in locations
                        if name == group
                    ],
                )
                for group, root in self.roots.items()
            },
        }
        self.value["source_bases"] = {
            "cells": self.value["source_identity"]["cells"]["head"]
        }

    def tearDown(self):
        self.temp.cleanup()

    def remove_records(self, group, names, *, trim_identity=False):
        value = copy.deepcopy(self.value)
        value["files"] = [
            row
            for row in value["files"]
            if row["root"] != group or row["path"] not in names
        ]
        if trim_identity:
            value["source_identity"][group]["files"] = [
                row
                for row in value["source_identity"][group]["files"]
                if row["path"] not in names
            ]
        return value

    def test_complete_freeze_is_accepted_and_legacy_does_not_gain_identity(self):
        verify_candidate_source_closure(self.value, self.roots)
        legacy = copy.deepcopy(self.value)
        del legacy["source_identity"]
        before = copy.deepcopy(legacy)
        verify_candidate_source_closure(legacy, self.roots)
        self.assertEqual(legacy, before)
        self.assertNotIn("source_identity", legacy)

    def test_trimmed_and_rewritten_semantic_or_update_entry_is_refused(self):
        names = {
            "scripts/hepta_cell_semantic_campaign_worker.py",
            "scripts/qualify_cell_updates.py",
        }
        for name in names:
            (self.roots["cells"] / name).write_text(
                "def operation():\n    return 'outside admitted source'\n"
            )
        for provenance in ("unchanged", "trimmed", "absent"):
            with self.subTest(provenance=provenance):
                value = self.remove_records(
                    "cells", names, trim_identity=provenance == "trimmed"
                )
                if provenance == "absent":
                    del value["source_identity"]
                with self.assertRaises(ValueError):
                    verify_candidate_source_closure(value, self.roots)

    def test_independent_reviewer_cannot_be_removed_from_execution_candidate(self):
        for name in (
            "review_hepta_maintenance_snapshot.py",
            "verify_hepta_maintenance_cycle.py",
            "verify_hepta_semantic_cycle.py",
        ):
            with self.subTest(name=name):
                value = self.remove_records(
                    "cells", {"scripts/" + name}, trim_identity=True
                )
                with self.assertRaises(ValueError):
                    verify_candidate_source_closure(value, self.roots)

    def test_tracked_package_source_cannot_hide_behind_skip_worktree(self):
        for group, name in (
            ("cells", "scripts/hepta_cells/model.py"),
            ("hia", "hepta/compiler.py"),
        ):
            with self.subTest(group=group):
                root = self.roots[group]
                git(root, "update-index", "--skip-worktree", name)
                (root / name).unlink()
                self.assertEqual(git(root, "status", "--porcelain"), b"")
                value = self.remove_records(group, {name}, trim_identity=True)
                with self.assertRaises(ValueError):
                    verify_candidate_source_closure(value, self.roots)

    def test_new_untracked_kernel_must_be_frozen_before_execution(self):
        path = self.roots["cells"] / "scripts/hepta_pred1/new_kernel.py"
        path.write_text("def predict():\n    return 2\n")
        with self.assertRaises(ValueError):
            verify_candidate_source_closure(self.value, self.roots)

    def test_identity_scope_cannot_silently_drop_or_add_source_rows(self):
        for action in ("drop", "duplicate", "other_root"):
            with self.subTest(action=action):
                value = copy.deepcopy(self.value)
                rows = value["source_identity"]["cells"]["files"]
                if action == "drop":
                    rows.pop()
                elif action == "duplicate":
                    rows.append(copy.deepcopy(rows[0]))
                else:
                    value["source_identity"]["hia"] = copy.deepcopy(
                        value["source_identity"]["cells"]
                    )
                with self.assertRaises(ValueError):
                    verify_candidate_source_closure(value, self.roots)

    def test_rehashing_manifest_does_not_override_frozen_identity_bytes(self):
        name = "scripts/hepta_cells/model.py"
        path = self.roots["cells"] / name
        path.write_text("def operation():\n    return 99\n")
        value = copy.deepcopy(self.value)
        next(
            row
            for row in value["files"]
            if row["root"] == "cells" and row["path"] == name
        )["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        with self.assertRaises(ValueError):
            verify_candidate_source_closure(value, self.roots)


if __name__ == "__main__":
    unittest.main(verbosity=2)
