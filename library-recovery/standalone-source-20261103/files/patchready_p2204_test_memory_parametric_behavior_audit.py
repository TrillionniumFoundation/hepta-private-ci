"""Immutable native Qwen pilot source tests; no additional model inference."""

from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from memory_parametric_behavior_audit import (
    ARCHIVES,
    audit,
    digest,
    score_pair,
    verified_archive,
)


class NativeParametricBehaviorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        names = {
            "locomo": os.environ.get("MEMORY_NATIVE_LOCOMO_ZIP"),
            "longmemeval": os.environ.get("MEMORY_NATIVE_LONGMEMEVAL_ZIP"),
        }
        if not all(names.values()):
            raise unittest.SkipTest(
                "both externally pinned original native ZIPs required"
            )
        cls.paths = {k: Path(v) for k, v in names.items()}
        cls.proofs = {k: verified_archive(v, k) for k, v in cls.paths.items()}

    def test_original_exact_head_128_calls_and_parameter_only_1_change(self):
        observed = audit(self.paths)
        self.assertEqual(observed["original_real_model_calls"], 128)
        self.assertEqual(observed["paired_parametric_comparisons"], 64)
        self.assertEqual(observed["paired_parametric_answers_exactly_identical"], 63)
        self.assertEqual(observed["paired_parametric_answers_changed"], 1)
        self.assertEqual(observed["distinct_source_family_proxies"], 3)
        self.assertFalse(observed["production_qualified"])
        self.assertFalse(observed["trained_parameter_advantage_established"])
        self.assertFalse(observed["independent_effective_n_certified"])

    def test_parameter_only_unmodified_answers_and_rag_one_changed(self):
        observed = audit(self.paths)["per_benchmark"]
        for bench, source in observed.items():
            with self.subTest(benchmark=bench):
                a = source["comparisons"]["no_memory_vs_parametric_only"]
                self.assertEqual(a["exact_answer_identical"], 16)
                self.assertEqual((a["f1_wins"], a["f1_losses"]), (0, 0))
                self.assertEqual(
                    source["inner_member_sha256_verified"], ARCHIVES[bench][1]
                )
        lora = observed["longmemeval"]["comparisons"]["rag_vs_rag_lora"]
        self.assertEqual(lora["exact_answer_identical"], 15)
        self.assertEqual(
            lora["changed_answer_digests"][0]["question_id"], "longmemeval:b5ef892d"
        )
        self.assertEqual(
            lora["changed_answer_digests"][0]["original_diagnostic_f1"], 0.0
        )
        self.assertEqual(
            lora["changed_answer_digests"][0]["candidate_diagnostic_f1"], 0.0
        )
        self.assertEqual(lora["f1_wins"], 0)
        self.assertEqual(lora["f1_losses"], 0)
        self.assertEqual(lora["f1_ties"], 16)

    def test_unscored_locomo_cases_retained_not_as_zero(self):
        reported = audit(self.paths)["per_benchmark"]["locomo"]["comparisons"]
        for comparison in ("no_memory_vs_parametric_only", "rag_vs_rag_lora"):
            self.assertEqual(reported[comparison]["paired_f1_scored"], 12)
            self.assertEqual(reported[comparison]["paired_f1_unscored"], 4)
            self.assertEqual(reported[comparison]["f1_ties"], 12)

    def test_changed_output_without_f1_win_is_explicit(self):
        report = self.proofs["longmemeval"]["results"]
        contrast = score_pair(report["rag"], report["rag_lora"])
        self.assertEqual(contrast["changed_answers"], 1)
        self.assertEqual(contrast["f1_wins"], 0)
        self.assertEqual(contrast["f1_losses"], 0)

    def test_changed_input_evidence_is_rejected(self):
        report = self.proofs["locomo"]["results"]
        mutated = deepcopy(report["rag_lora"])
        first = next(iter(mutated))
        mutated[first]["receipt"]["input_ids_sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "input/evidence mismatch"):
            score_pair(report["rag"], mutated)

    def test_missing_or_duplicate_question_not_a_paired_study(self):
        report = self.proofs["locomo"]["results"]
        mutated = dict(report["rag_lora"])
        mutated.pop(next(iter(mutated)))
        with self.assertRaisesRegex(ValueError, "unpaired question"):
            score_pair(report["rag"], mutated)

    def test_same_answer_cannot_receive_different_diagnostic_f1(self):
        report = self.proofs["locomo"]["results"]
        mutated = deepcopy(report["rag_lora"])
        first = next(
            k for k, row in mutated.items() if row["diagnostic_token_f1"] is not None
        )
        mutated[first]["diagnostic_token_f1"] = 0.999
        with self.assertRaisesRegex(ValueError, "identical paired answers"):
            score_pair(report["rag"], mutated)

    def test_changed_family_identity_rejected(self):
        report = self.proofs["locomo"]["results"]
        mutated = deepcopy(report["rag_lora"])
        first = next(iter(mutated))
        mutated[first]["citation_audit"]["request"]["family_digest"] = "a" * 64
        with self.assertRaisesRegex(ValueError, "source family attribution"):
            score_pair(report["rag"], mutated)

    def test_outer_sha_catches_changed_or_wrong_archives(self):
        with self.assertRaisesRegex(ValueError, "whole-ZIP SHA-256"):
            verified_archive(self.paths["locomo"], "longmemeval")
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "changed.zip"
            p.write_bytes(self.paths["locomo"].read_bytes() + b"tampered")
            with self.assertRaisesRegex(ValueError, "whole-ZIP SHA-256"):
                verified_archive(p, "locomo")

    def test_cli_roundtrip_and_no_overwrite(self):
        script = Path(__file__).with_name("memory_parametric_behavior_audit.py")
        with tempfile.TemporaryDirectory() as td:
            result = Path(td) / "result.json"
            cmd = [
                sys.executable,
                str(script),
                "--locomo",
                str(self.paths["locomo"]),
                "--longmemeval",
                str(self.paths["longmemeval"]),
                "--output",
                str(result),
            ]
            done = subprocess.run(cmd, text=True, capture_output=True, timeout=75)
            self.assertEqual(done.returncode, 0, done.stderr)
            report = json.loads(result.read_bytes())
            self.assertEqual(report["paired_parametric_answers_changed"], 1)
            self.assertIsNone(report["full_lifecycle_tco"])
            before = digest(result.read_bytes())
            repeated = subprocess.run(cmd, text=True, capture_output=True, timeout=75)
            self.assertNotEqual(repeated.returncode, 0)
            self.assertEqual(digest(result.read_bytes()), before)


if __name__ == "__main__":
    unittest.main()
