"""CPU/f64 independent gradient and obstacle checks for the regenerative bridge."""
import unittest

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
