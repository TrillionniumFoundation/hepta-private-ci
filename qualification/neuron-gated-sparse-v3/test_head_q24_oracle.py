#!/usr/bin/env python3
"""Native Head integer oracle: exact signed ties-even, physical F32, never authority."""
import hashlib
import math
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from head_q24_oracle import (Q, q24_from_f32, q24_mul, q24_head,
                             independent_same_activation_head_margin,
                             verify_native_head)


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

    def test_research_margin_strict_half_lsb_boundaries(self):
        for width in range(5,257):
            with self.subTest(width=width):
                activation=[0]*width
                twice_margin=9*width+1
                inside=twice_margin//2
                for logit in (-inside,0,inside):
                    status,bound=independent_same_activation_head_margin(logit,activation)
                    self.assertEqual(bound,twice_margin)
                    self.assertEqual(status,'QUANTIZATION_AMBIGUOUS_ABSTAIN')
                outside=twice_margin//2+1
                self.assertEqual(independent_same_activation_head_margin(
                    outside,activation)[0],'ACCEPT_POSITIVE_RESEARCH_ONLY')
                self.assertEqual(independent_same_activation_head_margin(
                    -outside,activation)[0],'ACCEPT_NEGATIVE_RESEARCH_ONLY')

    def test_margin_rejects_unbounded_or_malformed_native_activation(self):
        for activation in ([0]*4,[0]*257,[8*Q+1]+[0]*15,
                           [True]+[0]*15,tuple([0]*16)):
            with self.subTest(activation_type=type(activation).__name__), self.assertRaises(ValueError):
                independent_same_activation_head_margin(3000,activation)
        for logit in (True,1.0,-(1<<63)-1,1<<63):
            with self.subTest(logit=logit), self.assertRaises(ValueError):
                independent_same_activation_head_margin(logit,[0]*16)
        self.assertEqual(independent_same_activation_head_margin(
            -(1<<63),[0]*16)[0],'ACCEPT_NEGATIVE_RESEARCH_ONLY')

    def test_near_zero_quantized_head_never_claims_signed_decision(self):
        # Example where a tiny negative F32 coefficient quantizes to zero.
        import struct
        negative=struct.unpack('<f',struct.pack('<f',-0.25/Q))[0]
        self.assertLess(negative,0)
        self.assertEqual(q24_from_f32(negative),0)
        status,bound=independent_same_activation_head_margin(0,[0]*16)
        self.assertEqual(bound,145)
        self.assertEqual(status,'QUANTIZATION_AMBIGUOUS_ABSTAIN')

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
            rows=[]
            for i,activation in enumerate(activations):
                logit=q24_head(w,b,activation)
                status,margin=independent_same_activation_head_margin(logit,activation)
                rows.append({
                    'sequence':i+1, 'activation_q24':activation,
                    'quantized_head_logit_q24':logit,
                    'head_sign_margin_status':status,
                    'head_sign_margin_twice_q24_lsb':margin,
                })
            native={'width':5,'original_tick_count':2,'frontier':rows,
                    'head_sign_margin_profile':'hepta.neuron.same-activation-head-sign-margin.v1',
                    'head_margin_abstention_is_research_only':True,
                    'head_margin_authorized_for_final_use':False}
            result=verify_native_head(p,native)
            self.assertEqual(result['matched_step_count'],2)
            self.assertTrue(result['all_native_head_logits_match_independent_integer_oracle'])
            self.assertTrue(result['all_native_head_sign_margins_match_independent_integer_oracle'])
            self.assertEqual(sum(result['head_sign_margin_counts'].values()),2)
            self.assertFalse(result['full_original_f32_policy_execution_verified'])
            self.assertFalse(result['native_q24_model_production_qualification'])
            rows[1]['quantized_head_logit_q24']+=1
            with self.assertRaisesRegex(ValueError,'native Rust Q24 Head mismatch'):
                verify_native_head(p,native)
            rows[1]['quantized_head_logit_q24']-=1
            rows[1]['head_sign_margin_status']='QUANTIZATION_AMBIGUOUS_ABSTAIN'
            with self.assertRaisesRegex(ValueError,'sign margin'):
                verify_native_head(p,native)
            rows[1]['head_sign_margin_status']=independent_same_activation_head_margin(
                rows[1]['quantized_head_logit_q24'],rows[1]['activation_q24'])[0]
            rows[1]['head_sign_margin_twice_q24_lsb']+=2
            with self.assertRaisesRegex(ValueError,'sign margin'):
                verify_native_head(p,native)
            native['head_margin_authorized_for_final_use']=True
            with self.assertRaisesRegex(ValueError,'claimed final-use'):
                verify_native_head(p,native)


if __name__=='__main__':
    unittest.main()
