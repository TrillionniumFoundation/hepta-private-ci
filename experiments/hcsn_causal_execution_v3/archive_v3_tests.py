"""Evidence restoration must verify bytes and reject unsafe filesystem writes."""

import hashlib
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest import mock

from .archive_v3 import pack, relative, restore
from . import archive_v3


class EvidenceArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="hcsn_archive_test_")
        self.root = Path(self.temp.name)
        (self.root / "source/results").mkdir(parents=True)
        (self.root / "source/results/bytes.bin").write_bytes(bytes(range(256)) * 900)
        self.manifest = pack(self.root / "source", ["results"], self.root / "archive", "test")

    def tearDown(self):
        self.temp.cleanup()

    def test_roundtrip_idempotence_and_different_content_refusal(self):
        destination = self.root / "destination"
        self.assertEqual(restore(self.manifest, destination)["written"], 1)
        self.assertEqual(restore(self.manifest, destination)["identical_existing"], 1)
        target = destination / "results/bytes.bin"
        target.write_bytes(b"keep different user bytes")
        with self.assertRaises(FileExistsError):
            restore(self.manifest, destination)
        self.assertEqual(target.read_bytes(), b"keep different user bytes")

    def test_bad_part_hash_rejected_before_any_restore(self):
        data = json.loads(self.manifest.read_text())
        part = self.manifest.parent / data["parts"][0]["path"]
        part.write_bytes(part.read_bytes()[:-1] + b"X")
        with self.assertRaises(ValueError):
            restore(self.manifest, self.root / "destination")
        self.assertFalse((self.root / "destination").exists())

    def test_unsafe_path_forms_rejected(self):
        for name in ("../escape", "/absolute", "a/../../escape", "a//b", "a\\b", "C:/x", "."):
            with self.assertRaises(ValueError, msg=name):
                relative(name)

    def test_existing_symlink_directory_rejected(self):
        (self.root / "outside").mkdir()
        (self.root / "destination").mkdir()
        (self.root / "destination/results").symlink_to(self.root / "outside", target_is_directory=True)
        with self.assertRaises(ValueError):
            restore(self.manifest, self.root / "destination")
        self.assertEqual(list((self.root / "outside").iterdir()), [])

    def test_archive_symlink_and_hardlink_rejected(self):
        for kind in (tarfile.SYMTYPE, tarfile.LNKTYPE):
            data = json.loads(self.manifest.read_text())
            memory = io.BytesIO()
            with tarfile.open(fileobj=memory, mode="w:xz") as tar:
                info = tarfile.TarInfo("results/bytes.bin")
                info.type, info.linkname = kind, "../../escape"
                tar.addfile(info)
            blob = memory.getvalue()
            part_name = "malicious.part"
            (self.manifest.parent / part_name).write_bytes(blob)
            digest = hashlib.sha256(blob).hexdigest()
            data.update(parts=[dict(path=part_name, bytes=len(blob), sha256=digest)],
                        compressed_bytes=len(blob), archive_sha256=digest)
            altered = self.root / "archive/altered.json"
            altered.write_text(json.dumps(data))
            with self.assertRaises(ValueError):
                restore(altered, self.root / "destination")
            self.assertFalse((self.root / "destination").exists())

    def test_new_source_member_during_pack_is_not_silently_omitted(self):
        original_digest = archive_v3.digest

        def add_member_after_snapshot(path):
            if Path(path).name.endswith(".working.tar.xz"):
                (self.root / "source/results/new.txt").write_text("late evidence")
            return original_digest(path)

        with mock.patch.object(archive_v3, "digest", side_effect=add_member_after_snapshot):
            with self.assertRaises(ValueError):
                pack(self.root / "source", ["results"], self.root / "changed", "changed")
        self.assertFalse((self.root / "changed/changed.json").exists())


if __name__ == "__main__":
    unittest.main()
