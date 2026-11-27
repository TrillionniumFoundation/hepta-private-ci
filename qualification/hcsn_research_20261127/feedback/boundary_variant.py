"""Exact-structure and local-tangent comparators for the frozen 7149 affine regenerative QVI."""
import math
import torch
from torch.autograd.function import once_differentiable
from model import FeedbackBoundary

class DimensionlessRoot(torch.autograd.Function):
    """Principal root of u + eta exp(-u)=1+kD; explicit VJP for drift, cost, reset."""
    @staticmethod
    def forward(ctx, mu,cost,absolute,sigma,rho,eta,gain,maintenance):
        if mu.dtype!=torch.float64 or absolute.dtype!=torch.float64:
            raise ValueError("declared FP64 physical lane")
        root=(mu.square()+2*rho*sigma**2).sqrt()
        k=torch.where(mu>=0,(mu+root)/sigma**2,2*rho/(root-mu))
        s=gain/rho
        d=(1-eta)*(absolute+mu/rho-maintenance/gain)+cost/s
        h=1+k*d
        # u+ηexp(-u) strictly increases for u>=0. Positive root < h.
        # Four Halley steps on the fixed HCSN calibration rectangle.
        u=(2*(h-eta)).sqrt()
        for _ in range(4):
            q=eta*torch.exp(-u)
            val=u+q-h
            slope=1-q
            u=u-2*val*slope/(2*slope.square()-val*q)
        exp=eta*torch.exp(-u)
        mass=1-exp
        b=absolute-u/k
        if not bool((torch.isfinite(b)&(h>eta)&((u+exp-h).abs()<=5e-14)&(b<absolute-1e-4)&(b>absolute-8)).all()):
            raise FloatingPointError("dimensionless QVI validity gate")
        # Partial derivatives at fixed, exact root.
        dmu=u/(k*root)-(d/root + (1-eta)/rho)/mass
        dcost=-1/(s*mass)
        dabs=1-(1-eta)/mass
        ctx.save_for_backward(dmu,dcost,dabs)
        return b

    @staticmethod
    @once_differentiable
    def backward(ctx,cotangent):
        dmu,dcost,dabs=ctx.saved_tensors
        return cotangent*dmu,cotangent*dcost,cotangent*dabs,None,None,None,None,None

class BoundaryVariant(FeedbackBoundary):
    def __init__(self,arm,variant="halley", neurons=8):
        if variant not in ("halley","tangent","ordinary_learned"):
            raise ValueError("unknown boundary")
        super().__init__(arm,neurons=neurons)
        self.variant=variant
        c=self.config
        with torch.enable_grad():
            mu=torch.full_like(self.reset_absolute,c.base_drift,requires_grad=True)
            cost=torch.full_like(self.reset_absolute,c.cost,requires_grad=True)
            ref=super().qvi_boundary(mu,cost)
            gmu,gcost=torch.autograd.grad(ref.sum(),(mu,cost))
        self.register_buffer("tangent_mu",gmu)
        self.register_buffer("tangent_cost",gcost)
        if variant=="ordinary_learned":
            self.offset_mu=torch.nn.Parameter(torch.zeros_like(gmu))
            self.offset_cost=torch.nn.Parameter(torch.zeros_like(gcost))

    def qvi_boundary(self, drift,cost):
        if not hasattr(self,"variant"):
            return super().qvi_boundary(drift,cost)
        c=self.config
        if self.variant in ("tangent","ordinary_learned"):
            m,k=self.tangent_mu,self.tangent_cost
            if self.variant=="ordinary_learned":
                m=m*(1+.5*self.offset_mu.tanh()); k=k*(1+.5*self.offset_cost.tanh())
            return self.fixed_boundary + (drift-c.base_drift)*m + (cost-c.cost)*k
        eta=math.exp(-c.stages*math.log1p(c.discount*c.refractory/c.stages))
        b=DimensionlessRoot.apply(drift,cost,self.reset_absolute,c.sigma,c.discount,eta,c.gain,c.maintenance)
        nominal=(drift==c.base_drift)&(cost==c.cost)
        return torch.where(nominal,b+(self.fixed_boundary.expand_as(b)-b).detach(),b)
