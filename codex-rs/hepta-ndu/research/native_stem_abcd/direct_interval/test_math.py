"""R20 strict exact-Fraction interval proof, independent AD and finite risk law tests."""
from fractions import Fraction as F
import math,unittest
import numpy as np
import torch
from model import full,leaves,independent_full,forward, q,dq,ddq,ETA,LAMBDA,INITIALS
from fitters import ad_objective,METHODS
from global_interval import (qrange,square_range,cost_bounds,ce_lower,ce_upper,
     logcosh_lower,logcosh_upper,bisect,bnb)
torch.set_num_threads(1)

class MathTests(unittest.TestCase):
 def test_01_exact_rational_channel(self):
  self.assertEqual(q(F(1),F(1,8)),F(1,16))
  self.assertEqual(q(F(-1),F(1,8)),F(-1,16))
  self.assertEqual(dq(F(1),F(1,8)),F(0))
 def test_02_qrange_critical_points(self):
  self.assertEqual(qrange(F(-3),F(3),F(1,8)),(F(-1,16),F(1,16)))
  self.assertEqual(qrange(F(2),F(3),F(1,8)),(F(3,80),F(1,20)))
 def test_03_square_negative_and_crossing(self):
  self.assertEqual(square_range(F(-3),F(2)),(F(0),F(9)))
  self.assertEqual(square_range(F(-3),F(-1)),(F(1),F(9)))
 def test_04_invalid_boxes(self):
  with self.assertRaises(ValueError):qrange(F(1),F(0),ETA)
  with self.assertRaises(ValueError):cost_bounds((F(1),F(0),F(-1),F(1)))
 def test_05_symmetry_is_broken(self):
  a,b=1.6,.4
  self.assertNotEqual(forward([a,b],True)[1],forward([b,a],True)[1])
  self.assertGreater(abs(full([a,b],True)[0]-full([a,b],False)[0]),1e-3)
 def test_06_leaf_census_and_preference_flips(self):
  tab=leaves([1.6,.4],True)
  self.assertEqual(tab.shape,(16,10))
  for r in tab:
   x,p,e1,e2,p1,p2=r[:6]
   self.assertEqual(p1,int(p)^(int(e1)==1))
   self.assertEqual(p2,int(p1)^(int(e2)==1))
 def test_07_independent_direct_vs_analytic(self):
  for extra in (False,True):
   for x in INITIALS+((1.54,.45),(1.6,-.45)):
    self.assertLess(abs(full(x,extra)[0]-independent_full(x,extra)),3e-13)
 def test_08_ad_value_gradient_hessian(self):
  for extra in (False,True):
   for x in ([1.3,.6],[-.7,-1.],[0.,0.]):
    z=torch.tensor(x,dtype=torch.float64,requires_grad=True)
    val=ad_objective(z,extra)
    g=torch.autograd.grad(val,z,retain_graph=True)[0].detach().numpy()
    h=torch.autograd.functional.hessian(lambda p:ad_objective(p,extra),z).detach().numpy()
    score,ag,ah=full(x,extra)
    self.assertLess(abs(float(val.detach())-score),2e-13)
    np.testing.assert_allclose(g,ag,rtol=2e-11,atol=1e-11)
    np.testing.assert_allclose(h,ah,rtol=2e-11,atol=1e-11)
 def test_09_finite_difference_derivatives(self):
  for extra in (False,True):
   for x in ([1.43,.5],[-.5,-1.3]):
    theta=np.array(x);g=full(x,extra)[1];h=full(x,extra)[2]
    for j in range(2):
     e=np.eye(2)[j]*1e-5
     self.assertAlmostEqual((full(theta+e,extra)[0]-full(theta-e,extra)[0])/2e-5,g[j],places=7)
     np.testing.assert_allclose((full(theta+e,extra)[1]-full(theta-e,extra)[1])/2e-5,h[:,j],atol=2e-8,rtol=2e-6)
 def test_10_logcosh_global_bounding_polynomials(self):
  for z in np.linspace(-5,5,31):
   f=F(str(float(z)))
   truth=math.log(math.cosh(z))
   self.assertLessEqual(float(logcosh_lower(f)),truth+1e-13)
   self.assertGreaterEqual(float(logcosh_upper(f)),truth-1e-13)
 def test_11_ce_interval(self):
  for v0,v1 in [(F(0),F(1,50)),(F(2),F(1,2)),(F(30),F(3))]:
   for rho in (F(1,2),F(1)):
    actual=(float(v0)+float(v1))/2+math.log(math.cosh(float(rho*(v1-v0)/2)))/float(rho)
    self.assertLessEqual(float(ce_lower(v0,v1,rho)),actual+1e-12)
    self.assertGreaterEqual(float(ce_upper(v0,v1,rho)),actual-1e-12)
 def test_12_exact_leaf_objective_enclosure(self):
  for extra in (False,True):
   for a,b in [(F(0),F(0)),(F(154696889,100000000),F(44887401,100000000)),(F(-2),F(1)),(F(1,2),F(3,4))]:
    lower,upper=cost_bounds((a,a,b,b),extra)
    score=full([float(a),float(b)],extra)[0]
    self.assertLessEqual(float(lower),score+2e-13)
    self.assertGreaterEqual(float(upper),score-2e-13)
 def test_13_random_box_enclosures(self):
  rng=np.random.default_rng(159)
  for extra in (False,True):
   for i in range(18):
    aa=sorted((F(str(v)) for v in rng.uniform(-2,2,size=2)))
    bb=sorted((F(str(v)) for v in rng.uniform(-2,2,size=2)))
    lo,hi=cost_bounds((*aa,*bb),extra)
    for a in (aa[0],aa[1],(aa[0]+aa[1])/2):
     for b in (bb[0],bb[1],(bb[0]+bb[1])/2):
      score=full([float(a),float(b)],extra)[0]
      self.assertLessEqual(float(lo),score+1e-12)
      self.assertGreaterEqual(float(hi),score-1e-12)
 def test_14_domain_exclusion(self):
  for extra,a,b in [(True,F('1.54696889'),F('.44887401')),(False,F('1.64044199'),F('.42331392'))]:
   lo,hi=cost_bounds((a,a,b,b),extra)
   self.assertLess(hi,F(9,4))
 def test_15_bisection_cover(self):
  original=(F(-3),F(3),F(-3),F(3));a,b=bisect(original)
  self.assertEqual(a[0],original[0]);self.assertEqual(a[1],b[0]);self.assertEqual(b[1],original[1])
  self.assertEqual(a[2:],original[2:]);self.assertEqual(b[2:],original[2:])
 def test_16_two_successful_proof_censuses(self):
  for extra,a,b in [(True,F('1.54696889'),F('.44887401')),(False,F('1.64044199'),F('.42331392'))]:
   result=bnb(a,b,extra,F(1,100),50000)
   self.assertTrue(result['passes_frozen_global_threshold'])
   self.assertFalse(result['strong_convex_auxiliary_used'])
   self.assertLess(result['nodes_split'],50000)
 def test_17_mandatory_cap_retains_failure(self):
  r=bnb(F('1.54696889'),F('.44887401'),True,F(1,100),10)
  self.assertFalse(r['passes_frozen_global_threshold'])
  self.assertEqual(r['nodes_split'],10)
 def test_18_invalid_limit(self):
  with self.assertRaises(ValueError):bnb(F(1),F(1),node_cap=0)
 def test_19_all_strong_methods_present(self):
  self.assertEqual(set(METHODS),set(['adam','bfgs','lbfgs','trust-exact','ad-trust-exact']))
 def test_20_exact_16_leaf_cost_is_nonnegative(self):
  self.assertGreaterEqual(full((0,0),True)[0],0)
  self.assertGreaterEqual(full((0,0),False)[0],0)

if __name__=='__main__':unittest.main(verbosity=2)
