"""Support corrections remain mandatory even with zero sample variance."""

import math
import unittest

from .paid_audit import Plan
from .variance_audit import VarianceAudit, empirical_radius


class VarianceAuditTests(unittest.TestCase):
    def test_unbiased_sample_variance_and_range_constant(self):
        expected = math.sqrt(2*1.0*3.0/3)+7*2.0*3.0/(3*2)
        self.assertAlmostEqual(empirical_radius([1., 2., 3.], 2., 3.), expected)
        self.assertGreater(empirical_radius([1., 1., 1.], 2., 3.), 0.)

    def test_full_fee_and_missing_reset_controls_survive(self):
        for fee, expected in ((0.0, "adopt"), (0.002, "no-update")):
            audit = VarianceAudit(Plan("a"*64, 1., (0., 1.), (0., 0.), budget=2.))
            for i in range(512):
                audit.pair(str(i), "a"*64, 1., 0., 0., fee)
            self.assertEqual(audit.decide()["decision"], expected)
        audit = VarianceAudit(Plan("a"*64, 1., (0., 1.), (-1., 1.), beta=0.1))
        audit.pair("one", "a"*64, 1., 0., 0., 0.)
        audit.pair("two", "a"*64, 1., 0., 0., 0.)
        self.assertEqual(audit.decide()["reason"], "insufficient_independent_samples")

    def test_null_constant_outcomes_do_not_pass(self):
        audit = VarianceAudit(Plan("a"*64, 1., (0., 1.), (0., 0.)))
        for i in range(512):
            audit.pair(str(i), "a"*64, 0.4, 0.4, 0., 0.)
        self.assertEqual(audit.decide()["decision"], "no-update")


if __name__ == "__main__":
    unittest.main()
