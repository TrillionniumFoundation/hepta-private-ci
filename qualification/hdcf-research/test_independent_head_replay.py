"""Real CPU scalar replay + adversarial provenance/parameter tests."""
from __future__ import annotations

import copy
import math
import unittest

from independent_head_replay import audit_head_replay
from physical_bank import Denied, train
from test_physical_bank import original
from test_modernbert_feature_bridge import prepared, stage_original, fake_feature_bundle


class IndependentReplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bundle, _ = original()
        cls.trial = train(cls.bundle)

    def test_all_original_five_arms_replay_real_sgd(self):
        r = audit_head_replay(self.bundle, self.trial)
        self.assertEqual(r["original_prediction_rows_replayed"], 160)
        self.assertEqual(set(r["original_trained_weights_recomputed"]),
                         {"frozen", "shared_dense", "shared_one_touch", "split", "swapped"})
        self.assertFalse(r["independent_model_source_authenticated"])
        self.assertFalse(r["production_authorized"])

    def test_frozen_and_split_identity_differs(self):
        r = audit_head_replay(self.bundle, self.trial)
        self.assertNotEqual(r["original_trained_weights_recomputed"]["frozen"],
                            r["original_trained_weights_recomputed"]["split"])
        self.assertEqual(r["original_trained_weights_recomputed"]["split"],
                         r["original_trained_weights_recomputed"]["swapped"])

    def test_tamper_prediction_with_same_frozen_digest(self):
        bad = copy.deepcopy(self.trial)
        bad["predictions"]["split"][3]["p1"] += 0.002
        with self.assertRaisesRegex(Denied, "predictor logits"):
            audit_head_replay(self.bundle, bad)

    def test_tamper_true_training_digest(self):
        bad = copy.deepcopy(self.trial)
        bad["arms"]["shared_dense"]["weights_digest"] = "a" * 64
        with self.assertRaisesRegex(Denied, "training work"):
            audit_head_replay(self.bundle, bad)

    def test_launder_cost_or_false_run_count(self):
        for k, wrong in (("estimated_parameter_touches", 1), ("actual_sgd_steps", 0),
                         ("observed_train_cpu_ns", 0), ("observed_train_wall_ns", -1)):
            bad = copy.deepcopy(self.trial)
            bad["arms"]["split"][k] = wrong
            with self.subTest(k=k), self.assertRaises(Denied):
                audit_head_replay(self.bundle, bad)

    def test_launder_untrained_as_swapped(self):
        bad = copy.deepcopy(self.trial)
        bad["arms"]["swapped"].pop("reuses_split_weights")
        with self.assertRaisesRegex(Denied, "training work"):
            audit_head_replay(self.bundle, bad)

    def test_wrong_plan_or_feature_identity(self):
        for params in ({"steps": 255}, {"seed": 7}, {"lr": 0.02}):
            with self.subTest(params=params), self.assertRaisesRegex(Denied, "trial provenance"):
                audit_head_replay(self.bundle, self.trial, **params)
        bad = copy.deepcopy(self.bundle)
        bad["fit"][0]["vector"][0] += 0.011
        with self.assertRaisesRegex(Denied, "trial provenance"):
            audit_head_replay(bad, self.trial)

    def test_768_dimension_physical_float_updates_and_replay(self):
        resized = copy.deepcopy(self.bundle)
        for split in ("fit", "held"):
            for row in resized[split]:
                row["vector"].extend([0.0] * 764)
        resized["dimension"] = 768
        trial = train(resized, steps=24)
        result = audit_head_replay(resized, trial, steps=24)
        self.assertEqual(result["original_prediction_rows_replayed"], 160)
        self.assertFalse(result["actual_cpu_time_independently_verified"])

    def test_training_budget_structures_fail_closed(self):
        for bad in ({"steps": True}, {"seed": True}, {"lr": math.inf}, {"lr": math.nan}):
            with self.subTest(bad=bad), self.assertRaises(Denied):
                audit_head_replay(self.bundle, self.trial, **bad)

    def test_retained_historical_fake_dimension_not_a_pretrained_claim(self):
        inputs, observer, selection = prepared()
        pub, _ = stage_original(inputs, observer, selection)
        bundle = fake_feature_bundle(pub)
        trial = train(bundle, steps=24)
        r = audit_head_replay(bundle, trial, steps=24)
        self.assertEqual(r["original_prediction_rows_replayed"], 160)
        self.assertFalse(r["independent_model_source_authenticated"])


if __name__ == "__main__":
    unittest.main()
