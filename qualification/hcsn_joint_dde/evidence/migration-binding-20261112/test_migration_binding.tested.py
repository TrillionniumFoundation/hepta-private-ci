"""Reject conservative but incorrectly bound maps before changing a source law."""

import unittest
import numpy as np

from .graded import GradedSpatialGenerator
from .graded_migration import migrate, migration_weights
from .model import JointModel


class TestMigrationBinding(unittest.TestCase):
    def setUp(self):
        self.model = JointModel(GradedSpatialGenerator(64, 8., -.12, .35), .62, .2, .15)
        self.probability = np.zeros(25)
        self.probability[0] = 1.
        self.content = np.c_[2*self.probability, -3*self.probability]

    def test_rejects_conservative_replacement_law(self):
        weights, _ = migration_weights(self.model.spatial.nodes)
        altered = weights.copy()
        altered[0] = 0.
        altered[0, -1] = 1.
        with self.assertRaisesRegex(ValueError, "bound"):
            migrate(self.model, self.probability, self.content, altered)

    def test_rejects_same_shape_map_from_another_target_mesh(self):
        other = GradedSpatialGenerator(64, 8., -.12, .35, 0.)
        weights, _ = migration_weights(other.nodes)
        with self.assertRaisesRegex(ValueError, "bound"):
            migrate(self.model, self.probability, self.content, weights)

    def test_rejects_undeclared_source_endpoint_and_tail_law(self):
        for arguments in ({'endpoint':3.2}, {'tail_rate':2.}):
            weights, _ = migration_weights(self.model.spatial.nodes, **arguments)
            with self.assertRaisesRegex(ValueError, "bound"):
                migrate(self.model, self.probability, self.content, weights)

    def test_accepts_unchanged_declared_mapping_with_original_outputs(self):
        weights, _ = migration_weights(self.model.spatial.nodes)
        active, marked, phase, report = migrate(self.model, self.probability, self.content, weights)
        np.testing.assert_array_equal(active, weights[0])
        np.testing.assert_array_equal(marked, np.c_[2*weights[0], -3*weights[0]])
        self.assertEqual(phase, ())
        self.assertLess(abs(report['mass_residual']), 1e-15)

    def test_explicit_nondefault_source_law_is_bound_in_receipt(self):
        weights, _ = migration_weights(self.model.spatial.nodes, endpoint=3.2, tail_rate=2.)
        active, _, _, report = migrate(self.model, self.probability, self.content, weights,
                                      source_endpoint=3.2, source_tail_rate=2.)
        np.testing.assert_array_equal(active, weights[0])
        self.assertEqual(report['binding']['source_endpoint'], 3.2)
        self.assertEqual(report['binding']['source_tail_rate'], 2.)
        self.assertEqual(report['binding']['source_active_cells'], 16)


if __name__ == '__main__':
    unittest.main(verbosity=2)
