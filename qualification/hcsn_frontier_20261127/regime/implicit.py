"""Differentiable equilibria and two-channel outputs of the reduced Markov-modulated cell."""
import torch
from torch import nn
from torch.nn import functional as F
from stopping import Continuation,Model

def terms(parameters):
    cheap,dear,up,down=parameters.unbind()
    r=.08;d=.02;sigma=.23
    mu=r-d-.5*sigma**2
    def motion(q):
        q=parameters.new_tensor(q) if not torch.is_tensor(q) else q
        delta=(mu**2+2*sigma**2*q).sqrt()
        return torch.stack([(-mu+delta)/sigma**2,(-mu-delta)/sigma**2])
    c=torch.linalg.solve(torch.stack([torch.stack([r+up,-up]),torch.stack([-down,r+down])]),parameters[:2])
    mode=torch.stack([up,-down])/(up+down)
    mid=motion(r+up);high=torch.stack([motion(r)[1],motion(r+up+down)[1]])
    return c,mode,mid,high,d/(d+up),cheap/(r+up),motion

def coefficients(bounds,parameters):
    b0,b1=bounds.unbind();c,mode,n,k,slope,cost,motion=terms(parameters)
    eye=torch.ones_like(n)
    mid=torch.linalg.solve(torch.stack([eye,n]),torch.stack([cost-slope*b0,-slope*b0]))
    top=torch.stack([eye[0],mode[1]])
    high=torch.linalg.solve(torch.stack([top,top*k]),torch.stack([c[1]-b1,-b1]))
    return c,mode,n,k,slope,cost,mid,high,motion

def residual(bounds,parameters):
    b0,b1=bounds.unbind()
    c,mode,n,k,slope,cost,mid,high,_=coefficients(bounds,parameters)
    at=(b1/b0).pow(n)*mid
    high=high*torch.stack([torch.ones_like(b0),mode[0]])
    return torch.stack([slope*b1-cost+at.sum()-(b1-c[0]+high.sum()),slope*b1+(at*n).sum()-(b1+(high*k).sum())])

class ImplicitBoundary(torch.autograd.Function):
    @staticmethod
    def forward(ctx,parameters):
        if parameters.shape!=(4,) or parameters.dtype!=torch.float64:raise ValueError('expected four float64 law coefficients')
        cheap,dear,up,down=parameters.detach().cpu().tolist()
        e=Continuation(Model(cheap=cheap,dear=dear,up=up,down=down))
        bounds=parameters.new_tensor([e.b0,e.b1])
        ctx.save_for_backward(bounds,parameters)
        return bounds
    @staticmethod
    def backward(ctx,grad):
        b,params=ctx.saved_tensors
        with torch.enable_grad():
            b=b.detach().requires_grad_();p=params.detach().requires_grad_()
            jb,jp=torch.autograd.functional.jacobian(residual,(b,p))
            adj=torch.linalg.solve(jb.T,grad)
        return -jp.T@adj

def outputs(v,parameters):
    if (v<=0).any():raise ValueError('assets must be positive')
    bounds=ImplicitBoundary.apply(parameters)
    b0,b1=bounds.unbind();c,mode,n,k,slope,cost,cm,ch,motion=coefficients(bounds,parameters)
    middle=v.clamp(min=b0,max=b1);upper=v.clamp_min(b1)
    at=(middle[...,None]/b0).pow(n)@cm+slope*middle-cost
    hu=(upper[...,None]/b1).pow(k)*ch
    high=upper[...,None]-c+hu[...,:1]+hu[...,1:]*mode
    emid=torch.stack([at,torch.zeros_like(v)],-1)
    equity=torch.where((v>=b1)[...,None],high,torch.where((v>b0)[...,None],emid,torch.zeros_like(high)))
    q=.09;up,down=parameters[-2:].unbind()
    middle_n=motion(q+up);upper_n=torch.stack([motion(q)[1],motion(q+up+down)[1]])
    z=(b1/b0).pow(middle_n)
    one=torch.ones_like(up);zero=torch.zeros_like(up)
    matrix=torch.stack([torch.stack([one,one,zero,zero]),torch.stack([zero,zero,one,mode[1]]),
        torch.cat([z,torch.stack([-one,-mode[0]])]),torch.cat([z*middle_n,torch.stack([-upper_n[0],-mode[0]*upper_n[1]])])])
    constant=up/(q+up)
    hp=torch.linalg.solve(matrix,torch.stack([one-constant,one,-constant,zero]))
    p_middle=constant+(middle[...,None]/b0).pow(middle_n)@hp[:2]
    hu=(upper[...,None]/b1).pow(upper_n)*hp[2:]
    p_high=hu[...,:1]+hu[...,1:]*mode
    p_mid=torch.stack([p_middle,torch.ones_like(v)],-1)
    hit=torch.where((v>=b1)[...,None],p_high,torch.where((v>b0)[...,None],p_mid,torch.ones_like(p_high)))
    return equity,hit,bounds

class RegimeCell(nn.Module):
    """One shared law across input assets. The return exposes both regime-conditional states."""
    def __init__(self,cheap=.04,dear=.08,up=.12,down=.16):
        super().__init__()
        a=torch.tensor([cheap,dear-cheap,up,down],dtype=torch.float64)
        if (a<=0).any():raise ValueError('positive rates with dear > cheap required')
        self.raw=nn.Parameter(a.expm1().log())
    def forward(self,assets):
        c,gap,u,d=F.softplus(self.raw).unbind()
        return outputs(assets,torch.stack([c,c+gap,u,d]))
