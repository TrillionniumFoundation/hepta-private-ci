"""Learn every He–Xiong word-model parameter from data through local closed-form writes."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import sys
import time

import numpy as np
import torch
from torch.nn import functional as F

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from model import LanguageModel
from train import Windows,evaluate

D=32
RIDGE=.025


def whiten(values):
    m=values.mean(1,keepdims=True)
    return np.clip((values-m)/np.sqrt(np.mean((values-m)**2,axis=1,keepdims=True)+.08),-3.,3.)


class Fit:
    def __init__(self,dx,dy):
        self.X=np.zeros((dx+1,dx+1));self.Y=np.zeros((dx+1,dy));self.n=0
    def add(self,x,y):
        x=x.double();y=y.double()
        self.n+=len(x)
        self.X[:-1,:-1]+=(x.T@x).numpy();self.X[:-1,-1]+=x.sum(0).numpy()
        self.X[-1,:-1]=self.X[:-1,-1];self.X[-1,-1]=self.n
        self.Y[:-1]+=(x.T@y).numpy();self.Y[-1]+=y.sum(0).numpy()
    def solve(self):
        ridge=np.diag([RIDGE*self.n]*(self.X.shape[0]-1)+[0.])
        w=np.linalg.solve(self.X+ridge,self.Y)
        return w[:-1].T,w[-1]
    def affine(self):
        mu=self.X[:-1,-1]/self.n
        var=np.diag(self.X)[:-1]/self.n-mu**2
        gamma=1/np.sqrt(np.maximum(var,.05))
        return gamma,-mu*gamma


class Groups:
    def __init__(self,g):
        self.s=torch.zeros(g,D,dtype=torch.float64);self.n=torch.zeros(g,dtype=torch.float64)
        self.gram=torch.zeros(D,D,dtype=torch.float64)
    def add(self,x,g):
        x=x.double();self.s.index_add_(0,g,x);self.n+=torch.bincount(g,minlength=len(self.n))
        self.gram+=x.T@x
    def fit(self,prior):
        n=self.n.numpy();s=self.s.numpy();mu=s/(n[:,None]+1e-12)
        mean=s.sum(0)/n.sum()
        means=(s+40*mean)/(n[:,None]+40)
        within=(self.gram.numpy()-mu.T@s)/n.sum()
        ridge=.12*max(.1,np.trace(within)/D)
        w=np.linalg.solve(within+ridge*np.eye(D),means.T).T
        b=np.log(prior)-.5*np.sum(w*means,axis=1)
        return w,b,means


class Writer:
    def __init__(self,root,seed):
        self.root=root;self.seed=seed
        arr=np.load(root/'train.npy')
        self.v=int(json.loads((root/'data.json').read_text())['vocab'])
        self.rng=np.random.default_rng(seed)
        self.model=LanguageModel(self.v,'hx')
        self.names=dict(self.model.named_parameters());self.written={}
        for p in self.names.values():p.fill_(float('nan'))
        self.train=Windows(root/'train.npy')
        left=arr[:-1];right=arr[1:]
        position=np.arange(len(right))%128
        # 16 common words have their own categories; remaining words share
        # 16 deterministic seed-dependent bins. Distinct word rows persist.
        category=self.rng.integers(16,32,self.v);category[:16]=np.arange(16)
        freq=np.bincount(right,minlength=self.v).astype(float)
        hist=np.bincount(category[right],minlength=D).astype(float)+1.
        prior=hist/hist.sum()
        out=np.bincount(left.astype(np.int64)*D+category[right],minlength=self.v*D).reshape(self.v,D)
        prev=np.bincount(right.astype(np.int64)*D+category[left],minlength=self.v*D).reshape(self.v,D)
        def fingerprints(h):
            prob=(h+16*prior)/(h.sum(1,keepdims=True)+16)
            return np.log(np.maximum(1e-9,prob/prior)).clip(-4,4)
        embedding=whiten(.65*fingerprints(out)+.35*fingerprints(prev))
        pos=np.bincount(position*D+category[right],minlength=128*D).reshape(128,D)
        position_embedding=.12*fingerprints(pos)
        self.set('emb.weight',embedding);self.set('pos',position_embedding)
        hot=np.eye(D)[category]-.05
        self.target=torch.tensor(.60*np.tanh(embedding)+.40*hot,dtype=torch.float32)
        self.freq=freq
        groups=self.model.head.groups;tail=np.zeros(groups*128);tail[:self.v-128]=freq[128:]
        prior_count=tail.reshape(groups,128)+.25
        valid=128+np.arange(groups*128).reshape(groups,128)<self.v
        prior_count*=valid
        self.group_prior=prior_count/np.maximum(1e-9,prior_count.sum(1,keepdims=True))
        self.rank_prior=prior_count.sum(0)/prior_count.sum()
        self.root_prior=np.r_[freq[:128]+.25,prior_count.sum(1)];self.root_prior/=self.root_prior.sum()
        self.set('head.prior.weight',np.log(self.group_prior.clip(1e-12))/1.-np.log(self.rank_prior))
        order=self.rng.permutation(len(self.train.x))
        edges=(len(order)*np.array([0,.06,.12,.18,.24,.30,.36,.42,.48,.74,1.])).astype(int)
        self.parts=[order[a:b] for a,b in zip(edges[:-1],edges[1:])]
        self.exposure=[len(right)]
    def set(self,n,v):
        if n in self.written:raise ValueError(n)
        a=torch.as_tensor(v).float()
        if not a.isfinite().all():raise ArithmeticError(n)
        self.names[n].copy_(a)
        self.written[n]=dict(shape=list(a.shape),sha256=hashlib.sha256(a.numpy().tobytes()).hexdigest())
    def assign_linear(self,name,solve,normal=None):
        w,b=solve
        if normal is not None:
            g,offset=normal
            w=w/g;b=b-w@offset
        self.set(name+'.weight',w);self.set(name+'.bias',b)
    def assign_norm(self,name,affine):
        self.set(name+'.weight',affine[0]);self.set(name+'.bias',affine[1])
    def batches(self,part):
        seen=0
        for start in range(0,len(part),32):
            ii=part[start:start+32]
            x=self.train.x[ii];y=self.train.y[ii];ok=y>=0
            seen+=int(ok.sum())
            h=self.model.emb(x)+self.model.pos
            yield h,y,ok
        self.exposure.append(seen)
    def signal(self,b,x):
        q,k,v=b.qkv(b.pre(x)).chunk(3,-1)
        p=b.histpow
        hist=torch.cumsum(k*(1-b.decay)/p,1)*p
        u=torch.tanh(q+hist);mix=torch.sigmoid(v)
        e0=b.center[1]+b.slope[1]*u;e1=b.center[2]+b.slope[2]*u
        l0=b.center[3]+b.slope[3]*u;l1=b.center[4]+b.slope[4]*u
        return u+(e0+mix*(e1-e0))/b.center[2]-(l0+mix*(l1-l0))/b.center[3]
    def blocks(self):
        for ind,b in enumerate(self.model.blocks):
            prefix=f'blocks.{ind}.'
            for stage in range(4):
                widths=[(D,3*D),(D,D),(D,2*D),(2*D,D)]
                fit=Fit(*widths[stage])
                for x,y,ok in self.batches(self.parts[ind*4+stage]):
                    if ind:x=self.model.blocks[0](x)
                    target=self.target[y.clamp(min=0)]
                    desired=.76*target
                    c=b.slope[0]/b.center[0]
                    latent=torch.atanh((torch.expm1(c*desired)/c).clamp(-.97,.97))
                    if stage==0:
                        a=F.layer_norm(x,(D,))
                        future=torch.cat((target[:,1:],target[:,-1:]),1)
                        future_ok=torch.cat((ok[:,1:],ok[:,-1:]),1)
                        future=torch.where(future_ok[:,:,None],future,target)
                        lab=torch.cat((target, .6*target+.4*future,torch.roll(target,7,-1)),-1)
                    else:
                        sig=self.signal(b,x)
                        if stage==1:a=sig;lab=latent-x
                        else:
                            z=x+b.out(sig)
                            if stage==2:a=F.layer_norm(z,(D,));lab=torch.cat((target,-target),-1)
                            else:a=b.ff[:3](z);lab=latent-z
                    fit.add(a[ok],lab[ok])
                if stage==0:
                    aff=fit.affine();self.assign_norm(prefix+'pre',aff);self.assign_linear(prefix+'qkv',fit.solve(),aff)
                if stage==1:self.assign_linear(prefix+'out',fit.solve())
                if stage==2:
                    aff=fit.affine();self.assign_norm(prefix+'ff.0',aff);self.assign_linear(prefix+'ff.1',fit.solve(),aff)
                if stage==3:self.assign_linear(prefix+'ff.3',fit.solve())
    def head(self):
        h=self.model.head;g=Groups(128+h.groups)
        for x,y,ok in self.batches(self.parts[-2]):
            z=F.layer_norm(self.model.blocks[1](self.model.blocks[0](x)),(D,))[ok]
            t=y[ok];b=torch.where(t<128,t,128+(t-128)//128)
            g.add(z,b)
        n=g.n.sum().item();mu=g.s.sum(0).numpy()/n
        var=g.gram.diag().numpy()/n-mu**2;gamma=1/np.sqrt(np.maximum(var,.05));offset=-mu*gamma
        self.assign_norm('norm',(gamma,offset))
        w,b,m=g.fit(self.root_prior)
        self.assign_linear('head.root',(w,b),(gamma,offset))
        self.set('head.condition.weight',-(m[128:]*gamma+offset))
        rank=Groups(128)
        for x,y,ok in self.batches(self.parts[-1]):
            z=self.model.norm(self.model.blocks[1](self.model.blocks[0](x)))
            rare=ok&(y>=128);yy=y[rare]-128
            z=F.gelu(z[rare]+h.condition(yy//128))
            rank.add(z,yy%128)
        w,b,_=rank.fit(self.rank_prior)
        self.assign_linear('head.rank',(w,b))
    def finish(self):
        self.blocks();self.head()
        if self.written.keys()!=self.names.keys() or sum(self.exposure[1:])!=self.exposure[0]:raise ArithmeticError('coverage')
        fingerprint=hashlib.sha256()
        for name in sorted(self.names):
            fingerprint.update(name.encode());fingerprint.update(self.names[name].numpy().tobytes())
        return fingerprint.hexdigest()


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('root',type=Path);p.add_argument('seed',type=int);p.add_argument('--init',type=int,default=71)
    a=p.parse_args();torch.set_num_threads(1);torch.set_num_interop_threads(1);torch.manual_seed(a.init)
    with torch.no_grad():
        start=time.perf_counter();w=Writer(a.root,a.seed)
        sha=w.finish();elapsed=time.perf_counter()-start
        scores={}
        for spl in ('valid','test'):
            win=Windows(a.root/(spl+'.npy'));scores[spl]=evaluate(w.model,win,32,'cpu')
        scores['cut_test']=evaluate(w.model,Windows(a.root/'test.npy'),32,'cpu',cut=True)
        dest=a.root/'direct';name=f'direct-{a.seed}-init{a.init}'
        torch.save(w.model.state_dict(),dest/(name+'.pt'))
        result=dict(seed=a.seed,erased_initialization_seed=a.init,parameters=sum(p.numel() for p in w.names.values()),
           named_parameter_writes=w.written,state_hash=sha,training_target_exposures=w.exposure,
           training_seconds=elapsed,scores=scores,backprop_calls=0,optimizer_steps=0)
        (dest/(name+'.json')).write_text(json.dumps(result,indent=2)+'\n')
        print(name,sha,elapsed,scores,flush=True)
