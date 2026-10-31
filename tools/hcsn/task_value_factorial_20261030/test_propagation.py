"""Behavioral checks for event timing, conservation and derivative boundaries."""

from dataclasses import replace
import unittest

import numpy as np

from .propagation import Cell, NondifferentiablePoint, first_passage, flow, generator, remap, rollout
from .propagation_audit import protocol, uniformized


class PropagationTests(unittest.TestCase):
    def test_generator_and_direction_conserve_mass(self):
        cells = (Cell(reset=-.13, active=4), Cell(reset=-.17, active=4))
        q, rates, dq, _ = generator(cells, .13, ({"sigma": 1.}, {"drift": .4}))
        np.testing.assert_allclose(q.sum(1), 0, atol=4e-15)
        np.testing.assert_allclose(dq.sum(1), 0, atol=4e-15)
        self.assertGreaterEqual(float(np.min(q-np.diag(np.diag(q)))), 0)
        self.assertGreater(float(rates.sum()), 0)

    def test_same_physical_time_partition_preserves_count_and_state(self):
        cells = (Cell(),)
        a, ea, _, _ = flow(cells, .21)
        b, eb, _, _ = flow(cells, .35)
        whole, ew, _, _ = flow(cells, .56)
        np.testing.assert_allclose(a@b, whole, atol=2e-15)
        np.testing.assert_allclose(ea+a@eb, ew, atol=2e-15)

    def test_zero_duration_and_repeated_events(self):
        cells = (Cell(drift=2., sigma=.2, refractory=.05),)
        t, e, _, _ = flow(cells, 0)
        np.testing.assert_array_equal(t, np.eye(7))
        np.testing.assert_array_equal(e, np.zeros((7, 1)))
        _, long_events, _, _ = flow(cells, 10.)
        self.assertGreater(float(long_events[0, 0]), 1.)

    def test_lowered_boundary_fires_atom_and_keeps_refractory_phase(self):
        old = (Cell(active=4, reset=-.13),)
        new = (replace(old[0], boundary=.5),)
        matrix, atoms, _ = remap(old, new)
        self.assertEqual(atoms[3, 0], 1.)
        self.assertEqual(matrix[3, 5], 1.)
        np.testing.assert_array_equal(matrix[4:, 4:], np.eye(2))
        np.testing.assert_allclose(matrix.sum(1), 1., atol=2e-15)

    def test_boundary_atom_and_reset_knot_reject_false_smooth_derivative(self):
        c = Cell(active=4, reset=-.13)
        with self.assertRaises(NondifferentiablePoint):
            remap((c,), (replace(c, boundary=.75),), ({},), ({"boundary": 1.},))
        with self.assertRaises(NondifferentiablePoint):
            generator((replace(c, reset=-.25),), directions=({"reset": 1.},))

    def test_independent_cells_factorize_and_coupling_changes_law(self):
        cells = (Cell(active=3, reset=-.1), Cell(active=3, reset=-.15, refractory=.4))
        one, _, _, _ = flow((cells[0],), .4)
        two, _, _, _ = flow((cells[1],), .4)
        independent, _, _, _ = flow(cells, .4)
        coupled, _, _, _ = flow(cells, .4, coupling=.2)
        np.testing.assert_allclose(independent, np.kron(one, two), atol=2e-15)
        self.assertGreater(float(np.max(abs(coupled-independent))), 1e-4)

    def test_other_cell_continues_during_refractory(self):
        cells = (Cell(active=3, reset=-.1, refractory=10.),
                 Cell(active=3, reset=-.15, drift=2.))
        _, events, _, _ = flow(cells, .2)
        state = np.ravel_multi_index((4, 2), (5, 5))
        self.assertGreater(events[state, 1], .1)
        self.assertLess(events[state, 0], events[state, 1])

    def test_poisson_reference_for_small_noise_and_short_time(self):
        cells = (Cell(sigma=1e-8, drift=.3),)
        q, r, _, _ = generator(cells)
        t, e, _, _ = flow(cells, 1e-8)
        u, ue = uniformized(q, r, 1e-8)
        np.testing.assert_allclose(t, u, atol=2e-15)
        np.testing.assert_allclose(e, ue, atol=2e-15)

    def test_checkpoint_continuation_uses_same_forward_state(self):
        p, cells, schedule = protocol()
        full = rollout(p, cells, schedule)
        prefix = rollout(p, cells, schedule[:2])
        suffix = rollout(prefix["probability"], schedule[1]["cells"], schedule[2:])
        np.testing.assert_allclose(full["probability"], suffix["probability"], atol=2e-15)
        np.testing.assert_allclose(full["counts"], prefix["counts"]+suffix["counts"], atol=2e-15)

    def test_fpt_distinguishes_endpoint_and_handles_initial_atom(self):
        np.testing.assert_allclose(first_passage([0., 1., 1.], 0., 1., [0., 0., 1.]),
                                   [1., 0., .3173105078629141], atol=2e-15)
        self.assertGreater(float(first_passage(1., 0., 1., 1.)), .15865525393145707)
        with self.assertRaises(ValueError):
            first_passage(1., 0., 0., 1.)

    def test_invalid_stream_mass_and_topology_are_rejected(self):
        c = Cell()
        with self.assertRaises(ValueError):
            rollout(np.ones(7), (c,), [])
        with self.assertRaises(ValueError):
            remap((c,), (replace(c, phases=3),))


if __name__ == "__main__":
    unittest.main()
