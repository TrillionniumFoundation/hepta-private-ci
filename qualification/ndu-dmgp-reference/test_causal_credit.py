"""Adversarial shadow tests for prospective Cell credit; HMAC is fixture ONLY."""
import hashlib
import hmac
import math
import unittest
from dataclasses import replace
from itertools import combinations

from causal_credit import (
    CreditRejected, CoalitionOutcome, ProspectiveCreditTrial, verify_factorial_credit,
)

KEYS = {
    "registrar": b"preregister-fixture-not-a-trust-root",
    "observer": b"independent-observer-fixture-not-a-trust-root",
    "meter": b"independent-meter-fixture-not-a-trust-root",
}


def d(text):
    return hashlib.sha256(text.encode("utf8")).hexdigest()


def signature(identity, digest):
    return hmac.new(KEYS[identity], digest.encode("ascii"), "sha256").hexdigest()


def verifier(identity, digest, signed):
    return identity in KEYS and hmac.compare_digest(signature(identity, digest), signed)


def signed_trial(cells=("a", "b"), n=32, **kw):
    trial = ProspectiveCreditTrial(
        trial_id="credit-trial", actor_id="actor", registrar_id="registrar",
        objective_digest=d("immutable-objective"),
        snapshot_digest=d("selected-backbone"),
        encoder_digest=d("encoder"),
        decoder_digest=d("decoder-registry"),
        critic_digest=d("frozen-critic"),
        generation=5, registered_at=100, future_from=200,
        episodes=tuple((f"e-{i}", f"independent-cluster-{i}", d(f"input-{i}"))
                       for i in range(n)),
        cells=cells, resource_price=.01, risk_price=.1,
        max_compute_units=3.0, abs_ndu_bound=1.0,
        max_pair_interaction_fraction=.2, alpha=.05,
        registrar_signature="", **kw
    )
    return replace(trial, registrar_signature=signature("registrar", trial.digest()))


def signed_outcome(trial, episode, cluster, inp, active,
                   quality, compute=1.0, risk=.0):
    obs = CoalitionOutcome(
        trial_id=trial.trial_id, episode_id=episode, cluster_id=cluster,
        input_digest=inp, objective_digest=trial.objective_digest,
        snapshot_digest=trial.snapshot_digest, critic_digest=trial.critic_digest,
        generation=trial.generation, active_cells=active, split="future",
        observed_at=250, actor_id="actor", observer_id="observer", meter_id="meter",
        quality=quality, compute_units=compute, risk=risk,
        output_digest=d(f"output-{episode}-{active}"),
        meter_digest=d(f"meter-{episode}-{active}"),
        evidence_kind="independent_observation",
        observer_signature="", meter_signature="",
    )
    stamp = obs.digest()
    return replace(obs, observer_signature=signature("observer", stamp),
                   meter_signature=signature("meter", stamp))


def panel(trial, *, synergy=0.0, cancel=False):
    rows = []
    for episode, cluster, inp in trial.episodes:
        for size in range(len(trial.cells) + 1):
            for active in combinations(trial.cells, size):
                if cancel:
                    # Each individual cell looks helpful, but together erase gain.
                    quality = .2 if len(active) != 1 else .5
                else:
                    gains = {"a": .1, "b": .15, "c": .08}
                    quality = .2 + sum(gains[c] for c in active)
                    if {"a", "b"}.issubset(active):
                        quality += synergy
                rows.append(signed_outcome(trial, episode, cluster, inp,
                                           active, quality))
    return rows


class ProspectiveFactorialTests(unittest.TestCase):
    def test_complete_additive_panel_has_exact_but_not_causal_credit(self):
        trial = signed_trial()
        result = verify_factorial_credit(trial, panel(trial), verifier)
        self.assertTrue(result.exact_factorial_complete)
        self.assertEqual(result.episodes, 32)
        self.assertAlmostEqual(result.mean_shapley[0], .1)
        self.assertAlmostEqual(result.mean_shapley[1], .15)
        self.assertAlmostEqual(result.mean_global_delta, .25)
        self.assertAlmostEqual(result.max_pair_interaction_fraction, 0, places=9)
        self.assertTrue(result.low_interaction_supported)
        # n=32 is insufficient for uniformly positive Hoeffding credit bounds.
        self.assertFalse(result.positive_local_credit_supported)
        self.assertFalse(result.causal_effect_identified)
        self.assertFalse(result.production_blockers_closed)
        self.assertFalse(result.production_authority)

    def test_strong_cross_cell_synergy_refuses_local_credit(self):
        trial = signed_trial()
        result = verify_factorial_credit(trial, panel(trial, synergy=.3), verifier)
        self.assertAlmostEqual(result.mean_shapley[0], .25)
        self.assertAlmostEqual(result.mean_shapley[1], .30)
        self.assertAlmostEqual(result.mean_global_delta, .55)
        self.assertGreater(result.max_pair_interaction_fraction, .5)
        self.assertFalse(result.low_interaction_supported)
        self.assertFalse(result.positive_local_credit_supported)

    def test_zero_global_gain_with_illusive_local_gains_fails(self):
        trial = signed_trial()
        result = verify_factorial_credit(trial, panel(trial, cancel=True), verifier)
        self.assertAlmostEqual(result.mean_global_delta, 0)
        self.assertGreater(result.max_pair_interaction_fraction, 1)
        self.assertFalse(result.low_interaction_supported)

    def test_three_cell_complete_factorial_and_interaction_conservation(self):
        trial = signed_trial(cells=("a", "b", "c"))
        result = verify_factorial_credit(trial, panel(trial), verifier)
        self.assertEqual(result.episodes, 32)
        for found, expected in zip(result.mean_shapley, (.1, .15, .08)):
            self.assertAlmostEqual(found, expected)
        self.assertAlmostEqual(result.mean_global_delta, .33)

    def test_missing_duplicate_or_misassigned_coalitions_denied(self):
        trial = signed_trial()
        records = panel(trial)
        cases = [
            records[:-1],
            records + records[:1],
            records[:-1] + [records[0]],
            records[:-1] + [replace(records[-1], active_cells=("a",))],
        ]
        for rows in cases:
            with self.subTest(length=len(rows)), self.assertRaises(CreditRejected):
                verify_factorial_credit(trial, rows, verifier)

    def test_mutation_after_signature_never_reuses_observer_evidence(self):
        trial = signed_trial()
        records = panel(trial)
        row = records[1]
        mutations = (
            {"quality": .97}, {"compute_units": 3.}, {"risk": .25},
            {"output_digest": d("replaced-decoder")},
            {"meter_digest": d("replaced-meter")},
            {"active_cells": ()},
            {"observer_signature": "forged"},
            {"meter_signature": "forged"},
        )
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                changed = records.copy()
                changed[1] = replace(row, **mutation)
                with self.assertRaises(CreditRejected):
                    verify_factorial_credit(trial, changed, verifier)

    def test_verified_but_invalid_source_and_cost_fail_closed(self):
        trial = signed_trial()
        records = panel(trial)
        modifications = (
            {"actor_id": "observer"}, {"observer_id": "meter"},
            {"snapshot_digest": d("other-snapshot")},
            {"critic_digest": d("trained-on-future")},
            {"generation": 6}, {"generation": True},
            {"split": "train"}, {"observed_at": 199}, {"observed_at": True},
            {"quality": math.nan}, {"quality": True}, {"quality": 1.1},
            {"compute_units": 0.}, {"compute_units": math.inf},
            {"compute_units": 3.1}, {"risk": 1.1}, {"risk": math.nan},
            {"evidence_kind": "synthetic_generator"},
            {"input_digest": d("another-task")},
        )
        for mutation in modifications:
            with self.subTest(mutation=mutation):
                row = replace(records[0], **mutation)
                try:
                    digest = row.digest()
                    row = replace(row, observer_signature=signature("observer", digest),
                                  meter_signature=signature("meter", digest))
                except CreditRejected:
                    pass
                changed = records.copy()
                changed[0] = row
                with self.assertRaises(CreditRejected):
                    verify_factorial_credit(trial, changed, verifier)

    def test_preregistration_signature_identity_and_support_enforced(self):
        trial = signed_trial()
        records = panel(trial)
        with self.assertRaises(CreditRejected):
            verify_factorial_credit(trial, records, None)
        for mutation in (
            {"alpha": .3}, {"cells": ("b", "a")},
            {"objective_digest": d("changed-objective")},
            {"registered_at": 300}, {"generation": True},
            {"registrar_signature": "forged"},
        ):
            with self.subTest(mutation=mutation), self.assertRaises(CreditRejected):
                verify_factorial_credit(replace(trial, **mutation), records, verifier)
        with self.assertRaises(CreditRejected):
            signed_trial(n=31).check()
        repeated = replace(trial, episodes=tuple(
            (ep, "duplicate-cluster", inp) for ep, _, inp in trial.episodes
        ))
        with self.assertRaises(CreditRejected):
            repeated.check()


if __name__ == "__main__":
    unittest.main()
