import contextlib
import copy
import gzip
import hashlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zlib

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))
import verify_source53_log_custody as custody
import restore_raw_evidence as storage

REPOSITORY = SCRIPTS.parent


class Source53LogCustodyTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.temporary = Path(temporary.name)
        self.repository = self.temporary / "repository"
        for index in storage.INDEX_SHA256:
            target = self.repository / index
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(REPOSITORY / index, target)
        document = json.loads((REPOSITORY / storage.EXTENSION_INDEX).read_bytes())
        self.entry = copy.deepcopy(document["files"][0])
        self.original_path = self.entry["original_path"]
        self.carrier = self.repository / self.entry["stored_path"]
        self.carrier.parent.mkdir(parents=True, exist_ok=True)
        self.compressed = (REPOSITORY / self.entry["stored_path"]).read_bytes()
        self.carrier.write_bytes(self.compressed)
        self.original = gzip.decompress(self.compressed)

    def read(self):
        return storage.read_verified(
            self.repository,
            self.original_path,
            self.entry["original_bytes"],
            self.entry["original_sha256"],
        )

    def replace_carrier(self, raw):
        self.carrier.write_bytes(raw)
        self.entry["stored_bytes"] = len(raw)
        self.entry["stored_sha256"] = hashlib.sha256(raw).hexdigest()

    def test_all_three_original_manifests_and_complete_logs_verify(self):
        report = custody.verify(REPOSITORY)
        self.assertEqual(report["unique_original_parts"], 34)
        self.assertEqual(report["unique_original_bytes"], 6954814)
        self.assertEqual(
            [(row["jobs"], row["parts"], row["bytes"]) for row in report["snapshots"]],
            [(3, 11, 2301376), (6, 19, 3945935), (9, 34, 6954814)],
        )
        self.assertFalse(report["historical_logs_replayed"])
        self.assertFalse(report["scientific_or_runtime_qualification"])
        self.assertTrue(report["original_manifests_unchanged"])

    def test_existing_and_new_consumers_restore_all_original_logical_paths(self):
        destination = self.temporary / "restored"
        with contextlib.redirect_stdout(io.StringIO()):
            storage.restore(REPOSITORY, destination)
        inventory = storage.entries(REPOSITORY)
        self.assertEqual(
            {
                p.relative_to(destination).as_posix()
                for p in destination.rglob("*")
                if p.is_file()
            },
            set(inventory),
        )
        legacy_paths = set()
        for index in (storage.INDEX, storage.EXTENSION_INDEX):
            document = json.loads((REPOSITORY / index).read_bytes())
            legacy_paths.update(entry["original_path"] for entry in document["files"])
        self.assertEqual(len(legacy_paths), 110)
        self.assertLessEqual(legacy_paths, set(inventory))
        prior_indexes = (
            storage.INDEX,
            storage.EXTENSION_INDEX,
            storage.SOURCE84_INDEX,
            storage.SOURCE0A5_INDEX,
        )
        prior_paths = {
            record["original_path"]
            for index in prior_indexes
            for record in json.loads((REPOSITORY / index).read_bytes())["files"]
        }
        self.assertEqual(len(prior_paths), 188)
        self.assertLessEqual(prior_paths, set(inventory))
        for name, entry in inventory.items():
            data = storage.read_verified(
                destination, name, entry["original_bytes"], entry["original_sha256"]
            )
            self.assertEqual(custody.identity(data)["oid"], entry["original_git_blob"])
        with self.assertRaises(FileExistsError):
            storage.restore(REPOSITORY, destination)

    def test_original_source53_manifests_are_bound_without_rehashing(self):
        transport = json.loads((REPOSITORY / storage.EXTENSION_INDEX).read_bytes())
        for entry in transport["prior_controls"]:
            target = self.repository / entry["carrier"]["path"]
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(REPOSITORY / entry["carrier"]["path"], target)
        name = transport["original_manifests"][0]["path"]
        target = self.repository / name
        target.write_bytes((REPOSITORY / name).read_bytes() + b"\n")
        with self.assertRaisesRegex(
            ValueError,
            "exceeds the byte limit|original log manifest drift|exceeds its bound",
        ):
            custody.verify(self.repository)

    def test_both_registered_inventories_reject_changes(self):
        for name in storage.INDEX_SHA256:
            with self.subTest(index=name):
                path = self.repository / name
                original = path.read_bytes()
                path.write_bytes(original + b"\n")
                with self.assertRaisesRegex(ValueError, "storage inventory changed"):
                    self.read()
                path.write_bytes(original)

    def test_changed_carrier_is_rejected_before_restoration(self):
        self.carrier.write_bytes(self.compressed[:-1])
        with self.assertRaisesRegex(ValueError, "stored evidence checksum mismatch"):
            self.read()

    def test_decoder_rejects_truncation_concatenation_and_trailing_bytes(self):
        # Controlled test inventory identities let these cases reach the decoder;
        # the production reader separately pins both complete storage inventories.
        for raw in (
            self.compressed[:-1],
            self.compressed[:-8],
            self.compressed + gzip.compress(b"", mtime=0),
            self.compressed + b"\0",
        ):
            with self.subTest(bytes=len(raw)):
                self.replace_carrier(raw)
                with patch.object(
                    storage, "entries", return_value={self.original_path: self.entry}
                ):
                    with self.assertRaisesRegex(
                        ValueError, "truncated, oversized or concatenated"
                    ):
                        self.read()

    def test_decoder_rejects_crc_and_expansion_mismatch(self):
        corrupt = bytearray(self.compressed)
        corrupt[-8] ^= 1
        for raw, error in (
            (bytes(corrupt), zlib.error),
            (gzip.compress(self.original + b"\n", mtime=0), ValueError),
            (
                gzip.compress(
                    bytes([self.original[0] ^ 1]) + self.original[1:], mtime=0
                ),
                ValueError,
            ),
        ):
            with self.subTest(error=error.__name__):
                self.replace_carrier(raw)
                with patch.object(
                    storage, "entries", return_value={self.original_path: self.entry}
                ):
                    with self.assertRaises(error):
                        self.read()

    def test_optimized_custody_command_refuses(self):
        result = subprocess.run(
            [
                sys.executable,
                "-B",
                "-O",
                str(SCRIPTS / "verify_source53_log_custody.py"),
            ],
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("optimized verification refused", result.stderr)


if __name__ == "__main__":
    unittest.main()
