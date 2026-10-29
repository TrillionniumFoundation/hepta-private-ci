"""Finite-state first-passage operator and independent boundary root control.

The finite generator, reset interpolation and matrix-exponential / uniformization
implementations are preserved from the audited V2 source. They are exact finite
CTMC operations up to numerical evaluation, not an exact continuous diffusion.
"""
import math
import torch
from torch import nn
from torch.nn import functional as F

class _LambertW0(torch.autograd.Function):
    @staticmethod
    def forward(ctx, z):
        zz=z.to(torch.float64)
        w=zz.clone()
        for _ in range(16):
            ew=w.exp();residual=w*ew-zz
            w=w-residual/(ew*(w+1)-(w+2)*residual/(2*w+2))
        ctx.save_for_backward(w,zz)
        return w.to(z.dtype)

    @staticmethod
    def backward(ctx, gradient):
        w,z=ctx.saved_tensors
        return (gradient.to(torch.float64)*w/(z*(1+w))).to(gradient.dtype)


def frozen_control_boundary(drift, cost, sigma=.4, discount=.4, refractory=.1):
    """Scalar frozen-control impulse threshold; NOT a dynamic resource QVI."""
    gamma=(torch.sqrt(drift.square()+2*discount*sigma*sigma)-drift)/(sigma*sigma)
    z=-torch.exp(-discount*refractory-1-gamma*cost)
    return cost+(1+_LambertW0.apply(z))/gamma


class DensityNeuronOperator(nn.Module):
    """Finite CTMC operator with row-vector probability convention p exp(Q dt).

    generator(drift,boundary) returns (Q, event_rate), both differentiable in
    drift/boundary away from reset interpolation knots. The top transition is
    counted even if a zero-refractory reset lands back at its own state.
    """
    def __init__(self,grid_size=16,refractory_phases=2,lower_bound=-2.,sigma=.4,
                 refractory=.1,reset=0.,method='matrix_exp'):
        super().__init__()
        if grid_size<3 or refractory_phases<0:
            raise ValueError('grid_size>=3 and refractory_phases>=0 are required')
        if sigma<=0 or (refractory_phases and refractory<=0):
            raise ValueError('positive sigma and refractory mean are required')
        if lower_bound>=reset:
            raise ValueError('reset must be strictly above the reflecting floor')
        if method not in ('matrix_exp','uniformization'):
            raise ValueError('unknown finite-chain propagator')
        self.grid_size=int(grid_size);self.refractory_phases=int(refractory_phases)
        self.lower_bound=float(lower_bound);self.sigma=float(sigma)
        self.refractory=float(refractory);self.reset=float(reset);self.method=method
        self.state_size=self.grid_size+self.refractory_phases
        self.register_buffer('grid_fraction',torch.arange(self.grid_size,dtype=torch.float64)/self.grid_size)

    def nodes(self,boundary):
        return self.lower_bound+(boundary-self.lower_bound).unsqueeze(-1)*self.grid_fraction.to(boundary)

    def reset_distribution(self,boundary):
        n=self.grid_size
        z=(self.reset-self.lower_bound)/(boundary-self.lower_bound)*n
        lo=torch.floor(z).long().clamp(0,n-1)
        fraction=(z-lo.to(z.dtype)).clamp(0,1)
        hi=(lo+1).clamp(max=n-1)
        out=boundary.new_zeros(*boundary.shape,self.state_size)
        out=out.scatter_add(-1,lo.unsqueeze(-1),(1-fraction).unsqueeze(-1))
        return out.scatter_add(-1,hi.unsqueeze(-1),fraction.unsqueeze(-1))

    def generator(self,drift,boundary):
        """Upwind rates; spatial diffusion limit is first order for nonzero drift."""
        drift,boundary=torch.broadcast_tensors(drift,boundary)
        if bool((boundary<=self.reset).any()):
            raise ValueError('threshold must exceed reset')
        n=self.grid_size;s=self.state_size;k=self.refractory_phases
        spacing=(boundary-self.lower_bound)/n
        diffusion=self.sigma*self.sigma/(2*spacing.square())
        upward=diffusion+F.relu(drift)/spacing
        downward=diffusion+F.relu(-drift)/spacing
        q=drift.new_zeros(*drift.shape,s,s)
        indices=torch.arange(n-1,device=drift.device)
        q[...,indices,indices+1]=upward.unsqueeze(-1)
        q[...,indices+1,indices]=downward.unsqueeze(-1)
        reward=drift.new_zeros(*drift.shape,s)
        reward[...,n-1]=upward
        reset=self.reset_distribution(boundary)
        if k:
            q[...,n-1,n]=upward
            rate=k/self.refractory
            if k>1:
                phases=torch.arange(n,n+k-1,device=drift.device)
                q[...,phases,phases+1]=rate
            q[...,-1,:]=rate*reset
        else:
            q[...,n-1,:]=q[...,n-1,:]+upward.unsqueeze(-1)*reset
        q=q-torch.diag_embed(q.sum(dim=-1))
        return q,reward

    def _dt(self,dt,probability):
        value=torch.as_tensor(dt,dtype=probability.dtype,device=probability.device)
        while value.ndim<probability.ndim-1:
            value=value.unsqueeze(-1)
        if bool((value<0).any()):
            raise ValueError('negative elapsed time')
        return value.expand(probability.shape[:-1])

    def propagate(self,probability,dt,drift,boundary,method=None):
        """Return full probability and expected count, with no one-spike cap."""
        elapsed=self._dt(dt,probability)
        if not bool((elapsed>0).any()):
            return probability,torch.zeros_like(elapsed)
        q,reward=self.generator(drift,boundary)
        augmented=F.pad(q,(0,1,0,1))
        augmented[...,:self.state_size,-1]=reward
        initial=F.pad(probability,(0,1))
        method=self.method if method is None else method
        if method=='matrix_exp':
            transition=torch.matrix_exp(augmented*elapsed[...,None,None])
            result=torch.matmul(initial.unsqueeze(-2),transition).squeeze(-2)
        elif method=='uniformization':
            result=self._uniformization(initial,augmented,q,elapsed)
        else:
            raise ValueError('unknown finite-chain propagator')
        return result[...,:self.state_size],result[...,-1]

    def _uniformization(self,initial,augmented,q,elapsed):
        # Detaching the uniformization rate changes no infinite-series
        # derivative; the implemented series has a controlled tiny Poisson tail.
        rate=(-q.diagonal(dim1=-2,dim2=-1)).max().detach().clamp(min=1e-12)
        chunks=max(1,math.ceil(float((rate*elapsed.max()).detach())/16.))
        mean=rate*elapsed/chunks
        terms=math.ceil(float(mean.max().detach())+10*math.sqrt(float(mean.max().detach())+1)+20)
        eye=torch.eye(augmented.shape[-1],dtype=initial.dtype,device=initial.device)
        transition=eye+augmented/rate
        state=initial
        for _ in range(chunks):
            weight=torch.exp(-mean)
            term=state
            summed=weight.unsqueeze(-1)*term
            for order in range(1,terms+1):
                term=torch.matmul(term.unsqueeze(-2),transition).squeeze(-2)
                weight=weight*mean/order
                summed=summed+weight.unsqueeze(-1)*term
            state=summed
        return state

    def remap(self,probability,old_boundary,new_boundary,kick):
        """Conservative piecewise-linear voltage remapping at a true observation.

        Existing refractory phases are untouched. Active points beyond the new
        threshold fire immediately. Between the last active node and boundary,
        linear interpolation sends a fraction to the firing state; this is an
        explicit spatial remapping approximation, not an exact diffusion jump.
        Below-floor impulses clamp at the physical floor.
        """
        n=self.grid_size;k=self.refractory_phases;s=self.state_size
        locations=self.nodes(old_boundary)+kick.unsqueeze(-1)
        coordinates=((locations-self.lower_bound)/(new_boundary-self.lower_bound).unsqueeze(-1)*n).clamp(0,n)
        lo=torch.floor(coordinates).long()
        hi=(lo+1).clamp(max=n)
        fraction=coordinates-lo.to(coordinates.dtype)
        mapped=probability.new_zeros(*probability.shape[:-1],n+1)
        mapped=mapped.scatter_add(-1,lo,probability[...,:n]*(1-fraction))
        mapped=mapped.scatter_add(-1,hi,probability[...,:n]*fraction)
        fired=mapped[...,-1]
        result=F.pad(mapped[...,:n],(0,k))
        if k:
            result=result+F.pad(probability[...,n:],(n,0))
            destination=F.one_hot(torch.tensor(n,device=probability.device),s).to(probability)
            result=result+fired.unsqueeze(-1)*destination
        else:
            result=result+fired.unsqueeze(-1)*self.reset_distribution(new_boundary)
        return result,fired

    def remap_matrix(self,old_boundary,new_boundary,kick):
        """Return the stochastic observation map and immediate-count reward.

        Rows are source states. This exposes exactly the same discrete jump
        law to hard CTMC samplers or score-function training.
        """
        old_boundary,new_boundary,kick=torch.broadcast_tensors(old_boundary,new_boundary,kick)
        s=self.state_size
        identity=torch.eye(s,dtype=old_boundary.dtype,device=old_boundary.device)
        identity=identity.expand(*old_boundary.shape,s,s)
        expanded=[v.unsqueeze(-1).expand(*v.shape,s) for v in (old_boundary,new_boundary,kick)]
        return self.remap(identity,*expanded)

    def collapse_active_mean(self,probability,boundary):
        """Ablation: preserve active mass/mean and every refractory phase mass."""
        n=self.grid_size
        mass=probability[...,:n].sum(-1)
        mean=(probability[...,:n]*self.nodes(boundary)).sum(-1)/mass.clamp(min=1e-30)
        coordinate=((mean-self.lower_bound)/(boundary-self.lower_bound)*n).clamp(0,n-1)
        lo=torch.floor(coordinate).long();hi=(lo+1).clamp(max=n-1)
        fraction=coordinate-lo.to(coordinate.dtype)
        active=probability.new_zeros(*probability.shape[:-1],n)
        active=active.scatter_add(-1,lo.unsqueeze(-1),(mass*(1-fraction)).unsqueeze(-1))
        active=active.scatter_add(-1,hi.unsqueeze(-1),(mass*fraction).unsqueeze(-1))
        return torch.cat((active,probability[...,n:]),dim=-1)

    def readout(self,probability,boundary):
        value=torch.tanh(self.nodes(boundary))
        if self.refractory_phases:
            value=F.pad(value,(0,self.refractory_phases),value=math.tanh(self.reset))
        return (probability*value).sum(dim=-1)



class _RootBoundary(torch.autograd.Function):
    @staticmethod
    def forward(ctx, drift, cost, sigma, discount, refractory):
        import numpy as np
        from scipy.optimize import brentq
        a,c=torch.broadcast_tensors(drift.double(),cost.double())
        gamma=(torch.sqrt(a*a+2*discount*sigma*sigma)-a)/(sigma*sigma)
        values=[]
        for g,cc in zip(gamma.detach().numpy().flat,c.detach().numpy().flat):
            fn=lambda h:g*(h-cc)-1+math.exp(-discount*refractory-g*h)
            values.append(brentq(fn,float(cc),float(cc+1/g),xtol=1e-12,rtol=1e-12))
        h=torch.as_tensor(np.asarray(values).reshape(a.shape),dtype=torch.float64)
        ctx.save_for_backward(a,c,gamma,h)
        ctx.sigma=sigma;ctx.discount=discount;ctx.refractory=refractory
        ctx.drift_dtype=drift.dtype;ctx.cost_dtype=cost.dtype
        ctx.drift_shape=drift.shape;ctx.cost_shape=cost.shape
        return h.to(drift.dtype)

    @staticmethod
    def backward(ctx, grad):
        a,c,g,h=ctx.saved_tensors
        q=torch.exp(-ctx.discount*ctx.refractory-g*h)
        dg=(a/torch.sqrt(a*a+2*ctx.discount*ctx.sigma**2)-1)/ctx.sigma**2
        dh_da=-((h-c)-h*q)*dg/(g*(1-q))
        dh_dc=1/(1-q)
        return (grad.double()*dh_da).sum_to_size(ctx.drift_shape).to(ctx.drift_dtype),(grad.double()*dh_dc).sum_to_size(ctx.cost_shape).to(ctx.cost_dtype),None,None,None


def numerical_control_boundary(drift,cost,sigma=.4,discount=.4,refractory=.1):
    return _RootBoundary.apply(drift,cost,sigma,discount,refractory)
