"""Causal six-prefix fitted stopping policies, with source-held-out continuation returns."""
from functools import lru_cache
import hashlib
import numpy as np
import torch
from torch import nn

from qualification.hcsn_qvi_retrieval.dynamics import RetrievalFlow
from qualification.hcsn_qvi_task_surface.model import _IntervalBoundaries

STOP, READ, WAIT = range(3)
PRICE, RHO, RATE = .30, .20, .40
HORIZON = 6
RIDGE_TEACHER = .08


def validate(s):
    n = len(s['target'])
    x, f, p, dt = (np.asarray(s[k]) for k in ('x','scores','read_scores','dt'))
    if (not n or x.ndim != 3 or x.shape[:2] != (n,HORIZON) or x.shape[2] < 1
            or f.shape != (n,HORIZON,2) or p.shape != f.shape or dt.shape != f.shape[:2]
            or not all(np.isfinite(a).all() for a in (x,f,p,dt)) or (dt <= 0).any()
            or not np.array_equal(np.round(dt*1e6),dt*1e6)
            or s['target'].shape != (n,) or not np.isin(s['target'], [0,1]).all()):
        raise ValueError('invalid two-candidate six-prefix arrays')
    for k in ('source','group','query_id'):
        if s[k].shape != (n,) or any(not str(i).strip() for i in s[k]):
            raise ValueError('missing source, group or query identity')
    if len(set(map(str,s['query_id']))) != n:
        raise ValueError('query identities must be unique')


def free_state(x, scores, dt):
    """Only current and earlier free observations, candidate scores, and physical clocks."""
    x, scores, dt = (np.asarray(a,dtype=np.float64) for a in (x,scores,dt))
    prefix = np.arange(1,x.shape[1]+1)[None,:,None]
    gap = scores[...,1:2]-scores[...,0:1]
    previous = np.concatenate((gap[:,:1],gap[:,:-1]),axis=1)
    time = (dt.cumsum(1)-dt[:,:1])[...,None]
    onehot = np.broadcast_to(np.eye(HORIZON)[np.arange(x.shape[1])],(*x.shape[:2],HORIZON))
    return np.concatenate((x,x.cumsum(1)/prefix,scores,gap,abs(gap),gap-previous,
                           abs(gap).cumsum(1)/prefix,time,onehot),-1)


def stop_values(s):
    target = s['target'][:,None]
    return np.stack(((s['scores'].argmax(-1)==target).astype(float),
                     (s['read_scores'].argmax(-1)==target).astype(float)-PRICE),-1)


def fold_ids(s):
    # The connected component construction keeps shared creators and recordings together,
    # even if several source IDs appear under one creator or vice versa.
    parents = {}
    def root(k):
        parents.setdefault(k,k)
        while parents[k] != k:
            parents[k] = k = parents[parents[k]]
        return k
    pairs = [(('g',str(g)),('s',str(r))) for g,r in zip(s['group'],s['source'])]
    for g,r in pairs:
        a,b = root(g),root(r)
        parents[max(a,b)]=min(a,b)
    clusters = {}
    for i,(g,_) in enumerate(pairs):
        clusters.setdefault(root(g),[]).append(i)
    labels = np.asarray(s.get('class_id',s['target'])).astype(str)
    classes = sorted(set(labels))
    per_class = [sum(bool(set(labels[rows]) & {c}) for rows in clusters.values()) for c in classes]
    k = min(5,len(clusters),max(2,min(per_class)))
    if k<2:
        raise ValueError('at least two independent provenance components required')
    counts = np.zeros((k,len(classes)),dtype=int)
    sizes = np.zeros(k,dtype=int)
    order = sorted(clusters,key=lambda key:(-len(clusters[key]),hashlib.sha256(str(key).encode()).hexdigest()))
    assignment = np.empty(len(pairs),dtype=int)
    total = np.array([(labels==c).sum() for c in classes]).clip(min=1)
    for key in order:
        rows = clusters[key]
        hist = np.array([(labels[rows]==c).sum() for c in classes])
        # Greedily minimize total squared imbalance of class fractions and size.
        f = min(range(k),key=lambda j: (np.sum((2*counts[j]*hist+hist**2)/total**2)
                    +(2*sizes[j]*len(rows)+len(rows)**2)/len(labels)**2,sizes[j],j))
        assignment[rows]=f
        counts[f]+=hist
        sizes[f]+=len(rows)
    if set(assignment)!=set(range(k)):
        raise ValueError('empty source fold')
    return assignment


def _regress(z,y,groups):
    _,idx,counts=np.unique(groups,return_inverse=True,return_counts=True)
    w=1/counts[idx]; w=w/w.sum()
    mu=w@z; scale=np.sqrt(w@(z-mu)**2).clip(min=1e-6)
    a=((z-mu)/scale)*np.sqrt(w[:,None]); ym=w@y; y0=(y-ym)*np.sqrt(w[:,None])
    # Pick the smaller exact ridge normal equation for high-dimensional small folds.
    p,n=a.shape[1],len(a)
    if p<=n:
        coef=np.linalg.solve(a.T@a+RIDGE_TEACHER*np.eye(p),a.T@y0)
    else:
        coef=a.T@np.linalg.solve(a@a.T+RIDGE_TEACHER*np.eye(n),y0)
    return dict(mu=mu.tolist(),scale=scale.tolist(),coef=coef.tolist(),bias=ym.tolist(),offset=[0.]*3)


def _forecast(model, z):
    q=(z-np.asarray(model['mu']))/np.asarray(model['scale'])@np.asarray(model['coef'])
    q+=np.asarray(model['bias'])+np.asarray(model['offset'])
    return np.clip(q,[0.,-PRICE,-RATE/RHO-PRICE],[1.,1.-PRICE,1.])


def forecast(models,z):
    return np.stack([_forecast(m,z[:,t]) for t,m in enumerate(models[:z.shape[1]])],1)


def _actions(q,t,can_read):
    q=q.copy()
    if not can_read: q[...,READ]=-np.inf
    if t==HORIZON-1: q[...,WAIT]=-np.inf
    return q.argmax(-1)


def _next_value(future,dt):
    return np.exp(-RHO*dt)*future+RATE*np.expm1(-RHO*dt)/RHO


def fit_teacher(s,can_read):
    """Nested source-excluded least-squares Monte Carlo on realized continuation returns.

    At each WAIT label every later action is chosen before observing its reward, by
    policies fitted without any data from the trajectory's provenance component.
    Thus a maximum over that trajectory's future realized outcomes is never used.
    """
    z=free_state(s['x'],s['scores'],s['dt']); immediate=stop_values(s)
    if not can_read: immediate[:,:,READ]=0.0
    folds=fold_ids(s); all_folds=tuple(sorted(set(folds.tolist())))
    p=z.shape[-1]
    empty=dict(mu=[0.]*p,scale=[1.]*p,coef=[[0.]*3 for _ in range(p)],
               bias=[.5,.5-PRICE,.5],offset=[0.]*3)

    @lru_cache(None)
    def model(allowed,t):
        if not allowed: return empty
        ids=np.flatnonzero(np.isin(folds,allowed))
        y=target_rows(allowed,ids,t)
        m=_regress(z[ids,t],y,s['group'][ids])
        # Offset calibration uses held-source predictions only. Four identity-prior
        # pseudo-observations shrink the correction in small provenance folds.
        oof=np.empty_like(y)
        for f in allowed:
            mask=folds[ids]==f
            reduced=tuple(v for v in allowed if v!=f)
            oof[mask]=_forecast(model(reduced,t),z[ids[mask],t])
        group=s['group'][ids]; residual=y-oof
        by_group=np.asarray([residual[group==g].mean(0) for g in np.unique(group)])
        m['offset']=(by_group.sum(0)/(len(by_group)+4)).tolist() if len(allowed)>1 else [0.]*3
        return m

    def rollout(allowed,rows,t):
        value=None
        for j in reversed(range(t,HORIZON)):
            action=_actions(_forecast(model(allowed,j),z[rows,j]),j,can_read)
            result=immediate[rows,j,np.minimum(action,READ)]
            if value is not None:
                result=np.where(action==WAIT,_next_value(value,s['dt'][rows,j+1]),result)
            value=result
        return value

    def target_rows(allowed,rows,t):
        q=np.empty((len(rows),3)); q[:,:2]=immediate[rows,t]
        if t==HORIZON-1:
            q[:,WAIT]=q[:,STOP]
        else:
            for f in allowed:
                mask=folds[rows]==f; ids=rows[mask]
                reduced=tuple(v for v in allowed if v!=f)
                q[mask,WAIT]=_next_value(rollout(reduced,ids,t+1),s['dt'][ids,t+1])
        return q

    n=len(folds); all_rows=np.arange(n)
    targets=np.stack([target_rows(all_folds,all_rows,t) for t in range(HORIZON)],1)
    held=np.empty_like(targets)
    for f in all_folds:
        reduced=tuple(v for v in all_folds if v!=f); ids=np.flatnonzero(folds==f)
        held[ids]=forecast([model(reduced,t) for t in range(HORIZON)],z[ids])
    return dict(models=[model(all_folds,t) for t in range(HORIZON)],fold_ids=folds.tolist(),
                targets=targets,held=held,calibration_oof_mean_residual=(targets-held).mean(0).tolist(),
                teacher_submodels=model.cache_info().currsize)


class ExternalFlow(RetrievalFlow):
    def __init__(self,n): super().__init__(n,mode='fixed')

    def task_boundaries(self,q,can_read):
        stop=q[:,:,:2].amax(-1) if can_read else q[:,:,STOP]
        adv=(stop-q[:,:,WAIT]).tanh()
        terminal=torch.arange(q.shape[1],device=q.device)==HORIZON-1
        adv=torch.where(terminal,torch.ones_like(adv),adv)
        gap=self.task[3]-self.nominal_boundary
        radius=.9*torch.minimum(gap-self.flow.centers[0],self.flow.centers[-1]-gap)
        return self.nominal_boundary+radius*adv

    def forward(self,x,dt,q,can_read):
        return RetrievalFlow.forward(_IntervalBoundaries(self,self.task_boundaries(q,can_read)),x,dt)

    def edited(self,theta,x,dt,q,can_read):
        return torch.func.functional_call(self,{'flow.drive.bias':self.flow.drive.bias+theta[0],
            'flow.writer.bias':self.flow.writer.bias+self.mark_direction*theta[1]},(x,dt,q,can_read))


class ContextModel(nn.Module):
    """Trainable recurrent free-state context with the same conditional SVD head."""
    def __init__(self,n):
        super().__init__(); self.cell=nn.GRU(n,8,batch_first=True,dtype=torch.float64)
    def forward(self,z): return self.cell(z)[0]
    def initial_edit_vector(self): return torch.zeros(sum(p.numel() for p in self.parameters()),dtype=torch.float64)
    def edited(self,theta,z):
        params={}; at=0
        for name,p in self.named_parameters():
            size=p.numel(); params[name]=p+theta[at:at+size].reshape_as(p); at+=size
        if at!=len(theta): raise ValueError('unexpected GRU displacement')
        return torch.func.functional_call(self,params,(z,))


def representation(mode,seed,dimension):
    torch.manual_seed(seed)
    if mode=='plain': return None
    if mode=='context': return ContextModel(dimension)
    if mode=='external': return ExternalFlow(dimension)
    return RetrievalFlow(dimension,mode=mode)


def features(model,mode,can_read):
    def get(theta,s):
        z=s['zt']
        if mode=='plain': return z
        if mode=='context': h=model.edited(theta,z)
        elif mode=='external': h=model.edited(theta,z,s['clock'],s['qt'],can_read)
        else: h=model.features_with_edit(theta,z,s['clock'])
        return torch.cat((z,h),-1)
    return get
