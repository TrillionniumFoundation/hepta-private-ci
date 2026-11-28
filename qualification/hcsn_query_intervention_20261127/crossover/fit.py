"""Cohort-external fitting of matched senders for protocol response contrasts."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import pickle
import time
import numpy as np
from scipy.optimize import minimize
from scipy.special import expit
from sklearn.ensemble import HistGradientBoostingClassifier
from threadpoolctl import threadpool_limits
from features import A,AMP,H,PHASE,digest

MODELS=('smooth','dual','fixed','tangent','step','moving')
Y_TRAIN=(1,4,8); Y_COLD=(2,6); REG=(.001,.01)
def dump(path,o):path.write_text(json.dumps(o,indent=1,allow_nan=False)+'\n')
def get(data,cache,sid,typ,rep,amp,horizons):
    rec=json.loads((cache/f'{sid}.json').read_text());source=data/f'{sid}.npz';assert rec['source']==digest(source)
    blob=rec['outputs'][f'{typ}_{rep}'];fpath=cache/blob['file'];assert digest(fpath)==blob['sha']
    mask=np.isin(AMP,amp);hs=[int(np.flatnonzero(H==h)[0]) for h in horizons]
    with np.load(fpath) as zz:
        sh=zz['shared'][mask][:,hs];shape=sh.shape[:2];x={'shared':sh.reshape(-1,sh.shape[-1])}
        d=zz['dual'][mask];x['dual']=np.broadcast_to(d[:,None,:],(*shape,2)).reshape(-1,2)
        for key in MODELS[2:]:x[key]=zz[key][mask][:,hs].reshape(-1,1)
    with np.load(source) as raw:
        target=raw['y'+typ+'_'+str(rep)]
        count=np.r_[0,np.cumsum(target,dtype=int)];at=A[mask]
        y=np.stack([count[at+h]-count[at]>0 for h in horizons],axis=1).reshape(-1)
    return x,y
def table(data,cache,ids):
    cols={};ys=[]
    for sid in ids:
        for rep in (0,1):
            x,y=get(data,cache,sid,'1',rep,(1,2),Y_TRAIN)
            for key,z in x.items():cols.setdefault(key,[]).append(z)
            ys.append(y)
    return {k:np.concatenate(v) for k,v in cols.items()},np.concatenate(ys)
def design(x,name):
    if name in ('smooth','boost'):return x['shared']
    if name=='dual':return np.column_stack((x['shared'],x['dual']))
    return np.column_stack((x['shared'],x['dual'],x[name]))
def metrics(p,y):
    prob=np.clip(p.astype(np.float64),1e-7,1.-1e-7)
    return np.array([np.mean(-np.where(y,np.log(prob),np.log1p(-prob))),np.mean((prob-y)**2)])
def logistic(train,y,dev,dy):
    # All donors, sweeps, phases and cycles have identical support; these rows
    # therefore have equal weights in the training likelihood and validation score.
    u=train.astype(float);mean=u.mean(0);std=np.maximum(u.std(0),1e-6);u-=mean;u/=std
    med=(dev.astype(float)-mean)/std;results=[];yf=y.astype(float)
    for reg in REG:
        start=time.monotonic();init=np.r_[np.log(yf.mean()/(1.-yf.mean())),np.zeros(u.shape[1])]
        def loss(w):
            eta=w[0]+u@w[1:];delta=(expit(eta)-yf)/len(y)
            val=np.mean(np.logaddexp(0.,eta)-yf*eta)+.5*reg*(w[1:]@w[1:])
            return val,np.r_[delta.sum(),u.T@delta+reg*w[1:]]
        fit=minimize(loss,init,method='L-BFGS-B',jac=True,options={'ftol':1e-11,'gtol':1e-6,'maxiter':400})
        val=metrics(expit(fit.x[0]+med@fit.x[1:]).astype(np.float32),dy)
        results.append(dict(w=fit.x.tolist(),reg=reg,object=float(fit.fun),success=bool(fit.success),iterations=int(fit.nit),valid=val.tolist(),sec=time.monotonic()-start))
    best=min(results,key=lambda e:e['valid'][0])
    return dict(mean=mean.tolist(),std=std.tolist(),selected=best,all=results)
def prob(x,name,model):
    if name=='boost':return model.predict_proba(design(x,name))[:,1].astype(np.float32)
    w=np.array(model['selected']['w']);z=design(x,name)
    return expit((z-model['mean'])/model['std']@w[1:]+w[0]).astype(np.float32)
def fit(data,cache,test_data,price,out):
    out.mkdir(exist_ok=True,parents=True)
    ids=json.loads((data/'roster.json').read_text())['cells'];held=json.loads((test_data/'roster.json').read_text())['cells']
    assert len(ids)==24 and len(held)==48 and not (set(ids)&set(held))
    train,y=table(data,cache,ids[:18]);dev,dy=table(data,cache,ids[18:])
    weights={}
    for name in MODELS:
        weights[name]=logistic(design(train,name),y,design(dev,name),dy)
        print(name,weights[name]['selected']['valid'],flush=True)
    tic=time.monotonic();boost=HistGradientBoostingClassifier(max_leaf_nodes=15,min_samples_leaf=60,max_iter=160,learning_rate=.08,early_stopping=False,random_state=855950)
    boost.fit(design(train,'boost'),y);value=metrics(prob(dev,'boost',boost),dy)
    with gzip.open(out/'boost.pkl.gz','wb') as tar:pickle.dump(boost,tar,protocol=5)
    record=dict(train=ids[:18],validation=ids[18:],test=held,raw_test={str(i):digest(test_data/f'{i}.npz') for i in held},
        fit_feature_receipts={str(i):digest(cache/f'{i}.json') for i in ids},table_sha=digest(price),
        constructor_sha=digest(Path(__file__).with_name('features.py')),outcomes_train=int(y.sum()),forecast_rows_train=len(y),
        weights=weights,boost=dict(sha=digest(out/'boost.pkl.gz'),validation=value.tolist(),sec=time.monotonic()-tic))
    dump(out/'SEAL.json',record);print('boost',value,flush=True)
if __name__=='__main__':
    p=argparse.ArgumentParser()
    for k in ('data','cache','test-data','price','out'):p.add_argument('--'+k,required=True,type=Path)
    a=p.parse_args()
    with threadpool_limits(limits=1):fit(a.data,a.cache,a.test_data,a.price,a.out)
