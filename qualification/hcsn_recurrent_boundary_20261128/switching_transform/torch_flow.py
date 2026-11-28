"""Batched differentiable two-state transform; inputs are double-precision tensors."""
from math import comb
import torch


def value(assets, time, walls, rates, premia, sigma, *, bond=False,
          r=.08, payout=.02, coupon=6.39, principal=61.68, maturity=1., recovery=.6,
          width=24., terms=34, smooth=30):
    if (assets<=0).any() or (walls<=0).any() or time<=0 or sigma<=0:
        raise ValueError("Positive assets, walls, noise and horizon required")
    if (rates<0).any():raise ValueError("Nonnegative switching rates required")
    dev=assets.device
    order=torch.argsort(walls)
    w=walls[order]; jump=rates[order]
    q=premia[order]+r if bond else torch.zeros_like(w)
    k=torch.arange(terms+smooth+1,dtype=torch.float64,device=dev)
    s=torch.complex(torch.full_like(k,width/2),torch.pi*k)/time
    I=torch.eye(2,dtype=s.dtype,device=dev)
    off=torch.stack((torch.stack((jump[0],-jump[0])),torch.stack((-jump[1],jump[1]))))
    M=s[:,None,None]*I+torch.diag(q)+off
    D=sigma.square()/2; mu=r-payout-D
    force=(principal/maturity+coupon/(maturity*s) if bond else torch.zeros_like(s))
    one_over_s=1/s
    g0=torch.zeros_like(s) if bond else one_over_s
    gv=recovery*one_over_s/maturity if bond else torch.zeros_like(s)
    far=torch.linalg.solve(M,force[:,None,None].expand(-1,2,1)).squeeze(-1)
    H=mu.square()*I+4*D*M
    det_root=torch.sqrt(torch.linalg.det(H))
    sqrtH=(H+det_root[:,None,None]*I)/torch.sqrt(H.diagonal(dim1=-2,dim2=-1).sum(-1)+2*det_root)[:,None,None]
    K=(-mu*I-sqrtH)/(2*D)
    strip=torch.log(w[1]/w[0])
    kappa=s+q[0]+jump[0]
    rad=torch.sqrt(mu.square()+4*D*kappa)
    pos=(-mu+rad)/(2*D);neg=(-mu-rad)/(2*D)
    l=torch.exp(-pos*strip);rr=torch.exp(neg*strip)
    slope=jump[0]*gv/(kappa-mu-D)
    const=(force+jump[0]*g0)/kappa
    g=g0+gv*w[1];kh=K[:,0,0]
    matrix=torch.stack((torch.stack((l,torch.ones_like(l)),dim=-1),
                        torch.stack((pos-kh,(neg-kh)*rr),dim=-1)),dim=-2)
    targets=torch.stack((g0+gv*w[0]-(const+slope*w[0]),
                         kh*(const+slope*w[1]-far[:,0])+K[:,0,1]*(g-far[:,1])-slope*w[1]),dim=-1)
    coeff=torch.linalg.solve(matrix,targets.unsqueeze(-1)).squeeze(-1)
    endpoint=torch.stack((const+slope*w[1]+coeff[:,0]+coeff[:,1]*rr,g),dim=-1)
    x=torch.log(assets.reshape(-1)/w[0])
    z=torch.minimum(torch.clamp_min(x,0.),strip)
    in_strip=const+slope*w[0]*torch.exp(z[:,None])+coeff[:,0]*torch.exp(pos*(z[:,None]-strip))+coeff[:,1]*torch.exp(neg*z[:,None])
    immediate=g0+gv*assets.reshape(-1,1)
    # Only propagate to the right of the upper wall to avoid growing exponentials.
    length=torch.clamp_min(x-strip,0.)
    propagator=torch.linalg.matrix_exp(length[:,None,None,None]*K)
    upper=far+(propagator@(endpoint-far)[None,:,:,None]).squeeze(-1)
    strip_value=torch.stack((in_strip,immediate),dim=-1)
    transform=torch.where((x>strip)[:,None,None],upper,
                          torch.where((x>0)[:,None,None],strip_value,immediate[:,:,None]))
    partial=(((-1.)**k)[None,:,None]*transform.real).cumsum(dim=1)-transform.real[:,0:1,:]/2
    weights=torch.tensor([comb(smooth,j)/2**smooth for j in range(smooth+1)],dtype=k.dtype,device=dev)
    result=(partial[:,terms:,:]*weights[None,:,None]).sum(dim=1)*(torch.exp(torch.tensor(width/2,dtype=k.dtype,device=dev))/time)
    stopped=assets.reshape(-1,1)<=w
    exact=(recovery*assets.reshape(-1,1)/maturity if bond else torch.ones_like(result))
    return torch.where(stopped,exact,result)[:,torch.argsort(order)]
