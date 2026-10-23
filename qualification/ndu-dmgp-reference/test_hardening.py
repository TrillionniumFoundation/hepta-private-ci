"""New adversarial guardrails for the existing DMGP shadow reference."""
import math
import unittest
from dataclasses import replace

from reference import (Covariance, GateRejected, MediaEvent, MODALITIES, Objective,
                       Observation, cross_modal_contract, next_snapshot_gate,
                       portfolio_weights, reference_report)


def objective():
    return Objective("frozen", 1, MODALITIES, frozenset({"text", "image"}),
                     4., .1, .1, 1.)


def obs(episode, split, policy, quality=1.):
    j = objective()
    return Observation(episode, j.digest, 1, policy, "actor", "independent-observer",
                       split, 10, quality, 1., .1, "independent_observation", True)


class NativeShadowHardeningTests(unittest.TestCase):
    def test_a4_does_not_invent_risk_variance_from_forecast_noise(self):
        report = reference_report()
        # The synthetic audio expert has exactly constant forecast error.
        # Conditional residual covariance is unidentifiable and must fall back.
        self.assertFalse(report["covariance_supported"])
        self.assertEqual(report["summary"]["A5"]["mean_synthetic_ndu"],
                         report["summary"]["A1"]["mean_synthetic_ndu"])

    def test_risk_profile_nonfinite_asymmetric_or_indefinite_rejected(self):
        c = Covariance(True, ((1., 0.), (0., 1.)), 30, 1., 2, "test")
        with self.assertRaises(GateRejected):
            portfolio_weights((1., 2.), c, risk_price=math.nan)
        with self.assertRaises(GateRejected):
            portfolio_weights((1., 2.), c, risk_price=math.inf)
        malformed = Covariance(True, ((1., 2.), (0., 1.)), 30, 1., 2, "test")
        with self.assertRaises(GateRejected):
            portfolio_weights((1., 2.), malformed)
        indefinite = Covariance(True, ((1., 2.), (2., 1.)), 30, 1., 2, "test")
        with self.assertRaises(GateRejected):
            portfolio_weights((1., 2.), indefinite)
        nan_matrix = Covariance(True, ((1., math.nan), (math.nan, 1.)), 30, 1., 2, "test")
        with self.assertRaises(GateRejected):
            portfolio_weights((1., 2.), nan_matrix)

    def test_timeline_pair_must_have_both_audio_and_video(self):
        events = (
            MediaEvent("text", "text", 0, 100, frozenset({"A"}), frozenset({"event"})),
            MediaEvent("image", "image", 0, 100, frozenset({"A"}), frozenset({"event"})),
            MediaEvent("audio", "audio", 0, 100, frozenset({"A"}), frozenset({"event"}), "track-1"),
        )
        verdict = cross_modal_contract(objective(), events, frozenset({"A"}),
                                       frozenset({"event"}))
        self.assertFalse(verdict.supported)
        self.assertIn("unpaired audio-video timeline", verdict.violations)

    def test_policy_identity_cannot_be_spliced_across_future_and_retention(self):
        candidates = [obs(f"future-{i}", "future", "candidate", 10.) for i in range(16)]
        baselines = [obs(f"future-{i}", "future", "baseline", 5.) for i in range(16)]
        retention_c = [obs(f"ret-{i}", "retention", "candidate", 5.) for i in range(16)]
        retention_b = [obs(f"ret-{i}", "retention", "baseline", 5.) for i in range(16)]
        params = dict(candidate=candidates, baseline=baselines,
                      retention_candidate=retention_c, retention_baseline=retention_b,
                      objective=objective(), selected_generation=1, candidate_generation=2,
                      critic_frozen=True, trust_region_kl=.01)
        self.assertTrue(next_snapshot_gate(**params)[0])
        for mutation in (
            {"candidate": candidates[:-1] + [replace(candidates[-1], policy_id="baseline")]},
            {"retention_candidate": [replace(r, policy_id="other") for r in retention_c]},
            {"baseline": [replace(r, policy_id="candidate") for r in baselines]},
        ):
            with self.subTest(mutation=list(mutation)):
                allowed, errors = next_snapshot_gate(**{**params, **mutation})
                self.assertFalse(allowed)
                self.assertIn("candidate/baseline policy identity mismatch", errors)


if __name__ == "__main__":
    unittest.main()
