"""Regression coverage for sealing failures, cross-study reuse and trace tampering."""

import gzip
import json
from pathlib import Path
import tempfile
import unittest

from ..field_bridge_v3_20261027.training_common import object_hash, write_json
from .records import Journal, complete, verify_complete


class RecordContracts(unittest.TestCase):
    def test_chain_binds_order_and_record_contents(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "trace.jsonl.gz"
            with Journal(path) as journal:
                journal.append({"kind": "decision", "action": 2})
                journal.append({"kind": "transaction", "accepted": False})
            with gzip.open(path, "rt") as stream:
                rows = [json.loads(line) for line in stream]
            previous = None
            for index, row in enumerate(rows):
                identity = row.pop("record_sha256")
                self.assertEqual((row["record_index"], row["previous_record_sha256"]), (index, previous))
                self.assertEqual(object_hash(row), identity)
                previous = identity
            self.assertEqual((journal.head, journal.count), (previous, 2))
            rows[0]["action"] = 3
            self.assertNotEqual(object_hash(rows[0]), rows[1]["previous_record_sha256"])

    def test_seal_rejects_failure_and_another_study(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            write_json(path / "START.json", {"study_id": "a", "started_unix_ns": 1})
            write_json(path / "PATH.json", {"gradient_steps": 288})
            complete(path, {"train_paths": 1})
            self.assertEqual(verify_complete(path, {"study_id": "a"})["train_paths"], 1)
            with self.assertRaises(ValueError):
                verify_complete(path, {"study_id": "b"})
            write_json(path / "FAILED.json", {"failure": "postflight"})
            with self.assertRaises(ValueError):
                verify_complete(path)
            with self.assertRaises(ValueError):
                complete(path, {})

    def test_exact_inventory_and_bytes_reject_unsealed_outputs(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            write_json(path / "START.json", {"started_unix_ns": 1})
            complete(path, {})
            extra = path / "later.npz"
            extra.write_bytes(b"unsealed")
            with self.assertRaises(ValueError):
                verify_complete(path)
            extra.unlink()
            (path / "START.json").write_text(json.dumps({"started_unix_ns": 2}))
            with self.assertRaises(ValueError):
                verify_complete(path)


if __name__ == "__main__":
    unittest.main()
