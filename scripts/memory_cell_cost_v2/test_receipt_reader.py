"""Failure charging, raw identity and latency denominators are accounting gates."""

import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from receipt_reader import load_summary, read_receipt, total


class ReceiptTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def receipt(self, name, cpu, rc):
        folder = self.root / name
        folder.mkdir()
        (folder / "stdout.log").write_bytes(b"raw")
        (folder / "stderr.log").write_bytes(b"")
        value = {
            "wall_seconds": 1.25,
            "cpu_seconds": cpu,
            "returncode": rc,
            "stdout_sha256": hashlib.sha256(b"raw").hexdigest(),
            "stderr_sha256": hashlib.sha256(b"").hexdigest(),
        }
        path = folder / "receipt.json"
        path.write_text(json.dumps(value))
        return path

    def test_failed_cpu_charged_missing_meter_not_zero(self):
        a = read_receipt(
            self.receipt("failed", 2.5, 1), format_name="procedural-v1", attempt_id="a"
        )
        b = read_receipt(
            self.receipt("unknown", None, None),
            format_name="procedural-v1",
            attempt_id="b",
        )
        value = total([a, b])
        self.assertEqual(value["failed_attempts"], 2)
        self.assertEqual(
            value["dimensions"]["cpu_ns"],
            {"total": None, "known_subtotal": 2_500_000_000, "unknown_attempts": 1},
        )
        self.assertIsNone(value["billing_usd"])

    def test_nested_attribution_not_charged_twice(self):
        a = read_receipt(
            self.receipt("outer", 3, 0), format_name="procedural-v1", attempt_id="a"
        )
        b = read_receipt(
            self.receipt("nested", 2, 0),
            format_name="procedural-v1",
            attempt_id="b",
            role="attribution",
            parent_id="a",
        )
        self.assertEqual(total([a, b])["dimensions"]["cpu_ns"]["total"], 3_000_000_000)
        with self.assertRaises(ValueError):
            total([b])
        with self.assertRaises(ValueError):
            total([a, dict(a, attempt_id="copied")])

    def test_stream_drift_and_invalid_cpu_fail_closed(self):
        p = self.receipt("drift", 1, 0)
        (p.parent / "stdout.log").write_bytes(b"changed")
        with self.assertRaises(ValueError):
            read_receipt(p, format_name="procedural-v1", attempt_id="a")
        with self.assertRaises(ValueError):
            read_receipt(
                self.receipt("negative", -1, 0),
                format_name="procedural-v1",
                attempt_id="b",
            )

    def test_failed_sample_and_unattempted_denominator_retained(self):
        rows = [
            dict(
                phase="warmup",
                index=0,
                start_ns=0,
                end_ns=5,
                wall_ns=5,
                cpu_ns=4,
                success=True,
            ),
            dict(
                phase="measured",
                index=0,
                start_ns=10,
                end_ns=20,
                wall_ns=10,
                cpu_ns=8,
                success=True,
            ),
            dict(
                phase="measured",
                index=1,
                start_ns=30,
                end_ns=50,
                wall_ns=20,
                cpu_ns=17,
                success=False,
            ),
        ]
        value = load_summary(rows, 18)
        self.assertEqual(
            (value["attempted"], value["failed"], value["unattempted"]), (2, 1, 16)
        )
        self.assertEqual(
            (value["p50_all_attempts_ns"], value["p95_all_attempts_ns"]), (10, 20)
        )
        self.assertEqual(value["successful_queries_per_second"], 25_000_000)
        empty = load_summary([], 18)
        self.assertIsNone(empty["p95_all_attempts_ns"])
        self.assertIsNone(empty["successful_queries_per_second"])
        with self.assertRaises(ValueError):
            load_summary(rows + [rows[-1]], 18)


if __name__ == "__main__":
    unittest.main()
