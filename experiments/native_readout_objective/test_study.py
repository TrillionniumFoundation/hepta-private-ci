"""Phase and publication guards reject premature or changed scientific inputs."""

from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from . import source, study
from .common import canonical, read_json, scientific_files, sha


class StudyGuards(unittest.TestCase):
    def test_publication_requires_both_remote_ancestry_and_exact_artifact(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)

            def git(*args):
                return subprocess.check_output(
                    ["git", *args], cwd=root, stderr=subprocess.DEVNULL
                )

            git("init", "-q")
            (root / "seal.json").write_bytes(b"first\n")
            git("add", "seal.json")
            git(
                "-c",
                "user.name=Fixture",
                "-c",
                "user.email=fixture@example.invalid",
                "commit",
                "-qm",
                "first",
            )
            first = git("rev-parse", "HEAD").decode().strip()
            git("update-ref", source.REMOTE, first)
            (root / "seal.json").write_bytes(b"second\n")
            git(
                "-c",
                "user.name=Fixture",
                "-c",
                "user.email=fixture@example.invalid",
                "commit",
                "-qam",
                "second",
            )
            second = git("rev-parse", "HEAD").decode().strip()
            with patch.object(source, "REPOSITORY", root):
                source.verify_publication(first, "seal.json", b"first\n")
                with self.assertRaises(ValueError):
                    source.verify_publication(first, "seal.json", b"second\n")
                with self.assertRaises(subprocess.CalledProcessError):
                    source.verify_publication(second, "seal.json", b"second\n")

    def test_source_and_binary_mutations_reject_before_execution(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            module, binary = root / "module.py", root / "native"
            module.write_bytes(b"value = 1\n")
            binary.write_bytes(b"native-fixture")
            sealed = {
                "source_files": {"module.py": sha(module.read_bytes())},
                "native_binary_sha256": sha(binary.read_bytes()),
            }
            with patch.object(source, "REPOSITORY", root):
                source.verify_source(sealed, binary)
                module.write_bytes(b"value = 2\n")
                with self.assertRaises(ValueError):
                    source.verify_source(sealed, binary)
                module.write_bytes(b"value = 1\n")
                binary.write_bytes(b"other-native-fixture")
                with self.assertRaises(ValueError):
                    source.verify_source(sealed, binary)

    def test_partial_training_cannot_restart_or_open_contexts(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for name in [
                "PROTOCOL.json",
                "SOURCE_SEAL.json",
                "ENVIRONMENT.json",
                "TRAINING_STARTED.json",
            ]:
                (root / name).write_bytes(b"{}\n")
            (root / "costs.jsonl").touch()
            with (
                patch.object(study, "verify_frozen", return_value={}),
                patch.object(study, "load_contexts") as contexts,
            ):
                with self.assertRaises(ValueError):
                    study.train(root, root / "native")
                contexts.assert_not_called()

    def test_unpublished_selection_cannot_generate_confirmation(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "SELECTION_SEAL.json").write_bytes(b"{}\n")
            with (
                patch.object(study, "verify_frozen", return_value={}),
                patch.object(
                    study, "verify_publication", side_effect=ValueError("not published")
                ),
                patch.object(study, "load_contexts") as contexts,
            ):
                with self.assertRaises(ValueError):
                    study.confirm(root, root / "native", "0" * 40)
                contexts.assert_not_called()
            self.assertFalse((root / "EXTERNAL_SELECTION.json").exists())

    def test_changed_training_prefix_cannot_open_confirmation(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "costs.jsonl").write_bytes(b"original\n")
            (root / "data.json").write_bytes(b"{}\n")
            selection = {
                "training_files": {"data.json": sha(b"{}\n")},
                "training_costs_prefix_sha256": sha(b"original\n"),
                "training_costs_prefix_bytes": len(b"original\n"),
            }
            (root / "SELECTION_SEAL.json").write_bytes(canonical(selection) + b"\n")
            (root / "costs.jsonl").write_bytes(b"changed!\n")
            with (
                patch.object(study, "verify_frozen", return_value={}),
                patch.object(study, "verify_publication"),
                patch.object(study, "load_contexts") as contexts,
            ):
                with self.assertRaises(ValueError):
                    study.confirm(root, root / "native", "0" * 40)
                contexts.assert_not_called()

    def test_noncanonical_evidence_is_not_silently_accepted(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            path = root / "data.json"
            path.write_bytes(b'{"value":1,"value":2}')
            with self.assertRaises(ValueError):
                read_json(path)
            path.write_bytes(b'{"value":NaN}')
            with self.assertRaises(ValueError):
                read_json(path)
            path.unlink()
            path.symlink_to(root / "missing.json")
            with self.assertRaises(ValueError):
                scientific_files(root)

    def test_changed_environment_publication_rejects_before_execution(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for name in ["PROTOCOL.json", "SOURCE_SEAL.json"]:
                (root / name).write_bytes(b"{}\n")
            env = {
                "protocol_sha256": sha(b"{}\n"),
                "source_seal_sha256": sha(b"{}\n"),
                "publication_commit": "1" * 40,
            }
            (root / "ENVIRONMENT.json").write_bytes(canonical(env))
            with (
                patch.object(
                    source,
                    "verify_publication",
                    side_effect=ValueError("not published"),
                ),
                patch.object(source, "verify_source") as executable,
            ):
                with self.assertRaises(ValueError):
                    source.verify_frozen(root, root / "native")
                executable.assert_not_called()

    def test_incomplete_selected_roster_rejects_before_confirmation_contexts(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            env = {
                key: "1" * 64
                for key in [
                    "protocol_sha256",
                    "source_seal_sha256",
                    "native_binary_sha256",
                ]
            }
            raw = canonical(env)
            (root / "ENVIRONMENT.json").write_bytes(raw)
            (root / "costs.jsonl").touch()
            selection = {
                **env,
                "training_files": {"ENVIRONMENT.json": sha(raw)},
                "training_costs_prefix_sha256": sha(b""),
                "training_costs_prefix_bytes": 0,
                "checkpoints": [],
            }
            (root / "SELECTION_SEAL.json").write_bytes(canonical(selection))
            with (
                patch.object(study, "verify_frozen", return_value={}),
                patch.object(study, "verify_publication"),
                patch.object(study, "load_contexts") as contexts,
            ):
                with self.assertRaises(ValueError):
                    study.confirm(root, root / "native", "0" * 40)
                contexts.assert_not_called()


if __name__ == "__main__":
    unittest.main()
