import unittest
from .firsthit_precision_guard import screen,UnresolvedFirstHit

class TestFirstHit(unittest.TestCase):
    def test_real_dtype_bounded_cases(self):
        for dtype in ('fp32','bf16'):
            for y,mu,sigma,T in ((.5,0.,.4,1.),(1.,-.3,.6,2.),(.15,.2,.4,.5),(.8,.1,1.,2.)):
                out=screen(y,mu,sigma,T,dtype,tolerance=.05)
                self.assertEqual(out.status,'MEASURED_ONLY')
                self.assertGreaterEqual(out.reference,0)
    def test_strict_guard_can_refuse(self):
        out=screen(.5,0.,.4,1.,'bf16',tolerance=1e-8)
        self.assertEqual(out.status,'REFUSE')
    def test_invalid(self):
        with self.assertRaises(UnresolvedFirstHit): screen(0.,0.,.4,1.,'fp32',tolerance=.01)
        with self.assertRaises(UnresolvedFirstHit): screen(.2,0.,.4,1.,'fp16',tolerance=.01)
        with self.assertRaises(UnresolvedFirstHit): screen(.2,0.,.4,1.,'fp32',tolerance=0)
if __name__=='__main__': unittest.main()
