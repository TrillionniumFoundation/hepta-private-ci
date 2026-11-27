"""Layerwise Forward Projection with two standard ReLU controls and physical variants."""
import time
ENTRY=time.perf_counter();ENTRY_CPU=time.process_time()
import argparse
import json
from pathlib import Path
import numpy as np
from model import FP_ARMS,SEEDS,RUNGS,Cell,clone,fp_activation,fp_readout_features,macro,prep,read_batches,ridge,sha


def local_solve(X,Y,Q,U,reg):
    # Eq. 4 of O'Shea and Rajendran, target preactivation contains both signals.
    a=X.reshape(-1,X.shape[-1]);yt=np.repeat(Y,X.shape[1],axis=0)
    target=np.sign(a@Q)+np.sign(yt@U)
    gram=a.T@a/len(a);scale=np.trace(gram)/len(gram)
    return np.linalg.solve(gram+(reg*max(scale,1e-9)+1e-10)*np.eye(len(gram)),a.T@target/len(a))


def main():
    q=argparse.ArgumentParser()
    for n in ('archive','law','out'):q.add_argument(n,type=Path)
    q.add_argument('arm',choices=FP_ARMS);q.add_argument('seed',type=int,choices=SEEDS);a=q.parse_args()
    x,y,_,ids=read_batches(a.archive,range(1,6));xv,yv,bv,v_ids=read_batches(a.archive,(6,7))
    x0=np.sign(x)*np.log1p(abs(x));p={'mean':x0.mean(0),'sd':np.maximum(x0.std(0),1e-6)}
    t=prep(x,p);v=prep(xv,p);TY=np.eye(6)[y]
    physical=a.arm in ('fp_hcsn','fp_shuffle')
    law=Cell(a.law) if physical else None
    ww=32 if a.arm in ('fp_relu32','fp_flat32') else 8
    X=t.reshape(len(t),1,-1) if a.arm=='fp_flat32' else t
    status={'seed':a.seed,'arm':a.arm,'archive_sha256':sha(a.archive),'law_sha256':sha(a.law),'n_train':len(y),'n_dev':len(yv),'train_dev_duplicate_feature_ids':len(set(ids)&set(v_ids)),'common_process_wall':time.perf_counter()-ENTRY,'common_process_cpu':time.process_time()-ENTRY_CPU}
    started=time.perf_counter();cpu=time.process_time()
    rng=np.random.default_rng(a.seed)
    p0=[rng.normal(0,1/np.sqrt(X.shape[-1]),(X.shape[-1],ww)),rng.normal(0,1/np.sqrt(ww),(ww,ww))]
    # Shared target keys across width-matched physical, ReLU, shuffle.
    keys=[(rng.normal(size=(n,ww)),rng.normal(size=(6,ww))) for n in (X.shape[-1],ww)]
    localY=TY[rng.permutation(len(y))] if a.arm=='fp_shuffle' else TY
    hist=[];saved={r:None for r in RUNGS};best={r:None for r in RUNGS}
    for reg in (.001,.03,.3):
        p['w1']=local_solve(X,localY,*keys[0],reg)
        h=fp_activation(X,p['w1'],physical,law)
        if physical:h=h[...,0]
        p['m1']=h.mean((0,1));p['s1']=np.maximum(h.std((0,1)),1e-4)
        inp2=(h-p['m1'])/p['s1'];p['w2']=local_solve(inp2,localY,*keys[1],reg)
        h2=fp_activation(inp2,p['w2'],physical,law).reshape(len(t),-1)
        p['mh']=h2.mean(0);p['sh']=np.maximum(h2.std(0),1e-4)
        H=np.column_stack(((h2-p['mh'])/p['sh'],np.ones(len(h2))))
        p['w3']=ridge(H,TY,reg);z=fp_readout_features(v,p,a.arm,law)@p['w3']
        m=macro(z,yv,bv);mse=float(np.mean((z-np.eye(6)[yv])**2))
        c=time.process_time()-cpu;w=time.perf_counter()-started
        row={'penalty':reg,'hidden_updates':[1,1],'dev_macro':m,'dev_mse':mse,'fit_cpu':c,'fit_wall':w}
        hist.append(row)
        for r in RUNGS:
            rank=(m,-mse)
            if c<=r and (best[r] is None or rank>best[r]):saved[r]=(clone(p),dict(row));best[r]=rank
    a.out.mkdir(exist_ok=True,parents=True);status.update({'fit_cpu':time.process_time()-cpu,'fit_wall':time.perf_counter()-started,'history':hist,'selected':{}})
    for r,s in saved.items():
        if s is None:status['selected'][r]=None;continue
        state,row=s;file=a.out/f'{a.arm}_{a.seed}_{r}.npz';np.savez_compressed(file,**state)
        status['selected'][r]={**row,'sha256':sha(file),'hidden_deltas':[float(np.linalg.norm(state[k]-w)) for k,w in zip(('w1','w2'),p0)]}
    (a.out/f'{a.arm}_{a.seed}.json').write_text(json.dumps(status,indent=1)+'\n')
    print(a.arm,a.seed,len(hist),flush=True)


if __name__=='__main__':main()
