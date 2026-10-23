"""Shadow-only closure regression suite; signatures here are test fixtures."""
import hashlib
import hmac
import unittest
from dataclasses import replace

from causal_credit import CreditRejected
from history_closure import ClosureProtocol, ClosureTrace, audit_prospective_closure

KEYS = {"registrar": b"test-registrar", "observer": b"test-observer"}


def digest(s):
    return hashlib.sha256(s.encode()).hexdigest()


def sign(who, payload):
    return hmac.new(KEYS[who], payload.encode(), "sha256").hexdigest()


def verify(who, payload, signed):
    return who in KEYS and hmac.compare_digest(sign(who, payload), signed)


def case(history_signal=False):
    plan = ClosureProtocol(
        "trial", "registrar", "actor", digest("objective"), digest("snapshot"),
        digest("critic"), 1, 100, 200, 300,
        tuple((f"future-{i}", f"future-cluster-{i}") for i in range(96)),
        .26, .05, ""
    )
    plan = replace(plan, registrar_signature=sign("registrar", plan.digest()))

    def row(split, i):
        value = float(i % 2) if history_signal else .5
        result = ClosureTrace(
            plan.trial_id, f"{split}-{i}", f"{split}-cluster-{i}", split,
            plan.objective_digest, plan.snapshot_digest, plan.critic_digest, 1,
            "compressed-state", f"history-{i % 2}",
            320 if split == "future" else 120,
            350 if split == "future" else 130,
            value, "actor", "observer", "independent_observation", ""
        )
        return replace(result, observer_signature=sign("observer", result.digest()))

    return (plan, [row("train", i) for i in range(80)],
            [row("future", i) for i in range(96)])


class ClosureTests(unittest.TestCase):
    def test_no_history_signal_and_no_production_claim(self):
        plan, train, future = case()
        got = audit_prospective_closure(plan, train, future, verify)
        self.assertTrue(got.compressed_state_supported_in_region)
        self.assertFalse(got.exact_markov_sufficiency_proven)
        self.assertFalse(got.production_authority)

    def test_predictive_history_detected(self):
        plan, train, future = case(True)
        got = audit_prospective_closure(plan, train, future, verify)
        self.assertAlmostEqual(got.observed_mse_gain, .25)
        self.assertFalse(got.compressed_state_supported_in_region)

    def test_missing_future_or_out_of_scope_denied(self):
        plan, train, future = case()
        with self.assertRaises(CreditRejected):
            audit_prospective_closure(plan, train, future[:-1], verify)
        altered = future.copy()
        altered[0] = replace(future[0], outcome=.9)
        with self.assertRaises(CreditRejected):
            audit_prospective_closure(plan, train, altered, verify)
        with self.assertRaises(CreditRejected):
            audit_prospective_closure(plan, train, future, None)
        with self.assertRaises(CreditRejected):
            audit_prospective_closure(replace(plan, alpha=.5), train, future, verify)

    def test_unseen_history_or_reused_cluster_denied(self):
        plan, train, future = case()
        for change in ({"available_history": "unknown"},
                       {"cluster_id": train[0].cluster_id}):
            sample = replace(future[0], **change, observer_signature="")
            sample = replace(sample, observer_signature=sign("observer", sample.digest()))
            with self.assertRaises(CreditRejected):
                audit_prospective_closure(plan, train, [sample] + future[1:], verify)


if __name__ == "__main__":
    unittest.main()
