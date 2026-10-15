"""Actual archive/resource fail-closed tests; no model weights loaded for inference."""

from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from memory_native_adapter_cost import audit, measure_benchmark, positive
from memory_parametric_behavior_audit import ARCHIVES, verified_archive


class ResourceReceiptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        names = {
            "locomo": os.environ.get("MEMORY_NATIVE_LOCOMO_ZIP"),
            "longmemeval": os.environ.get("MEMORY_NATIVE_LONGMEMEVAL_ZIP"),
        }
        if not all(names.values()):
            raise unittest.SkipTest("two exact historical source ZIP paths required")
        cls.paths = {k: Path(v) for k, v in names.items()}
        cls.proofs = {k: verified_archive(cls.paths[k], k) for k in ARCHIVES}

    def test_actual_adapter_resources_and_no_quality_promotion(self):
        result = audit(self.paths)
        self.assertEqual(result["original_model_calls"], 128)
        self.assertEqual(result["trained_adapter_instances"], 32)
        self.assertEqual(result["original_optimizer_steps"], 128)
        self.assertEqual(result["original_training_tokens"], 15037)
        self.assertAlmostEqual(result["measured_training_seconds_sum"], 78.745424207)
        self.assertEqual(result["original_saved_adapter_tensor_bytes"], 29985792)
        self.assertEqual(result["scored_f1_positive_parameter_wins"], 0)
        self.assertEqual(result["original_parameter_answer_strings_identical"], 63)
        self.assertIsNone(result["cost_per_incremental_scored_win"])
        self.assertFalse(result["learned_parameter_promotion_allowed"])
        self.assertFalse(result["production_qualified"])

    def test_per_benchmark_tensor_count_and_lineage(self):
        for benchmark in ARCHIVES:
            with self.subTest(benchmark=benchmark):
                r = measure_benchmark(self.paths[benchmark], benchmark)
                self.assertEqual(r["actual_training_tasks"], 16)
                self.assertEqual(r["actual_optimizer_steps"], 64)
                self.assertEqual(r["saved_adapter_tensor_count"], 16)
                self.assertEqual(r["saved_tensor_bytes_per_adapter"], 937056)
                self.assertEqual(r["saved_adapter_tensor_bytes"], 14992896)
                self.assertEqual(r["trainable_parameters_per_adapter"], 230400)
                self.assertEqual(
                    r["optimizer_state_bytes_per_training_instance"], 1843680
                )
                self.assertGreater(r["min_trainable_delta_norm_squared"], 0)

    def test_missing_lineage_is_not_allowed(self):
        benchmark = "locomo"
        proof = deepcopy(self.proofs[benchmark])
        item = next(iter(proof["results"]["rag_lora"]))
        for arm in ("rag_lora", "parametric_only"):
            proof["results"][arm][item]["training"]["artifact_reload"][
                "manifest_sha256"
            ] = "0" * 64
        with self.assertRaisesRegex(
            ValueError, "missing or reused trained adapter lineage"
        ):
            measure_benchmark(self.paths[benchmark], benchmark, proof=proof)

    def test_change_training_receipt_between_arms_rejected(self):
        benchmark = "locomo"
        proof = deepcopy(self.proofs[benchmark])
        item = next(iter(proof["results"]["rag_lora"]))
        proof["results"]["parametric_only"][item]["training"]["steps"] = 0
        with self.assertRaisesRegex(ValueError, "parameter arms disagree"):
            measure_benchmark(self.paths[benchmark], benchmark, proof=proof)

    def test_invalid_training_duration_rejected(self):
        benchmark = "longmemeval"
        proof = deepcopy(self.proofs[benchmark])
        item = next(iter(proof["results"]["rag_lora"]))
        proof["results"]["rag_lora"][item]["training"]["train_seconds"] = -1
        proof["results"]["parametric_only"][item]["training"]["train_seconds"] = -1
        with self.assertRaisesRegex(ValueError, "training seconds"):
            measure_benchmark(self.paths[benchmark], benchmark, proof=proof)

    def test_mismatched_training_frozen_tensor_layout_rejected(self):
        benchmark = "locomo"
        proof = deepcopy(self.proofs[benchmark])
        item = next(iter(proof["results"]["rag_lora"]))
        for arm in ("rag_lora", "parametric_only"):
            proof["results"][arm][item]["training"]["trainable_parameters"] = 2
        with self.assertRaisesRegex(ValueError, "four-step candidate"):
            measure_benchmark(self.paths[benchmark], benchmark, proof=proof)

    def test_forged_positive_delta_or_nonfinite_not_measured(self):
        for v in (True, 0, -1, float("nan"), float("inf")):
            with self.subTest(v=v), self.assertRaises(ValueError):
                positive(v, "gradient norm")

    def test_wrong_archive_cannot_replace_original_lineage(self):
        with self.assertRaisesRegex(ValueError, "whole-ZIP SHA-256"):
            measure_benchmark(self.paths["locomo"], "longmemeval")

    def test_original_cost_missing_terms_remain_unknown(self):
        result = audit(self.paths)
        self.assertIsNone(result["actual_production_total_cost"])
        self.assertFalse(result["complete_total_cost_benefit_established"])
        self.assertIn("revocation", result["missing_cost_terms"])
        self.assertIn("raw_source_retention", result["missing_cost_terms"])
        self.assertFalse(result["independent_human_semantic_citation_review"])
        self.assertEqual(result["new_model_calls"], 0)

    def test_cli_produces_new_immutable_report_and_rejects_overwrite(self):
        script = Path(__file__).with_name("memory_native_adapter_cost.py")
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "result.json"
            argv = [
                sys.executable,
                str(script),
                "--locomo",
                str(self.paths["locomo"]),
                "--longmemeval",
                str(self.paths["longmemeval"]),
                "--output",
                str(target),
            ]
            p = subprocess.run(argv, capture_output=True, text=True, timeout=90)
            self.assertEqual(p.returncode, 0, p.stderr)
            report = json.loads(target.read_bytes())
            self.assertEqual(report["original_saved_adapter_tensor_bytes"], 29985792)
            original = target.read_bytes()
            q = subprocess.run(argv, capture_output=True, text=True, timeout=90)
            self.assertNotEqual(q.returncode, 0)
            self.assertEqual(target.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
