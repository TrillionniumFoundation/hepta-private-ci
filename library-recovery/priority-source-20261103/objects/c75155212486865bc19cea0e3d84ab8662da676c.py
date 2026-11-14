"""CPU/f64 PyTorch research bridge for a scalar regenerative QVI boundary.

This module uses the independent scalar Brownian regeneration oracle, NOT the
full coupled He--Xiong original equity/bond equilibrium. A custom autograd
Function supplies the *local implicit boundary gradient* from the analytic
smooth-fit equation while its forward value is calculated by the standalone
SciPy/Brent reference. This bridges the proven scalar math to a differentiable
PyTorch feature head without pretending a discrete FIRE action is smooth.

Only scalar CPU float64 physical parameters are admitted; Tensor.item() in
forward is deliberate and makes this unsuitable as a GPU production kernel.
Inputs exactly on a free boundary are rejected rather than choosing a fake
generalized derivative. Float32, BF16, and moving boundaries remain unqualified.
"""
from __future__ import annotations

import math
import torch
from torch import nn

from .regenerative_qvi_oracle_v2 import RegenerativeNeuron, UnresolvedQVI


class TorchQVIDomainError(ValueError):
    pass


class ScalarBoundary(torch.autograd.Function):
    """Inputs (mu,sigma,rho,K,reset,tau), outputs scalar Brownian QVI b."""

    @staticmethod
    def forward(ctx, mu, sigma, rho, cost, reset, refractory):
        params=(mu,sigma,rho,cost,reset,refractory)
        if any(not isinstance(t,torch.Tensor) or t.numel()!=1 or
               t.dtype!=torch.float64 or t.device.type!='cpu' for t in params):
            raise TorchQVIDomainError('scalar CPU float64 tensor parameters required')
        if not all(torch.isfinite(t).item() for t in params):
            raise TorchQVIDomainError('finite physical QVI parameters required')
        p=RegenerativeNeuron(*(float(t.detach().item()) for t in params))
        s=p.solution
        grads=p.boundary_sensitivities()
        ctx.derivatives=tuple(grads[key] for key in
            ('drift','sigma','discount','cost','reset','refractory'))
        return mu.new_tensor(s.boundary)

    @staticmethod
    def backward(ctx, grad_output):
        return tuple(grad_output*d for d in ctx.derivatives)


def scalar_value_features(x: torch.Tensor, mu: torch.Tensor, sigma: torch.Tensor,
                          rho: torch.Tensor, cost: torch.Tensor, reset: torch.Tensor,
                          refractory: torch.Tensor) -> tuple[torch.Tensor,torch.Tensor,torch.Tensor]:
    """Return (optimal J, continuation-over-immediate-FIRE, signed margin).

    Only x!=b with a prescribed f64 separation is supported; the function
    backpropagates through b via implicit derivatives and through kappa and
    post-FIRE continuation using ordinary PyTorch autograd.
    """
    if not isinstance(x,torch.Tensor) or x.dtype!=torch.float64 or x.device.type!='cpu':
        raise TorchQVIDomainError('state batch must be CPU float64')
    if x.ndim!=1 or x.numel()==0 or not bool(torch.isfinite(x).all()):
        raise TorchQVIDomainError('nonempty finite vector of states required')
    b=ScalarBoundary.apply(mu,sigma,rho,cost,reset,refractory)
    if bool((torch.abs(x-b)<=1e-10*(1+torch.abs(b))).any()):
        raise TorchQVIDomainError('free-boundary equality or unresolved nearby branch')
    d=torch.sqrt(mu*mu+2*rho*sigma*sigma)
    k=torch.where(mu>=0,2*rho/(d+mu),(d-mu)/(sigma*sigma))
    q=torch.exp(-rho*refractory-k*(b-reset))
    continue_value=torch.exp(k*(x-b))/k
    stop_value=x-cost+q/k
    value=torch.where(x<b,continue_value,stop_value)
    fire_value=x-cost+torch.exp(-rho*refractory)*torch.exp(k*(reset-b))/k
    # The two values must agree throughout the immediate-FIRE region.
    adv=value-fire_value
    if not bool(torch.isfinite(value).all() and torch.isfinite(adv).all()):
        raise TorchQVIDomainError('nonfinite differentiable QVI feature')
    if bool((adv<-1e-8*torch.maximum(value.abs(),torch.ones_like(value))).any()):
        raise TorchQVIDomainError('QVI obstacle sign violated by numerical evaluation')
    return value,adv,x-b


class TrainableRegenerativeFeature(nn.Module):
    """Small learnable scalar-QVI feature module, not a complete HCSN encoder."""

    def __init__(self):
        super().__init__()
        self.drift=nn.Parameter(torch.tensor(.1,dtype=torch.float64))
        self.log_sigma=nn.Parameter(torch.tensor(math.log(.6),dtype=torch.float64))
        self.log_discount=nn.Parameter(torch.tensor(math.log(.25),dtype=torch.float64))
        self.cost=nn.Parameter(torch.tensor(1.,dtype=torch.float64))
        self.log_reset_gap=nn.Parameter(torch.tensor(math.log(.9),dtype=torch.float64))
        self.log_refractory=nn.Parameter(torch.tensor(math.log(.3),dtype=torch.float64))

    def forward(self,x:torch.Tensor) -> torch.Tensor:
        sigma=torch.exp(self.log_sigma)
        rho=torch.exp(self.log_discount)
        gap=torch.exp(self.log_reset_gap)
        tau=torch.exp(self.log_refractory)
        j,adv,margin=scalar_value_features(
            x,self.drift,sigma,rho,self.cost,self.cost-gap,tau)
        return torch.stack((j,adv,margin),dim=-1)
