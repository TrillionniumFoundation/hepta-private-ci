"""Synthetic negative controls for 3x40 Q24 paired receipts; no efficacy claims."""
from __future__ import annotations

import copy
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import repeat_prepared_pair as repeated
import run_prepared_pair as paired
import test_verify_prepared_pair_report as old_fixture


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def reports(count: int = 3) -> list[dict]:
    return [copy.deepcopy(old_fixture.synthetic_report()) for _ in range(count)]


class RepeatedPairTests(unittest.TestCase):
    def test_three_repetitions_retain_120_original_process_receipts(self) -> None:
        out = repeated.aggregate(reports())
        self.assertEqual(out["repetitions"], 3)
        self.assertEqual(out["arm_scale_pairs"], 20)
        self.assertEqual(out["original_raw_native_process_receipts"], 120)
        self.assertEqual(len(out["raw_round_reports"]), 3)
        self.assertEqual(len(out["structural_round_audits"]), 3)
        self.assertEqual(out["comparisons"][0]["repeat_count"], 3)
        self.assertEqual(len(out["comparisons"][0]["per_repeat_raw_comparisons"]), 3)
        self.assertFalse(out["qualified_ci_host"])
        self.assertFalse(out["certified_p99_or_rss_improvement"])
        self.assertFalse(out["production_qualification"])
        self.assertEqual(out["decision"], "NO_PROMOTION")

    def test_zero_one_two_or_more_than_five_repetitions_rejected(self) -> None:
        for count in (0, 1, 2, 4, 6):
            with self.subTest(count=count):
                with self.assertRaises(ValueError):
                    repeated.aggregate(reports(count))

    def test_every_native_round_is_reaudited(self) -> None:
        value = reports()
        value[1]["pairs"][0]["prepared_p99_tick_nanos"] = 0
        with self.assertRaisesRegex(ValueError, "not reproducible"):
            repeated.aggregate(value)

    def test_changed_binary_and_trace_digests_rejected(self) -> None:
        for key in ("source_binary_sha256_claim", "source_trace_sha256"):
            value = reports()
            value[1][key] = sha(b"other")
            with self.subTest(key=key):
                with self.assertRaises(ValueError):
                    repeated.aggregate(value)

    def test_all_original_mode_frontiers_can_be_self_consistent_but_rounds_drift(self) -> None:
        value = reports()
        row = value[1]["pairs"][0]
        original = row["raw_mode_receipts"]
        for mode in paired.MODES:
            original[mode]["frontier_digest"] = sha(b"different-validated-frontier")
        value[1]["pairs"][0] = paired.validate_pair(
            original, row["arm"], row["cells"], value[1]["source_trace_sha256"], 8
        )
        with self.assertRaisesRegex(ValueError, "repetition changed Q24 checkpoint frontier"):
            repeated.aggregate(value)

    def test_rejects_forged_host_quality_or_ndu_authority(self) -> None:
        for key in ("target_host_certified", "ndu_eligible", "production_qualification"):
            value = reports()
            value[2][key] = True
            with self.subTest(key=key):
                with self.assertRaises(ValueError):
                    repeated.aggregate(value)

    def test_rejects_unverified_nonfinite_or_zero_ratios(self) -> None:
        for raw in ("0", "-1", "NaN", "Infinity", "", "a"):
            with self.subTest(value=raw):
                with self.assertRaises(ValueError):
                    repeated.positive_decimal(raw)

    def test_runner_executes_120_fresh_subprocesses_and_alternates_order(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            binary = Path(tmp) / "native"
            binary.write_bytes(b"binary")
            trace = Path(tmp) / "trace.json"
            trace.write_bytes(b"fixture mock only")
            offsets = []

            def fake_run(_binary, _trace, *, order_offset):
                offsets.append(order_offset)
                return copy.deepcopy(old_fixture.synthetic_report())

            with patch.object(repeated.paired, "run", side_effect=fake_run):
                out = repeated.run(binary, trace, 3)
            self.assertEqual(offsets, [0, 1, 0])
            self.assertEqual(out["original_raw_native_process_receipts"], 120)

    def test_wrong_physical_binary_fails_on_reaudit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "native"
            path.write_bytes(b"not-the-declared-binary")
            with self.assertRaisesRegex(ValueError, "executable SHA"):
                repeated.aggregate(reports(), binary=path)

    def test_descriptive_stats_do_not_claim_a_confidence_interval(self) -> None:
        from decimal import Decimal
        summary = repeated.describe([Decimal("1.1"), Decimal("1.7"), Decimal("2.3")])
        self.assertEqual(summary, {
            "minimum": "1.1", "median": "1.7", "maximum": "2.3"
        })
        self.assertNotIn("confidence_interval", summary)


if __name__ == "__main__":
    unittest.main()
