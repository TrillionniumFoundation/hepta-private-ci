"""New exact-renewal examples, independent age-grid convergence and delay limits."""

import json
import math
import unittest

from qualification.hcsn_adaptive.fixed_delay_reference import FixedDelayReference


class FixedDelayReferenceTests(unittest.TestCase):
    def test_no_second_event_before_delay_and_erlang_is_a_different_law(self):
        model = FixedDelayReference(2., 500_000).advance(250_000)
        result = model.summary()
        first = 1 - math.exp(-.5)
        self.assertAlmostEqual(result["expected_events"], first, places=14)
        self.assertAlmostEqual(result["first_event_probability"], first, places=14)
        self.assertAlmostEqual(result["refractory_mass"], first, places=14)
        # Same mean delay, one exponential waiting phase: repeated events can
        # occur before d. This closed two-state CTMC result is independent.
        erlang_count = .25 + .25 * (1 - math.exp(-1))
        self.assertGreater(erlang_count - result["expected_events"], .01)
        discount = .7
        exact = model.discounted_events(discount, "infinite")
        errors = []
        first_laplace = 2 / (2 + discount)
        for phases in (1, 8, 64):
            wait = (1 + discount * .5 / phases) ** -phases
            errors.append(first_laplace / (1 - wait * first_laplace) - exact)
        self.assertTrue(errors[0] > errors[1] > errors[2] > 0)

    def test_full_age_state_cold_restore_and_reward_continuation(self):
        original = FixedDelayReference(2., 500_000, cohorts=((.6, 0), (.4, 300_000)))
        early = original.advance(100_000)
        self.assertEqual(early.summary()["waiting_atoms_mass_age_micros"], ((.4, 300_000),))
        restored = FixedDelayReference.from_record(json.loads(json.dumps(early.to_record())))
        current = restored.advance(1_600_000)
        whole = original.advance(1_700_000)
        self.assertEqual(current.to_record(), whole.to_record())
        self.assertEqual(current.summary(), whole.summary())
        self.assertAlmostEqual(current.summary()["event_rate"], 2 * current.summary()["active_mass"], places=12)
        # Current age-law continuation must close the discounted reward identity.
        rho, reward, cost = .7, .4, .1
        paid = (reward / 2 - cost) * current.discounted_events(rho)
        expected = original.value(rho, reward, cost)
        actual = paid + math.exp(-rho * 1.7) * current.value(rho, reward, cost)
        self.assertAlmostEqual(actual, expected, places=12)
        # Independent midpoint integration of the full continuous age density.
        grid = 4096
        mass = math.fsum(current.age_density((j + .5) * .5 / grid) * .5 / grid for j in range(grid))
        self.assertAlmostEqual(mass, current.summary()["refractory_mass"], places=7)

    def test_independent_conservative_age_grid_has_first_order_refinement(self):
        rate, delay, horizon = 2., .5, 1.5
        target = FixedDelayReference(rate, 500_000).advance(1_500_000).summary()
        errors = []
        for cells in (16, 32, 64, 128):
            dt = delay / cells
            active, queue, events = 1., [0.] * cells, 0.
            for _ in range(3 * cells):
                hit = active * -math.expm1(-rate * dt)
                # Cohorts born inside an interval are placed at its right edge;
                # releases occur at an edge. The waiting-time error is <= dt
                # per event, giving first-order finite-horizon consistency.
                active = active - hit + queue[-1]
                queue = [hit] + queue[:-1]
                events += hit
                self.assertAlmostEqual(active + math.fsum(queue), 1., places=13)
            errors.append(abs(events - target["expected_events"]))
        self.assertTrue(all(errors[i] > errors[i + 1] for i in range(3)))
        self.assertTrue(all(1.8 < errors[i] / errors[i + 1] < 2.2 for i in range(3)))
        self.assertLess(abs(active - target["active_mass"]), .003)


if __name__ == "__main__":
    unittest.main()
