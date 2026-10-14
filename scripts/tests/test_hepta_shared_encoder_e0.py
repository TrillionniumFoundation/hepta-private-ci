"""Offline standard-library contract tests; no deployed Encoder assumed."""

import importlib.util
import os
from pathlib import Path
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "hepta-shared-encoder-e0.py"
SPEC = importlib.util.spec_from_file_location("hepta_shared_encoder_e0", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

CaptureError = MODULE.CaptureError
capture_baseline = MODULE.capture_baseline
capture_process = MODULE.capture_process
parse_stat = MODULE.parse_stat
parse_memory_kib = MODULE.parse_memory_kib
main = MODULE.main


class ProcessCaptureTests(unittest.TestCase):
    def test_stat_handles_parens_and_spaces(self):
        # proc(5) field 3 first, field 22 index 19, field 24 index 21.
        tail = ["S"] + ["0"] * 21
        tail[11] = "21"
        tail[12] = "5"
        tail[19] = "222"
        tail[21] = "64"
        parsed = parse_stat("17 (model ) strange) " + " ".join(tail))
        self.assertEqual(parsed["pid"], 17)
        self.assertEqual(parsed["start_time_ticks"], 222)
        self.assertEqual(parsed["rss_pages"], 64)

    def test_non_kib_mem_and_malformed_stat_rejected(self):
        with self.assertRaises(CaptureError):
            parse_memory_kib("VmRSS:\t42 MB", {"VmRSS"})
        with self.assertRaises(CaptureError):
            parse_stat("not a process stat")

    def test_duplicate_memory_fields_and_invalid_counter_rejected(self):
        with self.assertRaisesRegex(CaptureError, "duplicate"):
            parse_memory_kib("VmRSS: 100 kB\nVmRSS: 200 kB", {"VmRSS"})
        tail = ["S"] + ["0"] * 21
        tail[19] = "22"
        tail[21] = "-1"
        with self.assertRaises(CaptureError):
            parse_stat("17 (worker) " + " ".join(tail))

    def test_bounds_and_real_self_process_sample(self):
        for kwargs in ({"samples": 1}, {"samples": 257}, {"interval_ms": 0}):
            with self.assertRaises(CaptureError):
                capture_process(os.getpid(), **kwargs)
        result = capture_process(os.getpid(), samples=2, interval_ms=1, sleep=lambda _: None)
        self.assertEqual(result["sample_count"], 2)
        self.assertEqual(len(result["observations"]), 2)
        self.assertGreater(result["rss_pages_max"], 0)

    def test_never_upgrades_manifest_hash_to_execution_proof(self):
        with tempfile.TemporaryDirectory() as path:
            root = Path(path)
            manifest = root / "model.json"
            manifest.write_text('{"model":"fixture"}', encoding="utf-8")
            report = capture_baseline(os.getpid(), manifest, samples=2, interval_ms=1)
            self.assertEqual(report["status"], "PROCESS_OBSERVED_E0_INCOMPLETE")
            self.assertFalse(report["signed_runtime_execution_verified"])
            self.assertFalse(report["production_promotion_permitted"])
            self.assertIsNone(report["receipt_file_sha256_unverified"])
            out = root / "report.json"
            self.assertEqual(main([
                "--pid", str(os.getpid()), "--manifest", str(manifest),
                "--samples", "2", "--interval-ms", "1", "--out", str(out),
            ]), 0)
            self.assertTrue(out.exists())
            self.assertEqual(main([
                "--pid", str(os.getpid()), "--manifest", str(manifest),
                "--out", str(out),
            ]), 2)


if __name__ == "__main__":
    unittest.main()
