"""Seeded P0 numerical diagnostic, not continuum QVI certification."""
import math
import random
import unittest

from .stopping import Stop, qvi, regenerative_boundary


class QVIStressTests(unittest.TestCase):
    def test_seeded_finite_parameter_panel_keeps_only_valid_signs(self):
        rng = random.Random(2026103013)
        counts = dict(continue_accepted=0, fire_accepted=0,
                      boundary_refused=0, qvi_refused=0)
        for _ in range(5000):
            cost = rng.uniform(-3, 3)
            gap = 10 ** rng.uniform(-13, 2)
            p = Stop(rng.uniform(-2, 2), 10 ** rng.uniform(-40, 150),
                     10 ** rng.uniform(-4, 1), cost, cost-gap,
                     rng.uniform(0, 4))
            try:
                b = regenerative_boundary(p)
            except (ArithmeticError, ValueError, OverflowError):
                counts['boundary_refused'] += 1
                continue
            for fire in (False, True):
                delta = max(1e-10, abs(b)*rng.uniform(.01, 2))
                x = b+delta if fire else b-delta
                try:
                    got = qvi(p, x)
                except (ArithmeticError, ValueError, OverflowError):
                    counts['qvi_refused'] += 1
                    continue
                counts['fire_accepted' if fire else 'continue_accepted'] += 1
                self.assertEqual(got['fire'], fire)
                self.assertTrue(all(math.isfinite(got[name]) for name in
                                    ('value', 'obstacle', 'generator', 'complementarity')))
                self.assertLessEqual(got['obstacle'], 0)
                self.assertLessEqual(got['generator'], 0)
                self.assertEqual(got['complementarity'], 0)
        # Assert adequate exercise; refusals are exclusions, never successes.
        self.assertGreater(counts['continue_accepted'], 4000)
        self.assertGreater(counts['fire_accepted'], 4000)
        self.assertGreater(counts['boundary_refused']+counts['qvi_refused'], 0)


if __name__ == '__main__':
    unittest.main()
