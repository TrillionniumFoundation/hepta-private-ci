"""Real tensor arithmetic and existing artifact integration, not model efficacy."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import torch

from experiments.shared_stem_cell import execution as e
from experiments.shared_stem_cell import head_batch as b
from experiments.shared_stem_cell.head_artifacts import export_head


class HeadBatchTests(unittest.TestCase):
    def setUp(self):
        torch.set_num_threads(1)
        torch.manual_seed(47)

    def entries(self, kind="gated", n=4, width=8):
        return tuple((i, e.Head(width, 3, kind, min(4, width)).eval()) for i in range(n))

    def test_all_existing_heads_match_with_repeats_and_reordered_cells(self):
        for kind in ("linear", "gated", "low_rank", "sparse_expert"):
            with self.subTest(kind=kind):
                entries = self.entries(kind)
                cells = (3, 0, 3, 1, 0)
                x = torch.randn(5, 8)
                before = [e.parameters(m) for _, m in entries]
                result, counts = b.PackedHeads(entries).run(x, cells)
                expected = torch.cat([entries[c][1](x[i:i+1]) for i, c in enumerate(cells)])
                torch.testing.assert_close(result, expected, atol=b.ATOL, rtol=b.RTOL)
                self.assertTrue(torch.equal(result.argmax(-1), expected.argmax(-1)))
                self.assertEqual(before, [e.parameters(m) for _, m in entries])
                self.assertEqual(counts["active_cells"], 3)
                self.assertEqual(counts["active_rows"], 5)
                self.assertFalse(result.requires_grad)

    def test_chunk_accounting_matches_actual_bmm_invocations(self):
        for kind, factor in (("linear", 1), ("gated", 4), ("low_rank", 3), ("sparse_expert", 3)):
            with self.subTest(kind=kind):
                entries = self.entries(kind, n=65)
                bank = b.PackedHeads(entries)
                with patch.object(torch, "bmm", wraps=torch.bmm) as actual:
                    _, counts = bank.run(torch.randn(65, 8), tuple(range(65)))
                self.assertEqual(actual.call_count, 3 * factor)
                self.assertEqual(counts["bmm_calls"], actual.call_count)
                self.assertEqual(counts["physical_chunks"], 3)
                self.assertEqual(counts["expert_rows"], 65 if kind == "sparse_expert" else 0)

    def test_sparse_gate_evaluates_only_selected_expert_with_original_ties(self):
        entries = self.entries("sparse_expert", 2)
        with torch.no_grad():
            for i, (_, m) in enumerate(entries):
                m.router.weight.zero_()
                m.router.bias.copy_(torch.tensor([0., float(i)]))
                m.experts[0].weight.zero_()
                m.experts[0].bias.fill_(2)
                m.experts[1].weight.zero_()
                m.experts[1].bias.fill_(7)
        x = torch.ones(2, 8)
        value, count = b.PackedHeads(entries).run(x, (0, 1))
        expected = torch.cat([m(x[i:i+1]) for i, (_, m) in enumerate(entries)])
        torch.testing.assert_close(value, expected, atol=b.ATOL, rtol=b.RTOL)
        self.assertEqual(count["expert_rows"], 2)

    def test_late_invalid_member_rejected_before_any_arithmetic(self):
        bank = b.PackedHeads(self.entries())
        for x, cells in ((torch.ones(3, 8), (0, 1, 99)),
                         (torch.ones(3, 8), (0, 1, True)),
                         (torch.ones(3, 8, dtype=torch.float64), (0, 1, 2)),
                         (torch.ones(3, 9), (0, 1, 2)),
                         (torch.full((3, 8), float("nan")), (0, 1, 2))):
            with patch.object(torch, "bmm", wraps=torch.bmm) as actual:
                with self.assertRaises(e.InputError):
                    bank.run(x, cells)
                self.assertEqual(actual.call_count, 0)
        self.assertEqual(bank.backend_invocations, 0)

    def test_numeric_scratch_limit_rejects_then_clean_retry(self):
        bank = b.PackedHeads(self.entries())
        x, cells = torch.ones(3, 8), (0, 1, 2)
        limit = bank.preflight(x, cells, b.MAX_SCRATCH_BYTES)
        with patch.object(torch, "isfinite", wraps=torch.isfinite) as checked:
            with self.assertRaises(e.InputError):
                bank.run(x, cells, maximum_scratch_bytes=limit - 1)
            self.assertEqual(checked.call_count, 0)
        self.assertEqual(bank.backend_invocations, 0)
        bank.run(x, cells, maximum_scratch_bytes=limit)
        self.assertEqual(bank.backend_invocations, 1)

    def test_resident_parameter_budget_checked_before_stack(self):
        entries = self.entries()
        needed = sum(e.parameters(m)["parameter_bytes"] for _, m in entries)
        with patch.object(torch, "stack", wraps=torch.stack) as actual:
            with self.assertRaises(e.InputError):
                b.PackedHeads(entries, maximum_parameter_bytes=needed - 1)
            self.assertEqual(actual.call_count, 0)
        bank = b.PackedHeads(entries, maximum_parameter_bytes=needed)
        self.assertEqual(bank.parameter_bytes, needed)

    def test_duplicate_mixed_training_nonfinite_banks_reject(self):
        entries = self.entries()
        invalid = ((entries[0], entries[0]),
                   (entries[0], (4, e.Head(8, 3, "linear", 4).eval())),
                   ((0, deepcopy(entries[0][1]).train()),))
        for value in invalid:
            with self.assertRaises(e.InputError):
                b.PackedHeads(value)
        with torch.no_grad():
            entries[0][1].base.bias[0] = float("inf")
        with self.assertRaises(e.InputError):
            b.PackedHeads(entries)

    def test_owned_bank_is_independent_of_later_source_training(self):
        entries = self.entries()
        bank = b.PackedHeads(entries)
        x, cells = torch.randn(2, 8), (0, 3)
        before, _ = bank.run(x, cells)
        with torch.no_grad():
            entries[0][1].base.weight.add_(10)
        after, _ = bank.run(x, cells)
        self.assertTrue(torch.equal(before, after))
        self.assertNotEqual(bank.identity, b.PackedHeads(entries).identity)

    def test_compare_keeps_strong_grouped_baseline_and_counts_all_replays(self):
        entries = self.entries()
        cells = (2, 0, 2, 0, 2)
        with patch.object(entries[1][1], "forward", wraps=entries[1][1].forward) as idle:
            with patch.object(entries[2][1], "forward", wraps=entries[2][1].forward) as active:
                report = b.compare_heads(entries, torch.randn(5, 8), cells, repetitions=3)
        self.assertEqual(idle.call_count, 0)
        self.assertEqual(active.call_count, 3)  # one grouped call per repeat, not per row
        self.assertEqual(report["counts"]["per_cell_grouped"]["head_forward_calls"], 2)
        self.assertEqual({k: len(v) for k, v in report["samples_ns"].items()},
                         {"packed": 3, "per_cell_grouped": 3})
        self.assertTrue(report["numerical_parity_passed"])
        self.assertFalse(report["production_accepted"])

    def test_mismatch_is_reported_not_repaired_or_promoted(self):
        original = b.PackedHeads.run
        def wrong(bank, *args, **kwargs):
            value, info = original(bank, *args, **kwargs)
            value[:, 0] += 10
            return value, info
        with patch.object(b.PackedHeads, "run", wrong):
            report = b.compare_heads(self.entries(), torch.randn(4, 8), (0, 1, 2, 3), repetitions=3)
        self.assertFalse(report["numerical_parity_passed"])
        self.assertIsNone(report["pack_amortization_replays"])
        self.assertGreater(report["max_absolute_logit_difference"], 9)
        self.assertNotEqual(report["logits"]["packed"], report["logits"]["per_cell_grouped"])

    def test_repeated_rows_gather_each_head_once_per_bounded_block(self):
        bank = b.PackedHeads(self.entries(n=4))
        value, counts = bank.run(torch.randn(32, 8), (0, 1, 2, 3) * 8)
        self.assertEqual(counts["gathered_head_blocks"], 4)
        self.assertEqual(counts["physical_chunks"], 1)
        self.assertEqual(value.shape, (32, 3))

    def test_uneven_large_cell_groups_preserve_every_original_row(self):
        entries = self.entries("sparse_expert", n=4)
        cells = (3,) * 70 + (0,) * 8 + (1,) * 3
        x = torch.randn(len(cells), 8)
        value, counts = b.PackedHeads(entries).run(x, cells)
        reference = torch.empty_like(value)
        for cell, model in entries:
            ids = [i for i, c in enumerate(cells) if c == cell]
            if ids:
                reference[ids] = model(x[ids])
        torch.testing.assert_close(value, reference, atol=b.ATOL, rtol=b.RTOL)
        self.assertEqual(counts["expert_rows"], len(cells))
        self.assertEqual(counts["gathered_head_blocks"], 5)

    def test_actual_export_reload_and_generation_consistency(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            x = torch.randn(6, 8)
            cases = tuple(e.Case(str(i), str(i), "holdout", None, i % 2, "scope", str(i)) for i in range(6))
            costs = []
            for cell, model in self.entries(n=2):
                binding = {"logical_cell": str(cell), "scope": "scope", "generation": 1,
                           **{k: "a" * 64 for k in ("stem_sha256", "dataset_sha256", "feature_profile_sha256", "training_lineage_sha256")}}
                receipt = export_head(root / "gated" / f"cell-{cell}" / "learned", model, binding)
                costs.append({"cell": cell, "offline_head_artifacts": {"learned": {**receipt, "binding": binding}}})
            result = b.compare_exported_heads(root, {"gated": costs}, x, cases, repetitions=3)
            self.assertEqual(result["gated"]["case_ids"], [str(i) for i in range(6)])
            self.assertTrue(result["gated"]["numerical_parity_passed"])
            costs[-1]["offline_head_artifacts"]["learned"]["binding"]["generation"] = 2
            with self.assertRaises(e.InputError):
                b.compare_exported_heads(root, {"gated": costs}, x, cases, repetitions=3)

    def test_existing_execution_entrypoint_uses_actual_exported_heads_without_reencoding(self):
        class Encoder:
            identity = "a" * 64
            simulated = True
            calls = 0
            def __init__(self, *args):
                pass
            def encode(self, texts):
                Encoder.calls += 1
                return torch.tensor([[len(t), i + 1] for i, t in enumerate(texts)], dtype=torch.float32)
            def close(self):
                pass
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            rows = [{"case_id": str(i), "group": str(i), "split": split,
                     "observed_at": None, "cell": 0, "scope": "test-only",
                     "text": f"fixture {i}", "label": i % 2}
                    for i, split in enumerate(("train", "train", "calibration", "holdout"))]
            raw = b"".join(e.canonical(row) for row in rows)
            (root / "data.jsonl").write_bytes(raw)
            manifest = {"schema": "hepta.shared-stem-execution.v1", "classes": 2, "cells": 1,
                "steps": 2, "measure_head_batch": True,
                "dataset": {"path": "data.jsonl", "sha256": e.sha(raw)}, "model": {"path": "fixture"}}
            e.write_once(root / "manifest.json", manifest)
            with patch.object(e, "LocalEncoder", Encoder):
                result = e.run(root / "manifest.json", root / "out")
            self.assertEqual(Encoder.calls, 1)
            self.assertTrue(result["head_batch_executed"])
            raw = e.bound_file(root / "out/head-batch.json", result["head_batch_sha256"])
            reports = e.decode(raw)
            self.assertEqual(set(reports), {"linear", "gated", "low_rank", "sparse_expert"})
            self.assertTrue(all(r["numerical_parity_passed"] for r in reports.values()))
            self.assertEqual(len(result["scores"]), 4)
            self.assertFalse(result["production_accepted"])

    def test_all_4096_resident_cells_with_sparse_last_cell_activation(self):
        entries = self.entries("linear", n=4096, width=1)
        bank = b.PackedHeads(entries)
        x, cells = torch.ones(3, 1), (4095, 7, 4095)
        value, stats = bank.run(x, cells)
        self.assertEqual(stats["resident_cells"], 4096)
        self.assertEqual(stats["active_cells"], 2)
        self.assertEqual(stats["bmm_calls"], 2)  # exact-size buckets: two rows vs one
        torch.testing.assert_close(value[0], entries[-1][1](x[:1])[0], atol=b.ATOL, rtol=b.RTOL)
        self.assertTrue(torch.equal(value[0], value[2]))


if __name__ == "__main__":
    unittest.main()
