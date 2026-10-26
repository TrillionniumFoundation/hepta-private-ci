"""Lossless ledger persistence, tamper rejection and partial-prefix semantics."""

import copy
import gzip
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from cell_field_common_run_v8 import canonical, read, write
from cell_field_remaining_run_compressed_v8 import load_record, write_trace
from test_cell_field_policy_v7 import fixture


def partial_result():
    before, train, panels, anchors, _ = fixture()
    after = before.clone()
    action = np.zeros((1, before.parameter_count))
    receipt = after.advance(*train, intervention=.02*action[0])
    record = {"schema": "hepta.remaining-terminal-policy.v8", "method": "myopic_h1",
        "status": "not_executed_rejected", "error": None, "completed_steps": 1,
        "terminal_state_sha256": after.digest(), "common_J32": None, "parameter_action_penalty": 0.,
        "policy_call_cpu_ns": 1000, "policy_call_wall_ns": 1200, "receipts": [receipt],
        "steps": [{"failed_trial": {"actions": list(range(52)), "old_losses": [1., 2., 3., 4.],
            "status": "rejected", "cpu_ns": 123}, "unresolved_reason": "retained verbatim"}],
        "scientific_acceptance": False, "production_authority": False}
    return {"record": record, "states": [before, after], "state": after, "actions": action,
        "old_losses": np.stack([anchors, anchors]), "plans": []}


class CompressedRemainingStorageTests(unittest.TestCase):
    def test_complete_ledger_bytes_restore_and_gzip_has_deterministic_zero_timestamp(self):
        with tempfile.TemporaryDirectory() as temp:
            first, second = Path(temp)/"a", Path(temp)/"b"
            a, b = partial_result(), partial_result()
            write_trace(first, a)
            write_trace(second, b)
            raw = canonical(a["record"])+b"\n"
            self.assertEqual(gzip.decompress((first/"policy-record.json.gz").read_bytes()), raw)
            self.assertEqual(load_record(first), a["record"])
            self.assertEqual((first/"policy-record.json.gz").read_bytes(), (second/"policy-record.json.gz").read_bytes())
            self.assertEqual((first/"policy-record.json.gz").read_bytes()[4:8], b"\0"*4)
            self.assertEqual(read(first/"result.json")["schema"], "hepta.remaining-terminal-policy-record-index.v8")
            self.assertLess((first/"result.json").stat().st_size, len(raw))

    def test_missing_or_changed_gzip_and_changed_expanded_hash_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)/"case"
            write_trace(path, partial_result())
            member, index = path/"policy-record.json.gz", read(path/"result.json")
            original = member.read_bytes()
            member.write_bytes(original+b"extra")
            with self.assertRaisesRegex(ValueError, "compressed ledger identity"):
                load_record(path)
            member.unlink()
            with self.assertRaises(ValueError):
                load_record(path)
            member.write_bytes(original)
            bad = copy.deepcopy(index)
            bad["policy_record"]["uncompressed_sha256"] = "0"*64
            write(path/"result.json", bad)
            with self.assertRaisesRegex(ValueError, "expanded complete ledger identity"):
                load_record(path)

    def test_partial_cannot_be_indexed_as32_and_storage_failure_stays_a_failure(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)/"case"
            result = partial_result()
            write_trace(path, result)
            index = read(path/"result.json")
            index.update(status="completed", completed_steps=32)
            write(path/"result.json", index)
            with self.assertRaisesRegex(ValueError, "canonical ledger/index"):
                load_record(path)
            bad = partial_result()
            bad["record"]["status"] = "completed"
            with self.assertRaisesRegex(ValueError, "retained physical prefix"):
                write_trace(Path(temp)/"wrong32", bad)
            with patch("cell_field_remaining_run_compressed_v8.gzip.GzipFile", side_effect=OSError("fixture disk full")):
                with self.assertRaises(OSError):
                    write_trace(Path(temp)/"disk_error", partial_result())
            self.assertFalse((Path(temp)/"disk_error/result.json").exists())
            self.assertFalse((Path(temp)/"control_seal.json").exists())


if __name__ == "__main__":
    unittest.main()
