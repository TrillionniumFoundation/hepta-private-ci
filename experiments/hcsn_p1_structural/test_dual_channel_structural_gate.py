"""Independent arithmetic / Jacobian / first-passage adversarial probes."""
import math
import random
import unittest

import torch

try:
    from .dual_channel_structural_gate import (
        Refusal, channels, power_boundary, first_hit_probability,
        independent_first_hit_density_integral)
except ImportError:
    from dual_channel_structural_gate import (
        Refusal, channels, power_boundary, first_hit_probability,
        independent_first_hit_density_integral)


class StructureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(1)

    def test_put_call_parity_500_adversarial_states(self):
        rng = random.Random(3187)
        for _ in range(500):
            r = rng.uniform(.005,.25)
            delta = rng.uniform(.005,.18)
            sigma = rng.uniform(.02,.85)
            v = torch.tensor(rng.uniform(.1,5),dtype=torch.float64)
            k = torch.tensor(rng.uniform(.1,5),dtype=torch.float64)
            c = channels(v,k,r=r,delta=delta,sigma=sigma)
            self.assertAlmostEqual(float(c.call-c.put-v+k),0.,delta=1e-10)
            self.assertAlmostEqual(float(c.call_normalized-c.put_normalized-v/k+1),0.,delta=1e-11)

    def test_smooth_paste_call_and_nonzero_put_margin_slope(self):
        beta, ratio = power_boundary(.05,.03,.2)
        k = torch.tensor(1.,dtype=torch.float64)
        for m in (0.,1e-6,1e-4,.03,.5):
            v = torch.tensor(ratio*math.exp(m),dtype=torch.float64,requires_grad=True)
            c = channels(v,k)
            dc = torch.autograd.grad(c.call,v,retain_graph=True)[0].item()
            dp = torch.autograd.grad(c.put,v,retain_graph=True)[0].item()
            dm = torch.autograd.grad(c.margin,v)[0].item()
            expected = -math.expm1(-(beta+1)*m) if m>0 else 0.
            self.assertAlmostEqual(dc,expected,delta=2e-10)
            self.assertAlmostEqual(dp,expected-1,delta=2e-10)
            self.assertAlmostEqual(dm,1/v.item(),delta=3e-12)

    def test_scale_invariance_and_zero_common_scale_gradient(self):
        # Input feature vector (Call/K, Put/K, margin) cannot distinguish
        # (V,K) from (aV,aK) at *any* common scale a>0.
        v,k = 1.07,1.22
        for a in (.1,.7,1.,1e3):
            c0=channels(torch.tensor(v,dtype=torch.float64),torch.tensor(k,dtype=torch.float64))
            ca=channels(torch.tensor(a*v,dtype=torch.float64),torch.tensor(a*k,dtype=torch.float64))
            self.assertAlmostEqual(float(c0.call_normalized-ca.call_normalized),0.,delta=1e-12)
            self.assertAlmostEqual(float(c0.put_normalized-ca.put_normalized),0.,delta=1e-12)
            self.assertAlmostEqual(float(c0.margin-ca.margin),0.,delta=1e-12)
            self.assertAlmostEqual(float(ca.call-a*c0.call),0.,delta=1e-10)
        a=torch.tensor(1.3,dtype=torch.float64,requires_grad=True)
        c=channels(v*a,k*a)
        for z in (c.call_normalized,c.put_normalized,c.margin):
            dz=torch.autograd.grad(z,a,retain_graph=True)[0].item()
            self.assertLess(abs(dz),2e-12)

    def test_normalized_jacobian_rank_one_not_independent_channels(self):
        rng=random.Random(2026)
        for _ in range(64):
            a=rng.uniform(.5,1.8)
            b=rng.uniform(.7,1.8)
            def f(t):
                c=channels(t[0],t[1])
                return torch.stack((c.call_normalized,c.put_normalized,c.margin))
            jac=torch.autograd.functional.jacobian(f,torch.tensor((a,b),dtype=torch.float64))
            singular=torch.linalg.svdvals(jac)
            self.assertGreater(singular[0].item(),1e-4)
            self.assertLess(singular[1].item(),5e-12)

    def test_boundary_tracks_input_margin_gradient_can_vanish(self):
        # Previous 'margin always passes input gradient' is false when K
        # and thus the free boundary are contextual functions of the input.
        x=torch.tensor(1.3,dtype=torch.float64,requires_grad=True)
        c=channels(1.2*x,x)
        for value in (c.call_normalized,c.put_normalized,c.margin):
            self.assertLess(abs(torch.autograd.grad(value,x,retain_graph=True)[0].item()),2e-12)

    def test_reflection_cdf_vs_independent_density_quadrature(self):
        rng=random.Random(314159)
        worst=0.
        for _ in range(180):
            r=rng.uniform(.012,.17)
            delta=rng.uniform(.01,.14)
            sigma=rng.uniform(.075,.55)
            T=rng.uniform(.1,6)
            b=rng.uniform(.4,1.3)
            v=b*math.exp(rng.uniform(.01,.65))
            q=first_hit_probability(v,b,T,r=r,delta=delta,sigma=sigma)
            integ,err=independent_first_hit_density_integral(v,b,T,r=r,delta=delta,sigma=sigma)
            worst=max(worst,abs(q-integ))
            self.assertLess(abs(q-integ),max(2e-9,12*err))
        self.assertLess(worst,2e-9)

    def test_first_hit_probability_boundaries_and_underflow(self):
        for s in (.01,.2,1.):
            self.assertEqual(first_hit_probability(.8,1.,5.,sigma=s),1.)
            self.assertEqual(first_hit_probability(1.,1.,5.,sigma=s),1.)
            for v in (1.000001,1.1,2,10,100):
                for t in (1e-4,.01,1,50):
                    p=first_hit_probability(v,1.,t,sigma=s)
                    self.assertTrue(0.<=p<=1.)

    def test_high_power_stop_region_does_not_poison_autograd(self):
        # A straightforward torch.where over exp(-beta*negative-margin)
        # evaluates +inf even when its stop-branch is not selected.
        beta, ratio = power_boundary(.3,.001,.01)
        self.assertGreater(beta,1000)
        v=torch.tensor(1e-6,dtype=torch.float64,requires_grad=True)
        k=torch.tensor(1e6,dtype=torch.float64)
        c=channels(v,k,r=.3,delta=.001,sigma=.01)
        self.assertEqual(float(c.call.detach()),0.)
        self.assertTrue(torch.isfinite(c.call).item())
        self.assertTrue(torch.isfinite(c.put).item())
        self.assertTrue(torch.isfinite(torch.autograd.grad(c.call+c.put,v)[0]).item())

    def test_refuse_invalid_parameters_and_tensor_domains(self):
        with self.assertRaises(Refusal):power_boundary(0,.03,.2)
        with self.assertRaises(Refusal):power_boundary(.05,.03,float('nan'))
        with self.assertRaises(Refusal):first_hit_probability(0.,1.,1.)
        with self.assertRaises(Refusal):first_hit_probability(2.,1.,0.)
        for invalid in (float('nan'),float('inf'),-.5,0.):
            with self.assertRaises(Refusal):channels(torch.tensor(1.,dtype=torch.float64),torch.tensor(invalid,dtype=torch.float64))
        with self.assertRaises(Refusal):channels(torch.tensor(1.,dtype=torch.float32),torch.tensor(1.,dtype=torch.float32))


if __name__=='__main__':unittest.main()
