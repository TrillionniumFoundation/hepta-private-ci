"""Independent numerical, sensitivity, limits and failure-semantic checks."""
from __future__ import annotations
import math
import unittest

import numpy as np
import torch
try:
    from .moving_boundary_first_passage import (
        affine_hitting_torch, density_reference, sample_affine_hitting, piecewise_affine_hitting_mc)
except ImportError:
    from moving_boundary_first_passage import (
        affine_hitting_torch, density_reference, sample_affine_hitting, piecewise_affine_hitting_mc)


def d(x, requires_grad=False):
    return torch.tensor(x,dtype=torch.float64,requires_grad=requires_grad)


class TestAffineMovingFirstPassage(unittest.TestCase):
    def test_independent_density_96_panels(self):
        rng=np.random.default_rng(12001)
        max_err=0.
        for k in range(96):
            x=float(np.exp(rng.uniform(math.log(1e-4),math.log(2.))))
            T=float(np.exp(rng.uniform(math.log(.08),math.log(7.))))
            drift=float(rng.uniform(-.3,.3))
            sig=float(rng.uniform(.11,.85))
            slope=float(rng.uniform(-.18,.18))
            lam=float(rng.uniform(0.,.25))
            ans=affine_hitting_torch(d(x),d(T),d(drift),d(sig),d(slope),d(lam))
            f,g=density_reference(x,T,drift,sig,slope,lam)
            max_err=max(max_err,abs(ans.probability.item()-f),abs(ans.discounted_probability.item()-g))
            self.assertLess(max_err,1e-9,(k,x,T,drift,sig,slope,lam))
        self.assertLess(max_err,1e-9)

    def test_initial_and_zero_horizon(self):
        a=affine_hitting_torch(d([0.,.5,0.]),d([0.,0.,3.]),d(0.),d(.2),d(0.),d(.05))
        self.assertTrue(torch.equal(a.probability,d([1.,0.,1.])))
        self.assertTrue(torch.equal(a.discounted_probability,d([1.,0.,1.])))

    def test_discount_zero_and_boundary_slope(self):
        args=(d(.35),d(3.),d(.06),d(.24))
        z=affine_hitting_torch(*args,d(.02),d(0.))
        self.assertEqual(z.probability.item(),z.discounted_probability.item())
        slow=affine_hitting_torch(*args,d(-.2),d(.1))
        fast=affine_hitting_torch(*args,d(.2),d(.1))
        self.assertLess(slow.probability.item(),fast.probability.item())
        self.assertLess(slow.discounted_probability.item(),fast.discounted_probability.item())

    def test_autograd_vs_independent_centered_difference(self):
        # Compare six independent partial derivatives on non-degenerate points.
        v=[.37,2.4,.04,.32,.07,.095]
        x=[d(x,True) for x in v]
        a=affine_hitting_torch(*x)
        ga=torch.autograd.grad(a.discounted_probability,x)
        for k in range(6):
            h=2e-5*max(1.,abs(v[k]))
            up=v.copy();down=v.copy();up[k]+=h;down[k]-=h
            self.assertTrue(down[k]>=0 if k in (0,1,5) else True)
            fd=(density_reference(*up)[1]-density_reference(*down)[1])/(2*h)
            self.assertLess(abs(ga[k].item()-fd),2e-8,(k,ga[k].item(),fd))

    def test_mc_exact_hitting_time_with_defective_law(self):
        for mu in [-.15,0.,.15]:
            x=.34;sig=.38;T=2.8;lam=.12;slope=.05
            times=sample_affine_hitting(x,mu+slope,sig,slope,140000,seed=55)
            hit=np.isfinite(times)&(times<=T)
            f=float(hit.mean())
            g=float(np.where(hit,np.exp(-lam*np.minimum(times,T)),0.).mean())
            ans=affine_hitting_torch(d(x),d(T),d(mu+slope),d(sig),d(slope),d(lam))
            # Finite sample standard deviations, not scientific preregistration.
            se_f=math.sqrt(max(1e-9,f*(1-f))/len(times))
            se_g=math.sqrt(max(1e-9,g*(1-g))/len(times))
            self.assertLess(abs(f-ans.probability.item()),6*se_f+.001)
            self.assertLess(abs(g-ans.discounted_probability.item()),6*se_g+.001)

    def test_log_margin_small_and_far(self):
        for x in [1e-9,1e-6,.01,.2,2.,8.]:
            a=affine_hitting_torch(d(x),d(2.),d(.02),d(.27),d(.05),d(.08))
            self.assertTrue(math.isfinite(a.probability.item()))
            self.assertTrue(0<=a.discounted_probability.item()<=a.probability.item()+1e-13<=1+1e-13)
        small=affine_hitting_torch(d(1e-10),d(2.),d(.02),d(.27),d(.05),d(.08))
        self.assertLess(1-small.probability.item(),1e-8)

    def test_input_failure_and_shape(self):
        good=[d(.2),d(1.),d(.05),d(.2),d(.0),d(.04)]
        for i,bad in [(0,-.1),(1,-.2),(3,0.),(5,-.1),(0,float('nan')),
                      (0,101.),(1,1.e5),(2,21.),(3,1.e-8),(4,21.),(5,21.)]:
            args=good.copy();args[i]=d(bad)
            with self.assertRaises(ValueError):affine_hitting_torch(*args)
        good[3]=torch.tensor(.2,dtype=torch.float32)
        with self.assertRaises(TypeError):affine_hitting_torch(*good)


    def test_zero_relative_drift_and_zero_discount_autograd_regression(self):
        x=d(.2,True);mu=d(0.,True);lam=d(0.,True)
        ans=affine_hitting_torch(x,d(1.),mu,d(.2),d(0.),lam)
        gradients=torch.autograd.grad(ans.discounted_probability,[x,mu,lam])
        self.assertTrue(all(torch.isfinite(g).all() for g in gradients))
        self.assertEqual(ans.probability.item(),ans.discounted_probability.item())
        self.assertLess(gradients[0].item(),0.)

    def test_batched_gradients_all_finite(self):
        x=d([.15,.3,.45],True)
        a=affine_hitting_torch(x,d([1.,3.,5.]),d(.04),d(.3),d([-.08,0.,.12]),d(.07))
        loss=(a.probability+a.discounted_probability).sum()
        loss.backward()
        self.assertTrue(torch.isfinite(x.grad).all())
        self.assertTrue(bool((x.grad<0).all()))



    def test_piecewise_exact_bridge_matches_affine_closed_form(self):
        x=.3; sig=.31; drift=.02; slope=.11; horizon=3.
        ans=affine_hitting_torch(d(x),d(horizon),d(drift),d(sig),d(slope),d(.1))
        for segments in [1,3,12]:
            est=piecewise_affine_hitting_mc(x,drift,sig,
                np.full(segments,slope),np.full(segments,horizon/segments),
                paths=150000,seed=522)
            # Each bridge segment uses an exact conditional crossing probability.
            self.assertLess(abs(est.hit_probability-ans.probability.item()),
                            6*est.standard_error+.001)

    def test_boundary_history_matters_not_just_final_boundary(self):
        # Same initial/final boundary and integral slope; earlier high boundary
        # strictly dominates the later high boundary at intermediate times.
        early=piecewise_affine_hitting_mc(.22,0.,.26,[.45,-.45],[.8,.8],
                                         paths=250000,seed=1234)
        late=piecewise_affine_hitting_mc(.22,0.,.26,[-.45,.45],[.8,.8],
                                        paths=250000,seed=1234)
        self.assertGreater(early.hit_probability,late.hit_probability+.07)
        # Not a simulated 'spike advantage': demonstrates geometric history.

    def test_piecewise_adversarial_rejections(self):
        inputs=(.3,0.,.25,[.2,-.2],[1.,1.])
        for args in [(-.2,*inputs[1:]),(.3,0.,0.,inputs[3],inputs[4]),
                     (.3,0.,.25,[.2],[1.,1.]),(.3,0.,.25,[float('nan')],[1.]),
                     (.3,0.,.25,[.2],[0.])]:
            with self.assertRaises(ValueError):piecewise_affine_hitting_mc(*args)


if __name__=='__main__':
    unittest.main()
