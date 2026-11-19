"""Git and file mutations cannot inherit a previous candidate identity."""

from copy import deepcopy
from pathlib import Path
import subprocess
import tempfile
import unittest

from .candidate import COMPONENTS, seal_bundle, source_identity, verify_bundle


class CandidateTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name).resolve()

    def git(self, *args):
        return subprocess.check_output(["git", *args], cwd=self.root).decode().strip()

    def repository(self):
        self.git("init", "-q")
        self.git("config", "user.name", "Candidate Test")
        self.git("config", "user.email", "candidate@example.invalid")
        for patterns in COMPONENTS.values():
            path = self.root / patterns[0].replace("*", "example")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("# original committed fixture\n")
        self.git("add", ".")
        self.git("commit", "-qm", "fixture")
        return self.git("rev-parse", "HEAD")

    def bundle(self):
        contract = {
            name: {"profile": "test-only"}
            for name in (
                "model",
                "data",
                "codec",
                "utility",
                "budget",
                "recovery",
                "runtime",
            )
        }
        roles = {
            name: name + ".bin"
            for name in (
                "baseline",
                "candidate",
                "native_binary",
                "training",
                "registration",
            )
        }
        for role, name in roles.items():
            (self.root / name).write_bytes(role.encode())
        return seal_bundle(self.root, {"commit": "test-only"}, contract, roles)

    def test_source_tree_rebuild_and_hidden_tracked_mutation(self):
        head = self.repository()
        first = source_identity(self.root, head)
        self.assertEqual(source_identity(self.root, head), first)
        path = first["components"]["hepta_core"][0]
        self.git("update-index", "--assume-unchanged", path)
        (self.root / path).write_text("# changed without git status\n")
        self.assertEqual(self.git("status", "--porcelain"), "")
        with self.assertRaisesRegex(ValueError, "Source bytes differ"):
            source_identity(self.root, head)

    def test_untracked_and_ignored_imports_are_rejected(self):
        head = self.repository()
        (self.root / "unregistered.py").write_text("# import shadow\n")
        with self.assertRaisesRegex(ValueError, "Untracked"):
            source_identity(self.root, head)
        (self.root / ".git/info/exclude").write_text("unregistered.py\n")
        self.assertEqual(self.git("status", "--porcelain"), "")
        with self.assertRaisesRegex(ValueError, "Untracked"):
            source_identity(self.root, head)

    def test_changed_commit_cannot_reuse_source_identity(self):
        head = self.repository()
        self.git("commit", "--allow-empty", "-qm", "new identity")
        with self.assertRaisesRegex(ValueError, "HEAD"):
            source_identity(self.root, head)

    def test_hidden_required_test_mutation_cannot_inherit_identity(self):
        head = self.repository()
        path = source_identity(self.root, head)["components"]["required_tests"][0]
        self.git("update-index", "--assume-unchanged", path)
        (self.root / path).write_text("# changed acceptance test\n")
        self.assertEqual(self.git("status", "--porcelain"), "")
        with self.assertRaisesRegex(ValueError, "Source bytes differ"):
            source_identity(self.root, head)

    def test_sourceless_bytecode_shadow_is_rejected(self):
        head = self.repository()
        cache = self.root / "__pycache__/module.cpython-312.pyc"
        cache.parent.mkdir()
        cache.write_bytes(b"ordinary generated cache")
        source_identity(self.root, head)
        (self.root / "unregistered.pyc").write_bytes(b"sourceless import shadow")
        with self.assertRaisesRegex(ValueError, "Untracked"):
            source_identity(self.root, head)

    def test_replacement_ref_cannot_substitute_another_committed_tree(self):
        original = self.repository()
        path = self.root / COMPONENTS["v4"][0].replace("*", "example")
        path.write_text("# replacement source\n")
        self.git("add", ".")
        self.git("commit", "-qm", "replacement")
        replacement = self.git("rev-parse", "HEAD")
        self.git("replace", original, replacement)
        self.git("update-ref", "HEAD", original)
        self.assertEqual(self.git("status", "--porcelain"), "")
        with self.assertRaisesRegex(ValueError, "Tracked changes"):
            source_identity(self.root, original)

    def test_cold_manifest_verifies_all_roles_and_keeps_no_update(self):
        manifest = self.bundle()
        self.assertEqual(
            verify_bundle(
                self.root, deepcopy(manifest), manifest["candidate_identity"]
            ),
            manifest,
        )
        self.assertEqual(manifest["production_update"], "no-update")
        (self.root / "candidate.bin").write_bytes(b"changed weight")
        with self.assertRaisesRegex(ValueError, "artifacts"):
            verify_bundle(self.root, manifest, manifest["candidate_identity"])

    def test_contract_change_cannot_rebind_expected_identity(self):
        manifest = self.bundle()
        expected = manifest["candidate_identity"]
        manifest["contract"]["budget"] = {"profile": "unregistered-budget"}
        with self.assertRaisesRegex(ValueError, "identity"):
            verify_bundle(self.root, manifest, expected)

    def test_bundle_refuses_symlink_and_path_escape(self):
        manifest = self.bundle()
        roles = {k: v["path"] for k, v in manifest["artifacts"].items()}
        (self.root / "candidate.bin").unlink()
        (self.root / "candidate.bin").symlink_to(self.root / "baseline.bin")
        with self.assertRaisesRegex(ValueError, "non-symlinked"):
            seal_bundle(self.root, manifest["source"], manifest["contract"], roles)
        roles["candidate"] = "../outside.bin"
        with self.assertRaisesRegex(ValueError, "inside"):
            seal_bundle(self.root, manifest["source"], manifest["contract"], roles)


if __name__ == "__main__":
    unittest.main()
