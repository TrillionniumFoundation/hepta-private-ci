import unittest
from pathlib import Path
import tempfile

import numpy as np

from qualification.hcsn_boundary_audit.audit_representation import (
    capture_audit_sources, content_rank, error_record, operator_rank, record_errors,
    transition_defects, verify_audit_sources,
)


class RepresentationTests(unittest.TestCase):
    def test_content_compression_preserves_exact_rank_and_exposes_lost_observable(self):
        content = np.array([[[1., 0.], [0., .5], [0., 0.]]])
        np.testing.assert_allclose(content_rank(content, 2), content, atol=1e-15)
        reduced = content_rank(content, 1)
        np.testing.assert_allclose(reduced.sum(1), [[1., 0.]], atol=1e-15)
        self.assertGreater(np.linalg.norm(reduced.sum(1) - content.sum(1)), .49)

    def test_operator_compression_does_not_silently_repair_mass(self):
        stochastic = np.array([[.9, .1], [.4, .6]])
        reduced = operator_rank(stochastic, 1)
        self.assertGreater(np.max(np.abs(reduced.sum(1) - 1)), .05)
        np.testing.assert_allclose(operator_rank(stochastic, 2), stochastic, atol=1e-15)

    def test_worst_case_retains_signed_raw_values_and_identity(self):
        record = error_record()
        record_errors(record, np.array([.2, .9]), np.array([.1, .4]), {"seed": 7})
        self.assertEqual(record["worst_case"], dict(seed=7, flattened_index=1, reference=.9, approximation=.4))
        self.assertEqual(record["count"], 2)
        self.assertAlmostEqual(record["maximum_absolute"], .5)
        self.assertAlmostEqual(record["signed_sum"], -.6)

    def test_phase_destination_check_alone_misses_release_distribution_change(self):
        reference = np.array([[.9, 0., .1], [0., .8, .2], [.2, .3, .5]])
        changed = reference.copy()
        changed[2, :2] = [.4, .1]
        defects = transition_defects(reference, changed, 2)
        self.assertEqual(defects["maximum_phase_destination_row_l1_error"], 0.)
        self.assertEqual(defects["maximum_row_mass_defect"], 0.)
        self.assertGreater(defects["maximum_phase_source_row_l1_error"], .39)

    def test_audit_and_helper_source_changes_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = [Path(directory) / name for name in ('audit.py', 'helper.py')]
            for path in paths:
                path.write_text('original source\n')
            for changed in paths:
                before = capture_audit_sources(paths)
                self.assertEqual(verify_audit_sources(before), before)
                changed.write_text('changed source\n')
                with self.assertRaisesRegex(ValueError, 'source changed'):
                    verify_audit_sources(before)
                changed.write_text('original source\n')


if __name__ == "__main__":
    unittest.main()
