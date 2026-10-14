import unittest
from fractions import Fraction as Q
import numpy as np
from certificate import I,exp_enclosure,log_I,tanh_I,sigmoid_I,scalar_gradient,certify,LOWER_T,UPPER_T,S,G
from problem import loss_tree,ce_costs,c_derivatives,objective,derivative,populations_agree
class MathTests(unittest.TestCase):
 def test_interval_outward_basic(self):
  x=I.at(Q(1,3));y=I.at(Q(5,7))
  self.assertTrue((x*y).contains(Q(5,21)))
  self.assertTrue((x/y).contains(Q(7,15)))
  self.assertTrue((x+(-x)).contains(0))
  with self.assertRaises(ZeroDivisionError):_ = x/I(-1,1)
 def test_exp_log_tanh(self):
  self.assertTrue(exp_enclosure(0).contains(1))
  self.assertTrue(log_I(1).contains(0))
  self.assertTrue(tanh_I(0).contains(0))
  self.assertTrue(sigmoid_I(0).contains(Q(1,2)))
 def test_overflow_rejected(self):
  with self.assertRaises(ValueError):exp_enclosure(2)
  with self.assertRaises(ValueError):log_I(-1)
 def test_root_bracket_sign(self):
  self.assertLess(scalar_gradient(LOWER_T).hi,0)
  self.assertGreater(scalar_gradient(UPPER_T).lo,0)
 def test_exact_rigorous_bounds(self):
  c=certify()
  self.assertTrue(c['rigorous_global_certificate'])
  self.assertLess(Q(c['weight_component_error_upper']),Q(1,10**11))
  self.assertLess(Q(c['true_population_excess_upper']),Q(1,10**20))
  self.assertGreater(Q(c['one_weight_b_zero_regret_lower']),Q(39,100))
 def test_zero_risk_difference_proven(self):
  self.assertGreater(Q(certify()['rigorously_nonzero_risk_shift_lower']),Q(4,1000))
 def test_preference_branches(self):
  for p in (0,1):
   for e1 in (-1,1):
    for e2 in (-1,1):
     r=loss_tree(.8,.9,1,p,e1,e2)
     self.assertEqual(r['p1'],p^(e1==1));self.assertEqual(r['p2'],r['p1']^(e2==1))
 def test_independent_forward(self):
  for a,b in ((0.,0.),(.7,.9),(-.8,-.6),(2.,-1.)):
   x,y=populations_agree([a,b]);self.assertAlmostEqual(x,y,places=13)
 def test_gradient_finite_difference(self):
  for theta in ([.5,.8],[-1.2,1.3],[.9,.9]):
   g,h=derivative(theta)
   for k in range(2):
    d=np.eye(2)[k]*1e-5
    self.assertAlmostEqual((objective(np.array(theta)+d)-objective(np.array(theta)-d))/(2e-5),g[k],places=7)
    gh=(derivative(np.array(theta)+d)[0]-derivative(np.array(theta)-d)[0])/(2e-5)
    np.testing.assert_allclose(gh,h[:,k],atol=1e-8,rtol=1e-6)
 def test_global_scalar_curvature(self):
  for t in (-5,-1,0,.5,1,2,5):
   self.assertGreaterEqual(c_derivatives(t)[2],float(2*G*G)-1e-12)
 def test_origin_saddle(self):
  g,h=derivative((0,0));np.testing.assert_allclose(g,0,atol=0)
  self.assertLess(np.linalg.eigvalsh(h)[0],-1)
 def test_certificate_vs_float(self):
  c=certify(); t=float(S*S)
  full=c_derivatives(t)[1]+.5
  lo,hi=c['candidate_gradient_bounds']
  self.assertLess(abs(full-(float(Q(lo))+float(Q(hi)))/2),1e-12)
 def test_same_sign_global_minima(self):
  a=float(S)
  self.assertAlmostEqual(objective([a,a]),objective([-a,-a]),places=13)
  self.assertGreater(objective([a,-a]),objective([a,a]))
 def test_opposite_no_false_optimum(self):
  self.assertGreater(objective([0,0]),objective([float(S),float(S)]))
if __name__=='__main__':unittest.main(verbosity=2)
