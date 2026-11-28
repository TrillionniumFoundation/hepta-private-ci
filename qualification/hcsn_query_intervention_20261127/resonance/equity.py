"""Differentiable stationary He–Xiong Green operator through zero liquidity friction."""
import math
import torch
from torch import Tensor

def normal(z):
    return .5*torch.erfc(-z/math.sqrt(2.))

def cdf_integral(k:Tensor,location:Tensor,x:Tensor,width:Tensor):
    """Tail integral int_x^infty exp(k y) Phi((location-y)/width) dy."""
    z=(location-x)/width
    small=abs(k)*torch.maximum(torch.ones_like(x),abs(x)+abs(location)+width) < .025
    safe=torch.where(small,torch.ones_like(k),k)
    log_a=safe*location+.5*safe.square()*width.square()+torch.special.log_ndtr(z+safe*width)
    log_b=safe*x+torch.special.log_ndtr(z)
    divided=torch.exp(log_b)*torch.expm1(log_a-log_b)/safe
    probability=normal(z);edge=width*torch.exp(-.5*z.square())/math.sqrt(2*math.pi)
    prev=probability;moment=location*prev+edge
    total=moment-x*probability
    power=torch.ones_like(x);factor=1.
    for order in range(1,7):
        higher=location*moment+order*width.square()*prev+x.pow(order)*edge
        prev,moment=moment,higher
        power=power*k;factor*=order
        total=total+power/factor*(higher-x.pow(order+1)*probability)/(order+1)
    return torch.where(small,total,divided)

def curve(prem,margin,volatility=.23,maturity=1.,rate=.08,payout=.02,
          recovery=.60,tax=.27,coupon=6.39,principal=61.68):
    """Return endogenous B, equity, hit probability and discounted hit mass.

    prem is incremental liquidity yield q-r. The margin is log(V/B).
    The financial domain has prem>=0, volatility>0, maturity>0 and 0<payout<rate.
    Inputs use float64 on a common device. Tensor arguments support autograd.
    """
    def local(v):
        return torch.as_tensor(v,dtype=torch.float64,device=prem.device)
    prem,x,s,m=torch.broadcast_tensors(prem.to(torch.float64),local(margin),local(volatility),local(maturity))
    live=torch.clamp_min(x,0.);v=s.square();width=s*torch.sqrt(m);q=rate+prem
    a=(rate-payout-.5*v)/v
    z=torch.sqrt(a.square()+2*rate/v);zq=torch.sqrt(a.square()+2*q/v)
    eta=z-a;gamma=z+a;c=coupon/m;p=principal/m;gap=p-c/q;disc=torch.exp(-q*m)
    fixed=-(1-tax)*coupon+torch.expm1(-q*m)*gap
    fc=-disc*gap
    loc=torch.stack([-a*v*m,a*v*m,-zq*v*m,zq*v*m],dim=-1)
    shift=torch.stack([torch.zeros_like(a),-2*a,-a+zq,-a-zq],dim=-1)
    def integrals(exponent,at):
        terms=cdf_integral(exponent[...,None]+shift,loc,at[...,None],width[...,None])
        return terms[...,:2].sum(-1),terms[...,2:].sum(-1)
    zero=torch.zeros_like(x);F0,G0=integrals(-eta,zero)
    B=(-fixed/eta-fc*F0+(c/q)*G0)/(payout/(eta-1.)+recovery*G0/m)
    gc=recovery*B/m-c/q
    Fx,Gx=integrals(-eta,live);Fg0,Gg0=integrals(gamma,zero);Fgx,Ggx=integrals(gamma,live)
    Lg=payout*B*torch.expm1((gamma+1)*live)/(gamma+1)+fixed*torch.expm1(gamma*live)/gamma
    Lg=Lg+fc*(Fg0-Fgx)+gc*(Gg0-Ggx)
    Lm=payout*B*torch.exp((1-eta)*live)/(eta-1)+fixed*torch.exp(-eta*live)/eta+fc*Fx+gc*Gx
    Lm0=payout*B/(eta-1)+fixed/eta+fc*F0+gc*G0
    E=(torch.exp(-gamma*live)*(Lg-Lm0)+torch.exp(eta*live)*Lm)/(z*v)
    xq=live[...,None]
    weights=torch.stack([torch.zeros_like(a),-2*a,-a+zq,-a-zq],-1)
    atom=torch.exp(weights*xq+torch.special.log_ndtr((loc-xq)/width[...,None]))
    fv=atom[...,:2].sum(-1);gv=atom[...,2:].sum(-1)
    return B,torch.where(x>0,E,zero),torch.where(x>0,fv,torch.ones_like(x)),torch.where(x>0,gv,torch.ones_like(x))
