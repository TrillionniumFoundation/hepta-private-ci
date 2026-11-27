import dataclasses
from itertools import product
import math
import unittest

import numpy as np

from .contracts import (
    COSTS,
    JOINT_SUPPORT,
    OUTCOMES,
    TIMES,
    Evidence,
    EvidenceSource,
    FrozenObservation,
    allowed_mask,
    brier_score,
    coarsened_nll,
    crps_score,
    history_at,
    history_hash,
    score_exact,
)


class ContractTests(unittest.TestCase):
    def terminal(self, **changes):
        args = dict(
            source="simulator",
            observation_status="terminal",
            outcome=1,
            time_kind="exact",
            time_lower=2,
            final_cost=4,
            receipt_ref="run/receipt",
        )
        return Evidence(**(args | changes))

    def ongoing(self, **changes):
        args = dict(
            observation_status="verified_ongoing",
            time_kind="right_censored",
            time_lower=2,
            nonoccurrence_witness="readback/2",
        )
        return Evidence(**(args | changes))

    def test_grid_order_exact_atom_and_frozen_data(self):
        np.testing.assert_array_equal(
            JOINT_SUPPORT, list(product(OUTCOMES, TIMES, COSTS))
        )
        event = self.terminal()
        self.assertEqual(event.time_upper, 2)
        self.assertEqual(event.source, EvidenceSource.SIMULATOR)
        mask = allowed_mask(event)
        self.assertEqual(mask.sum(), 1)
        np.testing.assert_array_equal(JOINT_SUPPORT[mask][0], [1, 2, 4])
        with self.assertRaises(dataclasses.FrozenInstanceError):
            event.outcome = 0
        with self.assertRaises(ValueError):
            JOINT_SUPPORT[0, 0] = 1

    def test_unknown_never_becomes_failure_or_zero_cost(self):
        for status in ("receipt_missing", "awaiting", "cancel_requested"):
            mask = allowed_mask(
                Evidence(observation_status=status, confirmed_cost_lower_bound=2)
            )
            self.assertEqual(mask.sum(), 24)
            self.assertEqual(set(JOINT_SUPPORT[mask, 0]), {0, 1})
            self.assertEqual(set(JOINT_SUPPORT[mask, 1]), set(TIMES))
            self.assertTrue((JOINT_SUPPORT[mask, 2] >= 2).all())
            for extra in (
                {"outcome": 0},
                {"final_cost": 2},
                {
                    "time_kind": "right_censored",
                    "time_lower": 2,
                    "nonoccurrence_witness": "purported",
                },
            ):
                with (
                    self.subTest(status=status, extra=extra),
                    self.assertRaises(ValueError),
                ):
                    Evidence(observation_status=status, **extra)

    def test_right_censor_and_interval_have_correct_boundaries(self):
        mask = allowed_mask(self.ongoing())
        self.assertEqual(mask.sum(), 16)
        self.assertEqual(set(JOINT_SUPPORT[mask, 1]), {4, 8})
        interval = self.terminal(time_kind="interval", time_lower=1, time_upper=4)
        self.assertEqual(set(JOINT_SUPPORT[allowed_mask(interval), 1]), {2, 4})
        with self.assertRaises(ValueError):
            self.ongoing(nonoccurrence_witness=None)
        with self.assertRaises(ValueError):
            self.ongoing(time_upper=8)
        with self.assertRaises(ValueError):
            self.terminal(time_kind="interval", time_lower=4, time_upper=4)
        with self.assertRaises(ValueError):
            self.terminal(time_kind="right_censored")

    def test_terminal_and_imagination_provenance(self):
        with self.assertRaises(ValueError):
            self.terminal(receipt_ref=None)
        with self.assertRaises(ValueError):
            self.terminal(outcome=None)
        with self.assertRaises(ValueError):
            allowed_mask(self.terminal(source="imagined"))
        untimed = self.terminal(
            time_kind="unobserved", time_lower=None, final_cost=None
        )
        self.assertEqual(allowed_mask(untimed).sum(), 16)

    def test_numeric_validation_and_finite_support_failure(self):
        for value in (math.nan, math.inf, -math.inf, -1, True):
            for field in (
                "observed_at",
                "confirmed_cost_lower_bound",
                "time_lower",
                "final_cost",
            ):
                with (
                    self.subTest(field=field, value=value),
                    self.assertRaises(ValueError),
                ):
                    self.terminal(**{field: value})
        for bad in (
            {"outcome": 2},
            {"outcome": True},
            {"receipt_ref": " "},
            {"confirmed_cost_lower_bound": 8},
            {"time_upper": 4},
            {"confirmed_cost_lower_bound": None},
            {"observed_at": None},
        ):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                self.terminal(**bad)
        for event in (
            self.terminal(time_lower=3),
            self.ongoing(time_lower=8),
            Evidence(confirmed_cost_lower_bound=9),
        ):
            with self.assertRaises(ValueError):
                allowed_mask(event)

    def test_likelihood_uses_event_mass_and_keeps_zero_mass_infinite(self):
        p = np.full(32, 1 / 32)
        self.assertAlmostEqual(
            coarsened_nll(p, allowed_mask(self.terminal())), math.log(32)
        )
        self.assertAlmostEqual(
            coarsened_nll(p, allowed_mask(self.ongoing())), math.log(2)
        )
        self.assertEqual(coarsened_nll(p, allowed_mask(Evidence())), 0)
        # Coarsening a target to a larger compatible event cannot increase NLL.
        untimed = self.terminal(time_kind="unobserved", time_lower=None)
        self.assertLess(
            coarsened_nll(p, allowed_mask(untimed)),
            coarsened_nll(p, allowed_mask(self.terminal())),
        )
        self.assertEqual(coarsened_nll([1, 0], [False, True]), math.inf)
        for probs, mask in (
            ([0.2, 0.2], [True, False]),
            ([math.nan, 1], [True, False]),
            ([-0.1, 1.1], [True, False]),
            ([0.5, 0.5], [False, False]),
            ([0.5, 0.5], [1, 0]),
            ([0.5, 0.5], [True]),
        ):
            with self.subTest(probs=probs, mask=mask), self.assertRaises(ValueError):
                coarsened_nll(probs, mask)

    def test_exact_scores_against_analytic_distributions(self):
        self.assertAlmostEqual(brier_score(0.25, 1), 0.5625)
        self.assertEqual(crps_score([1, 3], [0.5, 0.5], 2), 0.5)
        self.assertEqual(crps_score([3], [1], 1), 2)
        p = allowed_mask(self.terminal()).astype(float)
        self.assertEqual(
            score_exact(p, 1, 2, 4),
            dict(outcome_brier=0, time_crps=0, cost_crps=0, joint_nll=0),
        )
        for call in (
            lambda: brier_score(1.1, 0),
            lambda: crps_score([math.inf], [1], 2),
            lambda: crps_score([1], [1], math.nan),
            lambda: score_exact(p, 1, 3, 4),
        ):
            with self.assertRaises(ValueError):
                call()

    def test_history_rejects_future_backfill_and_copies_payload(self):
        payload = {"status": ["pending"]}
        early = FrozenObservation(1, payload, "receipt/1")
        late = FrozenObservation(5, {"effect_time": 2, "outcome": 1}, "receipt/5")
        payload["status"].append("mutated")
        early.payload["status"].append("also-mutated")
        self.assertEqual(early.payload, {"status": ["pending"]})
        self.assertEqual(history_at([early, late], 2), (early,))
        self.assertEqual(history_at([early, late], 5), (early, late))
        self.assertEqual(history_hash([early], 2), history_hash([early, late], 2))
        self.assertNotEqual(history_hash([early], 2), history_hash([early], 3))
        self.assertNotEqual(history_hash([early], 5), history_hash([early, late], 5))
        for call in (
            lambda: FrozenObservation(1, {"x": math.nan}, "receipt"),
            lambda: FrozenObservation(1, {"nested": {1: "ambiguous key"}}, "receipt"),
            lambda: FrozenObservation(1, {}, ""),
            lambda: history_at([early], math.inf),
        ):
            with self.assertRaises(ValueError):
                call()


if __name__ == "__main__":
    unittest.main()
