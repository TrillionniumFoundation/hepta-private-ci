import unittest
import numpy as np
from head_only_physical import head_parameters,build_bank,forward,run
from dataclasses import replace

class PhysicalHeadTests(unittest.TestCase):
    def test_actual_geometry(self):
        self.assertEqual(head_parameters(),9744)
        b=build_bank(9)
        self.assertEqual(b.physical_parameters,9*9744)
        self.assertEqual(b.weight_bytes,9*9744*4)
        self.assertEqual(forward(b).shape,(9,8))
    def test_independent_cell_head_weights(self):
        b=build_bank(2)
        self.assertFalse(np.array_equal(b.down[0],b.down[1]))
        self.assertFalse(np.array_equal(forward(b)[0],forward(b)[1]))
    def test_shared_input_with_local_state(self):
        b=build_bank(2)
        a=forward(b)
        b.local[0,0]+=100
        y=forward(b)
        self.assertFalse(np.array_equal(a[0],y[0]))
        self.assertTrue(np.array_equal(a[1],y[1]))
    def test_no_fake_model_execution(self):
        r=run(4,trials=3)
        self.assertEqual(r['cells_actually_executed'],4)
        self.assertEqual(r['physical_encoder_forward_count'],0)
        self.assertEqual(r['batch_wall_p50_ns'] is not None,True)
        self.assertIsNone(r['batch_wall_p95_ns'])
        self.assertIsNone(r['batch_wall_p99_ns'])
        self.assertFalse(r['independent_task_utility_established'])
        self.assertFalse(r['production_accepted'])
    def test_reproducible_exact_output(self):
        self.assertTrue(np.array_equal(forward(build_bank(3,100)),forward(build_bank(3,100))))
        self.assertFalse(np.array_equal(forward(build_bank(3,100)),forward(build_bank(3,101))))
    def test_reject_unbounded(self):
        for n in (-1,0,4097,1.0,True):
            with self.subTest(n=n),self.assertRaises(ValueError):
                build_bank(n)
        with self.assertRaises(ValueError): run(2,trials=2)
    def test_shape_tamper(self):
        b=build_bank(2)
        bad=replace(b,gate_bias=np.zeros((8,),dtype=np.float32))
        with self.assertRaises(ValueError): forward(bad)

if __name__=='__main__': unittest.main()
