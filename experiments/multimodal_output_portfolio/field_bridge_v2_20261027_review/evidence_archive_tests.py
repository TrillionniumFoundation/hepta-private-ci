"""Small synthetic archive corruption/restore contracts; no study input access."""

import gzip
import hashlib
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch

from .evidence_archive import verify_archive, json_bytes, safe_name, check_gzip, SYNTHETIC_GZIP, invalid_gzip_receipt


# Exact deliberately truncated fixture that exposed the real packaging failure.
TRUNCATED_FIXTURE = bytes.fromhex(
    "1f8b0800166de06a02ff558bcb0ac2400c00ef7e45c959444b7de0cf2ceb6ed4c06e222655a4f4df9bd24b3d0e"
    "3333802266b83687f3b6814f2c3d3aec77add33796125867e994319192b0e300496a2533cca10a8b09535acacecb9"
    "86ce9404d5e30aee670fb196ae8ed7e99bdbce9411c0bac137dc6f678fad3e36602")


class ArchiveContracts(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="v2-archive-contract-")
        self.root = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def archive(self, payload=None, *, override=None, duplicate=False, omit=False, extra=None, entry_updates=None):
        payload = payload or {"data/rows.jsonl.gz": gzip.compress(b'{"value":3}\n'),
                              "data/opaque.bin": b"unchanged model bytes"}
        entries = [{"path": name, "bytes": len(data), "mode": 0o644,
                    "sha256": hashlib.sha256(data).hexdigest()} for name, data in payload.items()]
        for entry in entries:
            entry.update((entry_updates or {}).get(entry["path"], {}))
        manifest = json_bytes({"files": entries, "evaluation_subdirectory": "eval"})
        path = self.root / "synthetic.tar.gz"
        with tarfile.open(path, "w:gz") as archive:
            members = [("MANIFEST.json", manifest), *payload.items()]
            if omit:
                members.pop()
            if duplicate:
                members.append(members[-1])
            if extra is not None:
                members.append(extra)
            for name, data in members:
                if override is not None and name == override[0]:
                    data = override[1]
                header = tarfile.TarInfo(name)
                header.size, header.mode = len(data), 0o644
                archive.addfile(header, io.BytesIO(data))
        return path, hashlib.sha256(manifest).hexdigest()

    def test_full_hash_and_embedded_gzip_crc_without_extraction(self):
        path, manifest = self.archive()
        result = verify_archive(path, manifest, hashlib.sha256(path.read_bytes()).hexdigest())
        self.assertEqual(result["tar_regular_members"], 3)
        self.assertEqual(result["embedded_gzip_crc_checked"], 1)
        self.assertEqual(result["selectively_restored_files"], [])
        self.assertTrue(result["outer_gzip_crc_verified"])

    def test_selective_restore_preserves_bytes_and_excludes_unselected(self):
        path, manifest = self.archive()
        destination = self.root / "selected"
        result = verify_archive(path, manifest, destination=destination, patterns=["data/*.gz"])
        self.assertEqual(result["selectively_restored_files"], ["data/rows.jsonl.gz"])
        self.assertEqual(gzip.decompress((destination / "data/rows.jsonl.gz").read_bytes()), b'{"value":3}\n')
        self.assertFalse((destination / "data/opaque.bin").exists())
        self.assertTrue((destination / "MANIFEST.json").is_file())

    def test_wrong_payload_sha_rejected_and_new_restore_removed(self):
        path, manifest = self.archive(override=("data/opaque.bin", b"changed model bytes  "))
        destination = self.root / "failed"
        with self.assertRaises(ValueError):
            verify_archive(path, manifest, destination=destination, patterns=["*"])
        self.assertFalse(destination.exists())

    def test_missing_and_duplicate_members_rejected(self):
        for setting in ({"omit": True}, {"duplicate": True}):
            path, manifest = self.archive(**setting)
            with self.assertRaises(ValueError):
                verify_archive(path, manifest)

    def test_unsafe_unregistered_path_rejected(self):
        path, manifest = self.archive(extra=("../escape", b"no"))
        with self.assertRaises(ValueError):
            verify_archive(path, manifest)
        for name in (".", "../x", "/absolute", "a/../b", "a\\b"):
            with self.assertRaises(ValueError):
                safe_name(name)

    def test_inner_crc_rejected_even_when_member_sha_is_correct(self):
        compressed = bytearray(gzip.compress(b"complete original data"))
        compressed[-8] ^= 1
        path, manifest = self.archive(payload={"data/bad.gz": bytes(compressed)})
        with self.assertRaisesRegex(ValueError, "data/bad.gz: BadGzipFile"):
            verify_archive(path, manifest)

    def test_exact_observed_truncation_and_input_preflight(self):
        entry = {**SYNTHETIC_GZIP, "expected_invalid_gzip": SYNTHETIC_GZIP}
        self.assertEqual(len(TRUNCATED_FIXTURE), entry["bytes"])
        self.assertEqual(hashlib.sha256(TRUNCATED_FIXTURE).hexdigest(), entry["sha256"])
        self.assertFalse(check_gzip(io.BytesIO(TRUNCATED_FIXTURE), entry["path"], entry))
        with self.assertRaisesRegex(ValueError, "data/unregistered.gz: EOFError"):
            check_gzip(io.BytesIO(TRUNCATED_FIXTURE), "data/unregistered.gz", {})

    def test_registered_truncated_fixture_is_restored_with_exact_bytes(self):
        provenance = b'{"synthetic_provenance_for_archive_contract":true}\n'
        with patch.dict(SYNTHETIC_GZIP, contract_receipt_sha256=hashlib.sha256(provenance).hexdigest()):
            payload = {SYNTHETIC_GZIP["path"]: TRUNCATED_FIXTURE,
                       SYNTHETIC_GZIP["contract_receipt"]: provenance,
                       "EXPECTED_INVALID_GZIP.json": invalid_gzip_receipt()}
            updates = {SYNTHETIC_GZIP["path"]: {"expected_invalid_gzip": SYNTHETIC_GZIP}}
            path, manifest = self.archive(payload, entry_updates=updates)
            target = self.root / "registered"
            result = verify_archive(path, manifest, destination=target, patterns=["*"])
            self.assertEqual((target / SYNTHETIC_GZIP["path"]).read_bytes(), TRUNCATED_FIXTURE)
            self.assertEqual(result["expected_invalid_synthetic_gzip_preserved_by_sha256"], [SYNTHETIC_GZIP["path"]])
            self.assertEqual(result["embedded_gzip_crc_checked"], 0)
            self.assertTrue(result["all_member_sha256_verified"])
            self.assertTrue(result["outer_gzip_crc_verified"])
            for omitted in (SYNTHETIC_GZIP["contract_receipt"], "EXPECTED_INVALID_GZIP.json"):
                path, manifest = self.archive({k: v for k, v in payload.items() if k != omitted}, entry_updates=updates)
                with self.assertRaisesRegex(ValueError, "fixture lacks"):
                    verify_archive(path, manifest)
            changed = bytearray(TRUNCATED_FIXTURE)
            changed[4] ^= 1  # Header timestamp changes identity while retaining the same truncation.
            path, manifest = self.archive({**payload, SYNTHETIC_GZIP["path"]: bytes(changed)}, entry_updates=updates)
            with self.assertRaisesRegex(ValueError, "Synthetic fixture identity differs"):
                verify_archive(path, manifest)

    def test_completed_and_interrupted_scientific_gzip_cannot_receive_exception(self):
        for directory in ("eval", "eval_recovered"):
            name = f"bridge_v2_primary/{directory}/17/rows.jsonl.gz"
            for metadata in ({}, {"gzip_crc_required": False}, {"expected_invalid_gzip": SYNTHETIC_GZIP}):
                path, manifest = self.archive({name: TRUNCATED_FIXTURE}, entry_updates={name: metadata})
                with self.assertRaisesRegex(ValueError, name):
                    verify_archive(path, manifest)

    def test_outer_truncation_and_external_hashes_rejected(self):
        path, manifest = self.archive()
        with self.assertRaises(ValueError):
            verify_archive(path, "0" * 64)
        with self.assertRaises(ValueError):
            verify_archive(path, manifest, "0" * 64)
        path.write_bytes(path.read_bytes()[:-4])
        with self.assertRaises(EOFError):
            verify_archive(path, manifest)

    def test_existing_restore_not_overwritten_and_unmatched_pattern_rejected(self):
        path, manifest = self.archive()
        with self.assertRaises(ValueError):
            verify_archive(path, manifest, destination=self.root, patterns=["*"])
        with self.assertRaises(ValueError):
            verify_archive(path, manifest, destination=self.root / "none", patterns=["missing/*"])
        self.assertTrue(path.exists())
        self.assertFalse((self.root / "none").exists())


if __name__ == "__main__":
    unittest.main()
