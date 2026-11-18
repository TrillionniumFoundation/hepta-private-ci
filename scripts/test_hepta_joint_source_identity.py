"""Actual Git/source transitions for joint candidate and portable identities."""

import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from package_hia_cell_candidate import git
from qualify_hia_cell_joint import (
    capture_source_identity,
    execution_sources,
    verify_source_identity,
)
from refreeze_joint_worker import verify_transferred_identity


class SourceIdentityControls(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "repository"
        self.root.mkdir()
        git(self.root, "init", "-q")
        self.name = "scripts/worker.py"
        self.source = self.root / self.name
        self.source.parent.mkdir()
        self.source.write_text("def operation():\n    return 1\n")
        git(self.root, "add", self.name)
        self.commit("initial")

    def tearDown(self):
        self.temp.cleanup()

    def commit(self, message, *extra):
        git(
            self.root,
            "-c",
            "user.name=Source identity fixture",
            "-c",
            "user.email=fixture@example.invalid",
            "commit",
            "-qm",
            message,
            *extra,
        )

    def capture(self, *extra, allow_dirty=False):
        return capture_source_identity(
            self.root, [self.name, *extra], allow_dirty=allow_dirty
        )

    def test_changed_bytes_are_refused_even_when_git_index_hides_them(self):
        original = self.capture()
        git(self.root, "update-index", "--assume-unchanged", self.name)
        self.source.write_text("def operation():\n    return 2\n")
        self.assertEqual(git(self.root, "status", "--porcelain"), b"")
        with self.assertRaises(ValueError):
            verify_source_identity(self.root, original)
        observed = self.capture(allow_dirty=True)
        self.assertFalse(observed["exact_head_source"])
        self.assertEqual(observed["head"], original["head"])
        self.assertNotEqual(observed["files"], original["files"])

    def test_new_required_source_has_no_head_qualification(self):
        name = "scripts/new_semantic_worker.py"
        (self.root / name).write_text("def semantic_operation():\n    return True\n")
        with self.assertRaises(ValueError):
            self.capture(name)
        observed = self.capture(name, allow_dirty=True)
        self.assertFalse(observed["exact_head_source"])
        row = next(item for item in observed["files"] if item["path"] == name)
        self.assertIsNone(row["head_blob"])
        self.assertEqual(
            row["sha256"], hashlib.sha256((self.root / name).read_bytes()).hexdigest()
        )

    def test_missing_required_source_is_refused_including_exploration(self):
        original = self.capture()
        self.source.unlink()
        with self.assertRaises((OSError, ValueError)):
            verify_source_identity(self.root, original)
        with self.assertRaises((OSError, ValueError)):
            self.capture(allow_dirty=True)

    def test_same_content_on_another_branch_does_not_reuse_identity(self):
        original = self.capture()
        git(self.root, "checkout", "-qb", "same-bytes-other-branch")
        self.assertEqual(self.capture()["files"], original["files"])
        with self.assertRaises(ValueError):
            verify_source_identity(self.root, original)

    def test_same_tree_at_new_commit_does_not_reuse_identity(self):
        original = self.capture()
        self.commit("same tree different commit", "--allow-empty")
        self.assertEqual(self.capture()["tree"], original["tree"])
        with self.assertRaises(ValueError):
            verify_source_identity(self.root, original)

    def test_source_mode_change_is_refused(self):
        original = self.capture()
        self.source.chmod(0o755)
        with self.assertRaises(ValueError):
            verify_source_identity(self.root, original)

    def test_automatic_closure_includes_untracked_and_hidden_missing_package_source(
        self,
    ):
        package_file = self.root / "scripts/hepta_cells/cell.py"
        package_file.parent.mkdir()
        package_file.write_text("def cell():\n    return 1\n")
        for _, _, path in execution_sources(self.root, self.root):
            if not path.exists():
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("# required source fixture\n")
        git(self.root, "add", ".")
        self.commit("complete closure")

        def capture_closure(**kwargs):
            names = [
                str(path.relative_to(self.root))
                for group, _, path in execution_sources(self.root, self.root)
                if group == "cells"
            ]
            return capture_source_identity(self.root, names, **kwargs)

        capture_closure()
        new = package_file.parent / "new_kernel.py"
        new.write_text("def kernel():\n    return 2\n")
        with self.assertRaises(ValueError):
            capture_closure()
        exploration = capture_closure(allow_dirty=True)
        self.assertTrue(any(row["head_blob"] is None for row in exploration["files"]))
        new.unlink()
        git(
            self.root,
            "update-index",
            "--skip-worktree",
            str(package_file.relative_to(self.root)),
        )
        package_file.unlink()
        self.assertEqual(git(self.root, "status", "--porcelain"), b"")
        with self.assertRaises((OSError, ValueError)):
            capture_closure(allow_dirty=True)

    def portable(self):
        original = self.capture()
        target = Path(self.temp.name) / "portable"
        old = {
            "files": [
                {
                    "root": group,
                    "path": self.name,
                    "sha256": original["files"][0]["sha256"],
                }
                for group in ("cells", "hia")
            ],
            "source_identity": {
                group: copy.deepcopy(original) for group in ("cells", "hia")
            },
            "source_bases": {"cells": original["head"]},
        }
        mapped = []
        for group in ("cells", "hia"):
            path = target / group / self.name
            path.parent.mkdir(parents=True)
            path.write_bytes(self.source.read_bytes())
            path.chmod(self.source.stat().st_mode & 0o777)
            mapped.append(
                {
                    "path": group + "/" + self.name,
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                }
            )
        raw = json.dumps(old, sort_keys=True).encode()
        return (
            target,
            old,
            raw,
            {
                "files": mapped,
                "origin_candidate_sha256": hashlib.sha256(raw).hexdigest(),
            },
        )

    def test_portable_sources_preserve_origin_without_claiming_target_checkout(self):
        target, old, raw, mapped = self.portable()
        restored, observation = verify_transferred_identity(target, mapped, raw)
        self.assertEqual(restored, old)
        self.assertTrue(observation["origin_exact_head_source"])
        self.assertFalse(observation["target_git_checkout_verified"])
        mapped["files"].pop()
        with self.assertRaises(ValueError):
            verify_transferred_identity(target, mapped, raw)

    def test_portable_source_cannot_relabel_dirty_bytes_as_head(self):
        target, old, _, mapped = self.portable()
        old["source_identity"]["cells"]["files"][0]["head_blob"] = "0" * 40
        raw = json.dumps(old, sort_keys=True).encode()
        mapped["origin_candidate_sha256"] = hashlib.sha256(raw).hexdigest()
        with self.assertRaises(ValueError):
            verify_transferred_identity(target, mapped, raw)

    def test_portable_executable_mode_is_preserved_and_checked(self):
        self.source.chmod(0o755)
        git(self.root, "add", self.name)
        self.commit("executable entry point")
        target, _, raw, mapped = self.portable()
        verify_transferred_identity(target, mapped, raw)
        (target / "cells" / self.name).chmod(0o644)
        with self.assertRaises(ValueError):
            verify_transferred_identity(target, mapped, raw)

    def test_legacy_transfer_remains_explicitly_unqualified_and_origin_bound(self):
        target, old, _, mapped = self.portable()
        del old["source_identity"]
        raw = json.dumps(old, sort_keys=True).encode()
        mapped["origin_candidate_sha256"] = hashlib.sha256(raw).hexdigest()
        _, observation = verify_transferred_identity(target, mapped, raw)
        self.assertFalse(observation["origin_identity_recorded"])
        self.assertFalse(observation["origin_exact_head_source"])
        with self.assertRaises(ValueError):
            verify_transferred_identity(target, mapped, raw + b"\n")


if __name__ == "__main__":
    unittest.main(verbosity=2)
