"""Forward-only fitting of every active image, input-word, physical and next-word projection tensor."""
import math
import numpy as np
import torch
from net import patches,intercept


def solve(gram,rhs,reg):
    g=gram.clone()
    damp=max(1e-5,float(g.diagonal()[:-1].mean()*reg))
    g.diagonal()[:-1].add_(damp);g[-1,-1]+=1e-6
    chol=torch.linalg.cholesky(g)
    return torch.cholesky_solve(rhs,chol).float()


def gaussian(r,c,seed,normalized=True):
    self=torch.Generator().manual_seed(seed)
    return torch.randn(r,c,generator=self)/(math.sqrt(r) if normalized else 1.)


def wordsummary(y,u):
    valid=(y>=4).float()
    return (u[y]*valid[...,None]).sum(1)/valid.sum(1,keepdim=True).clamp_min(1)


@torch.no_grad()
def input_fits(net,src,ids,reg,check):
    v,h=net.vocab,net.width
    token_u=gaussian(v,h,net.seed+158559,False).tanh()
    word_q=gaussian(v,h,net.seed+258559,False).tanh()
    patch_q=gaussian(192,h,net.seed+358559)
    coff=torch.zeros(193,193,dtype=torch.float64);rhs=torch.zeros(193,h,dtype=torch.float64)
    token_sum=torch.zeros(v,h);counts=torch.zeros(v)
    for s in range(0,len(ids),16):
        check();p,x,y=src.batch(ids[s:s+16]);a=patches(p)
        label=wordsummary(y,token_u)
        z=torch.tanh(a@patch_q)+label[:,None,:]
        aa=intercept(a).reshape(-1,193).double();zz=z.reshape(-1,h).double()
        coff.addmm_(aa.T,aa);rhs.addmm_(aa.T,zz)
        mask=y!=0;keys=x[mask];targets=word_q[keys]+token_u[y[mask]]
        token_sum.index_add_(0,keys,targets);counts.index_add_(0,keys,torch.ones_like(keys,dtype=torch.float32))
    net.image.copy_(solve(coff,rhs,reg))
    used=counts>0;net.token[used]=token_sum[used]/(counts[used,None]+reg*counts[used].mean())
    return int(used.sum())


@torch.no_grad()
def hidden_fit(net,src,ids,reg,method,layer,check):
    W=net.weights[layer];d,h=W.shape
    q=gaussian(d-1,h,net.seed+(layer+1)*338559)
    u=gaussian(net.vocab,h,net.seed+(layer+1)*378559,False).tanh()
    gram=torch.zeros(d,d,dtype=torch.float64);rhs=torch.zeros(d,h,dtype=torch.float64)
    for s in range(0,len(ids),16):
        check();p,x,y=src.batch(ids[s:s+16]);lower=net.layers(net.inputs(p,x),layer)
        # Text positions receive true next words only while solving local weights.
        yv=wordsummary(y,u)
        control=torch.cat((yv[:,None,:].expand(-1,4,-1),u[y]),dim=1)
        target=torch.tanh(lower@q)+control
        if method=='boundary':
            bounded=.75*torch.tanh(target)
            boundary=torch.log1p(net.field.k*bounded)
            target=net.field(torch.atanh(torch.expm1(boundary)/net.field.k),forced=True)
        mask=torch.cat((torch.ones(len(p),4,dtype=torch.bool),y!=0),1)
        a=intercept(lower)[mask].double();z=target[mask].double()
        gram.addmm_(a.T,a);rhs.addmm_(a.T,z)
    W.copy_(solve(gram,rhs,reg))


@torch.no_grad()
def head_fit(net,src,ids,reg,check):
    d,v=net.output.shape
    gram=torch.zeros(d,d,dtype=torch.float64)
    sums=torch.zeros(v,d,dtype=torch.float64);aggregate=torch.zeros(d,dtype=torch.float64)
    for s in range(0,len(ids),16):
        check();p,x,y=src.batch(ids[s:s+16]);a=intercept(net.features(p,x))[y!=0].double()
        gram.addmm_(a.T,a);aggregate+=a.sum(0);sums.index_add_(0,y[y!=0],a)
    pr=net.logprior.exp().double()
    rhs=(sums.T-aggregate[:,None]*pr[None,:])/pr.clamp_min(.00025).sqrt()[None,:]
    net.output.copy_(solve(gram,rhs,reg))


def fit(net,data,ids,reg,method,check):
    words=0
    if method!='rf':
        words=input_fits(net,data,ids,reg,check)
        for i in range(3):hidden_fit(net,data,ids,reg,method,i,check)
    head_fit(net,data,ids,reg,check)
    return words
