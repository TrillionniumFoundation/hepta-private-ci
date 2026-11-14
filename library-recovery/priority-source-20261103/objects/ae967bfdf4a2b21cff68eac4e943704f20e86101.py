"""Derivative, boundary, QVI and trainability probes for f64 CPU bridge."""
from dataclasses import replace
import math
import unittest

import torch

from .regenerative_qvi_oracle_v2 import RegenerativeNeuron
from .torch_implicit_regenerative import (
    ScalarBoundary,scalar_value_features,TrainableRegenerativeFeature,TorchQVIDomainError,
)


class TorchImplicitRegenerativeTests(unittest.TestCase):
    def setUp(self):
        self.params=(.1,.6,.25,1.,.1,.3)

    def tensors(self,vals=None):
        return [torch.tensor(v,dtype=torch.float64,requires_grad=True)
                for v in (self.params if vals is None else vals)]

    def test_forward_matches_independent_scipy_qvi(self):
        p=RegenerativeNeuron(*self.params)
        b=p.solution.boundary
        args=self.tensors()
        self.assertAlmostEqual(ScalarBoundary.apply(*args).item(),b,places=12)
        x=torch.tensor([b-1.5,b-.5,b+.2,b+1],dtype=torch.float64)
        val,adv,margin=scalar_value_features(x,*args)
        for i,z in enumerate(x.tolist()):
            self.assertAlmostEqual(val[i].item(),p.value(z),delta=2e-12)
            self.assertAlmostEqual(adv[i].item(),-p.qvi(z).obstacle_residual,delta=1e-11)
            self.assertAlmostEqual(margin[i].item(),z-b,delta=1e-12)

    def test_implicit_gradient_matches_six_independent_fd(self):
        for vals in (self.params,(-.3,.7,.55,.6,-.9,.25)):
            args=self.tensors(vals)
            b=ScalarBoundary.apply(*args)
            gradients=torch.autograd.grad(b,args)
            for i,g in enumerate(gradients):
                v=vals[i]
                h=1e-5*max(1.,abs(v))
                lhs=list(vals); rhs=list(vals)
                lhs[i]-=h;rhs[i]+=h
                numerical=(RegenerativeNeuron(*rhs).solution.boundary-
                           RegenerativeNeuron(*lhs).solution.boundary)/(2*h)
                self.assertAlmostEqual(g.item(),numerical,
                    delta=1e-5*max(1.,abs(numerical)))

    def test_all_trainable_parameter_groups_receive_task_gradient(self):
        model=TrainableRegenerativeFeature()
        x=torch.tensor([-.5,.05,.2,.75,1.6,2.5],dtype=torch.float64)
        out=model(x)
        weights=torch.tensor([[.3,.15,-.04],[-.8,.13,.5],[.45,.9,-.8],
                              [.6,.03,.7],[-.2,.6,1.],[-.1,.4,.9]],dtype=torch.float64)
        loss=(out*weights).sum()
        loss.backward()
        for name,param in model.named_parameters():
            with self.subTest(name=name):
                self.assertTrue(bool(torch.isfinite(param.grad).all()))
                self.assertGreater(abs(param.grad.item()),1e-9)
        before={n:p.detach().clone() for n,p in model.named_parameters()}
        opt=torch.optim.SGD(model.parameters(),lr=.0003)
        opt.step()
        self.assertTrue(all(not torch.equal(p.detach(),before[n]) for n,p in model.named_parameters()))

    def test_branch_equality_rejected_not_fake_smooth(self):
        args=self.tensors()
        b=ScalarBoundary.apply(*args).item()
        with self.assertRaises(TorchQVIDomainError):
            scalar_value_features(torch.tensor([b],dtype=torch.float64),*args)

    def test_reject_f32_cpu_and_gpu_like_claims(self):
        bad=self.tensors()
        bad[0]=bad[0].float()
        with self.assertRaises(TorchQVIDomainError):
            ScalarBoundary.apply(*bad)
        with self.assertRaises(TorchQVIDomainError):
            scalar_value_features(torch.tensor([1.],dtype=torch.float32),*self.tensors())


if __name__=='__main__':
    unittest.main()
