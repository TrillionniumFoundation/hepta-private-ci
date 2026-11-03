import unittest
from fpt_reference import FPT,formula
from metamorphic_fpt import audit

class TestMetamorphic(unittest.TestCase):
    def test_compact_domain_invariants(self):
        evidence=audit(n=32)
        self.assertEqual(evidence['parameter_cases'],32)
    def test_absorbing_boundary(self):
        p=FPT(0.,-.4,.7,1.,.1)
        v=formula(p)
        self.assertEqual(v['F'],'1.0')
        self.assertEqual(v['G'],'1.0')
    def test_zero_horizon(self):
        p=FPT(.7,-.4,.7,0.,.1)
        v=formula(p)
        self.assertEqual(v['F'],'0.0')
        self.assertEqual(v['G'],'0.0')
    def test_parameter_rejection(self):
        for p in (FPT(-1.,0.,.7,1.,.1),FPT(1.,0.,0.,1.,.1),
                  FPT(1.,0.,.7,-1.,.1),FPT(1.,0.,.7,1.,-.1)):
            with self.assertRaises(ValueError): formula(p)

if __name__=='__main__':unittest.main()
