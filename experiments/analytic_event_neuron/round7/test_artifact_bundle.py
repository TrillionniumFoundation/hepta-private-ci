"""Small independent fixtures for multipart integrity and extraction boundaries."""

import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import random
import tarfile
import tempfile
import unittest

from .artifact_bundle import EMPTY_SHA256, Limits, MANIFEST_NAME, PART_BYTES, SCHEMA, pack, unpack


class ArtifactBundleTests(unittest.TestCase):
    def test_multipart_roundtrip_standard_tar_and_matching_existing_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "evidence"
            (source / "nested").mkdir(parents=True)
            (source / "empty").mkdir()
            (source / "__pycache__").mkdir()
            (source / "__pycache__/ignored.pyc").write_bytes(b"cache")
            payload = random.Random(1707).randbytes(700000)
            (source / "binary.bin").write_bytes(payload)
            (source / "binary.bin").chmod(0o755)
            (source / "nested/failure.json").write_text('{"status":"failed","retained":true}\n')
            manifest = pack(source, root / "parts")
            again = pack(source, root / "parts_again")
            self.assertGreater(len(manifest["parts"]), 1)
            self.assertEqual(manifest["parts"][0]["bytes"], PART_BYTES)
            self.assertEqual(manifest["archive_sha256"], again["archive_sha256"])
            raw = b"".join((root / "parts" / part["name"]).read_bytes() for part in manifest["parts"])
            with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as independent:
                self.assertEqual(independent.extractfile("binary.bin").read(), payload)
                self.assertEqual(independent.getmember("binary.bin").mode, 0o755)
                self.assertTrue(independent.getmember("empty").isdir())
            destination = root / "restored"
            result = unpack(root / "parts", destination)
            self.assertTrue(result["all_part_archive_member_checksums_verified"])
            self.assertEqual((destination / "binary.bin").read_bytes(), payload)
            self.assertEqual((destination / "binary.bin").stat().st_mode & 0o777, 0o755)
            self.assertTrue((destination / "empty").is_dir())
            self.assertFalse((destination / "__pycache__").exists())
            unpack(root / "parts", destination)
            (destination / "nested/failure.json").write_text("existing user bytes")
            with self.assertRaisesRegex(ValueError, "existing target bytes differ"):
                unpack(root / "parts", destination)
            self.assertEqual((destination / "nested/failure.json").read_text(), "existing user bytes")

    def test_nested_output_excluded_and_source_links_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source"
            source.mkdir()
            (source / "file.txt").write_text("complete evidence")
            manifest = pack(source, source / "bundle")
            self.assertEqual([m["path"] for m in manifest["members"]], ["file.txt"])
            os.symlink(source / "file.txt", source / "linked.txt")
            with self.assertRaisesRegex(ValueError, "link"):
                pack(source, Path(directory) / "reject_link")

    def test_existing_hardlink_rejected_without_chmod_or_partial_publication(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, target = root / "source", root / "target"
            source.mkdir()
            target.mkdir()
            payload = b"same verified bytes, different inode ownership scope"
            (source / "shared.bin").write_bytes(payload)
            (source / "shared.bin").chmod(0o755)
            (source / "new.txt").write_text("must not be published after a preflight rejection")
            outside = root / "outside.bin"
            outside.write_bytes(payload)
            outside.chmod(0o600)
            os.link(outside, target / "shared.bin")
            self.assertEqual(outside.stat().st_nlink, 2)
            pack(source, root / "parts")
            with self.assertRaisesRegex(ValueError, "no hard links"):
                unpack(root / "parts", target)
            self.assertEqual(outside.stat().st_mode & 0o777, 0o600)
            self.assertEqual((target / "shared.bin").stat().st_mode & 0o777, 0o600)
            self.assertEqual(outside.read_bytes(), payload)
            self.assertFalse((target / "new.txt").exists())

    def test_part_tamper_path_tamper_and_explicit_size_limits(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            source.mkdir()
            (source / "file.txt").write_text("retained evidence")
            manifest = pack(source, root / "parts")
            part = root / "parts" / manifest["parts"][0]["name"]
            original = part.read_bytes()
            part.write_bytes(bytes([original[0] ^ 1]) + original[1:])
            with self.assertRaisesRegex(ValueError, "part checksum"):
                unpack(root / "parts", root / "not_created")
            self.assertFalse((root / "not_created").exists())
            part.write_bytes(original)
            with self.assertRaises(ValueError):
                unpack(root / "parts", root / "too_small", Limits(max_member_bytes=2))
            manifest["members"][0]["path"] = "../escaped"
            (root / "parts" / MANIFEST_NAME).write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError, "traversal"):
                unpack(root / "parts", root / "unsafe")
            self.assertFalse((root / "escaped").exists())

    def test_forged_tar_links_traversal_and_duplicates_are_never_extracted(self):
        for variant in ("symlink", "hardlink", "fifo", "traversal", "duplicate"):
            with self.subTest(variant=variant), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                bundle = root / "parts"
                bundle.mkdir()
                raw = io.BytesIO()
                with tarfile.open(fileobj=raw, mode="w", format=tarfile.USTAR_FORMAT) as archive:
                    member = tarfile.TarInfo("../outside" if variant == "traversal" else "safe")
                    member.mode, member.size = 0o644, 0
                    if variant in ("symlink", "hardlink"):
                        member.type = tarfile.SYMTYPE if variant == "symlink" else tarfile.LNKTYPE
                        member.linkname = "../outside"
                    elif variant == "fifo":
                        member.type = tarfile.FIFOTYPE
                    archive.addfile(member)
                    if variant == "duplicate":
                        archive.addfile(member)
                compressed = gzip.compress(raw.getvalue(), mtime=0)
                digest = hashlib.sha256(compressed).hexdigest()
                (bundle / "part-00000.bin").write_bytes(compressed)
                manifest = {
                    "schema": SCHEMA, "archive_format": "ustar+gzip", "part_bytes": PART_BYTES,
                    "archive_bytes": len(compressed), "archive_sha256": digest,
                    "parts": [{"name": "part-00000.bin", "bytes": len(compressed), "sha256": digest}],
                    "member_count": 1, "unpacked_file_bytes": 0,
                    "members": [{"path": "safe", "kind": "file", "bytes": 0,
                                 "sha256": EMPTY_SHA256, "mode": 0o644}],
                }
                (bundle / MANIFEST_NAME).write_text(json.dumps(manifest))
                with self.assertRaises(ValueError):
                    unpack(bundle, root / "target")
                self.assertFalse((root / "target").exists())
                self.assertFalse((root / "outside").exists())


if __name__ == "__main__":
    unittest.main()
