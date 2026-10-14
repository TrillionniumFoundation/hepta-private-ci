"""R4: exact finite-law, preference-modulated shared representation control.

The quadratic conditional-cost profile is a restricted NDU special case, not
an arbitrary nonlinear recursive utility or a continuous-time FBSDE theorem.
"""
from dataclasses import dataclass
from itertools import product
import numpy as np
import torch
from torch import nn

DT = torch.float64


@dataclass(frozen=True)
class Problem:
    F: np.ndarray
    G: np.ndarray
    Q: np.ndarray
    R: np.ndarray
    terminal: np.ndarray
    transition: np.ndarray
    noise: np.ndarray
    target: np.ndarray
    readouts: np.ndarray
    gamma: float = 0.93
    horizon: int = 3

    def tensors(self):
        return {name: torch.tensor(getattr(self, name), dtype=DT) for name in
                ('F', 'G', 'Q', 'R', 'terminal', 'transition', 'noise', 'target', 'readouts')}


def make_problem(change='base'):
    a = np.array([[.62, .19, -.07], [-.13, .70, .17], [.08, -.16, .66]])
    if change == 'dynamics':
        a += np.array([[.12, -.10, .05], [.08, -.06, -.10], [0., .09, .11]])
    F = np.block([[a, np.zeros((3, 3))], [np.zeros((3, 3)), np.eye(3)]])
    G = np.vstack((np.eye(3), np.zeros((3, 3))))
    target = np.array([[1.10, .55, -.30], [-.45, .80, .40], [.25, -.60, 1.05]])
    readouts = np.array([[1.,0.,0.], [0.,1.,0.], [0.,0.,1.], [.6,-.8,.3], [-.4,.2,.9]])
    q, r, terminal = [], [], []
    error_map = np.column_stack((np.eye(3), -target))
    for mode, weights in enumerate(([1.,.4,1.5,.8,1.2], [.5,1.8,.7,1.4,.6])):
        W = readouts.T @ np.diag(weights) @ readouts
        terminal.append(error_map.T @ W @ error_map)
        q.append(np.diag([.02+.02*mode, .035, .025-.01*mode, 0., 0., 0.]))
        rr = np.array([[.19,.035,-.01],[.035,.27,.025],[-.01,.025,.23]])
        r.append(rr + mode*np.diag([.12,-.05,.08]))
    transition = np.array([[.72,.28],[.31,.69]])
    if change == 'preference': transition = np.array([[.35,.65],[.8,.2]])
    noise = np.array([[.06,-.035,.045,0.,0.,0.],[-.04,.07,.03,0.,0.,0.]])
    if change == 'noise': noise *= 3
    if change not in ('base','dynamics','preference','noise','horizon'):
        raise ValueError('unknown intervention')
    return Problem(F,G,np.array(q),np.array(r),np.array(terminal),transition,noise,
                   target,readouts,horizon=4 if change=='horizon' else 3)


def initial_states(split='train'):
    if split == 'train':
        states = np.array(list(product((-1.,1.), repeat=6)))
        states[:, :3] *= .25
    elif split in ('new','scale','correlated'):
        rng = np.random.default_rng(2026101441)
        states = rng.uniform(-1.,1.,(24,6))
        states[:,:3] *= .25
        if split == 'scale': states *= 3
        if split == 'correlated': states[:,:3] += .6*states[:,3:]
    else:
        raise ValueError('unknown state law')
    return states


def initial_moments(states):
    s = torch.as_tensor(states,dtype=DT)
    second = s.T @ s / len(s)
    return torch.stack((.5*second,.5*second))


class MatrixStem(nn.Module):
    """108 actual transition-control weights, shared over all inputs and readouts."""
    def __init__(self,seed=11,family='matrix'):
        super().__init__()
        if family not in ('matrix','scalar','diagonal'): raise ValueError('family')
        self.family=family
        shape={'matrix':(3,2,3,6),'scalar':(3,2,1),'diagonal':(3,2,3,2)}[family]
        rng=np.random.default_rng(seed)
        self.weights=nn.Parameter(torch.tensor(rng.normal(0,.04,shape),dtype=DT))

    def gains(self,weights=None):
        w=self.weights if weights is None else weights
        if self.family=='matrix': return w
        eye=torch.eye(3,dtype=DT)
        if self.family=='scalar': return w[...,None]*torch.cat((-eye,eye),dim=-1)
        return torch.cat((torch.diag_embed(w[...,0]),torch.diag_embed(w[...,1])),dim=-1)

    def forward(self,s,mode,time):
        return torch.einsum('bij,bj->bi',self.gains()[time%3,mode],s)


class AttentionStem(nn.Module):
    """From-scratch attention acting on (h,x), not a matrix-label generator."""
    def __init__(self,seed=11):
        super().__init__()
        with torch.random.fork_rng():
            torch.manual_seed(seed)
            self.embed=nn.Linear(6,8)
            self.attention=nn.TransformerEncoderLayer(8,2,16,dropout=0.,batch_first=True,
                                                      norm_first=True,activation='gelu')
            self.out=nn.Linear(8,3)
            with torch.no_grad(): self.out.weight.mul_(.1);self.out.bias.zero_()
        self.double()

    def forward(self,s,mode,time):
        batch=len(s)
        context=torch.stack((mode.to(DT),torch.full((batch,),float(time%3)/2,dtype=DT)),dim=-1)
        first=torch.cat((s[:,:3],context,torch.zeros((batch,1),dtype=DT)),dim=-1)
        second=torch.cat((s[:,3:],context,torch.ones((batch,1),dtype=DT)),dim=-1)
        encoded=self.embed(torch.stack((first,second),dim=1))
        return self.out(self.attention(encoded)[:,0])


def policy_value(gains,w,gamma,horizon):
    """Backward value/costate matrices for a FIXED policy, no minimization/oracle."""
    Ps=[w['terminal']]; cs=[torch.zeros(2,dtype=DT)];Es=[]
    for k in reversed(range(horizon)):
        K=gains[k%3]; A=w['F']+w['G']@K
        bar=torch.einsum('ij,jab->iab',w['transition'],Ps[-1])
        P=w['Q']+K.transpose(-1,-2)@w['R']@K+gamma*A.transpose(-1,-2)@bar@A
        c=gamma*(w['transition']@cs[-1]+torch.einsum('ia,iab,ib->i',w['noise'],bar,w['noise']))
        E=w['R']@K+gamma*w['G'].T@bar@A
        Ps.append(P);cs.append(c);Es.append(E)
    return list(reversed(Ps)),list(reversed(cs)),list(reversed(Es))


def objective(model,problem,states):
    if isinstance(model,AttentionStem):
        return enumerate_policy(model,problem,states)['cost'].mean()
    P,c,_=policy_value(model.gains(),problem.tensors(),problem.gamma,problem.horizon)
    return (P[0]*initial_moments(states)).sum()+c[0].mean()


def stationarity(model,problem,weights):
    """E=R K+gamma G' Pbar Acl. Equivalent to population gradient=0 if M>0."""
    gains=model.gains(weights)
    _,_,E=policy_value(gains,problem.tensors(),problem.gamma,3)
    E=torch.stack(E)
    if model.family=='matrix': return E.reshape(-1)
    # Restricted families require their TRUE population gradient, not unprojected E.
    P,c,_=policy_value(gains,problem.tensors(),problem.gamma,3)
    return ((P[0]*initial_moments(initial_states())).sum()+c[0].mean())


def moment_gradient(model,problem,states):
    """Independent forward occupancy x backward costate formula for all gains."""
    w=problem.tensors();Ks=model.gains();_,_,Es=policy_value(Ks,w,problem.gamma,3)
    M=initial_moments(states); mass=torch.tensor([.5,.5],dtype=DT);gradient=[];moments=[]
    for k in range(3):
        moments.append(M)
        gradient.append(2*problem.gamma**k*Es[k]@M)
        A=w['F']+w['G']@Ks[k]
        N=w['noise'].unsqueeze(-1)@w['noise'].unsqueeze(-2)
        before=A@M@A.transpose(-1,-2)+mass[:,None,None]*N
        M=torch.einsum('ij,iab->jab',w['transition'],before)
        mass=mass@w['transition']
    return torch.stack(gradient),torch.stack(moments)


def enumerate_policy(model,problem,states,gains=None):
    """Entire finite scenario tree: no sampling, detached dynamics or value targets."""
    w=problem.tensors();n=len(states)*2
    s=torch.as_tensor(np.repeat(states,2,axis=0),dtype=DT)
    mode=torch.tensor(np.tile([0,1],len(states)),dtype=torch.long)
    origin=torch.arange(n);prob=torch.ones(n,dtype=DT);cost=torch.zeros(n,dtype=DT)
    for k in range(problem.horizon):
        u=model(s,mode,k) if gains is None else torch.einsum('bij,bj->bi',gains[k%len(gains),mode],s)
        cost=cost+problem.gamma**k*(torch.einsum('bi,bij,bj->b',s,w['Q'][mode],s)+
                                     torch.einsum('bi,bij,bj->b',u,w['R'][mode],u))
        mean=s@w['F'].T+u@w['G'].T
        noise=w['noise'][mode]
        s=torch.stack((mean-noise,mean+noise,mean-noise,mean+noise),dim=1).reshape(-1,6)
        prob=(prob[:,None]*torch.stack((w['transition'][mode,0]/2,w['transition'][mode,0]/2,
                                       w['transition'][mode,1]/2,w['transition'][mode,1]/2),dim=1)).reshape(-1)
        mode=torch.tensor([0,0,1,1],dtype=torch.long).repeat(len(mean))
        cost=cost.repeat_interleave(4);origin=origin.repeat_interleave(4)
    cost=cost+problem.gamma**problem.horizon*torch.einsum('bi,bij,bj->b',s,w['terminal'][mode],s)
    per_initial=torch.zeros(n,dtype=DT).scatter_add(0,origin,prob*cost)
    return dict(cost=per_initial,states=s,prob=prob,origin=origin,path_cost=cost,mode=mode)


def riccati(problem):
    """Independent NumPy Bellman minimization; never used in any fitted arm."""
    P=problem.terminal.copy();c=np.zeros(2);gains=[];hessians=[]
    for _ in range(problem.horizon):
        bar=np.einsum('ij,jab->iab',problem.transition,P)
        H=problem.R+problem.gamma*problem.G.T@bar@problem.G
        K=-np.linalg.solve(H,problem.gamma*problem.G.T@bar@problem.F)
        A=problem.F+problem.G@K
        c=problem.gamma*(problem.transition@c+np.einsum('ia,iab,ib->i',problem.noise,bar,problem.noise))
        P=problem.Q+np.swapaxes(K,-1,-2)@problem.R@K+problem.gamma*np.swapaxes(A,-1,-2)@bar@A
        gains.append(K);hessians.append(H)
    return np.array(gains[::-1]),P,c,np.array(hessians[::-1])


def scalar_lower_bound(problem):
    """Performance-difference lower bound using only the initial decision."""
    K,_,_,H=riccati(problem);S=initial_states().T@initial_states()/len(initial_states())
    L=np.column_stack((-np.eye(3),np.eye(3)));parts=[];best=[]
    for p in range(2):
        alpha=np.trace(H[0,p]@K[0,p]@S@L.T)/np.trace(H[0,p]@L@S@L.T)
        D=alpha*L-K[0,p];parts.append(.5*np.trace(H[0,p]@D@S@D.T));best.append(alpha)
    return dict(objective_gap_lower_bound=float(sum(parts)),best_first_slopes=best,
                interval_certified=False,scope='all per-time/per-mode scalar policies u=alpha*(x-h)')
