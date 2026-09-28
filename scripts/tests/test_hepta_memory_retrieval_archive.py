"""Synthetic format fixtures: never product measurements."""
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from scripts import hepta_memory_retrieval_archive as archive

SOURCE = "a" * 40
TREE = "b" * 40


def fixture(changes=None):
    files = {"host.txt": f"source_commit={SOURCE}\nsource_tree={TREE}\n".encode()}
    for filename, phase in archive.PHASES.items():
        row = {"schema": "hepta.memory-retrieval.target-host.v1", "phase": phase, "iterations": 100}
        prefixes = ("retrieval_", "revalidation_") if phase == "sqlite-owner" else ("",)
        for prefix in prefixes:
            row.update({f"{prefix}p50_us": 1, f"{prefix}p95_us": 2, f"{prefix}p99_us": 3})
        files[filename] = b"test fixture ... " + json.dumps(row).encode() + b"\n"
    files.update(changes or {})
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as zipped:
        for name, data in files.items():
            zipped.writestr(name, data)
    return output.getvalue()


class ArchiveTests(unittest.TestCase):
    def inspect(self, data, source=SOURCE):
        return archive.inspect_archive(data, hashlib.sha256(data).hexdigest(), source, 1, 2)

    def test_canonical_receipt_preserves_all_phases_and_denies_product_claims(self):
        receipt = self.inspect(fixture())
        self.assertEqual(len(receipt["measurements"]), 3)
        self.assertEqual(receipt["source_tree"], TREE)
        for flag in ("currentSourceQualified", "productExecutionProved", "independentAcceptance",
                     "productionImplementation", "activation", "release"):
            self.assertIs(receipt[flag], False)

    def test_archive_hash_mismatch(self):
        with self.assertRaises(archive.ArchiveError):
            archive.inspect_archive(fixture(), "0" * 64, SOURCE, 1, 2)

    def test_source_mismatch(self):
        with self.assertRaises(archive.ArchiveError):
            self.inspect(fixture(), source="c" * 40)

    def test_duplicate_source_identity(self):
        data = fixture({"host.txt": f"source_commit={SOURCE}\nsource_commit={SOURCE}\nsource_tree={TREE}\n".encode()})
        with self.assertRaises(archive.ArchiveError):
            self.inspect(data)

    def test_traversal_or_extra_member(self):
        for name in ("../escape", "extra.txt"):
            with self.subTest(name=name), self.assertRaises(archive.ArchiveError):
                self.inspect(fixture({name: b"bad"}))

    def test_expansion_bound(self):
        with self.assertRaises(archive.ArchiveError):
            self.inspect(fixture({"host.txt": b"x" * (archive.MAX_EXPANDED + 1)}))

    def test_missing_measurement(self):
        with self.assertRaises(archive.ArchiveError):
            self.inspect(fixture({"hnmf-512.log": b"test did not run\n"}))

    def test_duplicate_phase(self):
        data = fixture()
        with zipfile.ZipFile(io.BytesIO(data)) as zipped:
            line = zipped.read("hnmf-512.log")
        with self.assertRaises(archive.ArchiveError):
            self.inspect(fixture({"hnmf-512.log": line + line}))

    def test_duplicate_json_key(self):
        bad = b'{"schema":"hepta.memory-retrieval.target-host.v1","phase":"hnmf","phase":"hnmf"}\n'
        with self.assertRaises(archive.ArchiveError):
            self.inspect(fixture({"hnmf-512.log": bad}))

    def test_percentiles_must_be_ordered_measured_integers(self):
        for value in (True, -1, 2.5, 4):
            row = {"schema": "hepta.memory-retrieval.target-host.v1", "phase": "hnmf",
                   "iterations": 100, "p50_us": value, "p95_us": 2, "p99_us": 3}
            with self.subTest(value=value), self.assertRaises(archive.ArchiveError):
                self.inspect(fixture({"hnmf-512.log": json.dumps(row).encode()}))

    def test_numeric_identity_does_not_accept_boolean(self):
        data = fixture()
        with self.assertRaises(archive.ArchiveError):
            archive.inspect_archive(data, hashlib.sha256(data).hexdigest(), SOURCE, True, 2)

    def test_retain_is_idempotent_and_detects_mutated_archive(self):
        with tempfile.TemporaryDirectory() as temp:
            raw = Path(temp) / "input.zip"
            raw.write_bytes(fixture())
            digest = hashlib.sha256(raw.read_bytes()).hexdigest()
            output = Path(temp) / "retained"
            receipt = archive.retain(raw, digest, SOURCE, 1, 2, output)
            self.assertEqual(archive.retain(raw, digest, SOURCE, 1, 2, output), receipt)
            self.assertEqual(archive.verify(receipt)["archive_sha256"], digest)
            (receipt.parent / "archive.zip").write_bytes(b"changed")
            with self.assertRaises(archive.ArchiveError):
                archive.verify(receipt)

    def test_mutated_receipt_or_promoted_claim_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            raw = Path(temp) / "input.zip"
            raw.write_bytes(fixture())
            digest = hashlib.sha256(raw.read_bytes()).hexdigest()
            receipt = archive.retain(raw, digest, SOURCE, 1, 2, Path(temp) / "retained")
            value = json.loads(receipt.read_text())
            value["productionImplementation"] = True
            receipt.write_bytes(archive.canonical(value))
            with self.assertRaises(archive.ArchiveError):
                archive.verify(receipt)


if __name__ == "__main__":
    unittest.main()
