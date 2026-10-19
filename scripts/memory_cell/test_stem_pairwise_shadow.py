"""Real CPU PyTorch pairwise-source Shadow Head regressions; not task gains."""

import unittest

import torch

from selector_head import Supervision
from stem_cell import StemHead, sha256
from stem_pairwise_shadow import fit_pairwise_shadow
from test_stem_cell import features, restore, training_cut


class PairwiseShadowTests(unittest.TestCase):
    def setUp(self):
        self.row = Supervision(features(), (0,))
        self.cut = training_cut()

    def head(self, kind="linear"):
        return StemHead(4, "encoder-v1", kind=kind, rank=4)

    def test_real_sgd_flips_weak_source_rank_without_training_null(self):
        original = self.head("linear")
        before = original.export()
        with torch.no_grad():
            self.assertEqual(original.decide(features(), revoked=set())[0], 1)
        null_weight = original.null.weight.detach().clone()
        null_bias = original.null.bias.detach().clone()
        receipt = fit_pairwise_shadow(
            original,
            (self.row,),
            self.cut,
            revoked=set(),
            steps=128,
            lr=0.03,
            margin=1.0,
        )
        self.assertGreater(receipt["tensor_delta_squared_norm"], 0)
        self.assertLess(receipt["last_loss"], receipt["first_loss"])
        self.assertEqual(original.decide(features(), revoked=set())[0], 0)
        self.assertTrue(torch.equal(null_weight, original.null.weight))
        self.assertTrue(torch.equal(null_bias, original.null.bias))
        self.assertEqual(receipt["checkpoint_pre_sha256"], sha256(before))
        self.assertEqual(receipt["checkpoint_post_sha256"], sha256(original.export()))
        self.assertEqual(receipt["distinct_eligible_contrastive_questions"], 1)
        self.assertFalse(receipt["actual_heldout_task_gain_established"])
        self.assertFalse(receipt["production_accepted"])

    def test_gated_head_local_gradients_from_no_grad_caller(self):
        head = self.head("gated")
        with torch.no_grad():
            self.assertFalse(torch.is_grad_enabled())
            receipt = fit_pairwise_shadow(
                head,
                (self.row,),
                self.cut,
                revoked=set(),
                steps=64,
            )
            self.assertFalse(torch.is_grad_enabled())
        self.assertGreater(receipt["tensor_delta_squared_norm"], 0)
        self.assertTrue(receipt["null_weights_unchanged"])

    def test_inference_mode_rejected_before_mutation(self):
        head = self.head()
        before = head.export()
        with torch.inference_mode():
            with self.assertRaisesRegex(ValueError, "pairwise shadow"):
                fit_pairwise_shadow(
                    head,
                    (self.row,),
                    self.cut,
                    revoked=set(),
                    steps=16,
                )
        self.assertEqual(head.export(), before)
        self.assertFalse(head.quarantined)

    def test_all_null_and_all_positive_do_not_fake_hard_negative_pairs(self):
        for positives in ((), (0, 1)):
            head = self.head()
            before = head.export()
            with (
                self.subTest(positives=positives),
                self.assertRaisesRegex(ValueError, "no contrastive TRAIN pair"),
            ):
                fit_pairwise_shadow(
                    head,
                    (Supervision(features(), positives),),
                    self.cut,
                    revoked=set(),
                )
            self.assertEqual(head.export(), before)
            self.assertFalse(head.quarantined)

    def test_pair_ineligible_admitted_weak_label_remains_in_accounting(self):
        head = self.head()
        second = Supervision(features("second"), ())
        receipt = fit_pairwise_shadow(
            head,
            (self.row, second),
            self.cut,
            revoked=set(),
            steps=24,
        )
        self.assertEqual(receipt["admitted_training_rows"], 2)
        self.assertEqual(receipt["distinct_eligible_contrastive_questions"], 1)
        self.assertEqual(receipt["pair_ineligible_weak_label_questions"], 1)
        self.assertEqual(receipt["pair_ineligible_question_ids"], ["second"])
        self.assertFalse(
            receipt["weak_distractors_not_verified_hard_negatives"] is False
        )

    def test_heldout_duplication_invalid_label_or_revoked_root_preflight(self):
        for mode in ("heldout", "duplicate", "positive", "revoked", "encoder"):
            head = self.head()
            before = head.export()
            rows, revoked = (self.row,), set()
            if mode == "heldout":
                rows = (Supervision(features("test"), (0,)),)
            elif mode == "duplicate":
                rows = (self.row, self.row)
            elif mode == "positive":
                rows = (Supervision(features(), (2,)),)
            elif mode == "revoked":
                revoked = {"root"}
            else:
                rows = (Supervision(features(identity="different"), (0,)),)
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                fit_pairwise_shadow(
                    head,
                    rows,
                    self.cut,
                    revoked=revoked,
                    steps=8,
                )
            self.assertEqual(head.export(), before)
            self.assertFalse(head.quarantined)

    def test_continual_head_artifact_reload_preserves_nonmomentum_counters(self):
        head = self.head()
        initial = fit_pairwise_shadow(
            head,
            (self.row,),
            self.cut,
            revoked=set(),
            steps=16,
        )
        saved = head.export()
        restored = restore(head)
        self.assertEqual(restored.export(), saved)
        next_receipt = fit_pairwise_shadow(
            restored,
            (self.row, Supervision(features("second"), (0,))),
            self.cut,
            revoked=set(),
            steps=16,
        )
        self.assertEqual(next_receipt["prior_cumulative_steps"], 16)
        self.assertEqual(next_receipt["cumulative_steps"], 32)
        self.assertEqual(next_receipt["consumed_steps"], 16)
        self.assertEqual(initial["checkpoint_post_sha256"], sha256(saved))
        self.assertNotEqual(restored.export(), saved)

    def test_frozen_original_control_unmodified_when_shadow_trains(self):
        control = self.head()
        shadow = self.head()
        baseline = control.export()
        fit_pairwise_shadow(
            shadow,
            (self.row,),
            self.cut,
            revoked=set(),
            steps=24,
        )
        self.assertEqual(control.export(), baseline)
        self.assertNotEqual(shadow.export(), baseline)

    def test_invalid_hyperparameters_and_prototype_reject(self):
        for kwargs in (
            {"steps": 0},
            {"steps": 2049},
            {"margin": -1},
            {"margin": 9},
            {"lr": 0},
            {"lr": float("nan")},
            {"pair_ceiling": 0},
        ):
            head = self.head()
            before = head.export()
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                fit_pairwise_shadow(
                    head,
                    (self.row,),
                    self.cut,
                    revoked=set(),
                    **kwargs,
                )
            self.assertEqual(head.export(), before)
        prototype = self.head("prototype")
        with self.assertRaises(ValueError):
            fit_pairwise_shadow(
                prototype,
                (self.row,),
                self.cut,
                revoked=set(),
            )


if __name__ == "__main__":
    unittest.main()
