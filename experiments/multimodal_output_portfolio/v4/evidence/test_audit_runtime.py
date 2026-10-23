"""Independent acceptance semantics: real sibling modality changes, not STOP."""

import unittest

import numpy as np

from audit_runtime import array, sequence_value, sibling_evidence


class RuntimeAuditTests(unittest.TestCase):
    def test_sibling_gate_requires_same_parent_and_two_different_refinements(self):
        key = (2, 'observed-initial-state', 1, 338944)
        groups = {key: {0: {2: [0, 3]}, 1: {0: [1]}, 2: {4: [2, 4, 5]}}}
        result = sibling_evidence(groups, [.25, .5, .25])
        self.assertTrue(result['strong_modality_reallocation_passed'])
        self.assertEqual(len(result['strong_pairs']), 1)
        self.assertEqual(len(result['stop_versus_refine_pairs']), 2)
        self.assertEqual([b['observed_count'] for b in result['strong_pairs'][0]['branches']], [2, 3])
        separate = {key: {0: {2: [0]}}, (2, 'different-initial-state', 1, 338944): {2: {4: [1]}}}
        self.assertFalse(sibling_evidence(separate, [.25, .5, .25])['strong_modality_reallocation_passed'])
        stop_only = {key: {0: {0: [0]}, 2: {4: [1]}}}
        self.assertFalse(sibling_evidence(stop_only, [.25, .5, .25])['strong_modality_reallocation_passed'])

    def test_impossible_or_nondeterministic_sibling_cannot_count(self):
        key = (1, 'state', 2, 338944)
        with self.assertRaises(AssertionError):
            sibling_evidence({key: {0: {2: [0]}, 2: {4: [1]}}}, [0., .5, .5])
        with self.assertRaises(AssertionError):
            sibling_evidence({key: {0: {2: [0], 4: [1]}}}, [.25, .5, .25])

    def test_committed_remaining_value_prices_each_future_action_once(self):
        losses = [np.full(n, .2) for n in (32, 384, 4608)]
        protocol = {'disturbance_design': {'branch_probabilities': [.25, .5, .25]},
                    'objective': {'gamma': 2., 'mac_price_lambda': .015 / 8704}}
        emit_value = -.2 - .015 / 8704 * 330240
        self.assertAlmostEqual(sequence_value(losses, 0, 0, (1, 1), protocol), emit_value - .03)
        self.assertAlmostEqual(sequence_value(losses, 1, 4, (1,), protocol), emit_value - .015)
        self.assertAlmostEqual(sequence_value(losses, 2, 49, (), protocol), emit_value)

    def test_saved_integer_controls_and_finite_arrays_required(self):
        with self.assertRaises(AssertionError):
            array({'world_id': np.array([0.])}, 'world_id', (1,), np.int64)
        with self.assertRaises(AssertionError):
            array({'latents': np.array([np.nan], np.float32)}, 'latents', (1,), np.float32)


if __name__ == '__main__':
    unittest.main()
