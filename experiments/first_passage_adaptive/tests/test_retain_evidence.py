import gzip
import hashlib
import io
import json
from pathlib import Path
import random
import tarfile
import tempfile
import unittest

from experiments.first_passage_adaptive import retain_evidence as retained


class EvidenceTransportTests(unittest.TestCase):
    def fixture(self, root):
        (root/"evidence"/"nested").mkdir(parents=True)
        (root/"evidence"/"nested"/"raw.gz").write_bytes(random.Random(8761).randbytes(600123))
        (root/"evidence"/"checkpoint.json").write_text('{"parameters":[0.2,0.8,0.4]}\n')
        (root/"evidence"/"journal.bin").write_bytes(b"native-journal\x00\xff")
        (root/"evidence"/"not-evidence.exe").write_bytes(b"must not be discovered")
        (root/"evidence"/"build").mkdir()
        (root/"evidence"/"build"/"binary").write_bytes(b"unselected build output")
        return retained.pack(root,["evidence"])

    def test_deterministic_bounded_pieces_and_fresh_restore(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first,second = self.fixture(root/"first"),self.fixture(root/"second")
            a,b = retained.load_manifest(first["manifest"]),retained.load_manifest(second["manifest"])
            self.assertEqual(a["archive"],b["archive"])
            self.assertEqual(a["pieces"],b["pieces"])
            self.assertGreater(len(a["pieces"]),2)
            self.assertTrue(all(row["bytes"] <= 256000 for row in a["pieces"]))
            self.assertEqual({row["path"] for row in a["files"]},
                             {"evidence/checkpoint.json","evidence/journal.bin","evidence/nested/raw.gz"})
            destination = root/"fresh"
            restored = retained.restore(destination,first["manifest"])
            self.assertEqual(restored["created"],3)
            again = retained.restore(destination,first["manifest"])
            self.assertEqual((again["created"],again["already_identical"]),(0,3))
            self.assertTrue(retained.check(destination,first["manifest"],include_restored=True)["restored_verified"])
            self.assertEqual((destination/"evidence/journal.bin").read_bytes(),b"native-journal\x00\xff")
            self.assertTrue((root/"first/evidence/nested/raw.gz").is_file())

    def test_conflict_does_not_overwrite_or_partially_restore(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            packed = self.fixture(root/"source")
            destination = root/"destination"
            (destination/"evidence").mkdir(parents=True)
            conflict = destination/"evidence/journal.bin"
            conflict.write_bytes(b"existing independent evidence")
            with self.assertRaises(FileExistsError):
                retained.restore(destination,packed["manifest"])
            self.assertEqual(conflict.read_bytes(),b"existing independent evidence")
            self.assertFalse((destination/"evidence/checkpoint.json").exists())

    def test_corrupted_piece_rejected_and_restored_only_check_supported(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            packed = self.fixture(root/"source")
            destination = root/"destination"
            retained.restore(destination,packed["manifest"])
            manifest = retained.load_manifest(packed["manifest"])
            piece = Path(packed["manifest"]).parent/manifest["pieces"][0]["path"]
            data = bytearray(piece.read_bytes())
            data[len(data)//2] ^= 1
            piece.write_bytes(data)
            with self.assertRaisesRegex(ValueError,"piece hash"):
                retained.check(destination,packed["manifest"])
            self.assertTrue(retained.check(destination,packed["manifest"],restored_only=True)["restored_verified"])

    def test_symlink_inputs_and_restore_ancestors_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            packed = self.fixture(root/"source")
            (root/"source/evidence/link").symlink_to(root/"source/evidence/checkpoint.json")
            with self.assertRaises(ValueError):
                retained.pack(root/"source",["evidence/link"],output="another-bundle")
            destination = root/"destination"
            destination.mkdir()
            (destination/"evidence").symlink_to(root/"source/evidence",target_is_directory=True)
            with self.assertRaises(ValueError):
                retained.restore(destination,packed["manifest"])

    def test_hostile_archive_paths_and_links_are_rejected_before_extraction(self):
        cases = [("../escape",tarfile.REGTYPE),("/absolute",tarfile.REGTYPE),
                 ("evidence/item",tarfile.SYMTYPE),("evidence/item",tarfile.LNKTYPE)]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for index,(name,kind) in enumerate(cases):
                folder = root/str(index)
                folder.mkdir()
                stream = io.BytesIO()
                with gzip.GzipFile(fileobj=stream,mode="wb",mtime=0) as compressed:
                    with tarfile.open(fileobj=compressed,mode="w") as archive:
                        info = tarfile.TarInfo(name)
                        info.type = kind
                        if kind != tarfile.REGTYPE:
                            info.linkname = "../escape"
                        archive.addfile(info,io.BytesIO(b""))
                payload = stream.getvalue()
                digest = hashlib.sha256(payload).hexdigest()
                (folder/"hostile.part000").write_bytes(payload)
                manifest = {"schema":retained.SCHEMA,"name":"hostile","piece_limit":256000,
                    "archive":{"format":"tar.gz","bytes":len(payload),"sha256":digest},
                    "pieces":[{"path":"hostile.part000","bytes":len(payload),"sha256":digest}],
                    "files":[{"path":"evidence/item","bytes":0,"sha256":hashlib.sha256(b"").hexdigest()}],
                    "total_file_bytes":0}
                path = folder/"manifest.json"
                path.write_text(json.dumps(manifest))
                with self.assertRaises(ValueError):
                    retained.restore(folder/"restored",path)
                self.assertFalse((root/"escape").exists())

    def test_manifest_traversal_and_duplicate_files_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            packed = self.fixture(Path(temporary)/"source")
            path = Path(packed["manifest"])
            original = json.loads(path.read_text())
            original["files"][0]["path"] = "evidence/../escape"
            path.write_text(json.dumps(original))
            with self.assertRaises(ValueError):
                retained.load_manifest(path)


if __name__ == "__main__":
    unittest.main()
