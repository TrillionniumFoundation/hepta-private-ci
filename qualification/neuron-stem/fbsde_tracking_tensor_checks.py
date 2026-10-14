"""Actual shared-gate learning on own simulator; not pretrained/BBH performance."""
from pathlib import Path
import tempfile
import unittest
from fbsde_tracking_study import run
from four_gate_common import strict_loads


class TrackingTensorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.output = Path(cls.temp.name)/'study'
        cls.result = run(cls.output, tracking_source='generated')
    @classmethod
    def tearDownClass(cls): cls.temp.cleanup()

    def test_actual_fit_reduces_operation_loss(self):
        fit = strict_loads((self.output/'fit.json').read_bytes())
        self.assertLess(fit['losses'][-1], fit['losses'][0])
        self.assertEqual(fit['parameters'], 2073)

    def test_corrected_complete_sequences_match_exact_reference(self):
        r = self.result['summary']
        self.assertEqual(r['verified_recurrent']['correct'], r['exact_reverse']['correct'])
        self.assertEqual(r['verified_recurrent']['correct'], 192)
        self.assertEqual(r['fault_verified']['correct'], 192)
        self.assertEqual(r['fault_verified']['repairs'], 192)

    def test_first_step_is_not_an_entire_multistep_solution(self):
        r = self.result['summary']
        self.assertLess(r['last_step_only']['correct'], r['exact_forward']['correct'])
        self.assertFalse(self.result['general_reasoning_proved'])
        self.assertFalse(self.result['real_pretrained_executed'])

    def test_encoder_reused_and_cost_is_not_declared_free(self):
        self.assertGreater(self.result['cached_feature_uses'], self.result['unique_encoded_texts'])
        self.assertGreater(self.result['fit_cpu_ns'], 0)
        self.assertTrue(self.result['arm_cpu_is_not_full_lifecycle_cost'])
        self.assertFalse(self.result['production_promotion_permitted'])


if __name__ == '__main__': unittest.main()
