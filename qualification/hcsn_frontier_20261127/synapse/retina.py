"""Recorded retinal input to postsynaptic output, with different time-local population ports."""
import argparse
import ctypes
import hashlib
import json
import sys
import time
from pathlib import Path

import numpy as np
from scipy.optimize import minimize
from scipy.signal import lfilter
from scipy.special import expit
from sklearn.metrics import average_precision_score

SIBLING=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(SIBLING/'neurons'))
from spikes import build_kernel
sys.path.insert(0,str(SIBLING/'reachable'))
from compress import histories,queries
from witness import Population


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def make_trial(folder,idx):
    files=[folder/f'Spks{k}_rep{idx}.txt' for k in ('Pre','Post')]
    pre,post=[np.loadtxt(f) for f in files]
    assert np.allclose(pre,np.rint(pre)) and np.allclose(post,np.rint(post))
    pre=pre.astype(int);post=post.astype(int)
    assert (np.diff(pre)>=0).all() and (np.diff(post)>=0).all()
    pos=np.searchsorted(pre,post,side='right')-1
    ok=(pos>=0)&(post-pre[pos]<=2);outcomes=np.isin(np.arange(len(pre)),pos[ok])
    eligible=(pre>=5000)&(pre<=9997)
    stream=np.bincount(pre[(pre>=0)&(pre<10000)],minlength=10000)
    bank=[]
    for tau in (2,4,8,16,40,100):
        a=np.exp(-1/tau);bank.append(lfilter([1.],[1,-a],stream))
    return dict(id=idx,features=np.stack(bank,-1),indices=np.ascontiguousarray(pre[eligible],dtype=np.int32),y=outcomes[eligible],input_sha=[sha(f) for f in files])


def get_trial_ports(trial,scale,center,sd,lib,lif_lib,kernel,basis,horizons):
    mats,reset,prices,_,ratio,step,start=kernel
    x=np.ascontiguousarray((trial['features']-center)/sd*scale)
    width=x.shape[1];n=len(reset);idx=trial['indices']
    state=np.zeros((len(idx),width,n+4))
    lib.capture(len(x),width,n-1,len(mats),start,step,ratio,x,mats,reset,prices,idx,len(idx),state)
    np.testing.assert_allclose(state[:,:,4:].sum(-1),1.,atol=2e-12)
    trac=np.zeros((len(x),width,4))
    lif_lib.reservoir(3,len(x),width,n-1,len(mats),start,step,ratio,x,mats,reset,prices,trac)
    st=state[:,:,4:];b=state[:,:,:1]
    return {k:v.reshape(len(idx),-1) for k,v in {
        'boundary':b,'flow':state[:,:,:2],'priced':state[:,:,:4],
        'augmented':np.concatenate([state[:,:,:4],st@horizons],-1),
        'predictive':np.concatenate([b,st@basis],-1),'full':np.concatenate([b,st[:,:,:-1]],-1),
        'lif':trac[idx],'glm':x[idx],'rate':np.empty((len(idx),0))}.items()}


def logistic(x,y,t,ridge):
    mean=x[t].mean(0);sd=x[t].std(0).clip(1e-8)
    z=np.column_stack([np.ones(len(x)),(x-mean)/sd]);a=z[t];b=y[t].astype(float)
    def fn(w):
        logits=a@w;r=w.copy();r[0]=0
        return np.mean(np.logaddexp(0,logits)-b*logits)+.5*ridge*(r@r),a.T@(expit(logits)-b)/len(b)+ridge*r
    w=np.zeros(z.shape[1]);w[0]=np.log(b.mean()/(1-b.mean()))
    sol=minimize(fn,w,jac=True,method='L-BFGS-B',options={'maxiter':300,'ftol':1e-12,'gtol':1e-8})
    return expit(z@sol.x).clip(1e-10,1-1e-10),dict(params=sol.x.tolist(),mean=mean.tolist(),sd=sd.tolist(),status=str(sol.message))


def bce(p,y):
    return -(y*np.log(p)+(1-y)*np.log1p(-p))


def main(args):
    args.out.mkdir(exist_ok=True,parents=True)
    trials=[make_trial(args.data,i) for i in range(1,76,2)]
    train=np.vstack([a['features'] for a in trials if a['id']<=43])
    center=train.mean(0);sd=train.std(0).clip(1e-7)
    kernel,num=build_kernel(args.core)
    from population import BoundaryPopulation
    pop=Population(BoundaryPopulation(1,1,12))
    q=queries(pop,histories(np.random.default_rng(92747),128,8,False))
    U,s,_=np.linalg.svd(q-q.mean(0),full_matrices=False)
    basis=U[:,:7];probes=pop.port[:,3:]
    lib=ctypes.CDLL(str(args.lib.resolve()));lif_lib=ctypes.CDLL(str(args.lif.resolve()))
    dp=np.ctypeslib.ndpointer(dtype=np.float64,flags='C_CONTIGUOUS')
    ip=np.ctypeslib.ndpointer(dtype=np.int32,flags='C_CONTIGUOUS')
    common=[ctypes.c_int]*4+[ctypes.c_double]*3
    lib.capture.argtypes=common+[dp]*4+[ip,ctypes.c_int,dp];lib.capture.restype=None
    lif_lib.reservoir.argtypes=[ctypes.c_int]*5+[ctypes.c_double]*3+[dp]*5
    lif_lib.reservoir.restype=None
    reps=np.concatenate([np.repeat(t['id'],len(t['y'])) for t in trials])
    times=np.concatenate([t['indices'] for t in trials]);y=np.concatenate([t['y'] for t in trials])
    train,dev,cold=reps<=43,(reps>=45)&(reps<=55),reps>=57
    scores={};records={};clocks={}
    for scale in (.6,1.3):
        c=time.perf_counter()
        feats=[get_trial_ports(t,scale,center,sd,lib,lif_lib,kernel,basis,probes) for t in trials]
        clocks[scale]=time.perf_counter()-c
        for k in feats[0]:
            if scale==1.3 and k=='rate':continue
            x=np.vstack([f[k] for f in feats])
            for ridge in ((.01,.0001) if k!='rate' else (.01,)):
                c=time.perf_counter();p,params=logistic(x,y,train,ridge)
                v=float(bce(p[dev],y[dev]).mean())
                records.setdefault(k,[]).append(dict(score=v,ridge=ridge,scale=scale,fit=params,fit_wall=time.perf_counter()-c))
                scores.setdefault(k,[]).append(p[cold])
    selected={k:int(np.argmin([a['score'] for a in rec])) for k,rec in records.items()}
    sealf=args.out/'seal.json'
    sealf.write_text(json.dumps({'model_selection':selected,'all_fits':records,'input_hashes':{t['id']:t['input_sha'] for t in trials},'transition':num,'features_s':clocks,'code':{p.name:sha(p) for p in [Path(__file__),Path(__file__).with_name('trace.cpp')]},'n_train_dev_cold':list(map(int,[train.sum(),dev.sum(),cold.sum()]))},indent=1)+'\n')
    ps={k:scores[k][i] for k,i in selected.items()};y=y[cold];reps=reps[cold]
    raw=args.out/'cold.npz';np.savez_compressed(raw,y=y,repeat=reps,time_ms=times[cold],**ps)
    ids=np.random.default_rng(30588).integers(0,10,(6000,10));groups=np.unique(reps)
    def stats(v):
        per=np.array([v[reps==g].mean() for g in groups])
        return dict(pooled=float(v.mean()),balanced=float(per.mean()),repeat_interval=np.quantile(per[ids].mean(1),[.025,.975]).tolist(),per_repeat=per.tolist())
    loss={k:bce(p,y) for k,p in ps.items()}
    results={}
    for k,p in ps.items():
        results[k]={'logloss':stats(loss[k]),'brier':stats((p-y)**2),'ap_pooled':float(average_precision_score(y,p)),'calibration_signed':stats(p-y),'bits_per_event_vs_rate':stats((loss['rate']-loss[k])/np.log(2))}
    report={'seal_sha256':sha(sealf),'prediction_sha256':sha(raw),'recording_repeats':len(groups),'cold_events':len(y),'matched_events':int(y.sum()),'models':results,'difference_predictive_minus':{k:stats(loss['predictive']-loss[k]) for k in ps if k!='predictive'},'difference_augmented_minus_boundary':stats(loss['augmented']-loss['boundary'])}
    (args.out/'scores.json').write_text(json.dumps(report,indent=1)+'\n')
    print({k:round(v['logloss']['balanced'],6) for k,v in results.items()},flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser()
    for k in ('lib','lif','core','out','data'):p.add_argument('--'+k,type=Path,required=True)
    main(p.parse_args())
