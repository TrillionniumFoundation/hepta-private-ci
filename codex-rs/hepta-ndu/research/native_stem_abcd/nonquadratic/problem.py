"""R5: bounded nonlinear forward policies, quartic tasks, entropic recursion."""
from dataclasses import dataclass, replace
from itertools import product
import numpy as np
import torch

DT = torch.float64

@dataclass(frozen=True)
class Problem:
    A: np.ndarray
    B: np.ndarray
    noise: np.ndarray
    branch: np.ndarray
    readouts: np.ndarray
    weights: np.ndarray
    target: np.ndarray
    action_cost: np.ndarray
    gamma: float = .93
    eta: float = .4
    quartic: float = .8
    state_cost: float = .04
    bound: float = 2.5
    horizon: int = 3

    def tensors(self):
        return {k: torch.tensor(getattr(self, k), dtype=DT) for k in
                ('A','B','noise','branch','readouts','weights','target','action_cost')}


def make_problem(change='base'):
    p = Problem(np.array([[.62,.23],[-.18,.71]]), np.array([[1.,.12],[-.08,.9]]),
                np.array([[.09,-.04],[-.05,.08]]), np.array([[.7,.3],[.35,.65]]),
                np.array([[1.,0.],[0.,1.],[.65,-.75]]),
                np.array([[1.,.6,1.2],[.5,1.4,.8]]),
                np.array([[1.1,.55],[-.45,.85]]),np.array([.22,.35]))
    if change=='base': return p
    if change=='risk': return replace(p,eta=0.)
    if change=='quartic': return replace(p,quartic=1.6)
    if change=='dynamics': return replace(p,A=p.A+np.array([[.12,-.08],[.06,.09]]))
    if change=='noise': return replace(p,noise=p.noise*3)
    if change=='horizon': return replace(p,horizon=4)
    raise ValueError('unknown intervention')


def initial(split='train'):
    if split=='train':
        s=np.array(list(product((-.8,.8),repeat=4)));s[:,:2]*=.3125
    elif split in ('new','scale','correlated'):
        s=np.random.default_rng(2026101451).uniform(-.8,.8,(12,4));s[:,:2]*=.3125
        if split=='scale':s*=2
        if split=='correlated':s[:,:2]+=.6*s[:,2:]
    else: raise ValueError('unknown initial distribution')
    return s


def target_np(x,p):
    return x@p.target.T + .18*np.column_stack((x[:,0]*x[:,1],np.sin(x[:,0]+x[:,1])))


def target_torch(x,w):
    return x@w['target'].T+.18*torch.stack((x[:,0]*x[:,1],torch.sin(x[:,0]+x[:,1])),-1)


def initial_weights(seed=11, family='nonlinear'):
    rng=np.random.default_rng(seed)
    if family=='scalar':return rng.normal(0,.03,6)
    K=rng.normal(0,.03,48)
    if family=='matrix':return K
    if family!='nonlinear':raise ValueError('family')
    return np.r_[K,rng.normal(0,.3,16),rng.normal(0,.03,4),rng.normal(0,.06,8),np.zeros(2)]


def unpack(theta,family):
    if family=='scalar':
        eye=torch.eye(2,dtype=DT)
        return theta.reshape(3,2,1,1)*torch.cat((-eye,eye),-1),None,None,None,None
    K=theta[:48].reshape(3,2,2,4)
    if family=='matrix':return K,None,None,None,None
    return K,theta[48:64].reshape(4,4),theta[64:68],theta[68:76].reshape(2,4),theta[76:78]


def control(theta,s,mode,k,p,family):
    K,W,b,V,c=unpack(theta,family)
    raw=torch.einsum('bij,bj->bi',K[k%3,mode],s)
    z=None
    if W is not None:
        z=torch.tanh(s@W.T+b);raw=raw+z@V.T+c
    u=p.bound*torch.tanh(raw/p.bound)
    return u,z


def rollout(theta,p,states,family='nonlinear',policy=None):
    """One exact full binary scenario tree for every initial state/regime."""
    w=p.tensors();s=torch.tensor(np.repeat(states,2,axis=0),dtype=DT)
    h,x=s[:,:2],s[:,2:];mode=torch.tensor(np.tile([0,1],len(states)))
    levels=[];mass=torch.ones(len(s),dtype=DT)
    for k in range(p.horizon):
        sx=torch.cat((h,x),-1)
        u,z=control(theta,sx,mode,k,p,family) if policy is None else (policy(sx,mode,k,p.bound),None)
        stage=.5*p.state_cost*h.square().sum(-1)+.5*w['action_cost'][mode]*u.square().sum(-1)
        levels.append(dict(s=sx,h=h,x=x,mode=mode,u=u,z=z,cost=stage,mass=mass))
        mean=h@w['A'].T+u@w['B'].T
        h=torch.stack((mean-w['noise'][mode],mean+w['noise'][mode]),1).reshape(-1,2)
        mass=(mass[:,None]*w['branch'][mode]).reshape(-1)
        x=x.repeat_interleave(2,0);mode=torch.tensor([0,1]).repeat(len(mean))
    e=h-target_torch(x,w);r=e@w['readouts'].T;a=w['weights'][mode]
    value=(a*(.5*r.square()+.25*p.quartic*r.pow(4))).sum(-1)
    terminal_grad=(a*(r+p.quartic*r.pow(3)))@w['readouts']
    terminal=dict(h=h,x=x,mode=mode,mass=mass,errors=r,value=value)
    tilts=[]
    for L in reversed(levels):
        v=value.reshape(-1,2);prob=w['branch'][L['mode']]
        if p.eta==0:
            tilt=prob;ce=(prob*v).sum(-1)
        else:
            logs=torch.log(prob)+p.eta*v;tilt=torch.softmax(logs,-1)
            ce=torch.logsumexp(logs,-1)/p.eta
        value=L['cost']+p.gamma*ce;tilts.append(tilt)
    return value,levels,list(reversed(tilts)),terminal,terminal_grad


def objective(theta,p,states,family='nonlinear'):
    return rollout(theta,p,states,family)[0].mean()


def adjoint(theta,p,states,family='nonlinear'):
    """Explicit population costate / recursive-risk adjoint, no autograd.grad.

    Local costate includes the derivative of downstream feedback with respect
    to h. Shared-parameter credit is weighted by risk-tilted reach, not physical
    branch probability. This is the same scalar objective as ordinary AD.
    """
    if p.horizon!=3:raise ValueError('fitting uses three layers')
    value,levels,tilts,terminal,lam=rollout(theta,p,states,family)
    w=p.tensors();K,W,b,V,c=unpack(theta,family)
    deltas=[]
    for k in reversed(range(3)):
        L=levels[k];expected=(tilts[k][...,None]*lam.reshape(-1,2,2)).sum(1)
        du=w['action_cost'][L['mode'],None]*L['u']+p.gamma*expected@w['B']
        draw=du*(1-(L['u']/p.bound).square())
        dh=torch.einsum('bi,bij->bj',draw,K[k,L['mode'],:,:2])
        if W is not None:
            hidden=(draw@V)*(1-L['z'].square());dh=dh+hidden@W[:,:2]
        lam=p.state_cost*L['h']+p.gamma*expected@w['A']+dh
        deltas.append(draw)
    deltas=list(reversed(deltas));alpha=torch.full_like(value,1/value.numel());gK=[]
    gW=torch.zeros((4,4),dtype=DT);gb=torch.zeros(4,dtype=DT)
    gV=torch.zeros((2,4),dtype=DT);gc=torch.zeros(2,dtype=DT)
    for k,L in enumerate(levels):
        d=deltas[k]*alpha[:,None]
        gK.append(torch.stack([torch.einsum('bi,bj->ij',d*(L['mode']==m)[:,None],L['s']) for m in (0,1)]))
        if W is not None:
            hidden=(d@V)*(1-L['z'].square());gW=gW+hidden.T@L['s'];gb=gb+hidden.sum(0)
            gV=gV+d.T@L['z'];gc=gc+d.sum(0)
        alpha=(p.gamma*alpha[:,None]*tilts[k]).reshape(-1)
    kg=torch.stack(gK)
    if family=='scalar':
        eye=torch.eye(2,dtype=DT);g=(kg*torch.cat((-eye,eye),-1)).sum((-1,-2)).flatten()
    elif family=='matrix':g=kg.flatten()
    else:g=torch.cat((kg.flatten(),gW.flatten(),gb,gV.flatten(),gc))
    return value.mean(),g
