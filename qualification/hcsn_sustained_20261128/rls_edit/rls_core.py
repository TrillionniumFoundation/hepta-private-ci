"""Row-key form of RLSEdit Equation 3 and the model-specific 72-prompt metrics."""
import numpy as np
import torch
from torch.nn import functional as F

BUDGETS=(8,32,128)
METHODS=('parent','rls-1','rls-4','recent-1','recent-4','quad-1','quad-4','ce-1','ce-4')
GROUPS=('current','past','protected','future','all')


def prior(w, anchors, mu):
    eye=torch.eye(w.shape[0],dtype=w.dtype)
    s=eye+mu**2*(anchors.T@anchors)
    return s, s@w


def rls_step(w, p, keys, values):
    """P is the inverse Gram before this block; both updates use its original gain."""
    for k,v in zip(keys.split(32), values.split(32)):
        ka=k@p
        small=torch.eye(len(k),dtype=p.dtype)+ka@k.T
        gain=torch.linalg.solve(small,ka).T
        w=w+gain@(v-k@w)
        p=p-gain@ka
        p=(p+p.T)/2
    return w,p


def target_labels(y,stage):
    s=y//6
    return torch.where(s<=stage,6*s+(y%6+1)%6,y)


def select_masks(y,stage):
    s=y//6
    return {'current':s==stage,'past':s<stage,'protected':s>=6,'future':(s>stage)&(s<6),'all':torch.ones_like(s,dtype=torch.bool)}


def projected(av,text,w):
    return 12*(F.normalize(av@w,dim=-1)@F.normalize(text@w,dim=-1).T)


def outcomes(z,old,y,stage):
    y1=target_labels(y,stage)
    q=F.log_softmax(z.double(),dim=-1);q0=F.log_softmax(old.double(),dim=-1)
    i=torch.arange(len(y)); comp=z.clone();comp[i,y1]=-torch.inf
    return {'nll':(-q[i,y1]).numpy(),'top1':(z.argmax(-1)==y1).double().numpy(),
            'agreement':(z.argmax(-1)==old.argmax(-1)).double().numpy(),
            'kl_parent_edited':(q0.exp()*(q0-q)).sum(1).numpy(),
            'target_margin':(z[i,y1]-comp.max(1).values).double().numpy()}


def summarize(z,old,y,stage):
    data=outcomes(z,old,y,stage)
    return {g:{'n':int(m.sum()),**{k:float(a[m.numpy()].mean()) for k,a in data.items()}} for g,m in select_masks(y,stage).items() if m.any()}


def gate(result,parent):
    c='current';p='protected';o='past'
    return (parent[c]['nll']-result[c]['nll']>=.10 and (o not in result or parent[o]['nll']-result[o]['nll']>=.05)
            and result[p]['nll']-parent[p]['nll']<=.10 and parent[p]['top1']-result[p]['top1']<=.02)


def unit():
    g=torch.Generator().manual_seed(1167)
    w=torch.randn(12,15,generator=g,dtype=torch.float64);a=torch.randn(21,12,generator=g,dtype=w.dtype)
    k=torch.randn(119,12,generator=g,dtype=w.dtype);v=torch.randn(119,15,generator=g,dtype=w.dtype)
    out=[]
    for mu in (1,4):
        s,t=prior(w,a,mu);actual,p=rls_step(w,torch.linalg.inv(s),k,v)
        ref=torch.linalg.solve(s+k.T@k,t+k.T@v)
        e=(actual-ref).abs().max().item();ep=(p-torch.linalg.inv(s+k.T@k)).abs().max().item()
        assert max(e,ep)<1e-11;out.append([mu,e,ep])
    return out
