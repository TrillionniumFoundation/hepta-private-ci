"""Exercise corruption, path confinement and frozen evidence reconstruction."""

import copy
import json
from pathlib import Path
import random
import tempfile
import unittest
import zipfile

from . import transport


class TransportTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / "source"
        frozen = self.source / "frozen"
        frozen.mkdir(parents=True)
        self.archive = frozen / "training.zip"
        generator, members = random.Random(23), []
        with zipfile.ZipFile(self.archive, "w", compression=zipfile.ZIP_STORED) as archive:
            for number in range(2):
                data, name = generator.randbytes(260_000), f"run/data{number}.bin"
                archive.writestr(name, data)
                members.append(dict(path=name, size=len(data), sha256=transport.sha256(data)))
        data = self.archive.read_bytes()
        original = dict(file=self.archive.name, size=len(data),
                        sha256=transport.sha256(data), members=members)
        (frozen / "INDEX.json").write_text(json.dumps(dict(archives=[original])))
        self.package, self.destination = self.root / "package", self.root / "restored"
        self.manifest = transport.pack(self.source, ["frozen/INDEX.json"], self.package, "a" * 40)
        self.index = self.package / "MANIFEST.json"

    def rewrite(self, manifest):
        self.index.write_text(json.dumps(manifest))

    def test_roundtrip_and_identical_existing_file(self):
        expected = dict(restored_archives=1, verified_members=2,
                        original_git_blobs_verified=True, byte_identities_verified=True)
        for _ in range(2):
            self.assertEqual(transport.restore(self.index, self.destination), expected)
        self.assertEqual((self.destination / "frozen/training.zip").read_bytes(), self.archive.read_bytes())
        for chunk in self.manifest["archives"][0]["chunks"]:
            data = (self.package / chunk["file"]).read_bytes()
            self.assertEqual(data[:3], b"\x1f\x8b\x08")
            self.assertLess(len(data), 500_000)

    def test_corrupt_container_rejected_before_output(self):
        chunk = self.package / self.manifest["archives"][0]["chunks"][0]["file"]
        data = bytearray(chunk.read_bytes())
        data[-8] ^= 1
        chunk.write_bytes(data)
        with self.assertRaises(ValueError):
            transport.restore(self.index, self.destination)
        self.assertFalse(self.destination.exists())

    def test_path_traversal_and_alternate_syntax_rejected(self):
        for bad in ("../outside.zip", "/absolute.zip", "C:/outside.zip", "frozen\\bad.zip"):
            with self.subTest(path=bad):
                manifest = copy.deepcopy(self.manifest)
                manifest["archives"][0]["source_path"] = bad
                self.rewrite(manifest)
                with self.assertRaises(ValueError):
                    transport.restore(self.index, self.destination)
        manifest = copy.deepcopy(self.manifest)
        manifest["archives"][0]["chunks"][0]["file"] = "../outside.gz"
        self.rewrite(manifest)
        with self.assertRaises(ValueError):
            transport.restore(self.index, self.destination)

    def test_symlink_escape_rejected(self):
        self.destination.mkdir()
        outside = self.root / "outside"
        outside.mkdir()
        try:
            (self.destination / "frozen").symlink_to(outside, target_is_directory=True)
        except OSError as error:
            self.skipTest(f"Symlink creation unavailable: {error}")
        with self.assertRaises(ValueError):
            transport.restore(self.index, self.destination)
        self.assertEqual(list(outside.iterdir()), [])

    def test_different_existing_bytes_are_not_overwritten(self):
        target = self.destination / "frozen/training.zip"
        target.parent.mkdir(parents=True)
        target.write_bytes(b"keep existing")
        with self.assertRaises(FileExistsError):
            transport.restore(self.index, self.destination)
        self.assertEqual(target.read_bytes(), b"keep existing")

    def test_member_and_original_hashes_are_verified(self):
        for key in ("member", "sha256", "source_git_blob"):
            with self.subTest(field=key):
                manifest = copy.deepcopy(self.manifest)
                entry = manifest["archives"][0]
                if key == "member":
                    entry["members"][0]["sha256"] = "0" * 64
                else:
                    entry[key] = "0" * len(entry[key])
                self.rewrite(manifest)
                with self.assertRaises(ValueError):
                    transport.restore(self.index, self.destination)
                self.assertFalse(self.destination.exists())

    def test_decompression_is_bounded(self):
        manifest = copy.deepcopy(self.manifest)
        manifest["archives"][0]["chunks"][0]["raw_size"] = transport.RAW_CHUNK_BYTES + 1
        self.rewrite(manifest)
        with self.assertRaises(ValueError):
            transport.restore(self.index, self.destination)

    def test_shipped_frozen_archives_roundtrip(self):
        shipped = Path(__file__).with_name("transport_evidence") / "MANIFEST.json"
        manifest = json.loads(shipped.read_bytes())
        repository = Path(__file__).resolve().parents[3]
        original_root = Path("tools/hcsn/task_aligned_r14_20261101")
        expected = {}
        for directory in ("archives", "development_archives"):
            index_path = original_root / directory / "TRAINING_ARCHIVES.json"
            original = json.loads((repository / index_path).read_bytes())
            for archive in original["archives"]:
                if archive["size"] >= transport.STRICT_BLOB_LIMIT:
                    path = (index_path.parent / archive["file"]).as_posix()
                    expected[path] = {key: archive[key] for key in ("size", "sha256", "members")}
        actual = {item["source_path"]: {key: item[key] for key in ("size", "sha256", "members")}
                  for item in manifest["archives"]}
        self.assertEqual(actual, expected)
        result = transport.restore(shipped, self.destination)
        self.assertEqual(result["restored_archives"], len(manifest["archives"]))
        self.assertEqual(result["verified_members"], sum(len(item["members"]) for item in manifest["archives"]))
        for index in manifest["frozen_indexes"]:
            data = (repository / index["path"]).read_bytes()
            self.assertEqual(transport.sha256(data), index["sha256"])
            self.assertEqual(transport.git_blob(data), index["git_blob"])


if __name__ == "__main__":
    unittest.main()
