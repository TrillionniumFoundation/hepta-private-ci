"""Fit and seal complete prospective donor-disjoint panels. No test labels are read."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time
import numpy as np
from scipy.special import expit,logit
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from model import HORIZONS,SUPERVISED,NEW,PENALTIES,SCALES,EPS,score
IDX_SUP=[HORIZONS.index(h) for h in SUPERVISED]
IDX_NEW=[HORIZONS.index(h) for h in NEW]
LINK_H=np.log(HORIZONS)
def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def sigma_model(x,y,penalty,weight=None):
    """Damped exact-Newton solve; fit intercept without penalty."""
    x=np.asarray(x,dtype=np.float64);y=np.asarray(y,dtype=float).ravel()
    weights=np.ones(len(y)) if weight is None else np.asarray(weight,dtype=float)
    mean=np.average(x,axis=0,weights=weights);std=np.maximum(np.sqrt(np.average((x-mean)**2,axis=0,weights=weights)),1e-7)
    z=np.column_stack([np.ones(len(x)),(x-mean)/std]);w=np.zeros(z.shape[1]);w[0]=logit(np.clip(np.average(y,weights=weights),.000001,.999999))
    reg=np.r_[0.,np.full(len(w)-1,penalty)]
    def obj(v):
        a=z@v;return weights@(np.logaddexp(0,a)-y*a)+.5*np.sum(reg*v*v)
    loss=obj(w)
    for iteration in range(75):
        eta=z@w;p=expit(eta);g=z.T@(weights*(p-y))+reg*w
        h=(z.T*(weights*p*(1-p)))@z+np.diag(reg+1e-11)
        step=np.linalg.solve(h,g);scale=1.
        if np.max(abs(step))<1e-8:break
        while scale>=2**-24:
            val=obj(w-scale*step)
            if val<=loss+1e-10:break
            scale/=2
        if scale<2**-24:break
        w-=scale*step;loss=val
        if scale*np.max(abs(step))<1e-8:break
    if not np.all(np.isfinite(w)):raise ArithmeticError('non-finite logistic solution')
    return {'mean':mean.tolist(),'std':std.tolist(),'w':w.tolist(),'iterations':iteration+1,'objective':float(loss)}
def linear(fit,x):
    w=np.asarray(fit['w']);return (np.asarray(x)-fit['mean'])/fit['std']@w[1:]+w[0]
def collect(data,cache,ids,conditions=('1','2')):
    records=[]
    for sid in ids:
        p=data/f'{sid}.npz';receipt=json.loads((data/f'{sid}.json').read_text())
        assert digest(p)==receipt['npz_sha256'];record_info=json.loads((cache/f'{sid}.json').read_text())
        assert record_info['source_sha256']==receipt['npz_sha256']
        with np.load(p) as z:
            for c in conditions:
                for rep in ('0','1'):
                    slot=c+'_'+rep;fpath=cache/(f'{sid}-'+slot+'.npz')
                    assert digest(fpath)==record_info['sweeps'][slot]['sha256']
                    with np.load(fpath) as comp:
                        a=comp['anchors'];y=z['y'+slot];ys=np.r_[0,np.cumsum(y,dtype=int)]
                        rows={'sid':sid,'slot':slot,'anchors':a,'binary':y[a].astype(np.float32),'raw_y':y,
                              'future':np.stack([ys[a+h]-ys[a]>0 for h in HORIZONS],1).astype(np.float32),'base_full':comp['base'],
                              'free':comp['free'][a],'phys':{}}
                        for law in ('fixed','tangent','literal'):
                            for sc in range(len(SCALES)):rows['phys'][law+str(sc)]=comp[law+str(sc)][a]
                        records.append(rows)
    return records
def sample_weight(records,horizons):
    # one unit per cell then sweep, with mean weight 1 so ridge scales remain transparent
    sizes=np.array([len(r['anchors'])*horizons for r in records]);mean=sizes.mean()
    return np.concatenate([np.full(n,mean/n) for n in sizes])
def mean_log(records,preds,ix):
    by={}
    for r,p in zip(records,preds):
        a,b=score(p[:,ix],r['future'][:,ix]);by.setdefault(r['sid'],[]).append((a.mean(),b.mean()))
    return np.mean([np.mean(v,0) for v in by.values()],0).tolist()
def baseline_hazard(raw,fit):
    hh=expit(linear(fit,raw['base_full'])).clip(EPS,1-EPS)
    cumulative=np.r_[0.,np.cumsum(np.log1p(-hh))]
    a=raw['anchors'];return -np.expm1(np.stack([cumulative[a+h]-cumulative[a] for h in HORIZONS],1))
def safest(p):return logit(np.clip(p,EPS,1-EPS)).astype(np.float32)
def hfeature(r):
    return np.broadcast_to(LINK_H,(len(r['anchors']),len(HORIZONS))).astype(np.float32)
def free_design(r):
    return np.concatenate([r['free'],hfeature(r)[:,:,None]],axis=-1)
def join(records,fn,ix):
    return np.concatenate([fn(r)[:,ix].reshape(-1,fn(r).shape[-1]) for r in records])
def fit_pre(train,dev):
    x=np.concatenate([r['base_full'][r['anchors']] for r in train]);y=np.concatenate([r['binary'] for r in train])
    ws=sample_weight(train,1);wy=sample_weight(train,len(IDX_SUP))
    free_x=join(train,free_design,IDX_SUP);fy=np.concatenate([r['future'][:,IDX_SUP].ravel() for r in train])
    out={}
    for pen in PENALTIES:
        hazard=sigma_model(x,y,pen,ws);free=sigma_model(free_x,fy,pen,wy)
        out[str(pen)]={'hazard':hazard,'free':free}
    return out
def add_base_features(records,pre):
    for r in records:
        r['hazard']={};r['learned_free']={}
        for p,weights in pre.items():
            r['hazard'][p]=safest(baseline_hazard(r,weights['hazard']))
            r['learned_free'][p]=linear(weights['free'],free_design(r)).astype(np.float32)
def design(r,name,pen,scale):
    h=hfeature(r);haz=r['hazard'][str(pen)]
    if name=='hazard':return np.stack([h,haz],-1)
    if name=='hazard+free':return np.stack([h,haz,r['learned_free'][str(pen)]],-1)
    law=name.split('+')[-1];phys=safest(r['phys'][law+str(scale)])
    if name.startswith('hazard+'):return np.stack([h,haz,phys],-1)
    return np.stack([h,phys],-1)
def pred(records,name,choice):
    return [expit(linear(choice['calibrator'],design(r,name,choice['penalty'],choice['scale_index']))).astype(np.float32) for r in records]
def fit(data,cache,out):
    out.mkdir(exist_ok=True,parents=True);roster=json.loads((data/'roster.json').read_text());ids=roster['cells'];assert len(ids)==24
    t0=time.monotonic();train=collect(data,cache,ids[:12]);dev=collect(data,cache,ids[12:16])
    pre=fit_pre(train,dev);add_base_features(train,pre);add_base_features(dev,pre)
    truth=np.concatenate([r['future'][:,IDX_SUP].ravel() for r in train]);weights=sample_weight(train,len(IDX_SUP))
    names=['hazard','hazard+free','fixed','tangent','literal','hazard+fixed','hazard+tangent','hazard+literal'];all_scores={};selected={}
    for name in names:
        choices=[]
        for pen in PENALTIES:
            for si in ([0] if name in ('hazard','hazard+free') else range(len(SCALES))):
                start=time.monotonic()
                design_x=np.concatenate([design(r,name,pen,si)[:,IDX_SUP].reshape(-1,design(r,name,pen,si).shape[2]) for r in train])
                calibration=sigma_model(design_x,truth,pen,weights)
                cand=dict(calibrator=calibration,penalty=pen,scale_index=si)
                pp=pred(dev,name,cand);cand['dev_nll'],cand['dev_brier']=mean_log(dev,pp,IDX_SUP)
                cand['wall_seconds']=time.monotonic()-start
                choices.append(cand)
        best=min(choices,key=lambda c:c['dev_nll']);selected[name]=best
        all_scores[name]=[{k:v for k,v in c.items() if k!='calibrator'} for c in choices];print(name,best['dev_nll'],flush=True)
    manifest={str(i):digest(data/f'{i}.npz') for i in ids}
    seal={'ids':ids,'roster_sha256':digest(data/'roster.json'),'source_sha256':manifest,'features_sha256':{str(i):digest(cache/f'{i}.json') for i in ids},'pre':pre,'selected':selected,'all_dev':all_scores,'total_fit_wall_s':time.monotonic()-t0}
    (out/'SEAL.json').write_text(json.dumps(seal,indent=2,allow_nan=False)+'\n')
if __name__=='__main__':
    ap=argparse.ArgumentParser()
    for k in ('data','cache','out'):ap.add_argument('--'+k,type=Path,required=True)
    a=ap.parse_args();fit(a.data,a.cache,a.out)
