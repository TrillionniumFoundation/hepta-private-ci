"""Source-exact REPLAY REQUIRED: compare theorem with existing scalar runtime.

Run in the real repository checkout, where stopping.py is present. Unlike the
isolated proof tests, this integration file is not executable from a subset
containing only the newly authored files.
"""

import math
import unittest

from .global_scalar_qvi_gate import ScalarCase, audit_scalar_global_qvi
from .stopping import Stop, regenerative_boundary, regenerative_value, qvi


class GlobalScalarSourceIntegrationTests(unittest.TestCase):
    def test_existing_threshold_and_values_match_decimal_theorem(self):
        cases = (
            ScalarCase(0, 1, .5, 0, -1, 0),
            ScalarCase(.5, .7, .3, 1, .2, .25),
            ScalarCase(-.8, 1, .2, 1, 0, .1),
            ScalarCase(0, 1, .5, 0, -1e-20, 0),
        )
        for c in cases:
            with self.subTest(c=c):
                p = Stop(c.drift, c.diffusion, c.discount,
                         c.cost, c.reset, c.refractory)
                observed = regenerative_boundary(p)
                w = audit_scalar_global_qvi(c, observed_boundary=observed)
                for x in (observed - .2, observed - .01,
                          observed + .01, observed + .2):
                    expected = (math.exp(w.kappa*(x-w.boundary))/w.kappa
                                if x < observed
                                else x-c.cost+w.renewal_ratio/w.kappa)
                    got = regenerative_value(p, x)
                    self.assertAlmostEqual(got, expected, delta=5e-8*max(1, abs(expected)))
                    out = qvi(p, x)
                    self.assertLessEqual(out['complementarity'], 1e-8)

    def test_guard_is_research_only_and_does_not_activate_neural_authority(self):
        c = ScalarCase(0, 1, .5, 0, -1, 0)
        w = audit_scalar_global_qvi(c)
        self.assertIn('NOT_PRODUCTION', w.scope)


if __name__ == '__main__':
    unittest.main()
