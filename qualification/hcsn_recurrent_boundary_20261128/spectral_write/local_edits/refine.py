"""Analytic local multinomial Fisher corrections to a low-rank empirical word law."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import sys
import time

import numpy as np
from scipy.linalg import helmert
from scipy.special import logsumexp
from scipy.sparse import coo_matrix
import torch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from write import conditional_basis, invert_block, fit


class Counts:
    def __init__(self,tokens,vocab):
        left=tokens[:-1];right=tokens[1:];rare=right>=128
        self.vocab=vocab;ng=(vocab-128+127)//128;nr=128+ng
        root=np.where(rare,128+(right-128)//128,right)
        self.root=coo_matrix((np.ones(len(right),np.float32),(left,root)),shape=(vocab,nr)).tocsr()
        pair_id=left[rare].astype(np.int64)*ng+(right[rare]-128)//128
        unique,pair=np.unique(pair_id,return_inverse=True)
        self.source=unique//ng;self.group=unique%ng
        self.rank=coo_matrix((np.ones(len(pair),np.float32),(pair,(right[rare]-128)%128)),
                             shape=(len(unique),128)).tocsr()
        self.root_n=np.asarray(self.root.sum(1)).ravel()
        self.rank_n=np.asarray(self.rank.sum(1)).ravel()
        root_prior=np.asarray(self.root.sum(0)).ravel()+.1
        self.root_prior=root_prior/root_prior.sum()
        mass=np.bincount(right[rare]-128,minlength=128*ng).astype(np.float32).reshape(ng,128)+.1
        mass.reshape(-1)[vocab-128:]=0
        self.conditional=mass/mass.sum(1,keepdims=True)


class Model:
    def __init__(self,z,v,b):
        self.z=np.ascontiguousarray(z,dtype=np.float32)
        self.v=np.ascontiguousarray(v,dtype=np.float32)
        self.b=np.ascontiguousarray(b,dtype=np.float32)


class Edits:
    def __init__(self,data,shrink):
        self.data=data;self.alpha=shrink;self.nr=data.root.shape[1]
        self.root_weight=data.root_n+shrink
        self.rank_weight=data.rank_n+1
        self.row_weight=self.root_weight+np.bincount(data.source,weights=self.rank_weight,
                                                     minlength=data.vocab).astype(np.float32)
        self.col_weight=np.r_[np.asarray(data.root.sum(0)).ravel()+shrink*data.vocab*data.root_prior,
                             np.asarray(data.rank.sum(0)).ravel()+np.bincount(data.group,minlength=len(data.conditional))@data.conditional]
        self.rank_prior=self.col_weight[self.nr:]/self.col_weight[self.nr:].sum()

    def statistics(self,model,derivatives):
        d=self.data;z,v,b=model.z,model.v,model.b
        total=0.;nr=self.nr
        gradz=np.zeros_like(z);gradv=np.zeros_like(v);gradb=np.zeros_like(b)
        for is_root,mat in ((True,d.root),(False,d.rank)):
            sl=slice(0,nr) if is_root else slice(nr,None)
            for a in range(0,mat.shape[0],1024):
                stop=min(a+1024,mat.shape[0]);i=slice(a,stop)
                src=i if is_root else d.source[i]
                rows=z[src];logits=rows@v[sl].T+b[sl]
                if is_root:
                    weight=self.root_weight[i]
                    target=mat[i].toarray()+self.alpha*d.root_prior
                else:
                    weight=self.rank_weight[i];prior=d.conditional[d.group[i]]
                    logits+=np.log(np.maximum(prior,1e-35))
                    target=mat[i].toarray()+prior
                logsum=logsumexp(logits,axis=1)
                total+=np.sum(weight*logsum-np.sum(logits*target,axis=1),dtype=np.float64)
                if not derivatives:continue
                residual=target-weight[:,None]*np.exp(logits-logsum[:,None])
                add=residual@v[sl]
                if is_root:gradz[src]+=add
                else:
                    first=np.r_[0,np.nonzero(np.diff(src))[0]+1]
                    gradz[src[first]]+=np.add.reduceat(add,first,axis=0)
                gradv[sl]+=residual.T@rows;gradb[sl]+=residual.sum(0)
        return total,(gradz,gradv,gradb)

    def direction(self,model,grad):
        z,v=model.z,model.v;gz,gv,gb=grad;nr=self.nr
        rr=self.root_weight.sum()/self.row_weight.sum()
        fisher=np.zeros((z.shape[1],z.shape[1]))
        for vec,p,prob in ((v[:nr],self.data.root_prior,rr),(v[nr:],self.rank_prior,1-rr)):
            centered=vec-p@vec;fisher+=prob*((centered*p[:,None]).T@centered)
        fisher+=max(1e-3,.12*np.trace(fisher)/len(fisher))*np.eye(len(fisher))
        dz=np.linalg.solve(fisher,(gz/self.row_weight[:,None]).T).T
        dz/=np.maximum(1,np.linalg.norm(dz,axis=1)/2)[:,None]
        features=np.column_stack((z,np.ones(len(z),np.float32)))
        design=(features*self.row_weight[:,None]).T@features/self.row_weight.sum()
        design+=.05*np.eye(len(design))
        g=np.column_stack((gv,gb))/np.maximum(1,self.col_weight[:,None])
        dh=np.linalg.solve(design,g.T).T
        rms=np.sqrt(np.maximum(0,np.sum((dh@design)*dh,axis=1)))
        dh/=np.maximum(1,rms/.8)[:,None]
        return Model(dz,dh[:,:-1],dh[:,-1])

    def update(self,model):
        before,grad=self.statistics(model,True)
        step=self.direction(model,grad)
        for rate in (1.,.5,.25,.125,.0625):
            candidate=Model(model.z+rate*step.z,model.v+rate*step.v,model.b+rate*step.b)
            after,_=self.statistics(candidate,False)
            if after<before:return candidate,dict(before=before,after=after,rate=rate)
        return model,dict(before=before,after=before,rate=0.)


@torch.no_grad()
def realize(net,coef,data):
    z=coef.z.astype(float);v=coef.v.astype(float);b=coef.b.astype(float)
    weight=data.root_n/data.root_n.sum()
    center=weight@z
    z-=center;b+=v@center
    norms=np.linalg.norm(z,axis=1);order=np.argsort(norms)
    radius=norms[order[np.searchsorted(np.cumsum(weight[order]),.995)]]
    coords=z/np.maximum(radius,norms)[:,None]
    residual=np.sqrt(np.maximum(0.,1.-np.sum(coords**2,axis=1)))
    rot=helmert(32,full=False).T
    desired=torch.tensor(.08*np.sqrt(32)*np.column_stack((coords,residual))@rot.T,dtype=torch.float32)
    y,e2=invert_block(net.blocks[1],desired)
    x,e1=invert_block(net.blocks[0],y)
    net.emb.weight.copy_(x)
    w=v@rot[:,:30].T*radius/np.sqrt(32)
    n=len(data.root_prior);h=net.head
    h.root.weight.copy_(torch.as_tensor(w[:n]));h.root.bias.copy_(torch.as_tensor(b[:n]))
    h.rank.weight.copy_(torch.as_tensor(w[n:]));h.rank.bias.copy_(torch.as_tensor(b[n:]-8*w[n:].sum(1)))
    return max(e1,e2)


def main(a):
    sys.path.insert(0,str(a.data/'src'))
    from model import LanguageModel
    from train import evaluate,Windows
    torch.set_num_threads(1);torch.set_num_interop_threads(1)
    a.out.mkdir(parents=True,exist_ok=True)
    tokens=np.load(a.data/'train.npy');dev=Windows(a.data/'valid.npy')
    tic=time.perf_counter();counts=Counts(tokens,33278);counts_s=time.perf_counter()-tic
    for seed in (137,311,557):
        if (a.out/f'dev-{seed}.json').exists():continue
        started=time.perf_counter()
        target,w,b,rp,tail,meta=conditional_basis(tokens,33278,seed,16,.25)
        # The construction has at most thirty active logit directions.
        _,_,vt=np.linalg.svd(w,full_matrices=False);space=vt[:30].T
        bias=b.copy();bias[:len(rp)]+=np.log(rp)
        initial=Model(target@space,w@space,bias)
        base,_=fit(LanguageModel,tokens,33278,seed,16,.25)
        initialization=time.perf_counter()-started;rows=[]
        for shrink in (4,16):
            coef=initial;rule=Edits(counts,shrink);times=[];updates=[]
            for level in range(1,17):
                clock=time.perf_counter();coef,diag=rule.update(coef);times.append(time.perf_counter()-clock);updates.append(diag)
                if level not in (1,4,8,16):continue
                clock=time.perf_counter();residual=realize(base,coef,counts);realize_s=time.perf_counter()-clock
                clock=time.perf_counter();scores=evaluate(base,dev,32,'cpu');valid_s=time.perf_counter()-clock
                tag=f'local-{seed}-{shrink}-{level}';file=a.out/(tag+'.npz')
                with file.open('wb') as f:np.savez_compressed(f,**{k:v.numpy() for k,v in base.state_dict().items()})
                row=dict(tag=tag,alpha=shrink,seed=seed,level=level,iterations=updates.copy(),edit_seconds=times.copy(),
                         cumulative_fit_s=counts_s+initialization+sum(times)+realize_s,realize_s=realize_s,
                         realization_residual=residual,validation_s=valid_s,valid=scores,sha256=sha256(file.read_bytes()).hexdigest())
                rows.append(row);print(tag,round(scores['ppl'],2),round(row['cumulative_fit_s'],2),flush=True)
        chosen=min(rows,key=lambda x:x['valid']['nll'])['tag']
        (a.out/f'dev-{seed}.json').write_text(json.dumps(dict(seed=seed,pair_contexts=len(counts.source),all=rows,
            chosen=chosen,counts_s=counts_s,initialization_s=initialization,
            total_fit_and_selection_wall_s=time.perf_counter()-started+counts_s),indent=2)+'\n')
    all_dev={str(s):sha256((a.out/f'dev-{s}.json').read_bytes()).hexdigest() for s in (137,311,557)}
    (a.out/'seal.json').write_text(json.dumps(all_dev,indent=2)+'\n')


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('data',type=Path);p.add_argument('out',type=Path)
    main(p.parse_args())
