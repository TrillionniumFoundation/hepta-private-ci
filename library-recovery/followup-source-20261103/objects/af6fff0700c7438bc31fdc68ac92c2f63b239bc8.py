import unittest
from hepta_pr1884_head_margin_reference import (classify_frozen_q24_head_sign as classify,
    H,Q)

class ResearchHeadMargin(unittest.TestCase):
    def test_width16_strict_boundary(self):
        x=[0]*16
        for v in (-72,0,72): self.assertEqual(classify(v,x).status,'QUANTIZATION_AMBIGUOUS_ABSTAIN')
        for v in (73,1000):self.assertEqual(classify(v,x).status,'ACCEPT_POSITIVE_RESEARCH_ONLY')
        for v in (-73,-1000):self.assertEqual(classify(v,x).status,'ACCEPT_NEGATIVE_RESEARCH_ONLY')
    def test_width256_strict_boundary(self):
        x=[H]*256
        self.assertEqual(classify(1152,x).status,'QUANTIZATION_AMBIGUOUS_ABSTAIN')
        self.assertEqual(classify(1153,x).status,'ACCEPT_POSITIVE_RESEARCH_ONLY')
    def test_real_f32_negative_bias_vs_rounded_zero_is_ambiguous(self):
        import struct
        from pathlib import Path
        f32=lambda v:struct.unpack('<f',struct.pack('<f',v))[0]
        source_bias=f32(-0.25/Q)
        assert source_bias<0
        # Q24 ties-even integer output after bias quantization rounds to zero;
        # sign would flip if 'zero implies positive' were accepted.
        self.assertEqual(round(source_bias*Q),0)
        self.assertEqual(classify(0,[0]*16).status,'QUANTIZATION_AMBIGUOUS_ABSTAIN')
    def test_no_authority_from_research_margin_decision(self):
        d=classify(Q,[Q]*16)
        self.assertFalse(d.production_qualification)
        self.assertFalse(d.ndu_eligible)
        self.assertFalse(d.native_activation_source_attested)
        self.assertFalse(d.real_float_policy_parity_verified)
    def test_wrong_activation_width_and_value_are_rejected(self):
        for x in ([0]*4,[0]*257,[H+1]+[0]*15,[True]+[0]*15,tuple([0]*16)):
            with self.assertRaises(ValueError):classify(Q,x)
    def test_wrong_logit_type_and_width_are_rejected(self):
        for v in (True,1.0,1<<63,-(1<<63)-1):
            with self.assertRaises(ValueError):classify(v,[0]*16)
    def test_nonzero_sign_accepted_only_outside_bound(self):
        for n in range(5,257):
            x=[0]*n
            first=(9*n+1)//2+1
            self.assertEqual(classify(first,x).status,'ACCEPT_POSITIVE_RESEARCH_ONLY')
            self.assertEqual(classify(-first,x).status,'ACCEPT_NEGATIVE_RESEARCH_ONLY')
            self.assertEqual(classify(first-1,x).status,'QUANTIZATION_AMBIGUOUS_ABSTAIN')

if __name__=='__main__': unittest.main()
