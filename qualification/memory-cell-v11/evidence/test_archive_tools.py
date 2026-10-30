"""Round-trip, determinism, corruption, and adversarial tar restoration tests."""

import base64
import hashlib
import io
import json
import os
from pathlib import Path
import tarfile
import tempfile
import unittest

from pack import directory_archive, package_archive
from restore import CHUNK_BYTES, SCHEMA, canonical_json, inspect_archive, relative_name, restore, sha256_file


class EvidenceArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def test_reproducible_metadata_and_full_roundtrip(self):
        source = self.root / "source"
        (source / "nested").mkdir(parents=True)
        (source / "nested" / "optimizer.pt").write_bytes(os.urandom(300_000))
        (source / "negative.json").write_text('{"admitted":false}\n')
        first, second = self.root / "first.tar.xz", self.root / "second.tar.xz"
        inventory = directory_archive(source, first)
        os.utime(source / "negative.json", (2_000_000, 2_000_000))
        (source / "negative.json").chmod(0o600)
        directory_archive(source, second)
        self.assertEqual(sha256_file(first), sha256_file(second))
        package = self.root / "package"
        wrapped = package_archive(first, package)
        self.assertGreater(wrapped["parts"], 1)
        output = self.root / "restored"
        result = restore(package, output)
        self.assertEqual((result["files_verified"], result["file_bytes_verified"]),
                         (inventory["file_count"], inventory["total_file_bytes"]))
        self.assertEqual((output / "nested" / "optimizer.pt").read_bytes(), (source / "nested" / "optimizer.pt").read_bytes())
        self.assertEqual((output / "negative.json").read_bytes(), (source / "negative.json").read_bytes())
        self.assertEqual(restore(package, verify_only=True)["archive_sha256"], sha256_file(first))

    def test_part_corruption_never_publishes_output(self):
        source = self.root / "source"
        source.mkdir()
        (source / "evidence").write_bytes(b"negative result")
        archive = self.root / "evidence.tar.xz"
        directory_archive(source, archive)
        package = self.root / "package"
        package_archive(archive, package)
        part = package / "part-00000.b64"
        text = part.read_bytes()
        part.write_bytes((b"A" if text[:1] != b"A" else b"B") + text[1:])
        output = self.root / "restored"
        with self.assertRaises(ValueError):
            restore(package, output)
        self.assertFalse(output.exists())

    def malicious_package(self, archive, inventory, name):
        package = self.root / name
        package.mkdir()
        data = archive.read_bytes()
        part = base64.b64encode(data) + b"\n"
        inventory_bytes = canonical_json(inventory)
        (package / "part-00000.b64").write_bytes(part)
        (package / "INVENTORY.json").write_bytes(inventory_bytes)
        manifest = dict(schema=SCHEMA, chunk_bytes=CHUNK_BYTES,
                        archive=dict(bytes=len(data), sha256=hashlib.sha256(data).hexdigest()),
                        inventory=dict(path="INVENTORY.json", sha256=hashlib.sha256(inventory_bytes).hexdigest()),
                        parts=[dict(path="part-00000.b64", binary_bytes=len(data), binary_sha256=hashlib.sha256(data).hexdigest(),
                                    text_bytes=len(part), text_sha256=hashlib.sha256(part).hexdigest())])
        (package / "MANIFEST.json").write_bytes(canonical_json(manifest))
        return package

    def test_restore_rejects_escaping_paths_before_writing(self):
        archive = self.root / "escape.tar.xz"
        with tarfile.open(archive, "w:xz") as tar:
            entry = tarfile.TarInfo("../escaped")
            entry.size = 4
            tar.addfile(entry, io.BytesIO(b"oops"))
        inventory = dict(schema="hepta.evidence.file-inventory.v1", file_count=1, directory_count=0,
                         total_file_bytes=4, members=[dict(path="../escaped", type="file", bytes=4,
                                                         sha256=hashlib.sha256(b"oops").hexdigest())])
        package = self.malicious_package(archive, inventory, "malicious")
        with self.assertRaises(ValueError):
            restore(package, self.root / "output")
        self.assertFalse((self.root / "escaped").exists())
        self.assertFalse((self.root / "output").exists())
        for name in ("/absolute", "C:/absolute", "a/../b", "a//b", "a\\b", "./a"):
            with self.assertRaises(ValueError):
                relative_name(name)

    def test_links_and_devices_are_not_packable_or_restorable(self):
        for index, kind in enumerate((tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.CHRTYPE)):
            archive = self.root / f"special-{index}.tar.xz"
            with tarfile.open(archive, "w:xz") as tar:
                entry = tarfile.TarInfo("special")
                entry.type = kind
                entry.linkname = "../outside"
                tar.addfile(entry)
            with self.assertRaises(ValueError):
                inspect_archive(archive)
        source = self.root / "source"
        source.mkdir()
        (source / "external").symlink_to(self.root / "special-0.tar.xz")
        with self.assertRaises(ValueError):
            directory_archive(source, self.root / "refused.tar.xz")


if __name__ == "__main__":
    unittest.main()
