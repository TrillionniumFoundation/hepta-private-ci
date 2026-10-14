"""Only synthetic assertions about the prepared-vs-legacy native probe contract."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import run_prepared_pair as pair
import run_shadow_probe_matrix as matrix


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


TRACE = sha(b"fixture-input")


def receipt(mode: str, arm: str = "v3", cells: int = 64, frontier: str | None = None) -> dict:
    value = 600 if mode == "legacy" else 400
    return {
        "schema": matrix.REPORT_SCHEMA,
        "evidence_kind": matrix.EVIDENCE_KIND,
        "production_qualification": False,
        "ndu_eligible": False,
        "trained_model": False,
        "all_model_parameter_budgets_matched": False,
        "state_persistence_measured": False,
        "microbatch_and_gpu_measured": False,
        "artifact_provenance_verified": False,
        "arm": arm,
        "execution_mode": mode,
        "single_selected_config_resident": True,
        "simultaneous_legacy_and_prepared_config_resident": False,
        "model_config_setup_micros": 120 if mode == "legacy" else 180,
        "cells": cells,
        "width": 32,
        "trace_sha256": TRACE,
        "logical_tick_count": cells * 8,
        "process_wall_micros": 100_000 + value,
        "p50_tick_nanos": value,
        "p95_tick_nanos": value + 300,
        "p99_tick_nanos": value + 500,
        "process_peak_rss_bytes": 10_000_000 + value,
        "mechanism_tick_throughput_per_second_milli": 100_000 + (600 - value),
        "frontier_digest": frontier or sha(f"{arm}:{cells}".encode()),
    }


class PreparedPairedSmokeTests(unittest.TestCase):
    def test_exact_checkpoint_same_scale_and_no_authority(self) -> None:
        matched = {mode: receipt(mode) for mode in pair.MODES}
        result = pair.validate_pair(matched, "v3", 64, TRACE, 8)
        self.assertTrue(result["exact_checkpoint_frontier_parity"])
        self.assertEqual(result["legacy_to_prepared_p99_ratio"], "1.222222")
        self.assertGreater(result["prepared_peak_rss_bytes"], 0)
        self.assertTrue(result["separate_mode_config_residency"])
        self.assertEqual(result["legacy_model_config_setup_micros"], 120)
        self.assertEqual(result["prepared_model_config_setup_micros"], 180)
        self.assertEqual(result["raw_mode_receipts"]["legacy"], matched["legacy"])
        self.assertEqual(result["raw_mode_receipts"]["prepared"], matched["prepared"])
        self.assertEqual(
            result["raw_mode_receipt_sha256"]["legacy"],
            pair.receipt_sha256(matched["legacy"]),
        )

    def test_changed_checkpoint_digest_rejected_even_with_better_speed(self) -> None:
        matched = {mode: receipt(mode) for mode in pair.MODES}
        matched["prepared"]["frontier_digest"] = sha(b"different-digest")
        with self.assertRaisesRegex(ValueError, "changed exact checkpoint"):
            pair.validate_pair(matched, "v3", 64, TRACE, 8)

    def test_missing_mode_or_reported_mode_spoofing_rejected(self) -> None:
        for updated in (
            {"legacy": receipt("legacy")},
            {"legacy": receipt("legacy"), "prepared": receipt("legacy")},
        ):
            with self.assertRaises(ValueError):
                pair.validate_pair(updated, "v3", 64, TRACE, 8)

    def test_cannot_forge_trained_or_production_flag(self) -> None:
        for name in (
            "production_qualification", "ndu_eligible", "trained_model",
            "all_model_parameter_budgets_matched", "artifact_provenance_verified",
        ):
            value = {mode: receipt(mode) for mode in pair.MODES}
            value["prepared"][name] = True
            with self.subTest(field=name):
                with self.assertRaises(ValueError):
                    pair.validate_pair(value, "v3", 64, TRACE, 8)

    def test_wrong_arm_scale_trace_timing_and_rss_rejected(self) -> None:
        for name, changed in (
            ("arm", "ssm"), ("cells", 256), ("trace_sha256", sha(b"tampered")),
            ("process_peak_rss_bytes", None), ("p99_tick_nanos", 0),
            ("p95_tick_nanos", 100_000), ("width", 100),
            ("single_selected_config_resident", False),
            ("simultaneous_legacy_and_prepared_config_resident", True),
            ("model_config_setup_micros", -1),
        ):
            records = {mode: receipt(mode) for mode in pair.MODES}
            records["prepared"][name] = changed
            with self.subTest(field=name):
                with self.assertRaises(ValueError):
                    pair.validate_pair(records, "v3", 64, TRACE, 8)

    def test_same_fixture_orchestrates_40_fresh_process_calls(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            binary = root / "native"
            binary.write_bytes(b"fake-executable-only-for-mocked-subprocess")
            trace = root / "q24.json"
            events = [
                {"sequence": i, "monotonic_micros": i * 100,
                 "drive_q24": [0] * 32, "prediction_q24": [0] * 32}
                for i in range(1, 9)
            ]
            trace.write_text(json.dumps({
                "schema": "hepta.neuron.mechanism-probe-trace.q24.v1",
                "width": 32, "events": events,
            }))
            digest = sha(trace.read_bytes())
            called: list[tuple[str, str, int]] = []

            def fake_run(args, **kwargs):
                arm = args[args.index("--arm") + 1]
                mode = args[args.index("--mode") + 1]
                cells = int(args[args.index("--cells") + 1])
                called.append((arm, mode, cells))
                value = receipt(mode, arm, cells)
                value["trace_sha256"] = digest

                class Result:
                    returncode = 0
                    stderr = ""
                    stdout = json.dumps(value)

                return Result()

            with patch.object(pair.subprocess, "run", side_effect=fake_run):
                output = pair.run(binary, trace)
            self.assertEqual(len(called), 40)
            self.assertEqual(output["pair_count"], 20)
            self.assertEqual(output["native_subprocess_count"], 40)
            self.assertEqual(output["source_binary_sha256_claim"], sha(binary.read_bytes()))
            self.assertFalse(output["source_binary_independently_attested"])
            self.assertTrue(all(set(row["raw_mode_receipts"]) == set(pair.MODES)
                                for row in output["pairs"]))
            self.assertEqual(sum(len(row["raw_mode_receipts"]) for row in output["pairs"]), 40)
            self.assertTrue(all(row["exact_checkpoint_frontier_parity"] for row in output["pairs"]))
            self.assertFalse(output["target_host_certified"])
            self.assertFalse(output["production_qualification"])
            self.assertEqual(output["decision"], "NO_PROMOTION")

    def test_duplicate_nonfinite_or_unbounded_native_receipt_rejected(self) -> None:
        for raw, reason in (
            ('{"arm":"v3","arm":"ssm"}', "duplicate JSON key"),
            ('{"p99_tick_nanos":NaN}', "nonfinite JSON number"),
            ('[]', "native receipt must be one JSON object"),
            ('{"x":"' + "0" * pair.MAX_NATIVE_RECEIPT_JSON_BYTES + '"}',
             "unbounded native receipt output"),
        ):
            with self.subTest(reason=reason):
                with self.assertRaisesRegex(ValueError, reason):
                    pair.parse_native_receipt(raw)

    def test_empty_binary_and_real_hash_readback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bin"
            path.write_bytes(b"")
            with self.assertRaisesRegex(ValueError, "missing or unbounded"):
                pair.sha256_binary(path)
            path.write_bytes(b"known-local-binary")
            self.assertEqual(pair.sha256_binary(path), sha(b"known-local-binary"))

    def test_nonpositive_ratio_rejected(self) -> None:
        for a, b in ((0, 10), (10, 0), (True, 1), (1, False)):
            with self.assertRaises(ValueError):
                pair.measured_ratio(a, b)


if __name__ == "__main__":
    unittest.main()
