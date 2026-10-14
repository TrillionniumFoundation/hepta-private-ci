"""Real unmodified Transformers architecture smoke, not pretrained quality.

Runs ONLY in the pinned installed-HF CI job, never silently skipped by the
source-only suite.
"""
import unittest

from hf_profile_checks import InstalledHFTests
from public_fanout_probe import run


class RealHFSharedFanoutTests(unittest.TestCase):
    def setUp(self):
        fixture=InstalledHFTests(methodName='test_full_stock_architecture_roundtrip_and_physical_tie')
        fixture.setUp()
        self.addCleanup(fixture.tmp.cleanup)
        self.snapshot=fixture.root

    def test_exact_stock_encoder_reuse_across_112_cells(self):
        result=run(self.snapshot,tasks=7)
        self.assertEqual((result['shared_encoder_calls'],result['repeated_encoder_calls']),(1,7))
        self.assertEqual(result['logical_cells'],112)
        self.assertEqual(result['logit_parity_max_abs_error'],0.)
        self.assertGreater(result['repeated_formula_flops'],result['shared_formula_flops'])
        self.assertFalse(result['any_trained_head'])
        self.assertFalse(result['latency_speedup_established'])


if __name__=='__main__':
    unittest.main()
