"""R21 actual 2/3/4 weight loss, derivatives, exact CE bounds and branch geometry."""
import unittest
from fractions import Fraction as F
import numpy as np
import torch
from model import full,leaf_table,independent_full,forward,INITIALS
from fitters import torch_full,fit
from global_interval import (qr,square,ce_lower,ce_upper,cost_bounds,bisect,
                             CANDIDATES,DOMAIN,NODE_CAP,TARGET,G,ETA,KAPPA)
class Tests(unittest.TestCase):
 def test_01_three_dimensions_true_forward_state(self):
  a=forward([.7,.9,0.],1,-1,1)
  b=forward([.7,.9,.3],1,-1,1)
  self.assertNotEqual(a[0],b[0]);self.assertNotEqual(a[1],b[1])
 def test_02_fourth_parameter_affects_mixing(self):
  a=forward([.7,.9,.3,0.],-1,-1,1)
  b=forward([.7,.9,.3,.4],-1,-1,1)
  self.assertNotEqual(a[1],b[1])
 def test_03_full_leaf_preference_law(self):
  for n in (2,3,4):
   raw=leaf_table(np.array([.6,.2,.1,.3][:n]))
   self.assertEqual(raw.shape,(16,10))
   for r in raw:
    self.assertEqual(int(r[4]),int(r[1])^(int(r[2])==1))
    self.assertEqual(int(r[5]),int(r[4])^(int(r[3])==1))
 def test_04_independent_tree_matches_analytic(self):
  rng=np.random.default_rng(17)
  for n in (2,3,4):
   for _ in range(4):
    v=rng.normal(size=n)
    self.assertAlmostEqual(full(v)[0],independent_full(v),places=13)
 def test_05_ad_objective_is_equal(self):
  for n in (2,3,4):
   v=np.array([.8,1.1,.6,.3][:n])
   self.assertAlmostEqual(full(v)[0],float(torch_full(torch.tensor(v)).detach()),places=13)
 def test_06_grad_equal_ad(self):
  for n in (2,3,4):
   v=np.array([.8,1.1,.6,.3][:n]);z=torch.tensor(v,requires_grad=True)
   gt=torch.autograd.grad(torch_full(z),z)[0].detach().numpy()
   np.testing.assert_allclose(gt,full(v)[1],rtol=4e-12,atol=4e-12)
 def test_07_hessian_equal_ad(self):
  for n in (2,3,4):
   v=np.array([.8,1.1,.6,.3][:n]);z=torch.tensor(v,requires_grad=True)
   H=torch.autograd.functional.hessian(torch_full,z).detach().numpy()
   np.testing.assert_allclose(H,full(v)[2],rtol=6e-11,atol=6e-11)
 def test_08_gradient_finite_diff(self):
  for n in (2,3,4):
   v=np.array([.3,-.7,.4,.2][:n])
   for k in range(n):
    eps=np.eye(n)[k]*1e-5
    fd=(full(v+eps)[0]-full(v-eps)[0])/(2e-5)
    self.assertAlmostEqual(fd,full(v)[1][k],places=7)
 def test_09_hessian_finite_diff(self):
  for n in (2,3,4):
   v=np.array([.3,-.7,.4,.2][:n])
   for k in range(n):
    eps=np.eye(n)[k]*1e-5
    fd=(full(v+eps)[1]-full(v-eps)[1])/(2e-5)
    np.testing.assert_allclose(fd,full(v)[2][:,k],rtol=3e-7,atol=3e-8)
 def test_10_fraction_point_bounds_include_float(self):
  for n in (2,3,4):
   cand=tuple((F(s),F(s)) for s in CANDIDATES[n]);lo,hi=cost_bounds(cand)
   fp=full(np.asarray([float(F(s)) for s in CANDIDATES[n]]))[0]
   self.assertLessEqual(float(lo)-1e-12,fp)
   self.assertGreaterEqual(float(hi)+1e-12,fp)
 def test_11_bounds_mono_root_and_candidate(self):
  for n in (2,3,4):
   box=tuple((-DOMAIN,DOMAIN) for _ in range(n));lo,hi=cost_bounds(box)
   point=tuple((F(s),F(s)) for s in CANDIDATES[n]);l,h=cost_bounds(point)
   self.assertLessEqual(lo,l);self.assertGreaterEqual(hi,h)
 def test_12_split_covers_and_conserves(self):
  for n in (2,3,4):
   root=tuple((-DOMAIN,DOMAIN) for _ in range(n));axis,left,right=bisect(root)
   self.assertEqual(left[axis][1],right[axis][0]);self.assertEqual(left[axis][0],root[axis][0]);self.assertEqual(right[axis][1],root[axis][1])
   for k in range(n):
    if k!=axis:self.assertEqual(left[k],right[k])
 def test_13_ce_bounds_include_independent_eval(self):
  import math
  for low,high in ((F(1,4),F(3,5)),(F(0),F(100)),(F(-1),F(1))):
   for rho in (F(1,2),F(1)):
    l=ce_lower(low,high,rho);u=ce_upper(low,high,rho)
    truth=math.log((math.exp(float(rho*low))+math.exp(float(rho*high)))/2)/float(rho)
    self.assertLessEqual(float(l)-1e-10,truth);self.assertGreaterEqual(float(u)+1e-10,truth)
 def test_14_q_and_square_range(self):
  for lo,hi in ((F(-3),F(3)),(F(-1),F(2)),(F(0),F(1))):
   ql,qh=qr((lo,hi),ETA)
   self.assertLessEqual(ql,ETA*lo/(1+lo*lo));self.assertGreaterEqual(qh,ETA*hi/(1+hi*hi))
   sq=square((lo,hi));self.assertGreaterEqual(sq[1],0)
 def test_15_domain_outside_proof(self):
  for n in (2,3,4):
   candidate=tuple((F(s),F(s)) for s in CANDIDATES[n]);self.assertLess(cost_bounds(candidate)[1],F(9,4))
 def test_16_fixed_protocol(self):
  self.assertEqual(NODE_CAP,4000);self.assertEqual(TARGET,F(1,100))
 def test_17_initial_controls_shared(self):
  self.assertEqual(len(INITIALS),8)
  self.assertEqual(tuple(INITIALS[0]),(0.,0.))
 def test_18_after_cpu_cap_not_success(self):
  theta=fit(np.zeros(3),'adam',cap=1e-9)
  self.assertEqual(theta['status'],'cpu_censored')
  self.assertEqual(theta['counts']['updates'],0)
if __name__=='__main__':unittest.main(verbosity=2)
