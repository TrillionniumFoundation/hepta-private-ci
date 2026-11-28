"""Same registered exact Newton objectives with bounded row blocks and recoverable candidates."""
import argparse
import gc
import json
import os
from pathlib import Path
import time
import numpy as np
from scipy.special import expit,logit
import estimate as e

def newton(x,y,penalty,weight=None):
    y=np.asarray(y,dtype=float).ravel();weights=np.ones(len(y)) if weight is None else np.asarray(weight,dtype=float)
    chunks=[slice(i,min(i+8192,len(y))) for i in range(0,len(y),8192)]
    total=weights.sum();k=x.shape[1]
    mean=sum(weights[s]@x[s].astype(float) for s in chunks)/total
    std=np.maximum(np.sqrt(sum(weights[s]@((x[s].astype(float)-mean)**2) for s in chunks)/total),1e-7)
    def normalized(s):
        return np.column_stack([np.ones(len(y[s])),(x[s].astype(float)-mean)/std])
    w=np.zeros(k+1);w[0]=logit(np.clip(weights@y/total,.000001,.999999));reg=np.r_[0.,np.full(k,penalty)]
    def obj(v):
        out=0.
        for s in chunks:
            a=normalized(s)@v;out+=weights[s]@(np.logaddexp(0,a)-y[s]*a)
        return out+.5*np.sum(reg*v*v)
    loss=obj(w)
    for iteration in range(75):
        grad=reg*w;hess=np.diag(reg+1e-11)
        for s in chunks:
            z=normalized(s);p=expit(z@w);wt=weights[s]
            grad+=z.T@(wt*(p-y[s]));hess+=(z.T*(wt*p*(1-p)))@z
        step=np.linalg.solve(hess,grad);scale=1.
        if np.max(abs(step))<1e-8:break
        while scale>=2**-24:
            val=obj(w-scale*step)
            if val<=loss+1e-10:break
            scale/=2
        if scale<2**-24:break
        w-=scale*step;loss=val
        if scale*np.max(abs(step))<1e-8:break
    if not np.isfinite(w).all():raise ArithmeticError('numerical error')
    return dict(mean=mean.tolist(),std=std.tolist(),w=w.tolist(),iterations=iteration+1,objective=float(loss))
def checkpoint(path,obj):
    tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(obj,indent=1,allow_nan=False)+'\n');os.replace(tmp,path)
def eqcheck():
    rng=np.random.default_rng(855966);x=rng.normal(size=(10003,7)).astype(np.float32);y=(rng.random(len(x))<.13);w=rng.uniform(.5,2,len(x))
    one=e.sigma_model(x,y,1.,w);two=newton(x,y,1.,w)
    diff=float(np.max(abs(e.linear(one,x)-e.linear(two,x))))
    if diff>1e-6:raise ArithmeticError(('row equivalence',diff))
    return diff
def fit(data,cache,out):
    tic=time.monotonic();out.mkdir(exist_ok=True,parents=True);ck=out/'candidate';ck.mkdir(exist_ok=True)
    err=eqcheck();ids=json.loads((data/'roster.json').read_text())['cells'];assert len(ids)==24
    train=e.collect(data,cache,ids[:12]);dev=e.collect(data,cache,ids[12:16])
    e.sigma_model=newton
    pre_file=ck/'pre.json'
    if pre_file.exists():pre=json.loads(pre_file.read_text())
    else:
        pre=e.fit_pre(train,dev);checkpoint(pre_file,pre)
    for block in (train,dev):
        e.add_base_features(block,pre)
        for r in block:
            for field in ('free','base_full','raw_y','binary'):r.pop(field)
    gc.collect()
    truth=np.concatenate([r['future'][:,e.IDX_SUP].ravel() for r in train]);weights=e.sample_weight(train,len(e.IDX_SUP))
    names=['hazard','hazard+free','fixed','tangent','literal','hazard+fixed','hazard+tangent','hazard+literal'];selected={};scores={}
    for name in names:
        choices=[]
        for pen in e.PENALTIES:
            for si in ([0] if name in ('hazard','hazard+free') else range(len(e.SCALES))):
                path=ck/f'{name}_{pen}_{si}.json'
                if path.exists():cand=json.loads(path.read_text())
                else:
                    start=time.monotonic();buf=[]
                    for r in train:
                        xx=e.design(r,name,pen,si)
                        buf.append(xx[:,e.IDX_SUP].reshape(-1,xx.shape[2]))
                    xx=np.concatenate(buf);del buf
                    sol=newton(xx,truth,pen,weights);del xx
                    cand=dict(calibrator=sol,penalty=pen,scale_index=si)
                    cand['dev_nll'],cand['dev_brier']=e.mean_log(dev,e.pred(dev,name,cand),e.IDX_SUP)
                    cand['wall_seconds']=time.monotonic()-start;checkpoint(path,cand)
                choices.append(cand)
        selected[name]=min(choices,key=lambda c:c['dev_nll']);scores[name]=[{k:v for k,v in c.items() if k!='calibrator'} for c in choices]
        print(name,selected[name]['dev_nll'],flush=True)
    seal=dict(ids=ids,roster_sha256=e.digest(data/'roster.json'),source_sha256={str(i):e.digest(data/f'{i}.npz') for i in ids},
     features_sha256={str(i):e.digest(cache/f'{i}.json') for i in ids},pre=pre,selected=selected,all_dev=scores,
     total_fit_wall_s=time.monotonic()-tic,chunk_equivalence_max_logit_error=err)
    checkpoint(out/'SEAL.json',seal)
if __name__=='__main__':
    p=argparse.ArgumentParser()
    for k in ('data','cache','out'):p.add_argument('--'+k,type=Path,required=True)
    a=p.parse_args();fit(a.data,a.cache,a.out)
