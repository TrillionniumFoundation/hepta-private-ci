"""Actual tiny Torch matched-initialization loss ablation, no QA model."""

from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

import torch

from selector_evaluation import support_indices
from selector_head import Supervision
from stem_native_matched_objectives import (
    KINDS, OBJECTIVES, STAGES,
    matched_objective_shadow, review_objectives,
)
from test_stem_cell import features
from test_stem_native_pairwise_shadow import fixture, targets_and_frozen


class ObjectiveMatchedNativeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(2)

    def execute(self):
        questions, supervised, encoded, cut, routes = fixture()
        with tempfile.TemporaryDirectory() as directory:
            fitted, decisions = matched_objective_shadow(
                questions, supervised, encoded, cut, routes, Path(directory),
            )
        return questions, supervised, encoded, cut, routes, fitted, decisions

    def test_all_24_heads_and_384_choices_have_exact_same_initial_weights(self):
        _, _, _, _, _, fitted, decisions = self.execute()
        self.assertEqual(len(fitted), 24)
        self.assertEqual(len(decisions), 384)
        self.assertTrue(all(r["status"] == "succeeded" for r in fitted))
        self.assertTrue(all(r["status"] == "succeeded" for r in decisions))
        self.assertTrue(all(r["receipt"]["consumed_steps"] == 128 for r in fitted))
        for kind in KINDS:
            for stage in STAGES:
                for cell in ("general", "temporal"):
                    pair = [f for f in fitted if f["kind"] == kind
                            and f["stage"] == stage and f["cell"] == cell]
                    self.assertEqual({x["objective"] for x in pair}, set(OBJECTIVES))
                    self.assertEqual(len({x["shared_initial_head_sha256"] for x in pair}), 1)
                    self.assertEqual(len({x["train_question_ids_sha256"] for x in pair}), 1)
                    self.assertEqual(
                        len({x["admitted_same_positive_negative_questions"]
                             for x in pair}), 1
                    )
        self.assertTrue(all(c["incremental_reader_calls"] == 0 for c in decisions))
        self.assertTrue(all(c["heldout_annotations_read_before_choices"] is False
                            for c in decisions))

    def test_postpolicy_review_has_all_192_matched_pairs_without_reader(self):
        questions, _, encoded, _, _, fitted, decisions = self.execute()
        pools, targets, _ = targets_and_frozen(questions, encoded)
        review = review_objectives(
            questions, fitted, decisions, pools, targets,
            support_indices=support_indices,
        )
        self.assertEqual(review["fitted_objective_checkpoints"], 24)
        self.assertEqual(review["label_blind_shadow_decisions"], 384)
        self.assertEqual(len(review["by_stage_phase_kind"]), 24)
        self.assertEqual(
            sum(r["attempted"] for r in review["by_stage_phase_kind"].values()),
            192,
        )
        self.assertTrue(review["initial_head_weights_identical"])
        for group in review["by_stage_phase_kind"].values():
            self.assertLessEqual(group["ce_vs_frozen_weak_source_gains"], 8)
            self.assertLessEqual(group["pairwise_vs_frozen_weak_source_gains"], 8)
            self.assertLessEqual(
                group["pairwise_over_ce_weak_source_gains"]
                + group["ce_over_pairwise_weak_source_gains"],
                group["matched_label_blind_selection_changes"],
            )
        self.assertFalse(review["independent_semantic_source_judgment"])
        self.assertFalse(review["production_accepted"])

    def test_tampered_head_or_candidate_pool_rejected_after_generation(self):
        questions, _, encoded, _, _, fitted, decisions = self.execute()
        pools, targets, _ = targets_and_frozen(questions, encoded)
        for field, corrupted in (
            ("matched_head_sha256", "a" * 64),
            ("pool_sha256", "different-pool"),
            ("shared_initial_head_sha256", "changed-seed"),
        ):
            changed = deepcopy(decisions)
            changed[0][field] = corrupted
            with self.subTest(field=field), self.assertRaises(ValueError):
                review_objectives(
                    questions, fitted, changed, pools, targets,
                    support_indices=support_indices,
                )

    def test_frozen_baseline_identity_must_match_both_objectives(self):
        questions, _, encoded, _, _, fitted, decisions = self.execute()
        pools, targets, _ = targets_and_frozen(questions, encoded)
        tampered = deepcopy(decisions)
        # Original frozen fixture scores [0.2, 0.5] select 1.
        tampered[0]["original_frozen_selected"] = 0
        with self.assertRaisesRegex(ValueError, "original frozen winner drift"):
            review_objectives(
                questions, fitted, tampered, pools, targets,
                support_indices=support_indices,
            )

    def test_train_supervision_cannot_use_registered_heldout_question(self):
        questions, supervised, encoded, cut, routes = fixture()
        extra = Supervision(features("test-0"), (0,))
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "held-out|reencoded"):
                matched_objective_shadow(
                    questions, supervised + (extra,), encoded, cut, routes,
                    Path(directory),
                )

    def test_noncontrastive_training_cannot_be_counted_as_source_learning(self):
        questions, supervised, encoded, cut, routes = fixture()
        abstain = tuple(
            Supervision(r.features, ()) for r in supervised
        )
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "positive/negative"):
                matched_objective_shadow(
                    questions, abstain, encoded, cut, routes, Path(directory),
                )

    def test_a_missing_shadow_answer_must_still_count_in_original_denominator(self):
        questions, _, encoded, _, _, fitted, decisions = self.execute()
        pools, targets, _ = targets_and_frozen(questions, encoded)
        changed = deepcopy(decisions)
        changed[0]["status"] = "failed"
        changed[0].pop("selected")
        changed[0].pop("matched_head_sha256")
        summary = review_objectives(
            questions, fitted, changed, pools, targets,
            support_indices=support_indices,
        )
        self.assertEqual(summary["by_stage_phase_kind"]["16/select/linear"]["attempted"], 8)
        self.assertEqual(summary["by_stage_phase_kind"]["16/select/linear"]["unscored_or_failed"], 1)


if __name__ == "__main__":
    unittest.main()
