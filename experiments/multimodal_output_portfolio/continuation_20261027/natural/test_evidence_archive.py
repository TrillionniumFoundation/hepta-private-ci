"""Exercise restoration and external-weight verification without a network call."""
import hashlib
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest

from .recover_models import recover
from .restore_evidence import restore


class EvidenceArchiveTests(unittest.TestCase):
    def make_archive(self, root, paths, content, declared_hash=None):
        digest = declared_hash or hashlib.sha256(content).hexdigest()
        index = {"schema": "hepta.ndu.natural.content-addressed-archive.v1", "external_models": [],
            "paths": [{"path": path, "sha256": digest, "bytes": len(content)} for path in paths]}
        archive = root/"raw.tar.gz"
        with tarfile.open(archive, "w:gz") as stream:
            for name, data in (("INDEX.json", json.dumps(index).encode()), ("blobs/"+digest, content)):
                member = tarfile.TarInfo(name)
                member.size = len(data)
                stream.addfile(member, io.BytesIO(data))
        return archive

    def test_every_duplicate_logical_path_reopens_with_original_bytes(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            content = b"An actual delivered transcript.\n"
            archive = self.make_archive(root, ["first.txt", "nested/second.txt"], content)
            receipt = restore(archive, root/"restored")
            self.assertEqual((root/"restored/first.txt").read_bytes(), content)
            self.assertEqual((root/"restored/nested/second.txt").read_bytes(), content)
            self.assertEqual((receipt["unique_blobs_rehashed"], receipt["logical_paths_actually_restored_and_reopened"]), (1, 2))
            discarded = restore(archive, root/"checked", verify_discard=True)
            self.assertEqual(discarded["logical_bytes_restored"], len(content)*2)
            self.assertFalse(any(path.is_file() for path in (root/"checked").rglob("*")))

    def test_traversal_and_corrupt_blobs_do_not_write_logical_files(self):
        for path, declared_hash in (("../escaped.txt", None), ("inside.txt", "0"*64)):
            with self.subTest(path=path), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                archive = self.make_archive(root, [path], b"payload", declared_hash)
                with self.assertRaises(ValueError):
                    restore(archive, root/"destination")
                self.assertFalse((root/"escaped.txt").exists())
                self.assertFalse(any(p.is_file() for p in (root/"destination").rglob("*")))

    def test_existing_model_mismatch_is_preserved_and_never_overwritten(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            target = root/"model.bin"
            target.write_bytes(b"wrong")
            metadata = root/"metadata.json"
            metadata.write_text(json.dumps({"models": [{"relative_path": "model.bin", "bytes": 5,
                "sha256": hashlib.sha256(b"right").hexdigest(),
                "url": "https://huggingface.co/Systran/example/resolve/frozen/model.bin"}]}))
            with self.assertRaisesRegex(ValueError, "no overwrite"):
                recover(root, metadata, verify_only=True)
            self.assertEqual(target.read_bytes(), b"wrong")
            target.write_bytes(b"right")
            self.assertTrue(recover(root, metadata, verify_only=True)[0]["verified"])


if __name__ == "__main__":
    unittest.main()
