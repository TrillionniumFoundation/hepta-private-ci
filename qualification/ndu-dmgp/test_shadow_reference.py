"""Adversarial deterministic reference tests; no production qualification claims."""
import unittest
from math import isclose

from shadow_reference import (
    Objective, Outcome, EvidenceError, InsufficientSupport,
    validated_outcomes, paired_advantage, ModalityTrace, CycleProbe,
    check_multimodal_consistency, JointSample, conditional_covariance,
    choose_portfolio, local_shapley_credit, ClosureRow, closure_audit,
    stage_next_snapshot, future_window_gate, EXPERIMENT_MODES,
)

O = Objective("frozen-objective-v1", "independent-observer", 4, 80)


def row(ep, action, utility, split="train", observer=O.observer_id,
        source="external", digest=O.digest, actual_cost=1):
    return Outcome(ep, action, split, digest, observer, source, utility, actual_cost)


class TestNduDmgpShadow(unittest.TestCase):
    def test_independent_observer_and_objective_freeze(self):
        rows = [row("e1", "base", 0.3)]
        self.assertEqual(validated_outcomes(rows, O, "actor", "critic"), tuple(rows))
        with self.assertRaises(EvidenceError):
            validated_outcomes(rows, O, O.observer_id, "critic")
        for bad in (row("e1", "base", .3, source="self"),
                    row("e1", "base", .3, digest="mutable"),
                    row("e1", "base", .3, observer="critic")):
            with self.assertRaises(EvidenceError):
                validated_outcomes([bad], O, "actor", "critic")
        with self.assertRaises(EvidenceError):
            validated_outcomes([rows[0], row("e1", "base", .8, split="future")], O, "actor", "critic")

    def test_real_cost_must_be_recorded_and_finite(self):
        with self.assertRaises(EvidenceError):
            validated_outcomes([row("e1", "a", 1, actual_cost=-2)], O, "actor", "critic")
        with self.assertRaises(EvidenceError):
            validated_outcomes([row("e1", "a", float("nan"))], O, "actor", "critic")

    def test_paired_training_only_and_no_missing_support(self):
        rows = [row(f"e{i}", a, u) for i in range(8)
                for a, u in (("base", .3), ("candidate", .7))]
        approved = validated_outcomes(rows, O, "actor", "critic")
        self.assertAlmostEqual(paired_advantage(approved, "base", "candidate"), .4)
        with self.assertRaises(InsufficientSupport):
            paired_advantage(approved[:8], "base", "candidate")

    def test_cross_modal_entities_sync_and_independent_cycles(self):
        outputs = [ModalityTrace("audio", (("speaker", "alice"),), (("speech", 200),)),
                   ModalityTrace("video", (("speaker", "alice"),), (("speech", 235),))]
        probes = [CycleProbe("audio", "video", "alice", "alice", "alice", O.observer_id)]
        r = check_multimodal_consistency(outputs, probes, O)
        self.assertEqual(r["synchronized_events"], 1)
        with self.assertRaises(EvidenceError):
            check_multimodal_consistency([outputs[0], ModalityTrace("video", (("speaker", "bob"),), (("speech", 235),))], probes, O)
        with self.assertRaises(EvidenceError):
            check_multimodal_consistency([outputs[0], ModalityTrace("video", (("speaker", "alice"),), (("speech", 500),))], probes, O)
        # A self-consistent hallucination is NOT an independent truth check.
        with self.assertRaises(EvidenceError):
            check_multimodal_consistency(outputs, [CycleProbe("audio", "video", "bob", "bob", "alice", O.observer_id)], O)
        with self.assertRaises(InsufficientSupport):
            check_multimodal_consistency(outputs, [], O)

    def test_conditional_covariance_supported_and_low_ess_fails_closed(self):
        rows = [JointSample("hard", (i/21, (21-i)/25 + (i%3)*.01), .5)
                for i in range(20)]
        c = conditional_covariance(rows, "hard", 2, rank=1)
        self.assertGreater(c.effective_n, 8)
        self.assertEqual(c.rank, 1)
        self.assertGreater(c.eigenvalues[-1], 0)
        self.assertAlmostEqual(c.matrix[0][1], c.matrix[1][0])
        with self.assertRaises(InsufficientSupport):
            conditional_covariance(rows[:5], "hard", 2)
        with self.assertRaises(InsufficientSupport):
            conditional_covariance(rows, "unknown-context", 2)
        low_ess = [JointSample("h", (i/20, i/30), .001 if i==0 else 1.) for i in range(20)]
        with self.assertRaises(InsufficientSupport):
            conditional_covariance(low_ess, "h", 2)
        with self.assertRaises(EvidenceError):
            conditional_covariance([JointSample("h", (0., 1.), 0.)]*20, "h", 2)

    def test_singular_joint_risk_requires_deterministic_fallback(self):
        with self.assertRaises(InsufficientSupport):
            conditional_covariance([JointSample("h", (.2, .2), 1.)]*20, "h", 2)
        with self.assertRaises(InsufficientSupport):
            choose_portfolio([.2, .3], [1, 2], 4, 1, None)
        p = choose_portfolio([.2, .3], [1, 2], 4, 0, None)
        self.assertEqual(p.method, "deterministic")
        self.assertAlmostEqual(sum(p.weights), 1)

    def test_hard_cost_before_utility_and_no_bypass(self):
        p = choose_portfolio([.2, 999.], [1, 5], 4, 0, None)
        self.assertEqual(p.weights, (1., 0.))
        with self.assertRaises(InsufficientSupport):
            choose_portfolio([1.], [5.], 4, 0, None)

    def test_shapley_requires_all_external_joint_ablations(self):
        values = {frozenset(): 0., frozenset({"text"}): .2,
                  frozenset({"image"}): .1, frozenset({"text", "image"}): .7}
        credit = local_shapley_credit(["text", "image"], values, O.observer_id, O)
        self.assertAlmostEqual(credit["text"], .4)
        self.assertAlmostEqual(credit["image"], .3)
        self.assertAlmostEqual(sum(credit.values()), .7)
        with self.assertRaises(InsufficientSupport):
            local_shapley_credit(["text", "image"], {frozenset():0., frozenset({"text", "image"}):.7}, O.observer_id, O)
        with self.assertRaises(EvidenceError):
            local_shapley_credit(["text"], {frozenset():0., frozenset({"text"}):1.}, "actor", O)

    def test_non_markov_compressed_state_rejected(self):
        rows = []
        for split, count in (("train", 12), ("future", 8)):
            for i in range(count):
                rows.append(ClosureRow("compressed", "emit", "past-a" if i%2 else "past-b", float(i%2), split))
        proof = closure_audit(rows)
        self.assertFalse(proof["sufficient"])
        self.assertGreater(proof["state_mse"], proof["history_mse"])
        state_sufficient = [ClosureRow("s", "a", "h1" if i%2 else "h0", .6, "train" if i<12 else "future") for i in range(20)]
        self.assertTrue(closure_audit(state_sufficient)["sufficient"])

    def test_policy_update_is_staged_frozen_critic_and_kl_bounded(self):
        proposal = stage_next_snapshot(4, 5, [.5,.5], [.52,.48], "critic-v1", "critic-v1")
        self.assertTrue(proposal["advisory_only"])
        with self.assertRaises(EvidenceError):
            stage_next_snapshot(4, 4, [.5,.5], [.52,.48], "critic-v1", "critic-v1")
        with self.assertRaises(EvidenceError):
            stage_next_snapshot(4, 5, [.5,.5], [.52,.48], "critic-v1", "critic-v2")
        with self.assertRaises(EvidenceError):
            stage_next_snapshot(4, 5, [.5,.5], [.99,.01], "critic-v1", "critic-v1")

    def test_future_window_and_retention_reject_weak_evidence(self):
        good = future_window_gate([.95]*300, [.05]*300, [1.]*300, [.8]*300)
        self.assertTrue(good["admitted"])
        self.assertFalse(good["authority_granted"])
        harmed = future_window_gate([.95]*300, [.05]*300, [.1]*300, [.8]*300)
        self.assertFalse(harmed["admitted"])
        with self.assertRaises(InsufficientSupport):
            future_window_gate([1.]*4, [0.]*4, [1.]*4, [0.]*4)

    def test_registered_a0_to_a5(self):
        self.assertEqual(set(EXPERIMENT_MODES), {f"A{i}" for i in range(6)})


if __name__ == "__main__":
    unittest.main()
