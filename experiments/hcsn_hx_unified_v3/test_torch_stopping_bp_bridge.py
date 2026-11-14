"""CPU/f64 independent gradient and obstacle checks for the regenerative bridge."""
import unittest
import math
import random

import torch

from .stopping import Stop, regenerative_boundary, regenerative_value, qvi
from .torch_stopping_bp_bridge import (
    ScalarQVISmoothFit, UnresolvedBP, scalar_qvi_features,
)


class TestScalarQVIBridge(unittest.TestCase):
    def tensors(self, values):
        return [torch.tensor(value, dtype=torch.float64, requires_grad=True)
                for value in values]

    def test_scalar_forward_agrees_with_independent_lambert(self):
        for vals in ((.1,.6,.25,1.,.1,.3),(-.3,.7,.55,.6,-.9,.25),
                     (0.,.24,.08,2.,.3,0.)):
            p=Stop(*vals)
            observed=ScalarQVISmoothFit.apply(*self.tensors(vals)).item()
            self.assertAlmostEqual(observed,regenerative_boundary(p),delta=1e-10)

    def test_six_implicit_gradients_vs_independent_central_differences(self):
        for vals in ((.1,.6,.25,1.,.1,.3),(-.3,.7,.55,.6,-.9,.25)):
            inputs=self.tensors(vals)
            gradient=torch.autograd.grad(ScalarQVISmoothFit.apply(*inputs),inputs)
            for i,g in enumerate(gradient):
                h=2e-5*max(1.,abs(vals[i]))
                left=list(vals); right=list(vals)
                left[i]-=h;right[i]+=h
                finite_difference=(regenerative_boundary(Stop(*right))-
                                   regenerative_boundary(Stop(*left)))/(2*h)
                self.assertAlmostEqual(g.item(),finite_difference,
                                       delta=2e-5*max(1.,abs(finite_difference)))

    def test_value_and_obstacle_vs_independent_scalar_qvi(self):
        vals=(.1,.6,.25,1.,.1,.3)
        p=Stop(*vals)
        b=regenerative_boundary(p)
        states=[b-1.6,b-.7,b-.05,b+.03,b+.8]
        value,adv,margin=scalar_qvi_features(torch.tensor(states,dtype=torch.float64),*self.tensors(vals))
        for i,x in enumerate(states):
            self.assertAlmostEqual(value[i].item(),regenerative_value(p,x),delta=1e-10)
            self.assertAlmostEqual(adv[i].item(),-qvi(p,x)['obstacle'],delta=1e-10)
            self.assertAlmostEqual(margin[i].item(),x-b,delta=1e-10)

    def test_loss_gradient_reaches_all_six_physical_inputs(self):
        vals=(.1,.6,.25,1.,.1,.3)
        args=self.tensors(vals)
        p=Stop(*vals); b=regenerative_boundary(p)
        state=torch.tensor([b-1.5,b-.7,b+.2,b+.9],dtype=torch.float64)
        value,adv,margin=scalar_qvi_features(state,*args)
        loss=(value*torch.tensor([.5,-.3,.4,.7])).sum() + (adv*torch.tensor([.2,.6,-.1,.4])).sum() + .05*margin.sum()
        gradients=torch.autograd.grad(loss,args)
        self.assertTrue(all(bool(torch.isfinite(g).all()) and abs(g.item())>1e-9 for g in gradients))

    def test_seeded_250_domain_probe_analytic_and_numerical_gradients(self):
        rng=random.Random(202610311026)
        accepted=0
        refused=0
        for _ in range(250):
            mu=rng.uniform(-.8,.8)
            sigma=math.exp(rng.uniform(math.log(.1),math.log(1.5)))
            rho=math.exp(rng.uniform(math.log(.08),math.log(1.2)))
            cost=rng.uniform(.4,3.)
            reset=cost-math.exp(rng.uniform(math.log(.1),math.log(2.)))
            tau=rng.uniform(0.,1.)
            values=(mu,sigma,rho,cost,reset,tau)
            args=self.tensors(values)
            try:
                b=ScalarQVISmoothFit.apply(*args)
                grad=torch.autograd.grad(b,args)
            except UnresolvedBP:
                refused+=1
                continue
            accepted+=1
            independent=regenerative_boundary(Stop(*values))
            self.assertAlmostEqual(b.item(),independent,delta=2e-10*max(1,abs(independent)))
            for i,g in enumerate(grad):
                h=1e-5*max(1,abs(values[i]))
                left=list(values);right=list(values)
                left[i]-=h;right[i]+=h
                if ((i in (1,2) and left[i]<=0) or
                        (i==5 and left[i]<0) or (i==4 and right[i]>=cost)):
                    continue
                numerical=(regenerative_boundary(Stop(*right))-
                           regenerative_boundary(Stop(*left)))/(2*h)
                self.assertAlmostEqual(g.item(),numerical,delta=2e-5*max(1,abs(numerical)))
        self.assertGreaterEqual(accepted,200)
        self.assertEqual(accepted+refused,250)

    def test_fail_closed_near_boundary_f32_and_invalid_domain(self):
        vals=(.1,.6,.25,1.,.1,.3)
        b=regenerative_boundary(Stop(*vals))
        with self.assertRaises(UnresolvedBP):
            scalar_qvi_features(torch.tensor([b],dtype=torch.float64),*self.tensors(vals))
        args=self.tensors(vals);args[0]=args[0].float()
        with self.assertRaises(UnresolvedBP):
            ScalarQVISmoothFit.apply(*args)
        with self.assertRaises(UnresolvedBP):
            ScalarQVISmoothFit.apply(*self.tensors((.1,0.,.25,1.,.1,.3)))
        with self.assertRaises(UnresolvedBP):
            ScalarQVISmoothFit.apply(*self.tensors((.1,.6,.25,1.,1.,.3)))


if __name__ == '__main__':
    unittest.main()
