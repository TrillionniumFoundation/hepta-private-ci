"""Peer-found identity/certificate gaps and independent compressed decoding."""

import gzip
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/"hepta-repo-v8/qa/stem-bakeoff"))

from cell_field_remaining_run_compressed_v8 import execute_one, write_trace
from cell_field_terminal_v8 import make_terminal_proposal
from remaining_audit_case_v8 import inspect_case
from remaining_audit_core_v8 import (bind_execution_identity, canonical, digest,
    file_hash, load_policy_record, read, required_hash)
from test_cell_field_policy_v7 import fixture
from test_cell_field_remaining_storage_v8 import partial_result


class RemainingBoundaryTests(unittest.TestCase):
    def test_external_seal_and_execution_identity_cannot_be_missing_or_old(self):
        for value in ({}, {"control_seal_sha256": ""}, {"control_seal_sha256": "z"*64}):
            with self.assertRaises(ValueError):
                required_hash(value, "control_seal_sha256")
        pins = {"protocol_sha256": "a"*64, "source_sha256": "b"*64, "source_commit": "c"*40}
        bind_execution_identity(pins, pins)
        for key in pins:
            wrong = {**pins, key: "d"*len(pins[key])}
            with self.assertRaises(ValueError):
                bind_execution_identity(wrong, pins)

    def test_deleted_paid_certificate_rejects_even_when_physical_prefix_and_hashes_match(self):
        state, train, panels, anchors, _ = fixture()
        count = 0
        def bounded(*args, **kwargs):
            nonlocal count
            count += 1
            if count == 2:
                raise RuntimeError("fixture stop after one committed step")
            return make_terminal_proposal(*args, **kwargs)
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)/"case"
            with patch("cell_field_remaining_v8.make_terminal_proposal", side_effect=bounded):
                execute_one(directory, state, train, panels+panels, anchors, "myopic_h1", "b"*64, "c"*64)
            result = inspect_case(directory, state, train, panels+panels, "myopic_h1", "b"*64, "c"*64, compressed=True)
            self.assertEqual(result["known_replayed_steps"], 1)
            record, index = load_policy_record(directory, True), read(directory/"result.json")
            del record["steps"][0]["repair"]
            raw = canonical(record)+b"\n"
            path = directory/"policy-record.json.gz"
            path.write_bytes(gzip.compress(raw, mtime=0))
            index["policy_record"].update(sha256=file_hash(path), bytes=path.stat().st_size,
                uncompressed_sha256=digest(raw), uncompressed_bytes=len(raw))
            (directory/"result.json").write_bytes(canonical(index)+b"\n")
            with self.assertRaisesRegex(ValueError, "complete error-free paid safety certificate"):
                inspect_case(directory, state, train, panels+panels, "myopic_h1", "b"*64, "c"*64, compressed=True)

    def test_independent_reader_checks_index_compressed_and_expanded_bytes(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)/"case"
            write_trace(directory, partial_result())
            original = load_policy_record(directory, True)
            self.assertEqual(original["completed_steps"], 1)
            index = read(directory/"result.json")
            index["completed_steps"] = 32
            (directory/"result.json").write_bytes(canonical(index)+b"\n")
            with self.assertRaisesRegex(ValueError, "ledger/index"):
                load_policy_record(directory, True)
            index["completed_steps"] = 1
            index["policy_record"]["uncompressed_sha256"] = "0"*64
            (directory/"result.json").write_bytes(canonical(index)+b"\n")
            with self.assertRaisesRegex(ValueError, "expanded ledger"):
                load_policy_record(directory, True)
            (directory/"policy-record.json.gz").unlink()
            with self.assertRaises(ValueError):
                load_policy_record(directory, True)


if __name__ == "__main__":
    unittest.main()
