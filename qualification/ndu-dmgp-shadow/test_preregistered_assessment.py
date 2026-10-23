"""Negative scientific-admission tests; synthetic rows are not real receipts."""
from dataclasses import replace
import unittest

from reference import Freeze, Outcome, Unavailable
from preregistered_assessment import ARMS, PairedProtocol, assess_paired_a0_a5

F = Freeze("objective", 3, "actor", "critic", "observer",
           "critic-sha", "feature-sha")
P = PairedProtocol(F.objective, F.generation, F.critic_digest, 2000, .0001)


def paired_rows(n=40, candidate=.65, baseline=.45):
    return tuple(
        Outcome(str(i), arm, F.objective, F.generation, F.observer,
                F.actor, F.critic_digest, f"unique-source:{i}",
                "future", candidate if arm == "A5" else baseline,
                1000 if arm == "A5" else 1100, 10, 5,
                f"actual-physical-work:{i}:{arm}")
        for i in range(n) for arm in ARMS
    )


class PreregisteredComparisonTests(unittest.TestCase):
    def test_paired_net_quality_not_mislabelled_as_production(self):
        report = assess_paired_a0_a5(paired_rows(), F, P)
        self.assertEqual(report["future_paired_episode_count"], 40)
        self.assertEqual(set(report["paired_net_advantage"]), set(ARMS[:-1]))
        self.assertFalse(report["production_blockers_closed"])
        self.assertFalse(report["external_observation_signed"])
        self.assertFalse(report["physical_decoder_meter_attested"])
        self.assertTrue(report["no_promotion_authority"])
        # The nominal 0.21 gain is NOT statistically identified at 40 samples.
        self.assertFalse(report["all_lcb_positive_given_iid"])
        self.assertGreater(report["hoeffding_radius"], .95)

    def test_huge_synthetic_advantage_still_cannot_promote(self):
        report = assess_paired_a0_a5(paired_rows(candidate=1., baseline=-1.), F, P)
        self.assertTrue(report["all_lcb_positive_given_iid"])
        self.assertFalse(report["production_blockers_closed"])
        self.assertFalse(report["external_independence_authenticated"])

    def test_missing_or_duplicate_arm_is_rejected(self):
        rows = paired_rows()
        with self.assertRaisesRegex(Unavailable, "incomplete paired"):
            assess_paired_a0_a5(rows[:-1], F, P)
        with self.assertRaisesRegex(Unavailable, "duplicate arm"):
            assess_paired_a0_a5(rows + (replace(rows[0], work_key="new-execution"),), F, P)

    def test_train_leakage_and_critic_drift(self):
        rows = paired_rows()
        with self.assertRaisesRegex(Unavailable, "leaked"):
            assess_paired_a0_a5((replace(rows[0], split="train"),) + rows[1:], F, P)
        with self.assertRaisesRegex(Unavailable, "drift"):
            assess_paired_a0_a5((replace(rows[0], critic_digest="changed"),) + rows[1:],
                                 F, P)
        with self.assertRaisesRegex(Unavailable, "unfrozen"):
            assess_paired_a0_a5(rows, F, replace(P, critic_digest="new-critic"))

    def test_sample_independence_and_inputs_must_not_be_reused(self):
        rows = paired_rows()
        # Repeated source across different episodes is pseudoreplication, not
        # a second independent future cluster.
        damaged = tuple(replace(r, source_digest="unique-source:0") if r.episode == "1"
                        else r for r in rows)
        with self.assertRaisesRegex(Unavailable, "pseudoreplicated"):
            assess_paired_a0_a5(damaged, F, P)
        damaged = (replace(rows[0], source_digest="different-input"),) + rows[1:]
        with self.assertRaisesRegex(Unavailable, "unmatched paired input"):
            assess_paired_a0_a5(damaged, F, P)

    def test_price_alpha_support_and_budget_must_be_frozen(self):
        rows = paired_rows()
        for p in (replace(P, cost_per_us=-.1),
                  replace(P, familywise_alpha=.2),
                  replace(P, familywise_alpha=float("nan")),
                  replace(P, min_future_episodes=2),
                  replace(P, max_total_us=True),
                  replace(P, cost_per_us=1e308),
                  replace(P, max_total_us=100)):
            with self.subTest(protocol=p):
                with self.assertRaises(Unavailable):
                    assess_paired_a0_a5(rows, F, p)

    def test_same_work_key_and_extra_arm_rejected(self):
        rows = paired_rows()
        forged = (replace(rows[1], work_key=rows[0].work_key),) + rows[:1] + rows[2:]
        with self.assertRaisesRegex(Unavailable, "duplicate physical"):
            assess_paired_a0_a5(forged, F, P)
        with self.assertRaisesRegex(Unavailable, "unexpected arm"):
            assess_paired_a0_a5((replace(rows[0], arm="A6"),) + rows[1:], F, P)


if __name__ == "__main__":
    unittest.main()
