"""Adversarial qualification tests for the NDU-DMGP shadow reference."""
import math
import unittest
from dataclasses import replace

from reference import (
    ARMS, MODALITIES, CellCredit, Covariance, GateRejected, GenerationAction,
    MediaEvent, Objective, Observation, Scenario, choose_action,
    closure_audit, credit_conservation, cross_modal_contract,
    independent_utility, fit_static_topk_router, make_scenarios, next_snapshot_gate,
    paired_covariance, portfolio_weights, reference_report, run_shadow_arm,
    validate_splits,
)


def objective():
    return Objective("fixed-task", 1, MODALITIES, frozenset(("text", "image")),
                     4., .1, .3, .9)


def obs(episode="E-1", split="train", actor="actor", observer="independent",
        quality=2., compute=3., risk=.1, at=100, policy="reference"):
    j = objective()
    return Observation(episode, j.digest, 1, policy, actor, observer, split, at,
                       quality, compute, risk, "independent_observation", True)


class FrozenUtilityTests(unittest.TestCase):
    def test_fixed_utility_and_noncompensable_source(self):
        record = obs()
        self.assertAlmostEqual(independent_utility(objective(), record), 1.67)
        for mutation in (
            {"actor_id": "independent"}, {"observer_id": "actor"},
            {"objective_digest": "wrong"}, {"generation": 2},
            {"evidence_kind": "synthetic_reference"}, {"resource_metered": False},
            {"compute_units": -1.}, {"risk": 5.}, {"quality": math.nan},
            {"policy_id": ""},
        ):
            with self.subTest(mutation=mutation), self.assertRaises(GateRejected):
                independent_utility(objective(), replace(record, **mutation))

    def test_immutable_objective_hash_and_bad_profile(self):
        obj = objective()
        self.assertNotEqual(obj.digest, replace(obj, risk_price=.4).digest)
        with self.assertRaises(GateRejected):
            Objective("bad", 1, MODALITIES, frozenset({"unknown"}), 2., 0., 0., 1.)
        with self.assertRaises(GateRejected):
            Objective("bad", 1, MODALITIES, frozenset(), math.nan, 0., 0., 1.)

    def test_future_split_no_leakage_and_time_order(self):
        validate_splits([obs("train", "train", at=4)],
                        [obs("heldout", "future", at=5)])
        with self.assertRaises(GateRejected):
            validate_splits([obs("same", "train", at=4)],
                            [obs("same", "future", at=5)])
        with self.assertRaises(GateRejected):
            validate_splits([obs("early", "train", at=6)],
                            [obs("later", "future", at=5)])


class ModalConsistencyTests(unittest.TestCase):
    def setUp(self):
        self.events = (
            MediaEvent("tx", "text", 0, 900, frozenset({"A"}), frozenset({"event"})),
            MediaEvent("im", "image", 0, 900, frozenset({"A"}), frozenset({"event"})),
            MediaEvent("au", "audio", 0, 900, frozenset({"A"}), frozenset({"event"}), "pair"),
            MediaEvent("vi", "video", 25, 925, frozenset({"A"}), frozenset({"event"}), "pair"),
        )

    def check(self, events):
        return cross_modal_contract(objective(), events,
                                    frozenset({"A"}), frozenset({"event"}))

    def test_bidirectional_entities_tags_av_timeline(self):
        result = self.check(self.events)
        self.assertTrue(result.supported)
        self.assertEqual(result.checked_pairs, 1)
        bad = self.check(self.events[:-1] +
                         (replace(self.events[-1], start_ms=500, end_ms=1500),))
        self.assertIn("audio-video temporal misalignment", bad.violations)
        bad2 = self.check(self.events[:-1] +
                          (replace(self.events[-1], entity_ids=frozenset({"B"})),))
        self.assertIn("unverified generated entity", bad2.violations)

    def test_missing_reconstruction_and_untrusted_tags(self):
        only_text = self.check((MediaEvent("tx", "text", 0, 1, frozenset(), frozenset()),))
        self.assertIn("missing required output modality", only_text.violations)
        self.assertIn("source entities lost in output reconstruction", only_text.violations)
        changed = self.check(self.events[:-1] +
                             (replace(self.events[-1], semantic_tags=frozenset({"hallucination"})),))
        self.assertIn("unsupported generated semantic tag", changed.violations)

    def test_duplicate_identity_and_invalid_duration(self):
        result = self.check(self.events + (replace(self.events[0], end_ms=0),))
        self.assertIn("duplicate/empty event identity", result.violations)
        self.assertIn("invalid event timeline", result.violations)


    def test_unpaired_audio_video_rejected_even_with_valid_tags(self):
        mismatched_pair = self.events[:2] + (
            replace(self.events[2], pair_id="audio-unmatched"), self.events[3],
        )
        result = self.check(mismatched_pair)
        self.assertFalse(result.supported)
        self.assertIn("unpaired audio-video output", result.violations)
        no_pair = self.events[:2] + (
            replace(self.events[2], pair_id=""), replace(self.events[3], pair_id=""),
        )
        result = self.check(no_pair)
        self.assertFalse(result.supported)
        self.assertIn("missing audio-video pairing evidence", result.violations)


class RiskIdentificationTests(unittest.TestCase):
    def samples(self, n=30):
        return {f"e{i}": {"text": (i % 7)*.2+i*.002,
                          "image": (i % 3)*.3-i*.004,
                          "audio": (i % 5)*.11+i*.005} for i in range(n)}

    def test_matched_shrinkage_low_rank_psd(self):
        c = paired_covariance(self.samples(), ("text", "image", "audio"), rank=2)
        self.assertTrue(c.supported, c.reason)
        self.assertEqual(c.factor_rank, 2)
        self.assertGreater(c.risk((.4, .3, .3)), 0.)
        self.assertLess(c.condition_number, 1e6)
        for i in range(3):
            for j in range(3):
                self.assertAlmostEqual(c.matrix[i][j], c.matrix[j][i], places=8)

    def test_missing_sample_and_singular_fall_back(self):
        insuff = paired_covariance(self.samples(5), ("text", "image", "audio"))
        self.assertFalse(insuff.supported)
        self.assertEqual(portfolio_weights((.5, .9, .1), insuff), (0., 1., 0.))
        constant = {f"e{i}": {"text": 1., "image": 1.} for i in range(25)}
        self.assertFalse(paired_covariance(constant, ("text", "image")).supported)
        mismatched = self.samples()
        mismatched["e0"].pop("audio")
        self.assertFalse(paired_covariance(mismatched, ("text", "image", "audio")).supported)

    def test_finite_optimization_and_dimension_fail_closed(self):
        c = paired_covariance(self.samples(), ("text", "image", "audio"))
        w = portfolio_weights((2., 1., .1), c)
        self.assertAlmostEqual(sum(w), 1., places=8)
        self.assertTrue(all(0. <= x <= 1. for x in w))
        with self.assertRaises(GateRejected):
            c.risk((1., 0.))
        with self.assertRaises(GateRejected):
            portfolio_weights((1., math.nan, 0.), c)
        self.assertFalse(paired_covariance(self.samples(),
                                          ("text", "image", "audio"), rank=4).supported)


    def test_nonfinite_risk_price_and_corrupt_covariance_reject(self):
        c = paired_covariance(self.samples(), ("text", "image", "audio"))
        with self.assertRaises(GateRejected):
            portfolio_weights((1., 2., 3.), c, risk_price=math.inf)
        damaged = replace(c, matrix=((math.nan, 0., 0.),) + c.matrix[1:])
        with self.assertRaises(GateRejected):
            portfolio_weights((1., 2., 3.), damaged)


class CreditClosureTests(unittest.TestCase):
    def test_local_credit_requires_supported_global_interaction(self):
        entries = (CellCredit("cell-1", 2., "auditor", "digest-1"),
                   CellCredit("cell-2", 3., "auditor", "digest-2"))
        self.assertAlmostEqual(credit_conservation(8., entries, 3.), 0.)
        with self.assertRaises(GateRejected):
            credit_conservation(8., entries, 0.)
        with self.assertRaises(GateRejected):
            credit_conservation(8., entries + entries[:1], 3.)
        with self.assertRaises(GateRejected):
            credit_conservation(8., (replace(entries[0], support_digest=""), entries[1]), 3.)

    def test_history_helps_predict_outcomes_reject_closure(self):
        train = (("state", "history-a", 0.), ("state", "history-a", 0.),
                 ("state", "history-b", 4.), ("state", "history-b", 4.))
        test = (("state", "history-a", 0.), ("state", "history-b", 4.))
        sufficient, benefit = closure_audit(train, test)
        self.assertFalse(sufficient)
        self.assertGreater(benefit, 3.)
        good_train = tuple(("state", tag, 2.) for tag in ("a", "a", "b", "b"))
        good_test = (("state", "a", 2.), ("state", "b", 2.))
        self.assertEqual(closure_audit(good_train, good_test), (True, 0.))
        with self.assertRaises(GateRejected):
            closure_audit(train, (("state", "missing", 0.), ("state", "missing", 1.)))


class FutureGateTests(unittest.TestCase):
    def setUp(self):
        self.cand = [obs(f"f-{i}", "future", quality=10., at=100+i,
                         policy="candidate") for i in range(16)]
        self.base = [obs(f"f-{i}", "future", quality=8., at=100+i)
                     for i in range(16)]
        self.old_c = [obs(f"r-{i}", "retention", quality=8., at=200+i,
                          policy="candidate") for i in range(16)]
        self.old_b = [obs(f"r-{i}", "retention", quality=8., at=200+i)
                      for i in range(16)]

    def gate(self, **kwargs):
        args = dict(candidate=self.cand, baseline=self.base,
                    retention_candidate=self.old_c, retention_baseline=self.old_b,
                    objective=objective(), selected_generation=1, candidate_generation=2,
                    critic_frozen=True, trust_region_kl=.01)
        args.update(kwargs)
        return next_snapshot_gate(**args)

    def test_shadow_candidate_passes_scoring_only_not_activation(self):
        self.assertEqual(self.gate(), (True, ()))
        accepted, reasons = self.gate(synthetic=True)
        self.assertFalse(accepted)
        self.assertIn("synthetic evidence is not deployment evidence", reasons)

    def test_freeze_trust_next_generation_and_retention(self):
        for mutation in ({"critic_frozen": False}, {"candidate_generation": 1},
                         {"trust_region_kl": .09},
                         {"retention_candidate": [replace(o, quality=5.) for o in self.old_c]},
                         {"candidate": [replace(o, quality=6.) for o in self.cand]}):
            with self.subTest(mutation=list(mutation)):
                self.assertFalse(self.gate(**mutation)[0])

    def test_forged_observer_rejected(self):
        altered = [replace(o, observer_id="actor") for o in self.cand]
        self.assertFalse(self.gate(candidate=altered)[0])
        self.assertFalse(self.gate(candidate=self.cand[:2])[0])
        wrong = [replace(o, episode=f"other-{i}") for i, o in enumerate(self.cand)]
        self.assertFalse(self.gate(candidate=wrong)[0])


    def test_duplicate_future_rows_and_policy_drift_rejected(self):
        duplicated = [self.cand[0]] + self.cand[:-1]
        self.assertFalse(self.gate(candidate=duplicated)[0])
        mixed = list(self.cand)
        mixed[0] = replace(mixed[0], policy_id="other-policy")
        self.assertFalse(self.gate(candidate=mixed)[0])
        changed_retention = [replace(r, policy_id="another-model") for r in self.old_c]
        self.assertFalse(self.gate(retention_candidate=changed_retention)[0])
        all_overlap = [replace(r, actor_id="independent") for r in self.old_c]
        self.assertFalse(self.gate(retention_candidate=all_overlap)[0])


class ExperimentTests(unittest.TestCase):
    def test_all_arms_common_episodes_and_no_promotion(self):
        report = reference_report()
        self.assertEqual(set(report["experiment_arms"]), set(ARMS))
        self.assertFalse(report["production_blockers_closed"])
        self.assertFalse(report["real_decoder_observed"])
        self.assertFalse(report["independent_future_observed"])
        self.assertEqual(report["training_episodes"], 24)
        self.assertEqual(report["evaluation_episodes"], 24)
        self.assertTrue(report["train_eval_episodes_disjoint"])
        self.assertTrue(report["a2_fitted_train_only"])
        for arm in ARMS:
            self.assertEqual(report["summary"][arm]["episodes"], 24)
            self.assertGreater(report["summary"][arm]["controller_peak_python_bytes_max_measured"], 0)
        # A5 exploits synthetic synergy, but A1 does as well: no universal win claim.
        self.assertGreater(report["summary"]["A5"]["mean_synthetic_ndu"],
                           report["summary"]["A0"]["mean_synthetic_ndu"])
        self.assertEqual(report["summary"]["A1"]["mean_synthetic_ndu"],
                         report["summary"]["A5"]["mean_synthetic_ndu"])

    def test_hard_budget_and_risk_filter(self):
        j = objective()
        scenario = Scenario("bounded", (
            GenerationAction("flash", "text", 2., 100., .99),
            GenerationAction("text", "text", 1., 2., .01),
            GenerationAction("image", "image", 2., 1., .01),
        ), {}, 2., 2)
        unsupported = Covariance(False, (), 0, math.inf, 0, "no support")
        for arm in ("A2", "A3", "A4", "A5"):
            self.assertNotEqual(choose_action(arm, scenario, (), 2., j, unsupported), "flash")
        result = run_shadow_arm("A5", scenario, j, unsupported)
        self.assertLessEqual(result["synthetic_compute_units"], scenario.budget)
        self.assertFalse(result["promotion_eligible"])
        self.assertFalse(result["decoder_runtime_measured"])

    def test_router_is_fitted_and_frozen_from_train_only(self):
        train = make_scenarios(48)[:24]
        evaluation = make_scenarios(48)[24:]
        self.assertFalse({s.episode for s in train} & {s.episode for s in evaluation})
        j = Objective("simulation", 1, MODALITIES, frozenset(), 2., .05, .5, 1.)
        scores = fit_static_topk_router(train, j)
        baseline = dict(scores)
        changed = replace(evaluation[0], actions=tuple(
            replace(a, observed_gain=-999.) for a in evaluation[0].actions
        ))
        c = Covariance(False, (), 0, math.inf, 0, "unsupported")
        self.assertEqual(choose_action("A2", evaluation[0], (), 2., j, c, scores),
                         choose_action("A2", changed, (), 2., j, c, scores))
        self.assertEqual(scores, baseline)
        with self.assertRaises(GateRejected):
            fit_static_topk_router(train[:3], j)
        with self.assertRaises(GateRejected):
            choose_action("A2", evaluation[0], (), 2., j, c, {"text": 1.})

    def test_required_outputs_are_hard_constraints(self):
        j = objective()
        scenario = Scenario("incomplete", (
            GenerationAction("flash", "text", 2., 6., .2),
            GenerationAction("text", "text", 1., 1., .1),
        ), {}, 2., 2)
        unsupported = Covariance(False, (), 0, math.inf, 0, "no support")
        for arm in ARMS:
            row = run_shadow_arm(arm, scenario, j, unsupported)
            self.assertFalse(row["output_contract_satisfied"])
            self.assertIsNone(row["synthetic_ndu"])
            self.assertEqual(row["disposition"], "abstain_missing_modality")

    def test_synthetic_shadow_repeatability_and_no_model_calls(self):
        scenario = make_scenarios(1)[0]
        j = Objective("simulation", 1, MODALITIES, frozenset(), 2., .05, .5, 1.)
        unsupported = Covariance(False, (), 0, math.inf, 0, "no support")
        first = run_shadow_arm("A5", scenario, j, unsupported)
        second = run_shadow_arm("A5", scenario, j, unsupported)
        for key in ("selected", "synthetic_ndu", "synthetic_compute_units",
                    "output_contract_satisfied", "promotion_eligible"):
            self.assertEqual(first[key], second[key])
        self.assertFalse(first["decoder_runtime_measured"])

    def test_invalid_generated_actions_or_interactions_reject(self):
        with self.assertRaises(GateRejected):
            GenerationAction("bad", "image", -1., 1., 0.)
        with self.assertRaises(GateRejected):
            GenerationAction("bad", "image", 1., 1., math.nan)
        with self.assertRaises(GateRejected):
            Scenario("bad", (GenerationAction("text", "text", 1., 1., 0.),),
                     {("text", "unknown"): 2.}, 2., 3)

    def test_a5_does_not_peek_observed_synergy(self):
        scenario = make_scenarios(1)[0]
        no_oracle = replace(scenario, observed_synergy={("text", "image"): -1000.})
        j = Objective("simulation", 1, MODALITIES, frozenset(), 2., .05, .5, 1.)
        unsupported = Covariance(False, (), 0, math.inf, 0, "no support")
        self.assertEqual(choose_action("A5", scenario, (), 2., j, unsupported),
                         choose_action("A5", no_oracle, (), 2., j, unsupported))
        self.assertNotEqual(run_shadow_arm("A5", scenario, j, unsupported)["synthetic_ndu"],
                            run_shadow_arm("A5", no_oracle, j, unsupported)["synthetic_ndu"])


    def test_forecast_cannot_masquerade_as_realized_gain_or_interaction(self):
        basic = (
            GenerationAction("text", "text", 1., 3., .1),
            GenerationAction("image", "image", 1., 3., .1, observed_gain=2.),
        )
        scene = Scenario("missing-observation", basic, {("text", "image"): 2.}, 2., 2,
                         {("text", "image"): 1.})
        with self.assertRaisesRegex(GateRejected, "missing observed generation outcome"):
            scene.value(("text", "image"), .1, .3, observed=True)
        both = replace(scene, actions=(replace(basic[0], observed_gain=1.), basic[1]),
                       observed_synergy=None)
        with self.assertRaisesRegex(GateRejected, "missing observed interaction outcome"):
            both.value(("text", "image"), .1, .3, observed=True)
        # Predictions remain legal for planning; only observed scoring is fail-closed.
        self.assertTrue(math.isfinite(scene.value(("text", "image"), .1, .3)))


if __name__ == "__main__":
    unittest.main()
