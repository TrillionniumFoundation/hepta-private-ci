"""Synthetic-only checks for the independent final statistical reviewer."""

from copy import deepcopy
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from ..statistics import paired_interval
from . import summary
from .audit_statistics import bootstrap, calibration, compare_tree, coverage_interval, reconstruct
from .audit_transport import Checks
from .registration import REGISTRATION
from .test_summary import synthetic_scopes


class IndependentStatistics(unittest.TestCase):
    def test_bootstrap_multiplicity_reference_crosses_draw_batches(self):
        matrix = np.random.default_rng(119).normal(size=(3, 7))
        for alpha in (.025, .05):
            expected = paired_interval(matrix, 431, 6623, alpha)
            actual = bootstrap(matrix, 431, 6623, alpha)
            compare_tree(actual, expected, Checks(), 'synthetic bootstrap')

    def test_erfc_bisection_gaussian_interval_and_first_stage_only(self):
        low, high = coverage_interval((1.0,), (.3,), (.49,))
        np.testing.assert_allclose([low, high], [.3 - .7 * 1.959963984540054,
                                                .3 + .7 * 1.959963984540054], atol=3e-15, rtol=0)
        rows = deepcopy(next(iter(synthetic_scopes().values()))['event'])
        actual = calibration(rows, REGISTRATION)
        compare_tree(actual, summary.first_stage_metrics(rows), Checks(), 'synthetic calibration')
        rows[0]['stages'].append({'private_selected_second_stage_not_used': True})
        self.assertEqual(actual, calibration(rows, REGISTRATION))

    def test_full_statistical_reconstruction_detects_failed_seed_gate(self):
        scopes = synthetic_scopes([-.002, .02, .02, .02, .02])
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(summary, 'verify'), patch.object(summary, 'load_scopes', return_value=(scopes, {})):
                actual = summary.summarize(directory, 'a' * 64)
        expected = reconstruct(scopes, REGISTRATION)
        for key, value in expected.items():
            compare_tree(actual[key], value, Checks(), 'synthetic full summary/' + key)
        item = expected['primary']['analytic-numeric']
        self.assertGreater(item['mean_difference'], .005)
        self.assertFalse(item['passes_registered_superiority'])
        self.assertFalse(expected['joint_research_gate_pass'])


if __name__ == '__main__':
    unittest.main()
