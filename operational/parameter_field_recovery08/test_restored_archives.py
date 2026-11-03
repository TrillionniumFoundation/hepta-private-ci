"""Synthetic copies exercise restoration identity, not scientific efficacy."""

from copy import deepcopy
from pathlib import Path
import os
import tempfile
import unittest

from . import common as c
from .test_postseal import archive_fixture, rebind
from .postseal import review
from .postseal.restored_archives import SCHEMA, RestoredMetadata, capture_proof


def replay_fixture(root):
    row, ack = archive_fixture(root)
    item = row["logical_files"][0]
    directory = Path(row["ack"]["path"]).parent
    proof = capture_proof(item, root / "synthetic_source",
                          directory / "upload/payload" / item["path"],
                          directory / "readback/payload" / item["path"])
    # A different machine's historical inode identities remain literal history.
    old = ack["readback"]["independent_device_inodes"][0]
    for index, field in enumerate(("source_device_inode", "staged_device_inode", "readback_device_inode")):
        old[field] = [7, index + 1]
    row = rebind(row, ack)
    value = {"schema": SCHEMA, "historical_receipts_modified": False,
             "archives": [{"artifact": row["artifact"], "ack": row["ack"],
                           "manifest": row["manifest"], "files": [proof]}]}
    return row, ack, value


class RestoredArchiveTests(unittest.TestCase):
    def test_fresh_independent_copies_admit_old_bytes_without_rewriting_receipts(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            row, ack, value = replay_fixture(root)
            before = Path(row["ack"]["path"]).read_bytes()
            with self.assertRaisesRegex(ValueError, "inode identity differs"):
                review.verify_ack(review.Metadata(), row, row["binding"])
            metadata = RestoredMetadata(c.write_new(root / "REPLAY.json", value), [row])
            self.assertEqual(review.verify_ack(metadata, row, row["binding"]), ack)
            metadata.stable()
            self.assertEqual(Path(row["ack"]["path"]).read_bytes(), before)

    def test_historical_same_inode_claim_is_still_rejected(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            row, ack, value = replay_fixture(root)
            proof = ack["readback"]["independent_device_inodes"][0]
            proof["source_device_inode"] = proof["staged_device_inode"]
            row = rebind(row, ack)
            value["archives"][0]["ack"] = row["ack"]
            metadata = RestoredMetadata(c.write_new(root / "REPLAY.json", value), [row])
            with self.assertRaisesRegex(ValueError, "Historical readback"):
                review.verify_ack(metadata, row, row["binding"])

    def test_wrong_artifact_ack_or_population_cannot_borrow_a_new_receipt(self):
        for change in ("artifact", "ack", "missing_file", "duplicate_archive"):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as name:
                root = Path(name)
                row, unused, value = replay_fixture(root)
                record = value["archives"][0]
                if change == "artifact":
                    record["artifact"] = {**record["artifact"], "sha256": "0" * 64}
                elif change == "ack":
                    record["ack"] = {**record["ack"], "sha256": "0" * 64}
                elif change == "missing_file":
                    record["files"] = []
                else:
                    value["archives"].append(deepcopy(record))
                with self.assertRaises(ValueError):
                    RestoredMetadata(c.write_new(root / "REPLAY.json", value), [row])

    def test_mutated_source_or_readback_and_hardlink_substitution_are_rejected(self):
        for change in ("source", "readback", "hardlink"):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as name:
                root = Path(name)
                row, unused, value = replay_fixture(root)
                metadata = RestoredMetadata(c.write_new(root / "REPLAY.json", value), [row])
                source = root / "synthetic_source"
                readback = root / "stage/readback/payload/raw/fixture.bin"
                if change == "hardlink":
                    readback.unlink()
                    os.link(source, readback)
                else:
                    (source if change == "source" else readback).write_bytes(b"changed")
                with self.assertRaises(ValueError):
                    review.verify_ack(metadata, row, row["binding"])

    def test_modified_new_receipt_is_detected_before_review_closure(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            row, unused, value = replay_fixture(root)
            path = root / "REPLAY.json"
            metadata = RestoredMetadata(c.write_new(path, value), [row])
            review.verify_ack(metadata, row, row["binding"])
            path.write_bytes(path.read_bytes() + b" ")
            with self.assertRaises(ValueError):
                metadata.stable()


if __name__ == "__main__":
    unittest.main()
