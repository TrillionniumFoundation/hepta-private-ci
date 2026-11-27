"""Fail-closed synthetic contract checks; no pretrained model or hardware call."""
from __future__ import annotations

import dataclasses
import unittest

from budget import CellUse, FeatureIdentity, Profile, estimate, example


def identity(*, scope="A", generation=1, source=4, stem=1, tokenizer=2, normalizer=3, options=5):
    def sha(x):
        return f"{x:064x}"
    return FeatureIdentity(scope, generation, sha(stem), sha(tokenizer),
                           sha(normalizer), sha(source), sha(options))


class BudgetContract(unittest.TestCase):
    def test_exact_4096_fp32_geometry_three_separate_controls(self):
        result = example(4096)
        self.assertEqual(result["fp_weight_bytes_only"]["resident_cell_heads"], 159_645_696)
        self.assertEqual(result["fp_weight_bytes_only"]["one_shared_97m_plus_heads"], 547_645_696)
        self.assertEqual(result["fp_weight_bytes_only"]["one_shared_421m_plus_heads"], 1_843_645_696)
        self.assertEqual(result["fp_weight_bytes_only"]["dedicated_421m_per_cell"], 6_897_664_000_000)
        self.assertFalse(result["measured"])
        self.assertEqual(result["hypothetical_best_reuse_distinct_scope_bound_stem_forwards"], 1)
        self.assertEqual(result["without_feature_reuse_stem_forwards"], 4096)

    def test_distinct_input_never_declares_compute_reuse(self):
        self.assertEqual(example(64, True)["saved_encoder_forwards_if_perfectly_coalesced"], 0)

    def test_scope_generation_and_source_prevent_reuse(self):
        keys = [identity(), identity(scope="B"), identity(generation=2), identity(source=8),
                identity(stem=9), identity(tokenizer=9), identity(normalizer=9), identity(options=9)]
        result = estimate([CellUse(str(i), key) for i, key in enumerate(keys)])
        self.assertEqual(result["hypothetical_best_reuse_distinct_scope_bound_stem_forwards"], len(keys))

    def test_cache_reuse_only_same_complete_identity(self):
        result = estimate([CellUse("a", identity()), CellUse("b", identity())])
        self.assertEqual(result["saved_encoder_forwards_if_perfectly_coalesced"], 1)
        self.assertEqual(result["active_cell_uses"], 2)

    def test_inactive_heads_still_count_resident_weights(self):
        result = estimate([CellUse("a", identity(), True), CellUse("b", identity(), False)])
        self.assertEqual(result["active_cell_uses"], 1)
        self.assertEqual(result["without_feature_reuse_stem_forwards"], 1)
        self.assertEqual(result["fp_weight_bytes_only"]["resident_cell_heads"], 2 * 9744 * 4)

    def test_graph_solver_work_not_hidden_in_head_counts(self):
        result = estimate([CellUse("a", identity())], graph_nodes=12, system2_solved_nodes=2)
        self.assertEqual((result["graph_nodes_declared"], result["graph_nodes_not_solved"]), (12, 10))
        self.assertIn("end_to_end_System2_cost_adjusted_advantage", result["not_proven"])

    def test_reject_noncanonical_digests_and_invalid_types(self):
        bad = [
            dataclasses.replace(identity(), source_sha256="x"),
            dataclasses.replace(identity(), source_sha256="A" * 64),
            dataclasses.replace(identity(), scope=""),
            dataclasses.replace(identity(), scope="A | B"),
            dataclasses.replace(identity(), generation=True),
            dataclasses.replace(identity(), generation=-1),
        ]
        for i, b in enumerate(bad):
            with self.subTest(i=i), self.assertRaises(ValueError):
                estimate([CellUse("a", b)])

    def test_reject_missing_identity_duplicate_ids_or_nontyped_flag(self):
        for uses in ([CellUse("a", identity()), CellUse("a", identity())],
                     [CellUse("a", identity(), 1)],
                     [CellUse("a", None)], [],
                     "this-is-not-a-workload"):
            with self.subTest(uses=str(uses)[:100]), self.assertRaises(ValueError):
                estimate(uses)

    def test_reject_unbounded_graph_and_profile(self):
        for kwargs in ({"graph_nodes": -1}, {"graph_nodes": 2, "system2_solved_nodes": 3},
                       {"graph_nodes": 1_000_001}, {"system2_solved_nodes": True}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                estimate([CellUse("a", identity())], **kwargs)
        for bad in (Profile(weight_bytes=3), Profile(weight_bytes=True),
                    Profile(gated_head_params=0), Profile(legacy_encoder_params=True)):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                estimate([CellUse("a", identity())], bad)

    def test_reject_more_than_4096_or_bool_example_count(self):
        for n in (0, 4097, True):
            with self.subTest(n=n), self.assertRaises(ValueError):
                example(n)


if __name__ == "__main__":
    unittest.main()
