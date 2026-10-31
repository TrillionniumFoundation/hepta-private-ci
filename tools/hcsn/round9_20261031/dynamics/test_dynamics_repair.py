"""Regression coverage for missed transitions and low-noise renewal integrals."""

from pathlib import Path
import unittest

from tools.hcsn.round8_20261031.event_dynamics.event_kernel import first_hit, two_segment_first_hit

from .audit import audit
from .clock_scaling import audit as clock_audit
from .recovery_scale import audit as recovery_audit


class ContinuousRepairTests(unittest.TestCase):
    def test_registered_independent_density_and_gradient_checks(self):
        result = audit(Path(__file__).resolve().parents[4])
        self.assertEqual([row["name"] for row in result["gates"] if not row["passed"]], [])

    def test_physical_clock_covariance(self):
        result = clock_audit()
        self.assertEqual([row["name"] for row in result["gates"] if not row["passed"]], [])

    def test_fast_recovery_value_and_gradient(self):
        result = recovery_audit(Path(__file__).resolve().parents[4])
        self.assertEqual([row["name"] for row in result["gates"] if not row["passed"]], [])

    def test_constant_process_is_invariant_to_segment_partition(self):
        for drift in (-.4, .4, 1.):
            for sigma in (.05, .6):
                reference = first_hit(.8, drift, sigma, 1.2)["probability"]
                for split in (.01, .1, .3, .7, 1.19):
                    actual = two_segment_first_hit(.8, (split, drift, sigma), (1.2 - split, drift, sigma))
                    self.assertLess(abs(actual["probability"] - reference), 2e-11,
                                    (drift, sigma, split, actual, reference))


if __name__ == "__main__":
    unittest.main()
