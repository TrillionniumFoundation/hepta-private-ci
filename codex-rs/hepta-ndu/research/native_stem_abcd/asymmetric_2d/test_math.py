"""R18 mechanism, exact moment, finite-tree and two-dimensional certificate tests."""
from fractions import Fraction as F
import unittest
import numpy as np
from numpy.testing import assert_allclose
from certificate import (I,G,M,A,B,NOISE,certificate,ablation_certificate,
                         quotient_gradient,exp_interval,log_interval,logcosh_interval,
                         tanh_interval,logistic_interval)
from problem import objective,direct,population,leaf,INITIALS,quotient
class MathTests(unittest.TestCase):
 def test_01_exact_interval_add(self):
  x,y=I.at(F(1,3)),I.at(F(7,11));self.assertTrue((x+y).contains(F(32,33)))
 def test_02_exact_interval_mul(self):
  x,y=I.at(F(-1,3)),I.at(F(7,11));self.assertTrue((x*y).contains(F(-7,33)))
 def test_03_exact_interval_inverse(self):self.assertTrue((1/I.at(F(3,7))).contains(F(7,3)))
 def test_04_reject_zero_division(self):
  with self.assertRaises(ZeroDivisionError):_ = I.at(1)/I(-1,1)
 def test_05_exp_interval(self):
  self.assertTrue(exp_interval(0).contains(1))
  with self.assertRaises(ValueError):exp_interval(2)
 def test_06_log_interval(self):
  self.assertTrue(log_interval(1).contains(0))
  with self.assertRaises(ValueError):log_interval(-1)
 def test_07_transcendental_at_zero(self):
  self.assertTrue(tanh_interval(0).contains(0))
  self.assertTrue(logcosh_interval(0).contains(0))
  self.assertTrue(logistic_interval(0).contains(F(1,2)))
 def test_08_exact_2d_gradient(self):
  a,b=quotient_gradient(A*B,(A-B)**2/4)
  self.assertLess(float(a.magnitude()+b.magnitude()),1e-20)
 def test_09_global_strong_convexity(self):self.assertEqual(M,F(81,50))
 def test_10_global_regret(self):
  c=certificate();self.assertTrue(c['globally_certified_2D'])
  self.assertLess(float(F(c['rigorous_true_population_regret_upper'])),1e-43)
 def test_11_weight_distance(self):
  c=certificate();self.assertLess(float(F(c['rigorous_weight_component_error_upper'])),1e-20)
 def test_12_genuine_off_diagonal_optimality(self):
  c=certificate();self.assertGreater(float(F(c['all_a_equal_b_regret_lower'])),.12)
 def test_13_one_weight_ablation(self):
  self.assertGreater(float(F(certificate()['all_b_zero_regret_lower'])),.39)
 def test_14_d0_negative_derivative(self):
  self.assertLess(float(quotient_gradient(A*B,0)[1].upper()),-.5)
 def test_15_shift0_separate_global_certificate(self):
  c=ablation_certificate();self.assertTrue(c['valid_global_certificate'])
  self.assertLess(float(F(c['rigorous_cost_regret_upper'])),1e-40)
 def test_16_positive_shift_changes_global_minimizers(self):
  self.assertGreater(abs(float(A-B)),1.)
 def test_17_full_leaf_matches_quotient(self):
  for sh in (0.,1.):
   for theta in ([0,0],[1.2,.7],[-1.3,1.5],[float(A),float(B)]):
    self.assertAlmostEqual(objective(theta,sh)[0],direct(theta,sh),places=12)
    self.assertAlmostEqual(objective(theta,sh)[0],quotient(theta,sh)[0],places=12)
 def test_18_full_gradient_and_hessian_fd(self):
  th=np.array([.7,1.3]);h=2e-5
  for sh in (0.,1.):
   _,g,H=objective(th,sh)
   for i in range(2):
    e=np.eye(2)[i]*h
    self.assertAlmostEqual((objective(th+e,sh)[0]-objective(th-e,sh)[0])/(2*h),g[i],places=7)
    assert_allclose((objective(th+e,sh)[1]-objective(th-e,sh)[1])/(2*h),H[:,i],rtol=1e-6,atol=1e-7)
 def test_19_quotient_gradient_fd(self):
  t,d=.63,.42;h=1e-5
  C,g,H=population(t,d)
  for i in range(2):
   e=np.eye(2)[i]*h
   v=[t,d]
   va=population(*(np.array(v)+e))[0];vb=population(*(np.array(v)-e))[0]
   self.assertAlmostEqual((va-vb)/(2*h),g[i],places=7)
 def test_20_quotient_positive_hessian(self):
  for t,d in [(.7,.4),(-2,0),(3,2),(.5,-2)]:
   self.assertGreaterEqual(np.linalg.eigvalsh(population(t,d)[2])[0],float(M)-1e-12)
 def test_21_origin_strict_saddle(self):
  for sh in (0.,1.):
   _,g,H=objective((0.,0.),sh)
   assert_allclose(g,[0,0],atol=0)
   self.assertLess(np.linalg.eigvalsh(H)[0],-.5)
 def test_22_preference_transitions(self):
  for x in (-1,1):
   for p in (0,1):
    for e1 in (-1,1):
     for e2 in (-1,1):
      l=leaf(.7,.4,x,p,e1,e2)
      self.assertEqual(l['p1'],p^(e1==1))
      self.assertEqual(l['p2'],l['p1']^(e2==1))
 def test_23_asymmetric_condition_breaks_evenness(self):
  # Reflecting d is no longer a global symmetry of this known problem.
  self.assertGreater(abs(population(.7,.4)[0]-population(.7,-.4)[0]),.1)
 def test_24_compare_shift0_frozen_not_reusing_optimum(self):
  c=ablation_certificate();self.assertNotEqual(str(A*B),str(F(c['candidate_a'])**2))
 def test_25_completeness(self):self.assertEqual(len(INITIALS),8)
if __name__=='__main__':unittest.main(verbosity=2)
