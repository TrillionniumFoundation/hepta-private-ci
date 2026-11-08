import copy
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import hepta_cell_joint_config as config


class JointConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "source"
        self.source.mkdir()
        self.artifacts = self.root / "artifacts"
        self.artifacts.mkdir()
        self.git("init", "-q")
        self.git("config", "user.name", "Cell integrity test")
        self.git("config", "user.email", "cell-integrity@example.invalid")
        (self.source / "code.rs").write_text("const VALUE: u8 = 1;\n")
        self.git("add", "code.rs")
        self.git("commit", "-qm", "test source")
        self.document = {
            "schema": config.SCHEMA,
            "source": {
                "repository": "example/cell",
                "commit": self.git("rev-parse", "HEAD"),
                "tree": self.git("rev-parse", "HEAD^{tree}"),
            },
            "artifacts": {
                role: self.bind(role, (role + "\n").encode()) for role in config.ROLES
            },
            "required_workflows": [".github/workflows/cell.yml"],
        }
        self.ci = {
            "total_count": 1,
            "workflow_runs": [{
                "id": 7,
                "head_sha": self.document["source"]["commit"],
                "repository": {"full_name": "example/cell"},
                "path": ".github/workflows/cell.yml",
                "status": "completed",
                "conclusion": "success",
                "run_attempt": 1,
                "html_url": "https://example.invalid/run/7",
            }],
        }
        self.bind_ci()

    def git(self, *args):
        return subprocess.check_output(
            ["git", "-C", str(self.source), *args], stderr=subprocess.PIPE
        ).decode().strip()

    def bind(self, name, data):
        (self.artifacts / name).write_bytes(data)
        return {
            "path": name, "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)
        }

    def bind_ci(self):
        self.document["ci_evidence"] = self.bind(
            "ci.json", json.dumps(self.ci).encode()
        )

    def verify(self):
        return config.verify(self.document, self.source, self.artifacts)

    def test_complete_identity_has_no_adoption_authority(self):
        result = self.verify()
        self.assertEqual(result["source"], self.document["source"])
        self.assertFalse(result["authority_granted"])
        self.assertFalse(result["production_qualification"])
        self.assertFalse(result["provider_authenticity_verified"])

    def test_unstaged_staged_and_untracked_sources_reject(self):
        for mode in ("unstaged", "staged", "untracked"):
            with self.subTest(mode=mode):
                if mode == "untracked":
                    (self.source / "extra.rs").write_text("changed")
                else:
                    (self.source / "code.rs").write_text("changed")
                    if mode == "staged":
                        self.git("add", "code.rs")
                with self.assertRaisesRegex(ValueError, "source checkout"):
                    self.verify()
                self.git("reset", "--hard", "HEAD")
                self.git("clean", "-fd")

    def test_same_tree_other_commit_is_not_same_execution(self):
        self.git("commit", "--allow-empty", "-qm", "other execution identity")
        with self.assertRaisesRegex(ValueError, "execution tree"):
            self.verify()

    def test_hidden_tracked_bytes_and_modes_are_rejected(self):
        path = self.source / "code.rs"
        original = path.read_bytes()
        for mode in ("assume-unchanged", "skip-worktree", "filemode"):
            with self.subTest(mode=mode):
                if mode == "filemode":
                    self.git("config", "core.filemode", "false")
                    path.chmod(0o755)
                else:
                    self.git("update-index", "--" + mode, "code.rs")
                    path.write_bytes(b"x" * len(original))
                self.assertEqual(self.git("status", "--porcelain"), "")
                with self.assertRaisesRegex(ValueError, "tracked source"):
                    self.verify()
                if mode != "filemode":
                    self.git("update-index", "--no-" + mode, "code.rs")
                path.write_bytes(original)
                path.chmod(0o644)

    def test_tracked_symlink_target_is_verified_without_following_it(self):
        link = self.source / "LICENSE"
        link.symlink_to("../outside-license")
        self.git("add", "LICENSE")
        self.git("commit", "-qm", "tracked link")
        self.document["source"].update(
            commit=self.git("rev-parse", "HEAD"),
            tree=self.git("rev-parse", "HEAD^{tree}"),
        )
        self.ci["workflow_runs"][0]["head_sha"] = self.document["source"]["commit"]
        self.bind_ci()
        self.verify()
        self.git("update-index", "--assume-unchanged", "LICENSE")
        link.unlink()
        link.symlink_to("../different-license")
        self.assertEqual(self.git("status", "--porcelain"), "")
        with self.assertRaisesRegex(ValueError, "tracked source symlink"):
            self.verify()

    def test_final_source_scan_rejects_parent_replacement_after_open(self):
        parent = self.source / "src"
        parent.mkdir()
        (self.source / "code.rs").rename(parent / "code.rs")
        self.git("add", "-A")
        self.git("commit", "-qm", "nested source")
        self.document["source"].update(
            commit=self.git("rev-parse", "HEAD"),
            tree=self.git("rev-parse", "HEAD^{tree}"),
        )
        self.ci["workflow_runs"][0]["head_sha"] = self.document["source"]["commit"]
        self.bind_ci()
        original, calls = config.regular_file, []

        @contextmanager
        def changing_read(root_fd, name):
            with original(root_fd, name) as stream:
                if name == "src/code.rs":
                    calls.append(name)
                    if len(calls) == 2:
                        moved = self.root / "moved-source"
                        parent.rename(moved)
                        parent.symlink_to(moved, target_is_directory=True)
                yield stream

        with patch.object(config, "regular_file", changing_read):
            with self.assertRaisesRegex(ValueError, "symlinks"):
                self.verify()
        self.assertEqual(len(calls), 2)

    def test_missing_role_cannot_freeze(self):
        for role in config.ROLES:
            document = copy.deepcopy(self.document)
            del document["artifacts"][role]
            with self.subTest(role=role), self.assertRaisesRegex(ValueError, "eight"):
                config.verify(document, self.source, self.artifacts)

    def test_same_size_model_tampering_is_detected(self):
        path = self.artifacts / "candidate_model"
        path.write_bytes(b"x" * path.stat().st_size)
        with self.assertRaisesRegex(ValueError, "artifact bytes"):
            self.verify()

    def test_an_earlier_artifact_cannot_change_while_later_inputs_are_read(self):
        read = config.read_artifact

        def changing_read(root, binding, **options):
            result = read(root, binding, **options)
            if binding["path"] == "budget":
                path = self.artifacts / "adoption_rules"
                path.write_bytes(b"x" * path.stat().st_size)
            return result

        with patch.object(config, "read_artifact", side_effect=changing_read):
            with self.assertRaisesRegex(ValueError, "during joint configuration"):
                self.verify()

    def test_artifact_size_symlink_and_escape_are_rejected(self):
        original = self.document["artifacts"]["trainer"].copy()
        for change in ({"bytes": True}, {"bytes": 1}, {"path": "../trainer"}):
            self.document["artifacts"]["trainer"] = original | change
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.verify()
        self.document["artifacts"]["trainer"] = original
        path = self.artifacts / "trainer"
        path.rename(self.artifacts / "original")
        path.symlink_to(self.artifacts / "original")
        with self.assertRaisesRegex(ValueError, "symlinks"):
            self.verify()

    def test_parent_symlink_swap_cannot_escape_the_artifact_root(self):
        nested = self.artifacts / "nested"
        outside = self.root / "outside"
        nested.mkdir()
        outside.mkdir()
        data = b"identical expected bytes"
        (outside / "model").write_bytes(data)
        self.document["artifacts"]["candidate_model"] = self.bind("nested/model", data)
        original_open, original_check = os.open, Path.is_symlink
        swapped = False

        def swap():
            nonlocal swapped
            if not swapped:
                nested.rename(self.artifacts / "moved")
                nested.symlink_to(outside, target_is_directory=True)
                swapped = True

        def checked(path):
            result = original_check(path)
            if path == nested and not result:
                swap()
            return result

        def opened(path, flags, *args, **kwargs):
            if path == "nested" and flags & os.O_DIRECTORY:
                swap()
            return original_open(path, flags, *args, **kwargs)

        with patch.object(Path, "is_symlink", checked):
            with patch.object(os, "open", side_effect=opened) as intercepted:
                with patch.object(
                    os, "supports_dir_fd", os.supports_dir_fd | {intercepted}
                ):
                    with self.assertRaises(ValueError):
                        self.verify()
        self.assertTrue(swapped)

    def test_ci_other_source_or_repository_is_rejected(self):
        for change in (
            {"head_sha": "1" * 40}, {"repository": {"full_name": "other/cell"}}
        ):
            original = self.ci["workflow_runs"][0].copy()
            self.ci["workflow_runs"][0].update(change)
            self.bind_ci()
            with self.subTest(change=change), self.assertRaisesRegex(
                ValueError, "another source"
            ):
                self.verify()
            self.ci["workflow_runs"][0] = original

    def test_incomplete_duplicate_and_missing_ci_are_rejected(self):
        for mode in ("pagination", "duplicate", "missing"):
            ci = copy.deepcopy(self.ci)
            if mode == "pagination":
                ci["total_count"] += 1
            elif mode == "duplicate":
                ci["workflow_runs"] *= 2
                ci["total_count"] = 2
            else:
                ci["workflow_runs"][0]["path"] = ".github/workflows/other.yml"
            self.document["ci_evidence"] = self.bind("ci.json", json.dumps(ci).encode())
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                self.verify()

    def test_required_failure_running_or_skipped_is_not_success(self):
        for status, conclusion in (
            ("in_progress", None), ("completed", "failure"), ("completed", "skipped")
        ):
            self.ci["workflow_runs"][0].update(status=status, conclusion=conclusion)
            self.bind_ci()
            with self.subTest(conclusion=conclusion), self.assertRaisesRegex(
                ValueError, "not succeeded"
            ):
                self.verify()

    def test_invalid_json_cannot_override_evidence(self):
        for raw in (
            b'{"head":1,"head":2}', b'{"cost":NaN}',
            b'{"cost":Infinity}', b'{"cost":1e999}',
        ):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                config.strict_json(raw)


if __name__ == "__main__":
    unittest.main()
