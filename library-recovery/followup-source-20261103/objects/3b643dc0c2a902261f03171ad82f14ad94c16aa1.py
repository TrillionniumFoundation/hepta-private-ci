import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import bench_shared_cell_cpu as bench

class ReferenceTests(unittest.TestCase):
    def test_one_and_eight_match(self):
        for n in (1,8):
            s=bench.measured_arm(n, 'shared', 4, 15)
            d=bench.measured_arm(n, 'duplicated', 4, 15)
            self.assertEqual(len(s['scores']),n)
            self.assertLess(max(abs(a-b) for a,b in zip(s['scores'],d['scores'])),3e-5)
            self.assertGreaterEqual(d['parameter_bytes_float32'],s['parameter_bytes_float32'])
    def test_unbounded_configuration_refused(self):
        with self.assertRaises(ValueError): bench.cpu_payload(8192,'shared',4)
        with self.assertRaises(ValueError): bench.cpu_payload(1,'bogus',4)
        with self.assertRaises(ValueError): bench.cpu_payload(1,'shared',100000)
    def test_real_synthetic_gradient_and_nochange(self):
        t=bench.synthetic_training()
        self.assertTrue(t['zero_delta_parity'])
        self.assertLess(t['synthetic_heldout_mse_after'],t['synthetic_heldout_mse_before'])
        self.assertFalse(t['external_independent_evaluation'])
        self.assertFalse(t['real_pretrained_encoder'])

if __name__=='__main__': unittest.main()
