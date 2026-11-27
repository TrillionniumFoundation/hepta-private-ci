import unittest
from fractions import Fraction as F
import numpy as np
from experiment import exact_J,exact_gap,OPT,SADDLE,proof,grad,hess,objective,run
class Tests(unittest.TestCase):
 def test_proof(self):self.assertTrue(proof()['globally_certified'])
 def test_exact_gap_nonnegative(self):
  for a in (F(-2),F(-1),F(0),F(1),F(2)):
   for b in (F(-2),F(-1),F(0),F(1),F(2)):self.assertGreaterEqual(exact_gap(a,b),0)
 def test_stationary_saddle(self):
  np.testing.assert_array_equal(grad([0,0]),[0,0]);self.assertLess(np.linalg.eigvalsh(hess([0,0]))[0],0)
 def test_terminal_noise_constant(self):self.assertEqual(OPT,F(179,400))
 def test_derivative(self):
  x=np.array([.43,-.77]);h=1e-6
  for k in range(2):
   e=np.eye(2)[k]*h
   self.assertAlmostEqual((objective(x+e)-objective(x-e))/(2*h),grad(x)[k],places=7)
 def test_24_fits(self):self.assertEqual(len(run()),24)
if __name__=='__main__':unittest.main()
