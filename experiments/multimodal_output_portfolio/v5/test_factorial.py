"""Adversarial mechanistic regressions; NOT a natural-data confirmation."""
import copy
import math
import unittest

from factorial import (
    ACTIONS, COSTS, CONTROLS, TRAININGS, EMISSION_COST, World,
    make_worlds, init_weights, train, predict, train_policies, choose,
    apply_action, decode_raw, independent_loss, risk_measure, cvar90,
    evaluate, run,
)


class FactorialTests(unittest.TestCase):
    def test_split_and_counterfactual_random_stream_separation(self):
        ids = set()
        for split in ("train", "dev", "test"):
            rows = make_worlds(17, split, 100)
            self.assertEqual(len(rows), 100)
            self.assertTrue(all(x.mode in ("easy", "hard") for x in rows))
            for w in rows:
                self.assertNotIn(w.source_id, ids)
                ids.add(w.source_id)
        self.assertEqual(make_worlds(17, "test", 10), make_worlds(17, "test", 10))
        with self.assertRaises(ValueError):
            make_worlds(17, "secret_test", 10)

    def test_model_and_policy_only_receive_structurally_public_inputs(self):
        one = make_worlds(17, "dev", 1)[0]
        other = World(one.source_id, one.mode, one.signals, 1 - one.witness,
                      1 - one.truth, not one.common_flip)
        self.assertEqual(one.public, other.public)
        params = init_weights(17)
        p = predict(one.public, params)
        self.assertEqual(p, predict(other.public, params))
        critic = train_policies(make_worlds(17, "dev", 100), params)
        for mode in CONTROLS:
            self.assertEqual(choose(one.public, p, critic, mode),
                             choose(other.public, p, critic, mode))
        self.assertFalse(hasattr(one.public, "truth"))
        self.assertFalse(hasattr(one.public, "witness"))
        self.assertFalse(hasattr(one.public, "common_flip"))

    def test_real_parameter_learning_starts_equally_and_has_direct_gradient(self):
        cohort = make_worlds(17, "train", 128)
        _, s = train(cohort, 17, "supervised", steps=10)
        _, r = train(cohort, 17, "ndu_risk", steps=10)
        self.assertEqual(s["initial_weight_digest"], r["initial_weight_digest"])
        self.assertNotEqual(s["final_weight_digest"], r["final_weight_digest"])
        self.assertEqual(s["head_forward_calls"], r["head_forward_calls"])
        self.assertEqual(r["nonzero_utility_weight_steps"], 10)
        self.assertEqual(r["nonzero_head_risk_gradient_steps"], [10]*4)
        self.assertEqual(s["nonzero_utility_weight_steps"], 0)

    def test_independent_terminal_scoring_catches_consistently_wrong_modalities(self):
        raw = decode_raw((.999, .999, .999, .999))
        loss, wrong, mismatch = independent_loss(raw, 0)
        self.assertEqual((loss, wrong, mismatch), (4, 4, 0))
        self.assertEqual(independent_loss(raw, 1), (0, 0, 0))
        broken = copy.deepcopy(raw)
        broken["audio"] = (1,)
        with self.assertRaises(ValueError):
            independent_loss(broken, 1)

    def test_cost_and_true_fractional_cvar(self):
        self.assertEqual(COSTS["EMIT"], EMISSION_COST)
        self.assertEqual(COSTS["QUERY"], EMISSION_COST + 3)
        self.assertAlmostEqual(cvar90([0]*10 + [10]), 10 / 1.1)
        self.assertEqual(cvar90([0, 10]), 10)
        self.assertAlmostEqual(risk_measure([0, 10], 0), 5.0)
        self.assertGreater(risk_measure([0, 10], 1), 5.0)
        with self.assertRaises(ValueError):
            risk_measure([math.inf], 1)

    def test_four_arm_development_run_records_paired_effects_and_costs(self):
        result = run(17, ntrain=128, ndev=64, ntest=64, steps=10)
        self.assertEqual(len(result["arms"]), 4)
        self.assertEqual(result["status"], "DEVELOPMENT_ONLY_NO_CONFIRMATORY_CLAIM")
        self.assertEqual(result["training"]["supervised"]["updates"], 10)
        self.assertTrue(result["training"]["ndu_risk"]["nonzero_utility_weight_steps"] >= 1)
        for name, metrics in result["arms"].items():
            self.assertEqual(metrics["test_sources"], 64)
            self.assertEqual(metrics["head_forward_calls"], 64*4)
            self.assertLessEqual(metrics["mean_cost_units"], 7)
            self.assertGreaterEqual(metrics["mean_cost_units"], 4)
            self.assertTrue(math.isfinite(metrics["cvar90_loss"]))
        arm = result["arms"]
        effect = (arm["ndu_risk|ndu_contextual"]["mean_loss"]
                  - arm["ndu_risk|static"]["mean_loss"])
        self.assertAlmostEqual(result["paired_mean_loss_contrasts"]["inference_effect_ndu"], effect)

    def test_negative_dynamic_policy_outcome_preserved(self):
        # One heldout synthetic seed is adverse: do not publish pooled gain
        # while concealing failure/actual cost under the nonlinear scorer.
        r = run(29, ntrain=768, ndev=256, ntest=512, steps=80)
        self.assertGreater(r["paired_mean_loss_contrasts"]["inference_effect_supervised"], 0)
        self.assertLess(r["arms"]["supervised|ndu_contextual"]["mean_cost_units"],
                        r["arms"]["supervised|static"]["mean_cost_units"])

    def test_frozen_independent_witness_breaks_under_shift(self):
        seed = 17
        params, _ = train(make_worlds(seed, "train", 768), seed,
                          "ndu_risk", steps=80)
        critic = train_policies(make_worlds(seed, "dev", 256), params)
        nominal = make_worlds(seed, "shift", 512, witness_accuracy=.97)
        failed = make_worlds(seed, "shift", 512, witness_accuracy=.03)
        base, _ = evaluate(nominal, params, critic, "ndu_contextual")
        shifted, _ = evaluate(failed, params, critic, "ndu_contextual")
        self.assertGreater(shifted["mean_loss"], base["mean_loss"])
        self.assertEqual(shifted["query_rate"], base["query_rate"])
        self.assertEqual(shifted["mean_cost_units"], base["mean_cost_units"])


if __name__ == "__main__":
    unittest.main()
