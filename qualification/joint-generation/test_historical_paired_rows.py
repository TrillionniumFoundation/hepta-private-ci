"""Verify the two historical H4 CSV exports without executing a producer."""
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import unittest


HERE = Path(__file__).resolve().parent
REPOSITORY = HERE.parent.parent
spec = importlib.util.spec_from_file_location("row_storage", HERE / "restore_historical_run_assets.py")
storage = importlib.util.module_from_spec(spec)
spec.loader.exec_module(storage)

FULL_HASH = "66f2a4b68596b7a6b1138ad44def05575a21dcb91b7ffd9150c47d8bf26d32ac"
PARTIAL_HASH = "3d93100d9c9aa56f8ee1ab5f2ca50b611e5444536288e41710046b9699b305df"


class HistoricalRowsTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.source = self.root / "source"
        self.output = self.root / "restored"
        manifest = storage.descriptor(REPOSITORY)
        self.descriptor = self.source / storage.DESCRIPTOR
        self.parts = [self.source / (storage.H4_ROWS + f".gz.part-{i:02d}") for i in range(2)]
        files = [storage.DESCRIPTOR, *(p + ".gz" for p in storage.ASSET_PATHS)]
        files += list(storage.CSV_ASSETS)
        files += [p.relative_to(self.source) for p in self.parts]
        files += [entry["path"] for group in ("markers", "sidecars") for entry in manifest[group]]
        for name in files:
            dest = self.source / name
            dest.parent.mkdir(exist_ok=True, parents=True)
            shutil.copyfile(REPOSITORY / name, dest)

    def test_both_receipts_and_every_original_csv_byte(self):
        receipt = storage.restore(self.source, self.output)
        full = (self.output / storage.H4_ROWS).read_bytes()
        partial = (self.output / storage.H4_PARTIAL).read_bytes()
        for body, size, rows, digest in (
            (full, 2_775_720, 9_216, FULL_HASH),
            (partial, 1_850_445, 6_144, PARTIAL_HASH),
        ):
            self.assertEqual(len(body), size)
            self.assertEqual(hashlib.sha256(body).hexdigest(), digest)
            self.assertEqual(body.count(b"\r\n"), rows + 1)
            self.assertEqual(body.count(b"\n"), rows + 1)
        self.assertEqual(full[:len(partial)], partial)
        self.assertEqual(len(receipt["files"]), 19)
        self.assertIn("h4-failed-export-prefix", receipt["consumed_relations"])
        self.assertIn("h4-complete-export", receipt["consumed_relations"])
        self.assertFalse(receipt["scientific_execution_performed"])
        storage.inspect_output(self.source, self.output)
        (self.output / storage.H4_PARTIAL).write_bytes(partial[:-1])
        with self.assertRaises(storage.ContractError):
            storage.inspect_output(self.source, self.output)

    def test_independent_source_exports_and_core_samples_match_original_sidecars(self):
        receipt = storage.restore(self.source, self.output)
        h4 = json.loads((self.source / (storage.H4 + "postrun-manifest.json")).read_bytes())["files"]
        core = json.loads((self.source / storage.CORE_SAMPLE_INDEX).read_bytes())
        for name in storage.CSV_ASSETS:
            data = (self.output / name).read_bytes()
            pin = (h4 if name.startswith(storage.H4) else core)[Path(name).name]
            self.assertEqual({"bytes": len(data), "sha256": storage.H(data)}, pin)
            self.assertEqual(data.count(b"\n"), data.count(b"\r\n"))
        full = (self.output / storage.H4_SOURCES).read_bytes()
        partial = (self.output / storage.H4_SOURCES_PARTIAL).read_bytes()
        self.assertFalse(full.startswith(partial))
        self.assertEqual([full.count(b"\r\n"), partial.count(b"\r\n")], [577, 385])
        self.assertEqual(receipt["scope"], "twelve-artifact-inspection")
        self.assertFalse(receipt["scientific_execution_performed"])

    def test_modified_csv_with_matching_transport_hash_fails_historical_sidecar(self):
        manifest = json.loads(self.descriptor.read_bytes())
        name = storage.CORE_SAMPLES[0]
        path = self.source / name
        original = path.read_bytes()
        wrong = (original if b"\r" in original else original.replace(b"\n", b"\r\n")).replace(b",", b";", 1)
        path.write_bytes(wrong)
        entry = next(row for row in manifest["assets"] if row["path"] == name)
        entry.update(original_bytes=len(wrong), original_sha256=storage.H(wrong))
        self.descriptor.write_bytes(storage.canonical(manifest))
        with self.assertRaisesRegex(storage.ContractError, "core-sample-inventory"):
            storage.restore(self.source, self.output)
        self.assertFalse(self.output.exists())

    def test_canonical_git_blobs_and_crlf_checkouts_restore_the_same_original_bytes(self):
        assets = storage.verified_inputs(self.source)["assets"]
        for name in storage.CSV_ASSETS:
            canonical = assets[name].replace(b"\r\n", b"\n")
            (self.source / name).write_bytes(canonical)
        self.assertEqual(storage.verified_inputs(self.source)["assets"], assets)
        name = storage.H4_SOURCES
        mixed = assets[name].replace(b"\r\n", b"\n", 1)
        (self.source / name).write_bytes(mixed)
        with self.assertRaisesRegex(storage.ContractError, "csv-original-integrity"):
            storage.restore(self.source, self.output)
        self.assertFalse(self.output.exists())

    def test_previous_descriptor_preserves_the_fourteen_file_receipt(self):
        manifest = json.loads(self.descriptor.read_bytes())
        manifest["schema"] = "joint-historical-assets-gzip-v2"
        manifest["assets"] = [r for r in manifest["assets"] if r["path"] not in storage.CSV_ASSETS]
        manifest["sidecars"] = [r for r in manifest["sidecars"] if r["path"] != storage.CORE_SAMPLE_INDEX]
        self.descriptor.write_bytes(storage.canonical(manifest))
        receipt = storage.restore(self.source, self.output)
        self.assertEqual(len(receipt["files"]), 14)
        self.assertEqual(receipt["scope"], "seven-artifact-inspection")
        self.assertEqual((self.output / storage.NOTE_PATH).read_bytes(), storage.H4_NOTE)

    def test_each_missing_or_modified_carrier_prevents_publication(self):
        for path in self.parts:
            original = path.read_bytes()
            for damage in ("missing", "truncated", "changed"):
                with self.subTest(path=path.name, damage=damage):
                    if damage == "missing":
                        path.unlink()
                    elif damage == "truncated":
                        path.write_bytes(original[:-1])
                    else:
                        path.write_bytes(bytes([original[0] ^ 1]) + original[1:])
                    with self.assertRaises((FileNotFoundError, storage.ContractError)):
                        storage.restore(self.source, self.output)
                    self.assertFalse(self.output.exists())
                    path.write_bytes(original)

    def test_second_gzip_member_is_rejected_even_with_matching_compressed_hash(self):
        self.parts[1].write_bytes(self.parts[1].read_bytes() + gzip.compress(b"", mtime=0))
        encoded = b"".join(path.read_bytes() for path in self.parts)
        manifest = json.loads(self.descriptor.read_bytes())
        entry = next(item for item in manifest["assets"] if item["path"] == storage.H4_ROWS)
        entry["compressed_bytes"] = len(encoded)
        entry["compressed_sha256"] = storage.H(encoded)
        self.descriptor.write_bytes(storage.canonical(manifest))
        with self.assertRaisesRegex(storage.ContractError, "gzip-integrity"):
            storage.restore(self.source, self.output)
        self.assertFalse(self.output.exists())

    def test_shorter_valid_prefix_must_match_original_run_manifest(self):
        manifest = json.loads(self.descriptor.read_bytes())
        entry = next(item for item in manifest["assets"] if item["path"] == storage.H4_PARTIAL)
        entry["original_bytes"] = 64
        full = gzip.decompress(b"".join(path.read_bytes() for path in self.parts))
        entry["original_sha256"] = storage.H(full[:64])
        self.descriptor.write_bytes(storage.canonical(manifest))
        with self.assertRaisesRegex(storage.ContractError, "relation:h4-inventory"):
            storage.restore(self.source, self.output)
        self.assertFalse(self.output.exists())


if __name__ == "__main__":
    unittest.main()
