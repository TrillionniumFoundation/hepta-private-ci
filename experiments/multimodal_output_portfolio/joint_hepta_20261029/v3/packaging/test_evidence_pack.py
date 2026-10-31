"""Round-trip, live-tree mutation, corruption and malicious archive checks."""

import io
import json
import lzma
import os
from pathlib import Path
import random
import tarfile
import tempfile
import unittest
from unittest.mock import patch

from . import evidence_pack as ep


def hostile_bundle(path, *, relative="value.bin", duplicate=False, symlink=False):
    """Self-consistent hashes ensure tests exercise extraction validation itself."""
    path.mkdir()
    entry = {"path": relative, "type": "file", "size": 3, "mode": 0o644, "sha256": ep.digest(b"raw")}
    manifest = ep.json_bytes({"schema": ep.SCHEMA, "root_name": "source", "root_mode": 0o755, "entries": [entry]})
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w", format=tarfile.PAX_FORMAT) as archive:
        archive.addfile(ep.tar_info(ep.MANIFEST_NAME, {"type": "file", "size": len(manifest), "mode": 0o644}), io.BytesIO(manifest))
        archive.addfile(ep.tar_info("payload", {"type": "directory", "size": 0, "mode": 0o755}))
        member = ep.tar_info("payload/" + relative, entry)
        if symlink:
            member.type, member.linkname, member.size = tarfile.SYMTYPE, "../../outside", 0
        archive.addfile(member, None if symlink else io.BytesIO(b"raw"))
        if duplicate:
            archive.addfile(member, io.BytesIO(b"raw"))
    writer = ep.ChunkWriter(path)
    writer.write(lzma.compress(raw.getvalue(), preset=0))
    writer.emit()
    page = ep.json_bytes({"schema": ep.SCHEMA, "chunks": writer.records})
    ep.write_new(path / "CHUNKS-000000.json", page)
    ep.write_new(path / "INDEX.json", ep.json_bytes({"schema": ep.SCHEMA, "format": "tar.xz", "chunk_bytes": ep.CHUNK_BYTES,
        "chunk_pages": [{"path": "CHUNKS-000000.json", "size": len(page), "sha256": ep.digest(page), "count": len(writer.records)}],
        "chunk_count": len(writer.records), "archive_bytes": writer.size, "archive_sha256": writer.hasher.hexdigest(),
        "manifest": {"path": ep.MANIFEST_NAME, "size": len(manifest), "sha256": ep.digest(manifest)},
        "root_name": "source", "file_count": 1, "directory_count": 0, "file_bytes": 3, "member_count": 3}))


class EvidencePackagingTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.source = self.root / "source"
        self.source.mkdir()
        (self.source / "empty").mkdir()
        (self.source / "nested").mkdir()
        (self.source / "nested/weights.pt").write_bytes(random.Random(19).randbytes(900000))
        (self.source / "SEAL.json").write_bytes(b'{"actual":true}\n')

    def tearDown(self):
        self.temporary.cleanup()

    def test_exact_deterministic_multichunk_roundtrip(self):
        first = ep.pack(self.source, self.root / "first", preset=0)
        os.utime(self.source / "SEAL.json", (17, 19))
        second = ep.pack(self.source, self.root / "second", preset=0)
        self.assertEqual((first["archive_sha256"], first["index_sha256"]),
                         (second["archive_sha256"], second["index_sha256"]))
        self.assertGreater(first["chunk_count"], 1)
        self.assertTrue(all(p.stat().st_size <= ep.CHUNK_BYTES for p in (self.root / "first").iterdir()))
        restored = self.root / "restored"
        ep.unpack(self.root / "first", restored, first["index_sha256"])
        original_entries, _ = ep.scan(self.source, True)
        restored_entries, _ = ep.scan(restored, True)
        self.assertEqual(original_entries, restored_entries)

    def test_corrupted_chunk_rejected_before_destination_creation(self):
        ep.pack(self.source, self.root / "bundle", preset=0)
        chunk = self.root / "bundle/archive.part-000000.bin"
        data = bytearray(chunk.read_bytes()); data[len(data) // 2] ^= 1; chunk.write_bytes(data)
        with self.assertRaisesRegex(ValueError, "integrity mismatch"):
            ep.unpack(self.root / "bundle", self.root / "restored")
        self.assertFalse((self.root / "restored").exists())

    def test_trusted_index_and_existing_destinations_are_enforced(self):
        ep.pack(self.source, self.root / "bundle", preset=0)
        with self.assertRaisesRegex(ValueError, "Trusted root"):
            ep.verify(self.root / "bundle", "0" * 64)
        existing = self.root / "existing"; existing.mkdir(); (existing / "keep").write_bytes(b"unchanged")
        with self.assertRaises(FileExistsError):
            ep.unpack(self.root / "bundle", existing)
        with self.assertRaises(FileExistsError):
            ep.pack(self.source, self.root / "bundle")
        self.assertEqual((existing / "keep").read_bytes(), b"unchanged")

    def test_self_consistent_traversal_duplicate_and_symlink_archives_rejected(self):
        for number, options in enumerate(({"relative": "../../escape"}, {"duplicate": True}, {"symlink": True})):
            with self.subTest(options=options):
                bundle, destination = self.root / f"bad-{number}", self.root / f"out-{number}"
                hostile_bundle(bundle, **options)
                with self.assertRaises(ValueError):
                    ep.unpack(bundle, destination)
                self.assertFalse(destination.exists())
                self.assertFalse((self.root / "escape").exists())

    def test_source_symlink_rejected_without_following(self):
        try:
            (self.source / "link").symlink_to(self.root / "outside")
        except (NotImplementedError, OSError):
            self.skipTest("Symlink creation is unavailable")
        with self.assertRaisesRegex(ValueError, "Symlinks"):
            ep.pack(self.source, self.root / "bundle")

    def test_new_source_file_during_pack_invalidates_bundle(self):
        original = ep.HashingReader.read
        added = False
        def read_and_add(reader, size=-1):
            nonlocal added
            if not added:
                (self.source / "late.json").write_bytes(b"late evidence")
                added = True
            return original(reader, size)
        with patch.object(ep.HashingReader, "read", read_and_add):
            with self.assertRaisesRegex(ValueError, "Source tree changed"):
                ep.pack(self.source, self.root / "bundle", preset=0)
        self.assertFalse((self.root / "bundle/INDEX.json").exists())
        self.assertEqual((self.source / "late.json").read_bytes(), b"late evidence")


if __name__ == "__main__":
    unittest.main()
