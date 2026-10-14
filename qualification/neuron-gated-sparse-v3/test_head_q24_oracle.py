#!/usr/bin/env python3
"""Native Head integer oracle: exact signed ties-even, physical F32, never authority."""
import hashlib
import math
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from head_q24_oracle import Q, q24_from_f32, q24_mul, q24_head, verify_native_head


class SignedQ24HeadOracleTests(unittest.TestCase):
    def test_f32_signed_ties_even(self):
        self.assertEqual(q24_from_f32(0.5/Q),0)
        self.assertEqual(q24_from_f32(1.5/Q),2)
        self.assertEqual(q24_from_f32(-1.5/Q),-2)
        self.assertEqual(q24_from_f32(-2.5/Q),-2)
        self.assertEqual(q24_from_f32(8.0),8*Q)
        self.assertEqual(q24_from_f32(-8.0),-8*Q)

    def test_q24_product_signed_ties_even(self):
        self.assertEqual(q24_mul(1,Q//2),0)
        self.assertEqual(q24_mul(3,Q//2),2)
        self.assertEqual(q24_mul(-3,Q//2),-2)
        self.assertEqual(q24_mul(-5,Q//2),-2)
        self.assertEqual(q24_mul(Q,-Q),-Q)
        self.assertEqual(q24_mul(-Q,-Q),Q)

    def test_exact_dot_and_overflow(self):
        self.assertEqual(q24_head([Q//2,-Q//2],Q//4,[Q,Q]),Q//4)
        self.assertEqual(q24_head([3,3],0,[Q//2,Q//2]),4)
        with self.assertRaisesRegex(ValueError,'sum exceeds i64'):
            q24_head([Q,Q],(1<<63)-1,[1,1])

    def test_forbid_nonfinite_and_unrepresentable(self):
        for v in (float('nan'),float('inf'),float('-inf'),8.01,-8.01):
            with self.subTest(value=v), self.assertRaises(ValueError):
                q24_from_f32(v)

    def test_from_physical_safetensors_with_complete_native_frontier(self):
        import torch
        from safetensors.torch import save_file
        torch.set_num_threads(1)
        with TemporaryDirectory() as temp:
            p=Path(temp)/'head.safetensors'
            weight=torch.tensor([[.1,-.2,.3, .0, -.1]],dtype=torch.float32)
            bias=torch.tensor([.25],dtype=torch.float32)
            save_file({'head.weight':weight, 'head.bias':bias},str(p))
            w=[q24_from_f32(float(v)) for v in weight.flatten().tolist()]
            b=q24_from_f32(float(bias.item()))
            activations=[[Q,Q//2,0,0,Q],[0,Q,Q,Q//2,0]]
            rows=[{
                'sequence':i+1, 'activation_q24':a,
                'quantized_head_logit_q24':q24_head(w,b,a),
            } for i,a in enumerate(activations)]
            result=verify_native_head(p,{'width':5,'original_tick_count':2,'frontier':rows})
            self.assertEqual(result['matched_step_count'],2)
            self.assertTrue(result['all_native_head_logits_match_independent_integer_oracle'])
            self.assertFalse(result['full_original_f32_policy_execution_verified'])
            self.assertFalse(result['native_q24_model_production_qualification'])
            rows[1]['quantized_head_logit_q24']+=1
            with self.assertRaisesRegex(ValueError,'native Rust Q24 Head mismatch'):
                verify_native_head(p,{'width':5,'original_tick_count':2,'frontier':rows})


if __name__=='__main__':
    unittest.main()
