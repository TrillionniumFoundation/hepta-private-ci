"""Drop-in stationary valuation for HCSN cells, including zero liquidity friction."""
from dataclasses import dataclass
import math
from typing import NamedTuple
import torch
from torch import Tensor,nn
from .equity import curve,normal,cdf_integral

@dataclass(frozen=True)
class StationaryLaw:
    r:float=.08
    payout:float=.02
    sigma:float=.23
    alpha:float=.60
    tax:float=.27
    C:float=6.39
    P0:float=61.68
    m:float=1.
    premium:float=.01

class StationaryChannels(NamedTuple):
    boundary:Tensor
    equity:Tensor
    hit:Tensor
    discounted_hit:Tensor

class StablePublished(nn.Module):
    """FP64 cell operator honoring the existing Published forward-facing methods.

    premium is the nonnegative incremental liquidity yield q-r. Optional tensor
    overrides retain autograd connectivity, including the physical right derivative
    at zero. Margins are log(V/B); the state at or below B is absorbing.
    """
    @torch.inference_mode(False)
    def __init__(self,p=None,validate_args=True):
        super().__init__();self.p=StationaryLaw() if p is None else p;self.validate_args=validate_args
        p=self.p
        fields=(p.r,p.payout,p.sigma,p.alpha,p.tax,p.C,p.P0,p.m,p.premium)
        if not all(math.isfinite(float(x)) for x in fields):raise ValueError('stationary law must be finite')
        if min(p.r,p.payout,p.sigma,p.m,p.P0)<=0:raise ValueError('rate, payout, volatility, maturity and principal must be positive')
        if not 0<=p.alpha<=1 or not 0<=p.tax<1 or min(p.C,p.premium)<0:raise ValueError('require recovery in [0,1], tax in [0,1), coupon and premium nonnegative')
        self.var=p.sigma**2;self.a=(p.r-p.payout-.5*self.var)/self.var;self.mu=self.a*self.var
        self.q=p.r+p.premium;self.z=math.sqrt(self.a**2+2*p.r/self.var);self.zb=math.sqrt(self.a**2+2*self.q/self.var)
        self.eta=self.z-self.a;self.gamma=self.z+self.a;self.c=p.C/p.m;self.disc=math.exp(-self.q*p.m)
        self.register_buffer('_premium',torch.tensor(p.premium,dtype=torch.float64),persistent=False)
        self.register_buffer('basis_y',torch.tensor([self.a,-self.a,self.zb,-self.zb],dtype=torch.float64))
        # The smooth-pasting Green condition is affine in coupon and principal;
        # these two basis values are used only at the fixed construction premium.
        self.bc=float(self._raw(self._premium,0.,0.,coupon=1.)[0])
        self.bp=float(self._raw(self._premium,0.,1.,coupon=0.)[0])
        self.B0=self.bc*p.C+self.bp*p.P0
        if not self.B0>0:raise ValueError('law does not give a positive endogenous boundary')
        width=p.sigma*math.sqrt(p.m)
        self._width=width
        loc=torch.tensor([-self.a,self.a,-self.zb,self.zb],dtype=torch.float64)*width**2
        shifts=torch.tensor([0.,-2*self.a,-self.a+self.zb,-self.a-self.zb],dtype=torch.float64)
        self.register_buffer('_locations',loc,persistent=False)
        self.register_buffer('_shifts',shifts,persistent=False)
        for prefix,root in (('left',self.gamma),('right',-self.eta)):
            kval=shifts+root
            narrow=torch.nonzero(abs(kval)<.025).flatten()
            self.register_buffer('_k_'+prefix,kval,persistent=False)
            self.register_buffer('_small_'+prefix,narrow,persistent=False)
            t0=cdf_integral(kval,loc,torch.tensor(0.,dtype=torch.float64),torch.tensor(width,dtype=torch.float64))
            self.register_buffer('_tails_'+prefix,torch.stack([t0[:2].sum(),t0[2:].sum()]),persistent=False)
        with torch.enable_grad():
            x=torch.tensor(.18,dtype=torch.float64,requires_grad=True)
            e,f=self.values(x,p.P0)
            dE,=torch.autograd.grad(e,x,retain_graph=True)
            dF,=torch.autograd.grad(f,x)
        for name,t in [('A0',e),('F0',f),('dA0',dE),('dF0',dF)]:self.register_buffer(name,t.detach())
    def _tensor(self,val):
        if isinstance(val,Tensor) and val.device!=self._premium.device:
            raise ValueError('move the module and tensor arguments to the same device')
        return torch.as_tensor(val,dtype=torch.float64,device=self._premium.device)
    def _require(self,valid,why):
        if self.validate_args and not bool(torch.all(valid)):raise ValueError(why)
    def _raw(self,q,x,principal,coupon=None):
        p=self.p
        return curve(q,x,volatility=p.sigma,maturity=p.m,rate=p.r,payout=p.payout,
             recovery=p.alpha,tax=p.tax,coupon=p.C if coupon is None else coupon,principal=principal)
    def _arguments(self,x,P,premium):
        q=self._premium if premium is None else self._tensor(premium)
        q,x,P=torch.broadcast_tensors(q,self._tensor(x),self._tensor(P))
        self._require(torch.isfinite(q)&(q>=0),'incremental liquidity yield must be finite and nonnegative')
        self._require(torch.isfinite(P)&(P>0),'principal must be finite and positive')
        self._require(torch.isfinite(x),'log margin must be finite')
        return q,x,P
    def boundary(self,P,*,premium=None):
        q,zero,P=self._arguments(0.,P,premium)
        return self.bc*self.p.C+self.bp*P if premium is None else self._raw(q,zero,P)[0]
    def _fixed_tail(self,x,side):
        k=getattr(self,'_k_'+side);tiny=getattr(self,'_small_'+side)
        loc=self._locations;width=self._width;xx=x[...,None];z=(loc-xx)/width
        kk=torch.where(abs(k)<.025,torch.ones_like(k),k)
        log_b=kk*xx+torch.special.log_ndtr(z)
        log_a=kk*loc+.5*(kk*width).square()+torch.special.log_ndtr(z+kk*width)
        tail=torch.exp(log_b)*torch.expm1(log_a-log_b)/kk
        if tiny.numel():
            exact=cdf_integral(k[tiny],loc[tiny],xx,torch.as_tensor(width,dtype=xx.dtype,device=xx.device))
            tail=torch.index_copy(tail,-1,tiny,exact)
        return tail[...,:2].sum(-1),tail[...,2:].sum(-1)
    def _fixed_channels(self,x,P):
        p=self.p;xx=x.clamp_min(0.);B=self.bc*p.C+self.bp*P
        gap=P/p.m-self.c/self.q;fixed=-(1-p.tax)*p.C+math.expm1(-self.q*p.m)*gap
        fc=-self.disc*gap;gc=p.alpha*B/p.m-self.c/self.q;lf,lg=self._fixed_tail(xx,'left')
        rf,rg=self._fixed_tail(xx,'right');gamma=self.gamma;eta=self.eta
        left=p.payout*B*torch.expm1((gamma+1)*xx)/(gamma+1)+fixed*torch.expm1(gamma*xx)/gamma
        left=left+fc*(self._tails_left[0]-lf)+gc*(self._tails_left[1]-lg)
        right=p.payout*B*torch.exp((1-eta)*xx)/(eta-1)+fixed*torch.exp(-eta*xx)/eta+fc*rf+gc*rg
        right0=p.payout*B/(eta-1)+fixed/eta+fc*self._tails_right[0]+gc*self._tails_right[1]
        equity=(torch.exp(-gamma*xx)*(left-right0)+torch.exp(eta*xx)*right)/(self.z*self.var)
        mat=xx[...,None]
        atom=torch.exp(self._shifts*mat+torch.special.log_ndtr((self._locations-mat)/self._width))
        return StationaryChannels(B,torch.where(x>0,equity,torch.zeros_like(x)),
              torch.where(x>0,atom[...,:2].sum(-1),torch.ones_like(x)),
              torch.where(x>0,atom[...,2:].sum(-1),torch.ones_like(x)))
    def channels(self,x,P,*,premium=None):
        q,x,P=self._arguments(x,P,premium)
        if premium is None:return self._fixed_channels(x,P)
        return StationaryChannels(*self._raw(q,x,P))
    def values(self,x,P,*,premium=None):
        c=self.channels(x,P,premium=premium)
        return c.equity,c.hit
    def equity(self,x,P,*,premium=None):
        return self.channels(x,P,premium=premium).equity
    def passage(self,x,t):
        x,t=torch.broadcast_tensors(self._tensor(x),self._tensor(t))
        self._require(torch.isfinite(x)&torch.isfinite(t)&(t>0),'horizon must be positive and inputs finite')
        xx=x.clamp_min(0.);s=self.p.sigma*torch.sqrt(t)
        f=normal((-xx-self.mu*t)/s)+torch.exp(-2*self.basis_y[0]*xx+torch.special.log_ndtr((-xx+self.mu*t)/s))
        return torch.where(x>0,f,torch.ones_like(x))
    def move_mean(self,x,dt=.25,reset=.30):
        x,dt,reset=torch.broadcast_tensors(self._tensor(x),self._tensor(dt),self._tensor(reset))
        self._require(torch.isfinite(x)&torch.isfinite(dt)&(dt>0)&torch.isfinite(reset)&(reset>=0),'require finite state, positive step and nonnegative reset')
        xx=x.clamp_min(0.);sd=self.p.sigma*torch.sqrt(dt)
        def positive_mean(m):
            t=m/sd
            return m*normal(t)+sd*torch.exp(-.5*t*t)/math.sqrt(2*math.pi)
        alive=positive_mean(xx+self.mu*dt)-torch.exp(-2*self.basis_y[0]*xx)*positive_mean(-xx+self.mu*dt)
        return torch.where(x>0,alive+reset*self.passage(xx,dt),reset)
    def forward(self,x,P,*,premium=None):
        return self.values(x,P,premium=premium)

def replace_published(cell,*,validate_args=True):
    """Replace only the exact stationary law of an existing LiteralCell in-place.

    Recompute law reference buffers. Cell weights, recurrent tensors and training
    mode are preserved. Load the existing checkpoint before calling this function.
    """
    old=cell.law;model=StablePublished(old.p,validate_args=validate_args)
    model.to(device=old.A0.device);model.train(old.training);cell.law=model
    return cell
