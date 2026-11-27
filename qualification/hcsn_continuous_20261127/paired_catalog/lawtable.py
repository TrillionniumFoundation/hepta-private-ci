"""Precompute the equity, priced loss, first-hit and mean-reset transitions in a bounded operating domain."""
import sys,math,json
from pathlib import Path
import numpy as np
from common import ROOT
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'core'))
def build():
    import torch
    from he_xiong import Published
    torch.set_num_threads(1);law=Published();g=torch.linspace(-1,1,161,dtype=torch.float64)
    # first axis is the bounded principal drive tanh(u), not the unbounded input
    x=torch.linspace(0,1.2,385,dtype=torch.float64)
    def direct(t,m):
        p=law.p.P0*(1+.28*t);b=law.boundary(p)
        E=law.equity(m,p);q=law.q;c=law.c;v=law.var;a=law.a;s=law.p.sigma
        def hit(y):return torch.exp(-(a-y)*m)*torch.special.ndtr((-m-y*v)/s)+torch.exp(-(a+y)*m)*torch.special.ndtr((-m+y*v)/s)
        L=law.disc*(p-c/q)*hit(a)+(c/q-law.p.alpha*b)*hit(law.zb)
        return torch.stack([E/20,L/20,law.passage(m,.25),law.move_mean(m,.25)],-1)
    fields=direct(g[:,None]+torch.zeros_like(x),x[None]+torch.zeros_like(g)[:,None]).numpy()
    u0=torch.tensor(0.,dtype=g.dtype);m0=torch.tensor(.18,dtype=g.dtype);eps=.0001
    center=direct(u0,m0).numpy();dm=(direct(u0,m0+eps)-direct(u0,m0-eps)).numpy()/(2*eps);du=(direct(u0+eps,m0)-direct(u0-eps,m0)).numpy()/(2*eps)
    k=law.bp*law.p.P0*.28/law.B0
    z=dict(fields=fields.astype(np.float32),center=center.astype(np.float32),dm=dm.astype(np.float32),du=du.astype(np.float32),k=np.array(k,dtype=np.float32))
    rng=np.random.default_rng(14077);t=rng.uniform(-1,1,1000);m=rng.uniform(.001,1.199,1000)
    exact=direct(torch.tensor(t),torch.tensor(m)).numpy()
    approx=lookup(z,t,m,'literal')
    err=np.max(abs(exact-approx),axis=0);assert np.max(err)<.0003,err
    np.savez(ROOT/'law.npz',**z)
    (ROOT/'law_audit.json').write_text(json.dumps({'max_grid_abs_error_per_channel':err.tolist(),'k':k,'torch':torch.__version__}))
def lookup(z,t,x,kind):
    x=np.maximum(0,np.minimum(1.2,x));u=np.maximum(-1,np.minimum(1,t));f=z['fields']
    a=(u+1)*((f.shape[0]-1)/2);b=x*((f.shape[1]-1)/1.2)
    i=np.minimum(a.astype(int),f.shape[0]-2);j=np.minimum(b.astype(int),f.shape[1]-2)
    s=(a-i)[...,None];r=(b-j)[...,None]
    v=((1-s)*((1-r)*f[i,j]+r*f[i,j+1])+s*((1-r)*f[i+1,j]+r*f[i+1,j+1])).astype(np.float32)
    if kind=='smooth':
        affine=(x[...,None]-.18)*z['dm'][:2]+u[...,None]*z['du'][:2]
        v[...,:2]=z['center'][:2]+np.tanh(affine)
    return v
def propagate(sequence,z,kind):
    prev=np.zeros_like(sequence[:,0]);margin=prev+.18;feedback=prev
    out=[]
    for i in range(sequence.shape[1]):
        t=np.tanh(sequence[:,i]+feedback);boundary=np.log1p(z['k']*t)
        value=lookup(z,t,margin+prev-boundary,kind)
        feedback=.15*np.tanh(value[...,0]-z['center'][0])+.15*np.tanh(value[...,1]-z['center'][1])
        out.append(np.stack([boundary,value[...,0],value[...,1],value[...,2]],axis=-1))
        prev=boundary;margin=value[...,3]
    return np.stack(out,axis=1)
if __name__=='__main__':build()
