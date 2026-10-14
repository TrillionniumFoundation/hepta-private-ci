"""Unittest coverage for the tensor-only Cell-head mechanism probe."""

import sys
from pathlib import Path
import unittest

try:
    import torch
except ImportError:  # pragma: no cover - CI installs pinned torch
    torch = None

sys.path.insert(0, str(Path(__file__).parent))
if torch is not None:
    from full_cell_heads_probe import (  # noqa: E402
        HEAD_KINDS,
        LowRankOutputAdapter,
        actual_param_counts,
        fixture,
        make_head,
        run_probe,
        source_digest,
        train_head,
    )


@unittest.skipIf(torch is None, "PyTorch is installed by the hosted research workflow")
class FullCellHeadsProbeTests(unittest.TestCase):
    def test_all_heads_train_with_actual_parameters_and_controls(self):
        rows, cut = fixture()
        before = [
            (r.features.paired.clone(), r.features.frozen_scores.clone()) for r in rows
        ]
        result = run_probe(rows, cut, steps=5, rank=3)
        self.assertEqual(result["schema"], "hepta.full-cell-heads-probe.v1")
        self.assertEqual(result["rows"], result["denominator"])
        self.assertEqual(result["mechanism_smoke_only"], True)
        self.assertEqual({r["kind"] for r in result["reports"]}, set(HEAD_KINDS))
        for report in result["reports"]:
            self.assertGreater(report["param_counts"]["total"], 0)
            self.assertEqual(
                report["param_counts"]["trainable"], report["param_counts"]["total"]
            )
            self.assertEqual(report["training"]["steps"], 5)
            self.assertFalse(report["training"]["shuffled_labels"])
            self.assertGreaterEqual(report["frozen_control_accuracy"], 0)
            self.assertGreaterEqual(report["shuffled_control_accuracy"], 0)
            self.assertGreaterEqual(report["median_latency_ms"], 0)
            if report["profiler_flops"] is not None:
                self.assertGreaterEqual(report["profiler_flops"], 0)
            self.assertFalse(report["efficacy_claim"])
        for row, (x, scores) in zip(rows, before):
            self.assertTrue(torch.equal(row.features.paired, x))
            self.assertTrue(torch.equal(row.features.frozen_scores, scores))

    def test_source_digest_without_numpy_handles_bfloat16_and_mutation(self):
        rows, _ = fixture()
        original = source_digest(rows)
        self.assertEqual(original, source_digest(rows))
        rows[0].features.paired = rows[0].features.paired.to(torch.bfloat16)
        rows[0].features.frozen_scores = rows[0].features.frozen_scores.to(
            torch.bfloat16
        )
        changed_dtype = source_digest(rows)
        self.assertNotEqual(original, changed_dtype)
        self.assertEqual(changed_dtype, source_digest(rows))
        with torch.no_grad():
            rows[0].features.paired[0, 0] += 1.0
        self.assertNotEqual(changed_dtype, source_digest(rows))

    def test_explicit_rank_above_feature_dimension_fails_before_training(self):
        rows, cut = fixture()
        with self.assertRaisesRegex(ValueError, "rank exceeds"):
            run_probe(rows, cut, steps=5, rank=16)

    def test_low_rank_is_explicit_output_adapter_not_layer_lora(self):
        head = LowRankOutputAdapter(8, rank=3)
        counts = actual_param_counts(head)
        self.assertGreater(counts["total"], 0)
        self.assertFalse(hasattr(head, "base_weight"))
        self.assertEqual(head.kind, "low_rank_output_adapter")

    def test_all_rows_are_validated_before_mutation(self):
        rows, cut = fixture()
        head = make_head("gated", 8, rank=3)
        state = {name: value.clone() for name, value in head.state_dict().items()}
        bad = list(rows)
        bad[-1].positive_indices = (99,)
        with self.assertRaises(ValueError):
            train_head(head, bad, cut, steps=4)
        self.assertTrue(
            all(
                torch.equal(value, state[name])
                for name, value in head.state_dict().items()
            )
        )


if __name__ == "__main__":
    unittest.main()
