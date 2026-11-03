"""Native compact-evidence roundtrip and confirmation generation fail-closed."""

import gzip
import json
import zlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ..audit import audit_episode
from ..ndu import NativeNduPort
from ..study import ARMS, run_episode, replay_episode, run_frozen
from ..study_io import HERE, GzipLedger, atomic_json, file_record, model_from_file, verify_records
from ..task import scenarios


class FrozenStudyTests(unittest.TestCase):
    def test_confirmation_generator_is_not_called_without_valid_freeze(self):
        with tempfile.TemporaryDirectory(dir=HERE) as directory:
            folder = Path(directory)
            freeze = folder / "invalid.json"
            atomic_json(freeze, {"schema": "wrong"})
            with patch("experiments.first_passage_cell.study.scenarios") as generator:
                with self.assertRaisesRegex(ValueError, "freeze"):
                    run_frozen(HERE / "prepared", folder, freeze, object(), "confirmation")
            generator.assert_not_called()

    def test_atomic_receipts_do_not_overwrite_and_detect_tampering(self):
        with tempfile.TemporaryDirectory(dir=HERE) as directory:
            path = Path(directory) / "receipt.json"
            atomic_json(path, {"one": 1})
            record = file_record(path)
            verify_records([record])
            with self.assertRaises(FileExistsError):
                atomic_json(path, {"two": 2})
            path.write_text('{"one":2}\n')
            with self.assertRaisesRegex(ValueError, "mismatch"):
                verify_records([record])

    def test_reserved_gzip_truncates_padding_and_preserves_exact_stream(self):
        with tempfile.TemporaryDirectory(dir=HERE) as directory:
            path = Path(directory) / "reserved.jsonl.gz"
            with GzipLedger(path, reserve_bytes=1024 * 1024) as ledger:
                self.assertEqual(ledger.temporary.stat().st_size, 1024 * 1024)
                ledger.append({"observation": 3, "reward": -1.5})
            self.assertLess(path.stat().st_size, 200)
            decompressor = zlib.decompressobj(16 + zlib.MAX_WBITS)
            payload = decompressor.decompress(path.read_bytes()) + decompressor.flush()
            self.assertEqual(decompressor.unused_data, b"")
            self.assertEqual(json.loads(payload), {"observation": 3, "reward": -1.5})
            with GzipLedger(Path(directory) / "unreserved.jsonl.gz", reserve_bytes=0) as ledger:
                ledger.append({"one": 1})

    def test_reserved_capacity_failure_preserves_an_explicit_incomplete_file(self):
        with tempfile.TemporaryDirectory(dir=HERE) as directory:
            path = Path(directory) / "small.jsonl.gz"
            with self.assertRaises(OSError):
                with GzipLedger(path, reserve_bytes=16) as ledger:
                    ledger.append({"value": "not enough capacity"})
            self.assertFalse(path.exists())
            self.assertTrue(path.with_suffix(path.suffix + ".incomplete").exists())
            self.assertLessEqual(path.with_suffix(path.suffix + ".incomplete").stat().st_size, 16)

    @unittest.skipUnless((HERE / "NATIVE_BUILD.json").exists()
                         and (HERE / "prepared" / "1103" / "model6.json").exists(),
                         "Requires the registered prepared model and built original NDU")
    def test_all_arms_retain_exact_factual_ledger_and_replay_native_receipts(self):
        native = NativeNduPort(HERE / "NATIVE_BUILD.json")
        model_path = HERE / "prepared" / "1103" / "model6.json"
        parameters, _ = model_from_file(model_path)
        scenario = scenarios(1103, 1, "diagnostic")[0]
        with tempfile.TemporaryDirectory(dir=HERE) as directory:
            path = Path(directory) / "episodes.jsonl.gz"
            with GzipLedger(path) as ledger:
                for index, arm in enumerate(ARMS):
                    parameter = 0.35 if arm == "learned_threshold7" else 0.0
                    chosen_path = (HERE / "prepared" / "1103" / "model7.json"
                                   if arm == "fixed_cross7" else model_path)
                    chosen = model_from_file(chosen_path)[0]
                    episode = run_episode(1103, "diagnostic", arm, scenario, chosen,
                                          chosen_path, native, parameter, {}, retain_full=index == 0)
                    audit_episode(episode)
                    self.assertGreaterEqual(episode["runtime"]["native_calls"], 1)
                    self.assertLess(abs(episode["total_reward"] - episode["realized_native_return"]), 2e-9)
                    ledger.append(episode)
            for index in range(len(ARMS)):
                replayed = replay_episode(path, index, native)
                self.assertTrue(replayed["realized_receipt_replayed"])


if __name__ == "__main__":
    unittest.main()
