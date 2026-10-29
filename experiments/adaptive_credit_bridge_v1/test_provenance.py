"""Missing packages, version drift, source escape and portable Git binding."""

from importlib import metadata
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from experiments.adaptive_neuron_v2.ledger import sha

from .provenance import (
    checked_input,
    environment,
    materialize_git_proof,
    verify_commit_inputs,
)


class ProvenanceChecks(unittest.TestCase):
    def test_missing_package_fails_closed(self):
        def missing(name):
            if name == "cryptography":
                raise metadata.PackageNotFoundError(name)
            return metadata.version(name)

        with self.assertRaisesRegex(ValueError, "missing"):
            environment(missing)

    def test_changed_version_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "differs"):
            environment(
                lambda name: (
                    "0.0.0" if name == "cryptography" else metadata.version(name)
                )
            )

    def test_source_symlink_and_escape_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            root = parent / "source"
            root.mkdir()
            (root / "valid.py").write_text("actual source\n")
            (parent / "outside.py").write_text("outside source\n")
            self.assertEqual(checked_input("valid.py", root), root / "valid.py")
            (root / "linked.py").symlink_to(root / "valid.py")
            (root / "outside-link.py").symlink_to(parent / "outside.py")
            (root / "linked-directory").symlink_to(root, target_is_directory=True)
            for name in (
                "linked.py",
                "outside-link.py",
                "linked-directory/valid.py",
                "../outside.py",
                str(parent / "outside.py"),
            ):
                with self.subTest(name=name), self.assertRaises(ValueError):
                    checked_input(name, root)

    def test_portable_git_commit_tree_and_blob_binding(self):
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            source, portable = parent / "source", parent / "portable"
            source.mkdir()
            (source / "nested").mkdir()
            input_file = source / "nested/required.py"
            input_file.write_text("frozen source\n")
            subprocess.run(["git", "init", "--quiet", str(source)], check=True)
            subprocess.run(["git", "add", "nested/required.py"], cwd=source, check=True)
            subprocess.run(
                [
                    "git",
                    "-c",
                    "user.name=Research Fixture",
                    "-c",
                    "user.email=fixture@invalid",
                    "commit",
                    "--quiet",
                    "-m",
                    "isolated provenance fixture",
                ],
                cwd=source,
                check=True,
            )
            commit = subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=source, text=True
            ).strip()
            tree = subprocess.check_output(
                ["git", "rev-parse", "HEAD^{tree}"], cwd=source, text=True
            ).strip()
            inputs = {
                "nested/required.py": {
                    "sha256": sha(input_file),
                    "bytes": input_file.stat().st_size,
                }
            }
            seal = parent / "SEAL.json"
            seal.write_text(
                json.dumps(
                    {"source_commit": commit, "source_tree": tree, "inputs": inputs}
                )
            )
            proof = materialize_git_proof(portable, seal, source)
            self.assertEqual(proof["input_blobs_verified"], 1)
            verify_commit_inputs(commit, inputs, portable)
            changed = {
                "nested/required.py": {
                    "sha256": "0" * 64,
                    "bytes": input_file.stat().st_size,
                }
            }
            with self.assertRaisesRegex(ValueError, "differs"):
                verify_commit_inputs(commit, changed, portable)
            blob = subprocess.check_output(
                ["git", "rev-parse", commit + ":nested/required.py"],
                cwd=portable,
                text=True,
            ).strip()
            (portable / ".git/objects" / blob[:2] / blob[2:]).unlink()
            with self.assertRaisesRegex(ValueError, "Missing"):
                verify_commit_inputs(commit, inputs, portable)


if __name__ == "__main__":
    unittest.main()
