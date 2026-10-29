"""Compatibility and integrity tests for the low-disk multipart archive path.

Run from the repository root:
    python -m experiments.hcsn_free_boundary_v1.archive_tests

All files are small synthetic fixtures in a TemporaryDirectory. Real archives
and research results are never changed by this suite.
"""
import hashlib
import io
import json
import lzma
from pathlib import Path
import random
import tarfile
import tempfile
import unittest
from unittest.mock import patch

from . import archive


def legacy_pack(root, destination, name, part_bytes=1048576):
    """Original pre-streaming pack, retained as the byte-compatibility oracle."""
    root, destination = Path(root).resolve(), Path(destination)
    if part_bytes < 4096 or not root.is_dir() or not name.replace("_", "").isalnum():
        raise ValueError("Require existing root, simple bundle name, and part size >=4096")
    destination.mkdir(parents=True, exist_ok=True)
    manifest_path = destination / f"{name}.json"
    if manifest_path.exists() or list(destination.glob(f"{name}.tar.xz.part*")):
        raise FileExistsError("Archive bundle already exists; preserve previous evidence")
    files = sorted(path for path in root.rglob("*")
                   if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc")
    if any(path.is_symlink() for path in files):
        raise ValueError("Symlinks are not accepted as evidence members")
    members = [{"path": path.relative_to(root).as_posix(), "bytes": path.stat().st_size,
                "sha256": archive.sha256(path)} for path in files]
    parts, whole = [], hashlib.sha256()
    with tempfile.TemporaryFile() as temporary:
        with lzma.LZMAFile(temporary, "w", preset=6) as compressed:
            with tarfile.open(fileobj=compressed, mode="w|") as tar:
                for path, record in zip(files, members, strict=True):
                    info = tarfile.TarInfo(record["path"])
                    info.size, info.mode, info.mtime = record["bytes"], 0o644, 0
                    with path.open("rb") as source:
                        tar.addfile(info, source)
        temporary.seek(0)
        index = 0
        while block := temporary.read(part_bytes):
            part_path = destination / f"{name}.tar.xz.part{index:04d}"
            part_path.write_bytes(block)
            whole.update(block)
            parts.append({"path": part_path.name, "bytes": len(block),
                          "sha256": hashlib.sha256(block).hexdigest(),
                          "git_blob_sha1": hashlib.sha1(
                              b"blob " + str(len(block)).encode() + b"\0" + block).hexdigest()})
            index += 1
    if any(archive.sha256(path) != record["sha256"] for path, record in zip(files, members, strict=True)):
        raise ValueError("An input changed while packing; do not publish this incomplete bundle")
    manifest = {"schema": "hcsn-evidence-bundle.v1", "name": name,
                "format": "deterministic POSIX tar, xz, concatenated parts in declared order",
                "archive_sha256": whole.hexdigest(), "parts": parts, "members": members,
                "uncompressed_file_bytes": sum(row["bytes"] for row in members),
                "compressed_bytes": sum(row["bytes"] for row in parts)}
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return manifest


class ArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="hcsn-archive-unit-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def bundle(self, count=14017, nested=False):
        source = self.root / "source"
        source.mkdir()
        target = source / "nested/payload.bin" if nested else source / "payload.bin"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(random.Random(731).randbytes(count))
        output = self.root / "bundle"
        manifest = archive.pack(source, output, "fixture", part_bytes=4096)
        return source, output / "fixture.json", manifest

    def write_manifest(self, path, value):
        path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")

    def test_old_pack_exact_bytes_and_manifest_at_small_and_default_part_sizes(self):
        source = self.root / "source"
        source.mkdir()
        (source / "random.bin").write_bytes(random.Random(194).randbytes(1100123))
        (source / "empty").write_bytes(b"")
        long_name = source / ("path_" + "long" * 30) / "unicode_数据.txt"
        long_name.parent.mkdir()
        long_name.write_text("deterministic tar metadata\n" * 37)
        (source / "__pycache__").mkdir()
        (source / "__pycache__/ignored.py").write_text("ignored")
        (source / "ignored.pyc").write_bytes(b"ignored")
        for size in (4096, 1048576):
            with self.subTest(part_bytes=size):
                old_dir = self.root / f"old_{size}"
                new_dir = self.root / f"new_{size}"
                expected = legacy_pack(source, old_dir, "same", size)
                with patch.object(archive.tempfile, "TemporaryFile", side_effect=AssertionError("pack must not spool compressed archive")):
                    actual = archive.pack(source, new_dir, "same", size)
                self.assertEqual(actual, expected)
                self.assertEqual((new_dir / "same.json").read_bytes(), (old_dir / "same.json").read_bytes())
                self.assertGreater(len(actual["parts"]), 1)
                for part in expected["parts"]:
                    self.assertEqual((new_dir / part["path"]).read_bytes(), (old_dir / part["path"]).read_bytes())

    def test_new_restore_and_identical_existing_need_no_archive_or_member_spool(self):
        source, manifest, _ = self.bundle(nested=True)
        target = self.root / "restored"
        result = archive.restore(manifest, target)
        self.assertEqual(result["restored_or_already_identical"], 1)
        path = target / "nested/payload.bin"
        self.assertEqual(path.read_bytes(), (source / "nested/payload.bin").read_bytes())
        before = (path.stat().st_ino, path.stat().st_mtime_ns)
        with patch.object(archive.tempfile, "TemporaryFile", side_effect=AssertionError("identical existing restore must not spool")):
            self.assertEqual(archive.restore(manifest, target), result)
        self.assertEqual((path.stat().st_ino, path.stat().st_mtime_ns), before)

    def test_tampered_last_part_rejected_before_any_extraction(self):
        _, manifest_path, manifest = self.bundle()
        last = manifest_path.parent / manifest["parts"][-1]["path"]
        contents = bytearray(last.read_bytes())
        contents[len(contents) // 2] ^= 1
        last.write_bytes(contents)
        target = self.root / "restored"
        with self.assertRaisesRegex(ValueError, "Corrupt archive part"):
            archive.restore(manifest_path, target)
        self.assertFalse(target.exists())

    def test_whole_archive_hash_rejected_before_any_extraction(self):
        _, manifest_path, manifest = self.bundle()
        manifest["archive_sha256"] = "0" * 64
        self.write_manifest(manifest_path, manifest)
        target = self.root / "restored"
        with self.assertRaisesRegex(ValueError, "Whole archive hash mismatch"):
            archive.restore(manifest_path, target)
        self.assertFalse(target.exists())

    def test_member_checksum_checked_before_final_path_write(self):
        _, manifest_path, manifest = self.bundle()
        manifest["members"][0]["sha256"] = "0" * 64
        self.write_manifest(manifest_path, manifest)
        target = self.root / "restored"
        with self.assertRaisesRegex(ValueError, "Member checksum mismatch"):
            archive.restore(manifest_path, target)
        self.assertFalse((target / "payload.bin").exists())

    def test_different_existing_file_rejected_and_not_modified(self):
        _, manifest, _ = self.bundle()
        target = self.root / "restored"
        archive.restore(manifest, target)
        path = target / "payload.bin"
        path.write_bytes(b"existing different content")
        with self.assertRaises(FileExistsError):
            archive.restore(manifest, target)
        self.assertEqual(path.read_bytes(), b"existing different content")

    def test_unsafe_declared_member_and_part_paths_rejected(self):
        _, manifest_path, base = self.bundle()
        for name in ("../escape", "/absolute", "nested/../../escape", "bad\\name", ""):
            with self.subTest(member=name):
                manifest = json.loads(json.dumps(base))
                manifest["members"][0]["path"] = name
                self.write_manifest(manifest_path, manifest)
                with self.assertRaises(ValueError):
                    archive.restore(manifest_path, self.root / "restored")
        for name in ("../part", "nested/part", "/part", "bad\\part"):
            with self.subTest(part=name):
                manifest = json.loads(json.dumps(base))
                manifest["parts"][0]["path"] = name
                self.write_manifest(manifest_path, manifest)
                with self.assertRaises(ValueError):
                    archive.restore(manifest_path, self.root / "restored")
        self.assertFalse((self.root / "restored").exists())

    def test_existing_parent_symlink_cannot_escape_destination(self):
        _, manifest, _ = self.bundle(nested=True)
        target, outside = self.root / "restored", self.root / "outside"
        target.mkdir()
        outside.mkdir()
        (target / "nested").symlink_to(outside, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "escapes"):
            archive.restore(manifest, target)
        self.assertFalse((outside / "payload.bin").exists())

    def custom_tar(self, members, expected):
        output = self.root / "custom"
        output.mkdir()
        buffer = io.BytesIO()
        with lzma.LZMAFile(buffer, "w", preset=6) as compressed:
            with tarfile.open(fileobj=compressed, mode="w|") as tar:
                for info, contents in members:
                    tar.addfile(info, io.BytesIO(contents) if contents is not None else None)
        block = buffer.getvalue()
        path = output / "custom.part"
        path.write_bytes(block)
        manifest = {"schema": "hcsn-evidence-bundle.v1", "parts": [{"path": path.name,
                    "bytes": len(block), "sha256": hashlib.sha256(block).hexdigest()}],
                    "archive_sha256": hashlib.sha256(block).hexdigest(), "members": expected}
        manifest_path = output / "manifest.json"
        self.write_manifest(manifest_path, manifest)
        return manifest_path

    def test_nonregular_tar_member_rejected(self):
        info = tarfile.TarInfo("payload")
        info.type = tarfile.SYMTYPE
        info.linkname = "../../outside"
        manifest = self.custom_tar([(info, None)], [{"path": "payload", "bytes": 0,
                    "sha256": hashlib.sha256(b"").hexdigest()}])
        target = self.root / "restored"
        with self.assertRaisesRegex(ValueError, "non-regular"):
            archive.restore(manifest, target)
        self.assertFalse(target.exists())

    def test_duplicate_tar_members_rejected(self):
        info = tarfile.TarInfo("payload")
        info.size = 1
        expected = [{"path": "payload", "bytes": 1, "sha256": hashlib.sha256(b"x").hexdigest()}]
        manifest = self.custom_tar([(info, b"x"), (info, b"x")], expected)
        with self.assertRaisesRegex(ValueError, "duplicate"):
            archive.restore(manifest, self.root / "restored")

    def test_unexpected_tar_member_rejected(self):
        info = tarfile.TarInfo("not_declared")
        info.size = 1
        expected = [{"path": "declared", "bytes": 1, "sha256": hashlib.sha256(b"x").hexdigest()}]
        manifest = self.custom_tar([(info, b"x")], expected)
        target = self.root / "restored"
        with self.assertRaisesRegex(ValueError, "Unexpected"):
            archive.restore(manifest, target)
        self.assertFalse(target.exists())

    def test_member_size_mismatch_rejected(self):
        _, manifest_path, manifest = self.bundle()
        manifest["members"][0]["bytes"] += 1
        self.write_manifest(manifest_path, manifest)
        with self.assertRaisesRegex(ValueError, "Member size mismatch"):
            archive.restore(manifest_path, self.root / "restored")
        self.assertFalse((self.root / "restored").exists())

    def test_bundle_overwrite_and_pack_symlinks_rejected(self):
        source, manifest, original = self.bundle()
        before = {path.name: path.read_bytes() for path in manifest.parent.iterdir()}
        with self.assertRaises(FileExistsError):
            archive.pack(source, manifest.parent, "fixture", 4096)
        self.assertEqual(before, {path.name: path.read_bytes() for path in manifest.parent.iterdir()})
        (source / "link").symlink_to(source / "payload.bin")
        with self.assertRaisesRegex(ValueError, "Symlinks"):
            archive.pack(source, self.root / "another", "fixture", 4096)

    def test_parts_are_rechecked_if_changed_after_preflight(self):
        _, manifest_path, manifest = self.bundle()
        part = manifest_path.parent / manifest["parts"][-1]["path"]
        original_enter = archive._PartReader.__enter__

        def alter_then_enter(reader):
            data = bytearray(part.read_bytes())
            data[-1] ^= 1
            part.write_bytes(data)
            return original_enter(reader)

        with patch.object(archive._PartReader, "__enter__", alter_then_enter):
            with self.assertRaises((ValueError, lzma.LZMAError, tarfile.ReadError)):
                archive.restore(manifest_path, self.root / "restored")


if __name__ == "__main__":
    unittest.main(verbosity=2)
