"""Closed local fits of all three maps and the multiclass head with streamed sufficient statistics."""
import numpy as np
import torch
from torch.nn import functional as F
from cifar_net import WIDTH,init_code,intercept,quadrants,raw_view


def solve(gram,rhs,reg):
    n=gram.shape[0]
    grams=gram.clone()
    penalty=float(grams.diagonal()[:-1].mean().clamp_min(.00001)*reg)
    grams.diagonal()[:-1].add_(penalty)
    grams[-1,-1]+=1e-8
    return torch.linalg.solve(grams,rhs).float()


def collect(gram,rhs,x,y):
    a=x.reshape(-1,x.shape[-1]).double()
    b=y.reshape(-1,y.shape[-1]).double()
    gram.addmm_(a.T,a)
    rhs.addmm_(a.T,b)


@torch.no_grad()
def local_fit(net,train,ix,method,reg,mix,check):
    wrong=train.y.copy()
    if method=='wrong':
        rng=np.random.default_rng(128559+net.seed)
        wrong[ix]=rng.permutation(wrong[ix])
    if method not in ('rf','raw'):
        for layer,w in enumerate(net.w):
            m=w.shape[0];gram=torch.zeros(m,m,dtype=torch.float64);rhs=torch.zeros(m,WIDTH,dtype=torch.float64)
            q,u=init_code(net.seed,layer,m-1)
            for start in range(0,len(ix),64):
                check()
                rows=ix[start:start+64];x,_,_=train.batch(rows)
                h=net.representation(x,layer)
                code=torch.tanh(h@q)+mix*torch.tanh(u[wrong[rows]])[:,None,:]
                if method in ('boundary','wrong'):
                    target_u=.75*torch.tanh(code)
                    boundary=torch.log1p(net.fields.k*target_u)
                    potential=torch.atanh(torch.expm1(boundary)/net.fields.k)
                    target=net.fields(potential,forced=True)
                else:target=code
                collect(gram,rhs,intercept(h),target)
            w.copy_(solve(gram,rhs,reg))
    raw=method=='raw'
    size=193 if raw else net.head.shape[0]
    gram=torch.zeros(size,size,dtype=torch.float64);rhs=torch.zeros(size,100,dtype=torch.float64)
    for start in range(0,len(ix),64):
        check()
        x,y,_=train.batch(ix[start:start+64])
        feature=raw_view(x) if raw else quadrants(net.representation(x))
        collect(gram,rhs,intercept(feature),F.one_hot(y,100))
    head=solve(gram,rhs,reg)
    if raw:return head
    net.head.copy_(head)
    return None
