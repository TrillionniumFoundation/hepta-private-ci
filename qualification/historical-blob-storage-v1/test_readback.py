import copy
import gzip
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import unittest

import readback


class HistoricalStorageTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.parent = Path(self.temporary.name)
        self.root = self.parent / "repo"
        self.root.mkdir()
        self.manifest = json.loads((readback.ROOT / readback.MANIFEST).read_bytes())
        paths = [readback.MANIFEST, *readback.PRESERVED_PATHS]
        paths.extend(
            part["path"]
            for entry in self.manifest["artifacts"]
            for part in entry["storage"]["parts"]
        )
        for relative in paths:
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(readback.ROOT / relative, path)
        self.part = self.root / self.manifest["artifacts"][0]["storage"]["parts"][0]["path"]

    def save_manifest(self):
        (self.root / readback.MANIFEST).write_text(json.dumps(self.manifest), encoding="utf-8")

    def replace_gzip(self, compressed):
        pin = self.manifest["artifacts"][-1]["storage"]["parts"][0]
        (self.root / pin["path"]).write_bytes(compressed)
        pin["bytes"] = len(compressed)
        pin["sha256"] = hashlib.sha256(compressed).hexdigest()
        self.save_manifest()

    def test_real_artifacts_round_trip_to_new_directory(self):
        decoded = readback.verify(self.root)
        destination, restored = readback.restore(self.root, self.parent / "restored")
        self.assertEqual(restored, decoded)
        observed = {
            path: (len((destination / path).read_bytes()), hashlib.sha256((destination / path).read_bytes()).hexdigest())
            for path in decoded
        }
        self.assertEqual(observed, readback.ORIGINALS)
        self.assertTrue(all((destination / path).read_bytes() == data for path, data in decoded.items()))

    def test_missing_part(self):
        self.part.unlink()
        with self.assertRaises(OSError):
            readback.verify(self.root)

    def test_changed_part(self):
        data = bytearray(self.part.read_bytes())
        data[20] ^= 1
        self.part.write_bytes(data)
        with self.assertRaisesRegex(readback.ArchiveError, "SHA-256 mismatch"):
            readback.verify(self.root)

    def test_truncated_part(self):
        self.part.write_bytes(self.part.read_bytes()[:-1])
        with self.assertRaisesRegex(readback.ArchiveError, "size mismatch"):
            readback.verify(self.root)

    def test_stored_part_size_bound(self):
        self.part.write_bytes(b"x" * (readback.MAX_PART_BYTES + 1))
        with self.assertRaisesRegex(readback.ArchiveError, "stored size exceeds bound"):
            readback.verify(self.root)

    def test_reordered_duplicate_and_escaped_parts(self):
        original = copy.deepcopy(self.manifest)
        for mutation in ("reorder", "duplicate", "escape"):
            with self.subTest(mutation=mutation):
                self.manifest = copy.deepcopy(original)
                parts = self.manifest["artifacts"][0]["storage"]["parts"]
                if mutation == "reorder":
                    parts.reverse()
                elif mutation == "duplicate":
                    parts[1] = copy.deepcopy(parts[0])
                else:
                    parts[0]["path"] = "../../outside.bin"
                self.save_manifest()
                with self.assertRaisesRegex(readback.ArchiveError, "part order or path"):
                    readback.verify(self.root)

    def test_manifest_cannot_inflate_original_or_part_bound(self):
        original = copy.deepcopy(self.manifest)
        for mutation in ("original", "part", "boolean_offset"):
            with self.subTest(mutation=mutation):
                self.manifest = copy.deepcopy(original)
                entry = self.manifest["artifacts"][0]
                if mutation == "original":
                    entry["bytes"] = 10**12
                elif mutation == "part":
                    entry["storage"]["parts"][0]["bytes"] = 10**12
                else:
                    entry["storage"]["parts"][0]["offset"] = False
                self.save_manifest()
                with self.assertRaises(readback.ArchiveError):
                    readback.verify(self.root)

    def test_original_receipt_change(self):
        path = self.root / self.manifest["preserved_files"][0]["path"]
        data = bytearray(path.read_bytes())
        data[-1] ^= 1
        path.write_bytes(data)
        with self.assertRaisesRegex(readback.ArchiveError, "SHA-256 mismatch"):
            readback.verify(self.root)

    def test_duplicate_and_incomplete_receipt_inventory(self):
        original = copy.deepcopy(self.manifest)
        for mutation in ("duplicate", "missing"):
            with self.subTest(mutation=mutation):
                self.manifest = copy.deepcopy(original)
                if mutation == "duplicate":
                    self.manifest["preserved_files"][1] = self.manifest["preserved_files"][0]
                else:
                    self.manifest["preserved_files"].pop()
                self.save_manifest()
                with self.assertRaises(readback.ArchiveError):
                    readback.verify(self.root)

    def test_ambiguous_original_and_stored_representation(self):
        (self.root / self.manifest["artifacts"][0]["path"]).write_bytes(b"duplicate")
        with self.assertRaisesRegex(readback.ArchiveError, "ambiguous"):
            readback.verify(self.root)

    def test_symlink_part_and_parent(self):
        saved = self.parent / "saved-part"
        self.part.rename(saved)
        try:
            self.part.symlink_to(saved)
        except OSError as error:
            self.skipTest(f"symlinks unavailable: {error}")
        with self.assertRaisesRegex(readback.ArchiveError, "symlink"):
            readback.verify(self.root)
        self.part.unlink()
        saved.rename(self.part)
        folder = self.part.parent
        moved = self.parent / "saved-folder"
        folder.rename(moved)
        folder.symlink_to(moved, target_is_directory=True)
        with self.assertRaisesRegex(readback.ArchiveError, "symlink"):
            readback.verify(self.root)

    def test_gzip_bounds_crc_truncation_and_extra_member(self):
        decoded = readback.verify(self.root)
        raw = decoded[self.manifest["artifacts"][-1]["path"]]
        original = (self.root / self.manifest["artifacts"][-1]["storage"]["parts"][0]["path"]).read_bytes()
        bad_crc = bytearray(original)
        bad_crc[-8] ^= 1
        cases = {
            "truncated": original[:-1],
            "crc": bytes(bad_crc),
            "extra_member": original + gzip.compress(b"", mtime=0),
            "overflow": gzip.compress(raw + b"x", mtime=0),
            "underflow": gzip.compress(raw[:-1], mtime=0),
        }
        for name, compressed in cases.items():
            with self.subTest(mutation=name):
                self.replace_gzip(compressed)
                with self.assertRaises(readback.ArchiveError):
                    readback.verify(self.root)

    def test_duplicate_json_key(self):
        path = self.root / readback.MANIFEST
        data = path.read_text(encoding="utf-8")
        path.write_text('{"schema":"duplicate",' + data[1:], encoding="utf-8")
        with self.assertRaisesRegex(readback.ArchiveError, "duplicate JSON key"):
            readback.verify(self.root)

    def test_restore_does_not_replace_an_existing_directory(self):
        destination = self.parent / "existing"
        destination.mkdir()
        sentinel = destination / "sentinel"
        sentinel.write_bytes(b"keep this")
        with self.assertRaises(FileExistsError):
            readback.restore(self.root, destination)
        self.assertEqual(list(destination.iterdir()), [sentinel])
        self.assertEqual(sentinel.read_bytes(), b"keep this")

    def test_restore_rejects_repository_and_validates_before_creation(self):
        with self.assertRaisesRegex(readback.ArchiveError, "outside repository"):
            readback.restore(self.root, self.root / "restored")
        self.assertFalse((self.root / "restored").exists())
        self.part.unlink()
        destination = self.parent / "must-not-be-created"
        with self.assertRaises(OSError):
            readback.restore(self.root, destination)
        self.assertFalse(destination.exists())


if __name__ == "__main__":
    unittest.main()
