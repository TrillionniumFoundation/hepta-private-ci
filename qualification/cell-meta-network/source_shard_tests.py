import argparse
import contextlib
import io
import json
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest
from unittest.mock import patch

from locality_study import extract_snapshot
from source_shard import freeze, freeze_tree, pack, read_tree_file, tree_digest


class SourceShardTests(unittest.TestCase):
    def test_plain_source_tree_has_content_identity_without_an_upstream_commit(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); source = root / "existing-node-source"; source.mkdir()
            (source / "source.rs").write_bytes(b"a\nb\n")
            (source / "z-duplicate.rs").write_bytes(b"a\nb\n")
            with contextlib.redirect_stdout(io.StringIO()):
                freeze_tree(argparse.Namespace(source_root=source, output=root / "snapshot"))
                pack(argparse.Namespace(snapshot=root / "snapshot", output=root / "source.tar.gz"))
            manifest = json.loads((root / "snapshot/manifest.json").read_bytes())
            receipt = json.loads((root / "snapshot/FREEZE.json").read_bytes())
            self.assertIsNone(manifest["source_commit"])
            self.assertEqual(len(manifest["files"]), 1)
            self.assertEqual(manifest["source_tree_sha256"], tree_digest(manifest["files"]))
            self.assertEqual(manifest["source_tree_sha256"], "9cf0ca7fafefd8f96785f0c7749f58ecc635def158c352e86851cdf3774a6734")
            self.assertEqual(receipt["selected_source_entries"], 2)
            self.assertEqual(receipt["duplicate_contents_excluded"], 1)
            incoming = root / "incoming"; incoming.mkdir()
            extract_snapshot(root / "source.tar.gz", incoming, manifest)
            self.assertEqual((incoming / "source.rs").read_bytes(), b"a\nb\n")
            self.assertEqual((source / "source.rs").read_bytes(), b"a\nb\n")
            self.assertFalse((source / ".git").exists())

    def test_plain_tree_rejects_source_symlinks_and_copy_time_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); source = root / "source"; source.mkdir()
            original = source / "source.rs"; original.write_bytes(b"a\nb\n")
            linked = source / "linked.rs"; linked.symlink_to(original)
            with self.assertRaises(ValueError):
                freeze_tree(argparse.Namespace(source_root=source, output=root / "symlink-snapshot"))
            linked.unlink()
            def changing_read(*args):
                data = read_tree_file(*args)
                original.write_bytes(b"c\nd\n")
                return data
            with patch("source_shard.read_tree_file", side_effect=changing_read), self.assertRaisesRegex(ValueError, "changed"):
                freeze_tree(argparse.Namespace(source_root=source, output=root / "changed-snapshot"))
            self.assertFalse((root / "changed-snapshot/manifest.json").exists())

    def test_snapshot_reads_fixed_git_objects_without_modifying_worktree(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); repo = root / "repo"; repo.mkdir()
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            (repo / "a.rs").write_text("fn a() {}\n")
            (repo / "duplicate.rs").write_text("fn a() {}\n")
            (repo / "b.py").write_text("answer = 42\n")
            subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
            subprocess.run(["git", "-C", str(repo), "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "-qm", "source snapshot"], check=True)
            commit = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
            (repo / "a.rs").write_text("uncommitted local work\n")
            with contextlib.redirect_stdout(io.StringIO()):
                freeze(argparse.Namespace(repo=repo, commit=commit, prefix=[], output=root / "snapshot"))
                pack(argparse.Namespace(snapshot=root / "snapshot", output=root / "source.tar.gz"))
            manifest = json.loads((root / "snapshot/manifest.json").read_bytes())
            self.assertEqual(len(manifest["files"]), 2)
            self.assertEqual((root / "snapshot/source/a.rs").read_text(), "fn a() {}\n")
            self.assertEqual((repo / "a.rs").read_text(), "uncommitted local work\n")
            incoming = root / "incoming"; incoming.mkdir()
            extract_snapshot(root / "source.tar.gz", incoming, manifest)
            self.assertEqual((incoming / "b.py").read_text(), "answer = 42\n")

    def test_archive_cannot_escape_destination_or_add_unregistered_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); incoming = root / "incoming"; incoming.mkdir()
            archive = root / "bad.tar.gz"
            with tarfile.open(archive, "w:gz") as stream:
                item = tarfile.TarInfo("../outside.rs"); item.size = 1
                stream.addfile(item, io.BytesIO(b"x"))
            with self.assertRaises(ValueError):
                extract_snapshot(archive, incoming, {"files":[{"path":"expected.rs", "bytes":1, "sha256":"a"*64}]})
            self.assertFalse((root / "outside.rs").exists())


if __name__ == "__main__":
    unittest.main()
