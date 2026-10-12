"""Torch placebo experiment tests; authored Features are not real Reader results."""

from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

import torch

from selector_evaluation import support_indices
from selector_head import Supervision
from stem_label_placebo import (
    LABELS,
    label_placebo_shadow,
    placebo_labels,
    review_placebo,
)
from test_stem_native_pairwise_shadow import fixture, targets_and_frozen


class LabelPlaceboTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(2)

    def execute(self):
        questions, rows, features, cut, routes = fixture()
        with tempfile.TemporaryDirectory() as directory:
            fits, decisions = label_placebo_shadow(
                questions,
                rows,
                features,
                cut,
                routes,
                Path(directory),
            )
        return questions, fits, decisions, features

    def test_placebo_never_reuses_a_labelled_positive(self):
        _, rows, _, _, _ = fixture()
        for row in rows:
            left = set(row.positive_indices)
            right = set(placebo_labels(row).positive_indices)
            self.assertTrue(left.isdisjoint(right))
            self.assertEqual(len(left), len(right))
            self.assertEqual(
                placebo_labels(row).positive_indices,
                placebo_labels(row).positive_indices,
            )

    def test_same_initial_weights_training_ids_and_budgets(self):
        questions, fits, decisions, _ = self.execute()
        self.assertEqual(len(fits), 24)
        self.assertEqual(len(decisions), 384)
        self.assertTrue(all(x["status"] == "succeeded" for x in fits))
        self.assertTrue(all(x["status"] == "succeeded" for x in decisions))
        self.assertTrue(all(x["receipt"]["consumed_steps"] == 128 for x in fits))
        for stage in (16, 32, 48):
            for kind in ("linear", "gated"):
                for cell in ("general", "temporal"):
                    pair = [
                        x
                        for x in fits
                        if (x["stage"], x["kind"], x["cell"]) == (stage, kind, cell)
                    ]
                    self.assertEqual({x["condition"] for x in pair}, set(LABELS))
                    self.assertEqual(len({x["initial_seed_sha256"] for x in pair}), 1)
                    self.assertEqual(
                        len({x["training_question_ids_sha256"] for x in pair}),
                        1,
                    )
                    self.assertNotEqual(
                        pair[0]["supervision_sha256"],
                        pair[1]["supervision_sha256"],
                    )
        self.assertEqual(len(questions["test"]), 8)
        self.assertTrue(all(x["original_reader_calls"] == 0 for x in decisions))
        self.assertTrue(all(x["heldout_labels_read"] is False for x in decisions))

    def test_post_seal_weak_source_review_not_qa_gain(self):
        questions, fits, decisions, features = self.execute()
        pools, targets, _ = targets_and_frozen(questions, features)
        result = review_placebo(
            questions,
            fits,
            decisions,
            pools,
            targets,
            support_indices=support_indices,
        )
        self.assertEqual(result["trained_heads"], 24)
        self.assertEqual(result["sealed_choices"], 384)
        self.assertEqual(len(result["by_stage_phase_kind"]), 24)
        self.assertEqual(
            sum(x["attempted"] for x in result["by_stage_phase_kind"].values()),
            192,
        )
        self.assertIsNone(result["independent_semantic_citation_precision"])
        self.assertFalse(result["production_accepted"])

    def test_tampered_head_seed_pool_or_missing_record_reject(self):
        questions, fits, decisions, features = self.execute()
        pools, targets, _ = targets_and_frozen(questions, features)
        for field, val in (
            ("head_sha256", "a" * 64),
            ("initial_seed_sha256", "wrong"),
            ("pool_sha256", "wrong"),
            ("feature_sha256", "wrong"),
        ):
            changed = deepcopy(decisions)
            changed[0][field] = val
            with self.subTest(field=field), self.assertRaises(ValueError):
                review_placebo(
                    questions,
                    fits,
                    changed,
                    pools,
                    targets,
                    support_indices=support_indices,
                )
        with self.assertRaises(ValueError):
            review_placebo(
                questions,
                fits,
                decisions[:-1],
                pools,
                targets,
                support_indices=support_indices,
            )

    def test_heldout_labels_can_never_become_training_rows(self):
        from test_stem_cell import features as make_features

        questions, rows, enc, cut, routes = fixture()
        forged = Supervision(make_features("test-0"), (0,))
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "TRAIN|overlapping"):
                label_placebo_shadow(
                    questions,
                    rows + (forged,),
                    enc,
                    cut,
                    routes,
                    Path(directory),
                )

    def test_all_positives_or_ambiguous_weak_labels_not_faked(self):
        questions, rows, enc, cut, routes = fixture()
        ambiguous = tuple(
            Supervision(row.features, tuple(range(len(row.features.candidate_ids))))
            for row in rows
        )
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "usable paired TRAIN"):
                label_placebo_shadow(
                    questions,
                    ambiguous,
                    enc,
                    cut,
                    routes,
                    Path(directory),
                )


if __name__ == "__main__":
    unittest.main()
