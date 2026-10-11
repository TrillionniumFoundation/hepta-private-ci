"""Finite probability and training-only selection tests, not efficacy evidence."""
import copy
from itertools import product
import json
import unittest
from four_gate_common import digest
from fbsde_acquisition_support import regularized_counts, select_counts, CANDIDATES
from fbsde_acquisition_kernel_audit import verified_counts


class SupportTests(unittest.TestCase):
    def sample(self):
        rows = list(product(range(2), repeat=4))*3
        hashes = [digest(f'source-{i}') for i in range(len(rows))]
        return rows, hashes

    def test_legacy_counts_unchanged(self):
        rows = [(0, 0, 1, 1), (0, 0, 1, 1)]
        values = regularized_counts(rows, 2, 'legacy')
        self.assertEqual(values[3], 2.01)
        self.assertAlmostEqual(sum(values), 2+.16)

    def test_anchor_is_positive_and_preserves_real_counts(self):
        rows, _ = self.sample()
        for candidate in CANDIDATES[1:]:
            values = regularized_counts(rows, 2, candidate)
            self.assertTrue(all(v > 3 for v in values))
            self.assertAlmostEqual(sum(values), len(rows)+int(candidate.split(':')[1]))

    def test_full_view_anchor_preserves_conditional_label_when_views_exchangeable(self):
        rows = [(y, a, b, y) for y, a, b in product(range(2), repeat=3)]*10
        values = regularized_counts(rows, 2, 'anchor:128')
        self.assertAlmostEqual(values[0], values[2])
        self.assertGreater(values[0], values[8])

    def test_complete_cv_and_independent_reconstruction(self):
        rows, hashes = self.sample()
        values, report = select_counts(rows, hashes, 2)
        reconstructed = verified_counts(rows, hashes, 2, json.loads(json.dumps(report)))
        self.assertTrue(all(abs(a-b) < 1e-12 for a, b in zip(values, reconstructed)))
        self.assertEqual(len(report['scores']), 5)
        self.assertFalse(report['test_labels_used'])
        self.assertFalse(report['prior_mass_is_observation_count'])

    def test_reordering_rows_keeps_selected_distribution(self):
        rows, hashes = self.sample()
        a, x = select_counts(rows, hashes, 2)
        b, y = select_counts(rows[::-1], hashes[::-1], 2)
        self.assertEqual(a, b)
        self.assertEqual(x['selected'], y['selected'])

    def test_same_source_cannot_enter_two_folds(self):
        rows, hashes = self.sample(); hashes[1] = hashes[0]
        with self.assertRaisesRegex(ValueError, 'unique'): select_counts(rows, hashes, 2)

    def test_changed_winner_or_cv_score_is_rejected(self):
        rows, hashes = self.sample(); _, record = select_counts(rows, hashes, 2)
        for mode in ('winner', 'score', 'source'):
            mutated = json.loads(json.dumps(record))
            if mode == 'winner': mutated['selected'] = 'not-registered'
            if mode == 'score': mutated['scores'][0]['mean_conditional_log_loss'] += 1
            if mode == 'source': mutated['source_folds'][0][0] = digest('other')
            with self.assertRaises(ValueError): verified_counts(rows, hashes, 2, mutated)

    def test_unknown_model_or_noninteger_symbols_fail(self):
        with self.assertRaises(ValueError): regularized_counts([(0, 0, 0, 0)], 2, 'unknown')
        with self.assertRaises(ValueError): regularized_counts([(0, True, 0, 0)], 2, 'legacy')


if __name__ == '__main__': unittest.main()
