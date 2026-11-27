"""Train and score the preregistered post-hoc strict-lag retinal sensitivity."""
import argparse
import ctypes
import gzip
import hashlib
import json
from pathlib import Path
import sys
import time

import numpy as np
from scipy.optimize import brentq
from scipy.special import expit,logit
from sklearn.metrics import average_precision_score
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parent))
from retina import bce,build_kernel,get_trial_ports,histories,logistic,make_trial,Population,queries
sys.path.insert(0,str(HERE.parent/'clock_correction'))
from correct import eval_readout,features as lif_features,init as lif_init

ARMS=('boundary','flow','priced','augmented','predictive','full','lif','glm','rate')
CONDITIONS=('frozen','intercept','refit')


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def dump(path,value):path.write_text(json.dumps(value,sort_keys=True,indent=1,allow_nan=False)+'\n')


def signatures(a):
    files=[HERE/'PROTOCOL.md',Path(__file__),HERE.parent/'retina.py',HERE.parent/'trace.cpp',HERE.parents[1]/'neurons/reservoir.cpp',HERE.parents[1]/'neurons/spikes.py',HERE.parents[1]/'reachable/compress.py',HERE.parents[1]/'reachable/witness.py',HERE.parent/'clock_correction/correct.py',HERE.parent/'clock_correction/lif.cpp',HERE.parent/'clock_correction/retinal_io.py',a.legacy/'seal.json.gz',a.corrected/'SEAL.json',a.lib,a.oldlib,a.clocklib,a.core/'population.py',a.core/'he_xiong.py']
    return {str(p.name)+'|'+str(i):sha(p) for i,p in enumerate(files)}


def trial(path,num):
    t=make_trial(path,num)
    pre=np.loadtxt(path/f'SpksPre_rep{num}.txt').astype(int);post=np.loadtxt(path/f'SpksPost_rep{num}.txt').astype(int)
    eligible=(pre>=5000)&(pre<=9997)
    orig_ids=np.searchsorted(pre,post,side='right')-1;oo=(orig_ids>=0)&(post-pre[orig_ids]<=2)
    ids=orig_ids[oo];lag=post[oo]-pre[ids]
    assert np.array_equal(np.isin(np.arange(len(pre)),ids)[eligible],t['y'])
    original=t['y'].copy();remove0=np.isin(np.arange(len(pre)),ids[lag>=1])[eligible]
    prior=np.searchsorted(pre,post,side='left')-1
    ok=(prior>=0)&(post-pre[prior]<=2)
    t['old_y']=original;t['y']=np.isin(np.arange(len(pre)),prior[ok])[eligible]
    t['count']={'events':len(original),'original_positive':int(original.sum()),'strict_positive':int(t['y'].sum()),'changed':int((original!=t['y']).sum()),'vs_deleting_zero':int((t['y']!=remove0).sum()),'original_post_lag_counts':np.bincount(lag[eligible[ids]],minlength=3).tolist()}
    return t


def kernels(a):
    kernel,_=build_kernel(a.core)
    from population import BoundaryPopulation
    pop=Population(BoundaryPopulation(1,1,12))
    q=queries(pop,histories(np.random.default_rng(92747),128,8,False))
    u,_,_=np.linalg.svd(q-q.mean(0),full_matrices=False)
    lib=ctypes.CDLL(str(a.lib.resolve()));oldlib=ctypes.CDLL(str(a.oldlib.resolve()))
    dp=np.ctypeslib.ndpointer(dtype=np.float64,flags='C_CONTIGUOUS');ip=np.ctypeslib.ndpointer(dtype=np.int32,flags='C_CONTIGUOUS')
    lib.capture.argtypes=[ctypes.c_int]*4+[ctypes.c_double]*3+[dp]*4+[ip,ctypes.c_int,dp];lib.capture.restype=None
    oldlib.reservoir.argtypes=[ctypes.c_int]*5+[ctypes.c_double]*3+[dp]*5;oldlib.reservoir.restype=None
    return kernel,u[:,:7],pop.port[:,3:],lib,oldlib,lif_init(a.clocklib)


def panel(trials,mu,sd,backend):
    kernel,basis,hz,lib,oldlib,lif=backend;store={}
    for scale in (.6,1.3):
        features=[get_trial_ports(t,scale,mu,sd,lib,oldlib,kernel,basis,hz) for t in trials]
        for arm in ARMS:store[arm,scale]=np.vstack([f[arm] for f in features])
        store['lif',scale]=lif_features(trials,scale,mu,sd,lif,1.)
    return store


def incumbents(a):
    old=json.loads(gzip.decompress((a.legacy/'seal.json.gz').read_bytes()))
    incumbent={k:dict(old['all_fits'][k][old['model_selection'][k]]) for k in ARMS}
    corr=json.loads((a.corrected/'SEAL.json').read_bytes());rec=corr['candidates'][corr['selected']]
    incumbent['lif']={'scale':rec['scale'],'fit':rec['readout']}
    return incumbent,old


def fit(a):
    if a.seal.exists():raise FileExistsError(a.seal)
    begin=time.perf_counter();trials=[trial(a.data,i) for i in range(1,56,2)];backend=kernels(a)
    orig,old=incumbents(a);assert all(t['input_sha']==old['input_hashes'][str(t['id'])] for t in trials)
    pool=np.vstack([t['features'] for t in trials if t['id']<=43]);mu=pool.mean(0);sd=pool.std(0).clip(1e-7)
    inputs=panel(trials,mu,sd,backend);y=np.concatenate([t['y'] for t in trials])
    rep=np.concatenate([np.repeat(t['id'],len(t['y'])) for t in trials])
    train=rep<=43;dev=rep>=45;candidates={};selected={};intercepts={}
    for k in ARMS:
        m=orig[k];x=inputs[k,m['scale']];oldp=eval_readout(x,m['fit'])
        l=logit(oldp[train]);offset=brentq(lambda b:float(expit(l+b).mean()-y[train].mean()),-40.,40.,xtol=1.e-13)
        intercepts[k]=float(offset);opts=[]
        for scale in ((.6,) if k=='rate' else (.6,1.3)):
            for reg in ((.01,) if k=='rate' else (.01,.0001)):
                p,c=logistic(inputs[k,scale],y,train,reg)
                opts.append({'scale':scale,'ridge':reg,'fit':c,'dev_bce':float(bce(p[dev],y[dev]).mean())})
        candidates[k]=opts;selected[k]=int(np.argmin([o['dev_bce'] for o in opts]))
    dump(a.seal,{'code':signatures(a),'mu':mu.tolist(),'sd':sd.tolist(),'selection':selected,'candidates':candidates,'intercepts':intercepts,'input_sha':{t['id']:t['input_sha'] for t in trials},'trials':{t['id']:t['count'] for t in trials},'fit_wall':time.perf_counter()-begin})


def confirm(a):
    file=a.out/'strict_predictions.npz'
    if file.exists():raise FileExistsError(file)
    begin=time.perf_counter();a.out.mkdir(exist_ok=True,parents=True);s=json.loads(a.seal.read_bytes());assert signatures(a)==s['code']
    trials=[trial(a.data,i) for i in range(57,76,2)];orig,old=incumbents(a);assert all(t['input_sha']==old['input_hashes'][str(t['id'])] for t in trials)
    x=panel(trials,np.array(s['mu']),np.array(s['sd']),kernels(a));y=np.concatenate([t['y'] for t in trials]);original=np.concatenate([t['old_y'] for t in trials]);time_ms=np.concatenate([t['indices'] for t in trials])
    rep=np.concatenate([np.repeat(t['id'],len(t['y'])) for t in trials]);pred={}
    for k in ARMS:
        m=orig[k];pred['frozen_'+k]=eval_readout(x[k,m['scale']],m['fit'])
        pred['intercept_'+k]=expit(logit(pred['frozen_'+k])+s['intercepts'][k])
        opt=s['candidates'][k][s['selection'][k]]
        pred['refit_'+k]=eval_readout(x[k,opt['scale']],opt['fit'])
    with np.load(a.legacy/'cold.npz') as legacy,np.load(a.corrected/'cold.npz') as fixed:
        assert np.array_equal(y.shape,legacy['y'].shape) and np.array_equal(original,legacy['y']) and np.array_equal(rep,legacy['repeat']) and np.array_equal(time_ms,legacy['time_ms'])
        gaps={k:float(abs(pred['frozen_'+k]-(fixed['corrected_lif'] if k=='lif' else legacy[k])).max()) for k in ARMS}
        assert max(gaps.values())<1e-10,gaps
        old_lif=legacy['lif']
    np.savez_compressed(file,y=y,old_y=original,repeat=rep,time_ms=time_ms,legacy_lif_2ms=old_lif,**pred)
    g=np.unique(rep);rand=np.random.default_rng(30588).integers(0,len(g),(6000,len(g)))
    def stats(v):
        by=np.array([v[rep==i].mean() for i in g]);return {'pooled':float(v.mean()),'balanced':float(by.mean()),'ci95':np.quantile(by[rand].mean(1),[.025,.975]).tolist(),'by_repeat':by.tolist()}
    metrics={};paired={};between={}
    for con in CONDITIONS:
        for k in ARMS:
            key=con+'_'+k;pr=pred[key]
            metrics[key]={'loss':stats(bce(pr,y)),'brier':stats((pr-y)**2),'calibration':stats(pr-y),'ap':float(average_precision_score(y,pr))}
        for ref in ARMS:
            key=con+'_predictive_minus_'+ref
            paired[key]=stats(bce(pred[con+'_predictive'],y)-bce(pred[con+'_'+ref],y))
    for k in ARMS:
        for left,right in [('intercept','frozen'),('refit','intercept'),('refit','frozen')]:
            between[k+'_'+left+'_minus_'+right]=stats(bce(pred[left+'_'+k],y)-bce(pred[right+'_'+k],y))
    dump(a.out/'RESULTS.json',{'seal_sha256':sha(a.seal),'predictions_sha256':sha(file),'trial_counts':{t['id']:t['count'] for t in trials},'frozen_replay_errors':gaps,'metrics':metrics,'paired':paired,'effect_of_recalibration_or_refit':between,'legacy_lif_strict_frozen_loss':stats(bce(old_lif,y)),'cold_wall':time.perf_counter()-begin})
    print('cold',len(y),'original',original.sum(),'strict',y.sum(),'frozen max',max(gaps.values()),flush=True)


if __name__=='__main__':
    q=argparse.ArgumentParser();q.add_argument('cmd',choices=('fit','score'))
    for k in ('data','core','lib','oldlib','clocklib','legacy','corrected','seal','out'):q.add_argument(k,type=Path)
    a=q.parse_args();(fit if a.cmd=='fit' else confirm)(a)
