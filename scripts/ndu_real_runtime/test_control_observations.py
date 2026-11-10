"""Manufactured label-contract tests; no real-observation fit or gain claim."""

from copy import deepcopy
import unittest

from .control_observations import continuation_label, implementation_label
from .control_test_fixtures import row


class ControlObservationTests(unittest.TestCase):
    def test_complete_identity_success_observed_mismatch_and_unknown(self):
        sample = row("s")["implementation"]
        self.assertEqual(implementation_label(sample), 1.0)
        sample["observed_candidate_id"] = "other-candidate"
        self.assertEqual(implementation_label(sample), 0.0)
        sample["delivered_payload_sha256"] = None
        self.assertIsNone(implementation_label(sample))
        for key, value in (
            ("completed", False),
            ("independent_observation", False),
            ("observer_id", "actor"),
            ("provenance", "fixture"),
        ):
            altered = deepcopy(row("s")["implementation"])
            altered[key] = value
            self.assertIsNone(implementation_label(altered))

    def test_marginal_full_cost_is_charged_once(self):
        sample = row("s", gain=1.25)
        self.assertAlmostEqual(continuation_label(sample), 1.25)
        sample["branches"]["continue"]["costs_in_utility"]["delivery"] = 0.75
        self.assertAlmostEqual(continuation_label(sample), 0.5)
        # Identical sunk/common cost in both branch totals cancels.
        for branch in sample["branches"].values():
            branch["costs_in_utility"]["residency"] = 4.0
        self.assertAlmostEqual(continuation_label(sample), 0.5)

    def test_unmeasured_cost_or_missing_outcome_remains_unknown(self):
        for mutation in (
            lambda b: b["costs_in_utility"].pop("residency"),
            lambda b: b["costs_in_utility"].update(control=None),
            lambda b: b["costs_in_utility"].update(control=-1),
            lambda b: b.update(completed=False),
            lambda b: b.update(all_costs_measured=False),
            lambda b: b.update(gross_utility=float("nan")),
        ):
            sample = row("s")
            mutation(sample["branches"]["continue"])
            self.assertIsNone(continuation_label(sample))

    def test_pair_identity_and_single_continuation_are_required(self):
        for key, value in (
            ("source_id", "different"),
            ("pre_state_sha256", "0" * 64),
            ("branch_snapshot_sha256", "0" * 64),
            ("continuation_count", 2),
            ("operation_id", "s/stop"),
            ("evaluator_sha256", "0" * 64),
            ("tariff_sha256", "0" * 64),
        ):
            sample = row("s")
            sample["branches"]["continue"][key] = value
            with self.assertRaises(ValueError):
                continuation_label(sample)


if __name__ == "__main__":
    unittest.main()
