"""Fail-closed structural evidence tests; HMAC fixtures are NOT production trust."""
import hashlib
import hmac
import math
import unittest
from dataclasses import replace

from reference import MODALITIES, GateRejected, Objective
from admission import (RunEvidence, admit_run, compare_a0_a5,
                       conditional_covariance, evidence_digest)

KEYS = {"independent-observer": b"observer-test-fixture-not-real-trust",
        "host-meter": b"meter-test-fixture-not-real-trust"}
D = lambda value: hashlib.sha256(value.encode()).hexdigest()


def objective():
    return Objective("heldout-task", 1, MODALITIES, frozenset({"text", "image"}),
                     3., .02, .1, .9)


def verify(principal, digest, signature):
    key = KEYS.get(principal)
    return key is not None and hmac.compare_digest(
        hmac.new(key, digest.encode(), "sha256").hexdigest(), signature)


def signed(record):
    digest = evidence_digest(record)
    return replace(record, observer_signature=hmac.new(
        KEYS[record.observer_id], digest.encode(), "sha256").hexdigest(),
        meter_signature=hmac.new(
            KEYS[record.meter_id], digest.encode(), "sha256").hexdigest())


def raw(i=0, arm="A5", split="future", quality=.8, cost=1.):
    return RunEvidence(
        run_id=f"{split}-{i}-{arm}", episode=f"{split}-{i}", arm=arm,
        split=split, stratum="text-image", objective_digest=objective().digest,
        generation=1, input_digest=D(f"input-{split}-{i}"),
        encoder_digest=D("encoder"), decoder_registry_digest=D("decoders"),
        selected_snapshot_digest=D("selected"), critic_digest=D("critic-v1"),
        actor_id=f"policy-{arm}", observer_id="independent-observer", meter_id="host-meter",
        observed_at=(50+i if split == "train" else 200+i),
        quality=quality, compute_units=cost, risk=.04, wall_us=2000.,
        encoder_us=150., decoder_us=1400., controller_us=50.,
        peak_rss_bytes=4000000, peak_vram_bytes=300000, energy_mj=40.,
        required_modalities=("text", "image"), emitted_modalities=("text", "image"),
        consistency_evidence_digest=D(f"consistency-{split}-{i}-{arm}"),
        evidence_kind="independent_observation", observer_signature="", meter_signature="",
    )


def admitted(records):
    return [admit_run(signed(x), objective(), verify) for x in records]


class IndependentEvidenceTests(unittest.TestCase):
    def test_external_verifier_mandatory_and_both_signatures_bound(self):
        good = signed(raw())
        with self.assertRaisesRegex(GateRejected, "verifier unavailable"):
            admit_run(good, objective())
        accepted = admit_run(good, objective(), verify)
        self.assertFalse(accepted.production_authority)
        self.assertAlmostEqual(accepted.net_ndu, .8-.02-.004)
        for mutation in (
            {"quality": .95}, {"compute_units": 2.}, {"controller_us": 100.},
            {"input_digest": D("other-input")}, {"selected_snapshot_digest": D("new")},
            {"critic_digest": D("critic-v2")},
            {"emitted_modalities": ("text",)},
            {"consistency_evidence_digest": D("fake-reconstruction")},
            {"observer_signature": "forged"}, {"meter_signature": "forged"},
        ):
            with self.subTest(mutation=mutation), self.assertRaises(GateRejected):
                admit_run(replace(good, **mutation), objective(), verify)

    def test_structural_hard_fails_even_with_valid_signatures(self):
        for mutation in (
            {"actor_id": "host-meter"}, {"observer_id": "host-meter"},
            {"objective_digest": D("different-objective")},
            {"evidence_kind": "synthetic_reference"},
            {"required_modalities": ("text",)},
            {"emitted_modalities": ("text",)},
            {"peak_rss_bytes": 0}, {"peak_vram_bytes": -1},
            {"wall_us": 30.}, {"controller_us": math.nan},
            {"quality": 1.1}, {"risk": 1.1}, {"compute_units": 5.},
        ):
            with self.subTest(mutation=mutation), self.assertRaises(GateRejected):
                changed = replace(raw(), **mutation)
                # An authorized signer cannot legalize illegal source, scope or physics.
                digest = evidence_digest(changed) if math.isfinite(changed.controller_us) else "bad"
                record = replace(changed,
                                 observer_signature=hmac.new(KEYS["independent-observer"],
                                     digest.encode(), "sha256").hexdigest(),
                                 meter_signature=hmac.new(KEYS["host-meter"],
                                     digest.encode(), "sha256").hexdigest())
                admit_run(record, objective(), verify)


class MatchedStatisticalTests(unittest.TestCase):
    def matrix(self, n=36, equal=False, split="future"):
        return admitted([raw(i, arm, split=split,
                 quality=(.8 if arm == "A5" else (.8 if equal else .1))
                         + .01*math.sin(i))
                         for i in range(n) for arm in ("A0", "A1", "A2", "A3", "A4", "A5")])

    def test_all_arms_paired_and_conservative_cannot_claim_production(self):
        verdict = compare_a0_a5(self.matrix(n=1024), ndu_abs_bound=1.,
                                max_controller_fraction=.1)
        self.assertTrue(verdict.qualifies_statistically)
        self.assertEqual(verdict.episodes, 1024)
        self.assertFalse(verdict.production_authority)
        self.assertFalse(verdict.production_blockers_closed)
        self.assertEqual(len(verdict.simultaneous_lcb), 5)

    def test_a5_tied_with_a1_fails_regardless_of_synthetic_gain(self):
        verdict = compare_a0_a5(self.matrix(n=512, equal=True), ndu_abs_bound=1.)
        self.assertFalse(verdict.qualifies_statistically)
        self.assertLessEqual(dict(verdict.simultaneous_lcb)["A1"], 0)

    def test_missing_arm_duplicate_mixed_split_or_manifest_is_rejected(self):
        items = self.matrix(n=32)
        changes = [items[:-1], items + items[:1],
                   items[:-1] + admitted([raw(31, "A5", "train")]),
                   items[:-1] + admitted([replace(raw(31, "A5"),
                                                encoder_digest=D("other"))])]
        for rows in changes:
            with self.subTest(count=len(rows)), self.assertRaises(GateRejected):
                compare_a0_a5(rows, ndu_abs_bound=1.)

    def test_insufficient_episodes_or_unsupported_numerical_profile(self):
        with self.assertRaises(GateRejected):
            compare_a0_a5(self.matrix(n=24), ndu_abs_bound=1.)
        with self.assertRaises(GateRejected):
            compare_a0_a5(self.matrix(n=36), ndu_abs_bound=math.nan)
        too_slow = [replace(row, evidence=replace(row.evidence, controller_us=1000.))
                    for row in self.matrix(n=64)]
        self.assertFalse(compare_a0_a5(too_slow, ndu_abs_bound=1.).qualifies_statistically)


class ConditionalRiskTests(unittest.TestCase):
    def matrix(self, n=36, split="train"):
        return admitted([raw(i, arm, split=split, quality=(
            .2 + .25 * ((i % 7) / 7) if arm == "A0" else
            .3 + .3 * ((i % 5) / 5)))
            for i in range(n) for arm in ("A0", "A1")])

    def test_paired_condition_scoped_covariance_and_low_rank(self):
        result = conditional_covariance(self.matrix(), ("A0", "A1"),
                                        train_cutoff=150, stratum="text-image", rank=1)
        self.assertTrue(result.supported, result.reason)
        self.assertEqual(result.sample_count, 36)
        self.assertEqual(result.factor_rank, 1)
        self.assertGreater(result.risk((.5, .5)), 0)

    def test_covariance_future_leakage_and_selective_missing_reject(self):
        rows = self.matrix()
        for changed in (rows[:-1], self.matrix(split="future"),
                        [replace(r, evidence=replace(r.evidence, observed_at=200))
                         for r in rows]):
            with self.assertRaises(GateRejected):
                conditional_covariance(changed, ("A0", "A1"),
                                       train_cutoff=150, stratum="text-image")
        self.assertFalse(conditional_covariance(self.matrix(n=4), ("A0", "A1"),
                                                train_cutoff=150, stratum="text-image").supported)


if __name__ == "__main__":
    unittest.main()
