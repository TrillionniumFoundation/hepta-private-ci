"""A killed drifted Brownian transition on the registered four-atom physical grid."""
import numpy as np
import torch

SIGMA=.23
DT=.25
MU=.08-.02-.23**2/2
def log_ndtr(x):
    return torch.special.log_ndtr(torch.as_tensor(x,dtype=torch.float64)).numpy()

NODES=4097
BOUND=5.

def table(grid):
    x=np.asarray(grid,dtype=float)[None,:,None]
    d=np.linspace(-BOUND,BOUND,NODES)[:,None,None]
    threshold=np.r_[0.,.5*(x.ravel()[:-1]+x.ravel()[1:])][None,None,:]
    scale=SIGMA*np.sqrt(DT)
    l0=log_ndtr((x+d*DT-threshold)/scale)
    l1=-2*d*x/SIGMA**2+log_ndtr((-x+d*DT-threshold)/scale)
    tail=np.exp(l0)*(-np.expm1(np.minimum(0.,l1-l0)))
    live=np.concatenate((tail[:,:,:-1]-tail[:,:,1:],tail[:,:,-1:]),-1)
    hit=np.exp(log_ndtr((-x-d*DT)/scale))+np.exp(-2*d*x/SIGMA**2+log_ndtr((-x+d*DT)/scale))
    result=np.concatenate((live,hit),-1)
    if np.min(result)<-1e-13 or np.max(abs(result.sum(-1)-1))>5e-12:raise ValueError("invalid mass kernel")
    return result.clip(0.,1.)

def transport(values,drift):
    # All drives and bounded gains give a relative drift strictly inside [-5,5].
    coord=(drift+BOUND)*((NODES-1)/(2*BOUND))
    i=coord.long().clamp(0,NODES-2)
    return torch.lerp(values[i],values[i+1],(coord-i)[...,None,None])

def signed_term(arm,w,mass,ref,quotes,grid,reset):
    xstar=(grid*reset).sum()
    alive=mass.sum(-1)
    mx=(mass*grid).sum(-1)
    mean=torch.where(alive>0,mx/torch.where(alive>0,alive,1.),xstar)
    if arm=="nonfinancial":
        signals=torch.stack(((mx/xstar).tanh(),ref.tanh()),-1)
    else:
        signals=quotes.clamp_min(0.).tanh()
    if arm=="free":
        gains=1.3*torch.tanh(.5493061443340548+w/3)
    else:
        gains=1.3*torch.sigmoid(w)
    force=gains[:,0]*signals[...,0]*(xstar-mean)-gains[:,1]*signals[...,1]
    return force if arm!="noforce" else force*0.
