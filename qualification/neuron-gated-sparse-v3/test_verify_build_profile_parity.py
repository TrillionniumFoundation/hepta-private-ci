"""Research-only negative tests for paired DEBUG/RELEASE Q24 fixture evidence."""
from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import verify_build_profile_parity as verifier
from run_shadow_probe_matrix import ARMS, SCALES, EVIDENCE_KIND, REPORT_SCHEMA


def digest(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def make_matrix(debug_assertions: bool) -> dict:
    trace_hash = digest("frozen-common-q24-events")
    measurements = []
    for cells in SCALES:
        for arm in ARMS:
            measurements.append({
                "schema": REPORT_SCHEMA,
                "evidence_kind": EVIDENCE_KIND,
                "production_qualification": False,
                "ndu_eligible": False,
                "trained_model": False,
                "all_model_parameter_budgets_matched": False,
                "state_persistence_measured": False,
                "microbatch_and_gpu_measured": False,
                "artifact_provenance_verified": False,
                "compiler_debug_assertions_enabled": debug_assertions,
                "arm": arm,
                "cells": cells,
                "width": 32,
                "trace_sha256": trace_hash,
                "logical_tick_count": cells * 8,
                "process_wall_micros": 10_000,
                "p50_tick_nanos": 100,
                "p95_tick_nanos": 200,
                "p99_tick_nanos": 300 if debug_assertions else 250,
                "process_peak_rss_bytes": 1_024_000,
                "mechanism_tick_throughput_per_second_milli": (
                    1_000_000 if debug_assertions else 1_200_000),
                "frontier_digest": digest(f"native-checkpoint:{arm}:{cells}"),
                "temporal_parameter_count_only": 192 if arm == "min_gru" else None,
                "warning": "synthetic protocol test, not physical execution",
            })
    return {
        "schema": "hepta.neuron.mechanism-only-matrix.v1",
        "source_evidence_kind": EVIDENCE_KIND,
        "target_host_qualified": False,
        "trained_artifacts_qualified": False,
        "parameter_budgets_matched": False,
        "ndu_eligible": False,
        "trace_sha256": trace_hash,
        "arms": list(ARMS),
        "scales": list(SCALES),
        "results": measurements,
        "warning": "synthetic protocol test, not native verification",
    }


class BuildProfileParityTests(unittest.TestCase):
    def matrices(self):
        return make_matrix(True), make_matrix(False)

    def test_complete_pairs_keep_disposition_denied(self):
        debug, release = self.matrices()
        result = verifier.compare(debug, release)
        self.assertEqual(result["pair_count"], 20)
        self.assertEqual(len(result["pairs"]), 20)
        self.assertTrue(result["all_twenty_native_frontier_pairs_equal"])
        self.assertTrue(result["profiles_compiled_debug_assertions_differ"])
        self.assertFalse(result["ndu_eligible"])
        self.assertFalse(result["production_qualification"])
        self.assertFalse(result["learned_heads_or_future_quality_evaluated"])
        self.assertFalse(result["native_optimizer_flags_independently_attested"])
        self.assertEqual(result["pairs"][0]["release_over_debug_p99_ratio"],
                         "0.833333")

    def test_missing_or_forged_compiler_mode_rejected(self):
        for field, value in (
            ("debug", None), ("debug", False), ("debug", "true"),
            ("release", None), ("release", True), ("release", 0),
        ):
            with self.subTest(field=field, value=value):
                a, b = self.matrices()
                victim = a if field == "debug" else b
                if value is None:
                    victim["results"][0].pop("compiler_debug_assertions_enabled")
                else:
                    victim["results"][0]["compiler_debug_assertions_enabled"] = value
                with self.assertRaisesRegex(ValueError, "compiled assertion mode"):
                    verifier.compare(a, b)

    def test_mismatched_q24_frontier_is_not_paired(self):
        a, b = self.matrices()
        b["results"][14]["frontier_digest"] = digest("different-transition")
        with self.assertRaisesRegex(ValueError, "frontier_digest"):
            verifier.compare(a, b)

    def test_parameter_geometry_or_width_drift_not_a_build_comparison(self):
        for field, value in (
            ("width", 64),
            ("temporal_parameter_count_only", 11),
            ("logical_tick_count", 3),
            ("trace_sha256", digest("different-case")),
        ):
            a, b = self.matrices()
            b["results"][19][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                verifier.compare(a, b)

    def test_same_input_trace_mandatory_even_if_frontiers_forged(self):
        a, b = self.matrices()
        new_trace = digest("different-input")
        b["trace_sha256"] = new_trace
        for row in b["results"]:
            row["trace_sha256"] = new_trace
        with self.assertRaisesRegex(ValueError, "input trace drift"):
            verifier.compare(a, b)

    def test_duplicate_or_missing_record_must_reject(self):
        a, b = self.matrices()
        b["results"][-1] = copy.deepcopy(b["results"][0])
        with self.assertRaisesRegex(ValueError, "duplicate"):
            verifier.compare(a, b)
        a, b = self.matrices()
        a["results"].pop()
        with self.assertRaisesRegex(ValueError, "exactly 20"):
            verifier.compare(a, b)

    def test_forbidden_authority_and_fake_quality_rejected(self):
        for key in ("ndu_eligible", "target_host_qualified",
                    "trained_artifacts_qualified", "parameter_budgets_matched"):
            a, b = self.matrices()
            b[key] = True
            with self.subTest(key=key), self.assertRaises(ValueError):
                verifier.compare(a, b)

    def test_zero_or_nonfinite_metrics_reject(self):
        a, b = self.matrices()
        b["results"][3]["p99_tick_nanos"] = 0
        with self.assertRaises(ValueError):
            verifier.compare(a, b)
        a, b = self.matrices()
        b["results"][3]["mechanism_tick_throughput_per_second_milli"] = True
        with self.assertRaises(ValueError):
            verifier.compare(a, b)

    def test_parser_exact_digest_and_duplicate_json_reject(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "artifact.json"
            raw = json.dumps(make_matrix(True)).encode()
            path.write_bytes(raw)
            doc, observed = verifier.read_snapshot(path)
            self.assertEqual(observed, hashlib.sha256(raw).hexdigest())
            self.assertTrue(doc["results"][0]["compiler_debug_assertions_enabled"])
            path.write_text('{"schema":"fake","schema":"other"}')
            with self.assertRaisesRegex(ValueError, "duplicate JSON key"):
                verifier.read_snapshot(path)

    def test_symlink_missing_or_unbounded_file_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            original = root / "matrix.json"
            original.write_text(json.dumps(make_matrix(True)))
            link = root / "alias.json"
            link.symlink_to(original)
            with self.assertRaises(OSError):
                verifier.read_snapshot(link)
            missing = root / "missing.json"
            with self.assertRaises(OSError):
                verifier.read_snapshot(missing)
            original.write_bytes(b"x" * (verifier.MAX_BYTES + 1))
            with self.assertRaisesRegex(ValueError, "unbounded"):
                verifier.read_snapshot(original)

    def test_cli_create_once_and_no_implicit_authority(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            debug = root / "debug.json"
            release = root / "release.json"
            output = root / "paired.json"
            debug.write_text(json.dumps(make_matrix(True)))
            release.write_text(json.dumps(make_matrix(False)))
            argv = [sys.executable, str(Path(verifier.__file__)),
                    "--debug-matrix", str(debug),
                    "--release-matrix", str(release),
                    "--output", str(output)]
            run = subprocess.run(argv, text=True, capture_output=True)
            self.assertEqual(run.returncode, 0, run.stderr)
            result = json.loads(output.read_text())
            self.assertEqual(result["decision"], "NO_MODEL_PROMOTION")
            self.assertFalse(result["same_source_native_binary_identity_independently_signed"])
            self.assertEqual(len(result["debug_matrix_file_sha256"]), 64)
            second = subprocess.run(argv, text=True, capture_output=True)
            self.assertNotEqual(second.returncode, 0)
            self.assertIn("BLOCKED_BUILD_PROFILE_PARITY", second.stderr)

    def test_same_physical_path_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            a = Path(temp) / "one.json"
            a.write_text(json.dumps(make_matrix(True)))
            run = subprocess.run(
                [sys.executable, str(Path(verifier.__file__)),
                 "--debug-matrix", str(a), "--release-matrix", str(a),
                 "--output", str(Path(temp) / "result.json")],
                capture_output=True, text=True,
            )
            self.assertNotEqual(run.returncode, 0)
            self.assertIn("must not be one input path", run.stderr)


if __name__ == "__main__":
    unittest.main()
