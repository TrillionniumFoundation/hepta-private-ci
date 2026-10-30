"""Seeded broad-but-bounded finite-grid adversarial check; not all-domain proof."""
import random
import unittest

from .regenerative_grid import Grid, solve_policy
from .stopping import Stop, regenerative_boundary, regenerative_value


class RegenerativeGridStress(unittest.TestCase):
    def test_400_bounded_drift_diffusion_discount_reset_sweeps(self):
        rng = random.Random(20261030)
        biggest_value_error = 0.
        biggest_boundary_error = 0.
        biggest_residual = 0.
        for sample in range(400):
            p = Stop(drift=rng.uniform(-.25,.25),
                     diffusion=rng.uniform(.15,.9),
                     discount=rng.uniform(.05,.5),
                     cost=rng.uniform(.6,1.6),
                     reset=rng.uniform(-.45,.3),
                     refractory=rng.uniform(0,3))
            boundary = regenerative_boundary(p)
            # Check this sampled domain is interior to our fixed upper wall.
            self.assertLess(boundary,7.,(sample,p))
            grid = solve_policy(p, Grid(-12.,8.,257))
            biggest_value_error = max(biggest_value_error,
                abs(grid.at(p.reset)-regenerative_value(p,p.reset)))
            biggest_boundary_error = max(biggest_boundary_error,
                abs(grid.boundary_high-boundary))
            biggest_residual = max(biggest_residual, grid.residual)
        self.assertLess(biggest_value_error,.001)
        self.assertLess(biggest_boundary_error,.07)
        self.assertLess(biggest_residual,1e-10)


if __name__ == '__main__':
    unittest.main()
