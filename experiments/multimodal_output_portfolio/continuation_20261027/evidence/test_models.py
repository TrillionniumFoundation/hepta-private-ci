"""Behavioral checks for source dependence, unidentified support and target-free delivery."""

from pathlib import Path
import tempfile
import unittest

import numpy as np

from ...repair_20261026.evidence.joint import arrived_receipts
from .models import fit_law, measured_pairs, posterior
from .run import deliver


def source_rows(digits=range(10)):
    return [{"speaker": str(speaker), "target": digit, "index": index,
             "observation": (digit + speaker) % 10, "event_id": f"{speaker}/{digit}/{index}"}
            for speaker in range(2) for digit in digits for index in range(20)]


class SourcePoolingTests(unittest.TestCase):
    def test_shared_source_dependence_changes_the_measured_joint_prediction(self):
        observed = source_rows()
        mixture = fit_law(observed, "speaker_mixture", .5)
        independent = fit_law(observed, "independent", .5)
        # Errors shift both digit labels together within a physical source.
        supported = 10 + 10 * 0 + 1
        cross_source = 10 + 10 * 0 + 2
        self.assertGreater(mixture.likelihood[supported, 1], independent.likelihood[supported, 1])
        self.assertLess(mixture.likelihood[cross_source, 1], independent.likelihood[cross_source, 1])

    def test_missing_measured_targets_remain_unknown_and_block_positive_prior(self):
        for family in ("independent", "paired", "speaker_mixture"):
            law = fit_law(source_rows(range(1)), family, .5)
            self.assertEqual(np.flatnonzero(law.known_targets).tolist(), [0])
            with self.assertRaisesRegex(ValueError, "Unidentified"):
                posterior(law, ("a", "a"), (0, 0), np.full(100, .01))

    def test_coupling_comparison_shares_marginals_and_duplicate_fit_events_are_idempotent(self):
        observed = source_rows()
        reference = fit_law(observed, "independent", 10)
        for family in ("paired", "speaker_mixture"):
            law = fit_law(observed, family, 2, marginal_strength=10)
            repeated = fit_law(observed + observed, family, 2, marginal_strength=10)
            np.testing.assert_array_equal(law.likelihood, repeated.likelihood)
            for target in range(100):
                left, right = divmod(target, 10)
                if left != right:
                    table = law.likelihood[10:, target].reshape(10, 10)
                    expected = reference.likelihood[10:, target].reshape(10, 10)
                    np.testing.assert_allclose(table.sum(0), expected.sum(0), rtol=0, atol=2e-12)
                    np.testing.assert_allclose(table.sum(1), expected.sum(1), rtol=0, atol=2e-12)

    def test_direct_full_arrival_matches_receipt_filter_and_duplicate_receipt(self):
        law = fit_law(source_rows(), "speaker_mixture", 2)
        for row in measured_pairs(source_rows())[::220]:
            probability, _ = posterior(law, row["event_ids"], row["values"], np.full(100, .01))
            filtering = law.start_filter(np.full(100, .01))
            receipts = arrived_receipts(tuple(row["event_ids"]), tuple(row["values"]))
            once = filtering.update(receipts)
            repeated = filtering.update([*receipts, *receipts])
            np.testing.assert_allclose(np.array([once[index] for index in range(100)]), probability,
                                       rtol=0, atol=1e-14)
            self.assertEqual(once, repeated)

    def test_reserved_source_and_private_target_cannot_enter_fitting_or_delivery(self):
        with self.assertRaisesRegex(ValueError, "Reserved"):
            fit_law(source_rows(), "paired", .5, excluded_speakers=("1",))
        law = fit_law(source_rows(), "paired", .5)
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "target-free"):
                deliver(Path(directory) / "output.jsonl", law, [measured_pairs(source_rows())[0]])
        with self.assertRaisesRegex(ValueError, "contradictory"):
            posterior(law, ("same", "same"), (0, 1), np.full(100, .01))


if __name__ == "__main__":
    unittest.main()
