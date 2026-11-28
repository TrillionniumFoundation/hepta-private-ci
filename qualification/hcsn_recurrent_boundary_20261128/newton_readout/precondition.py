"""Test a curvature-preconditioned L-BFGS reference on the same frozen returning features."""
import argparse
import json
from pathlib import Path
import time
import numpy as np
from scipy.optimize import minimize
from scipy.special import softmax
from fit_newton import DATA,SEEDS,load_data,law,make_features,local_scores,digest
STEPS=(1,5,10,20,40,80,150)
LAM=(.01,.001,.1)


def fitting(out):
    out.mkdir(parents=True,exist_ok=True)
    tic=time.perf_counter()
    x,y,actors,(tr,dev,_)=load_data(DATA)
    load_s=time.perf_counter()-tic
    tic=time.perf_counter()
    table=law("returning")
    table_s=time.perf_counter()-tic
    result={}
    for seed in SEEDS:
        start=time.perf_counter()
        both=make_features(x[np.r_[tr,dev]],"returning",seed,table)
        X,V=both[:len(tr)],both[len(tr):]
        mu,sd=X.mean(0),X.std(0).clip(.001)
        X,V=(X-mu)/sd,(V-mu)/sd
        d=X.shape[1]; k=72; n=len(tr)
        Y=np.eye(k)[y[tr]]
        freq=Y.mean(0)
        c,Q=np.linalg.eigh(np.diag(freq)-np.outer(freq,freq))
        c=np.maximum(0,c)
        # Fix the logit gauge for biases by dropping the constant class direction.
        bias_scales=np.divide(1.,np.sqrt(c),out=np.zeros_like(c),where=c>1e-10)
        g,U=np.linalg.eigh(X.T@X/n)
        g=np.maximum(0.,g)
        A,B=X@U,V@U
        prior=np.log(freq)
        hist=[]
        for lam_id,lam in enumerate(LAM):
            scales=1/np.sqrt(g[:,None]*c[None,:]+lam)
            def unpack(z):
                wt=(z[:-k].reshape(d,k)*scales)@Q.T
                bias=(z[-k:]*bias_scales)@Q.T+prior
                return wt,bias
            def objective(z):
                wt,bias=unpack(z)
                scores=A@wt+bias
                p=(softmax(scores,1)-Y)/n
                grad=(A.T@p+lam*wt)@Q
                db=p.sum(0)@Q
                return float(local_scores(scores,y[tr])[0].mean()+.5*lam*np.vdot(wt,wt)),np.r_[(grad*scales).ravel(),db*bias_scales]
            it=0
            def release(z,step):
                key=f"{seed}-{lam_id}-{step}"
                if hist and hist[-1]["key"]==key:return
                wt,bias=unpack(z)
                dev_loss=local_scores(B@wt+bias,y[dev])[0].mean()
                dest=out/(key+".npz")
                np.savez_compressed(dest,w=U@wt,b=bias,mean=mu,scale=sd)
                hist.append(dict(key=key,lambda_=lam,step=step,development=float(dev_loss),
                                 sha=digest(dest),charged_through_checkpoint=load_s+table_s+time.perf_counter()-start))
            def callback(z):
                nonlocal it
                it+=1
                if it in STEPS:release(z,it)
            fit=minimize(objective,np.zeros((d+1)*k),jac=True,method="L-BFGS-B",callback=callback,
                         options=dict(maxiter=150,ftol=1e-11,gtol=1e-7,maxcor=10))
            if fit.status not in (0,1):raise ValueError(fit.message)
            release(fit.x,int(fit.nit))
            hist[-1].update(final_grad_max=float(abs(fit.jac).max()),status=int(fit.status))
        best=min(hist,key=lambda e:e["development"])
        first={str(t):next((e["key"] for e in hist if e["development"]<=t),None) for t in (4.1,3.75)}
        result[str(seed)]=dict(history=hist,best=best["key"],first=first,
                        complete_cost=load_s+table_s+time.perf_counter()-start)
        print(seed,first,best["key"],flush=True)
    (out/"seal.json").write_text(json.dumps(result,indent=2)+"\n")


def held(out):
    meta=json.loads((out/"seal.json").read_text())
    for info in meta.values():
        for row in info["history"]:assert row["sha"]==digest(out/(row["key"]+".npz"))
    x,y,actors,(_,_,ix)=load_data(DATA)
    table=law("returning")
    details={}
    for seed in SEEDS:
        cfg=meta[str(seed)]
        tic=time.perf_counter()
        features=make_features(x[ix],"returning",seed,table)
        shared=time.perf_counter()-tic
        rec={}
        for r in cfg["history"]:
            tic=time.perf_counter()
            key=r["key"]
            with np.load(out/(key+".npz")) as z:
                scores=((features-z["mean"])/z["scale"])@z["w"]+z["b"]
            nll,acc=local_scores(scores,y[ix])
            rec[key]=dict(nll=float(nll.mean()),accuracy=float(acc.mean()),held_cost=time.perf_counter()-tic+shared)
        first={}
        for t,k in cfg["first"].items():
            first[t]=None if k is None else dict(key=k,held=rec[k]["nll"],passed=bool(rec[k]["nll"]<=float(t)),
                              charged_search_prefix=next(r["charged_through_checkpoint"] for r in cfg["history"] if r["key"]==k))
        best=cfg["best"]
        details[str(seed)]=dict(best=best,best_result=rec[best],complete_cost=cfg["complete_cost"]+rec[best]["held_cost"],
                                first=first,all_endpoints=rec)
    (out/"terminal.json").write_text(json.dumps(dict(seal=digest(out/"seal.json"),results=details),indent=2)+"\n")


if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("stage",choices=("fit","held"));p.add_argument("out",type=Path)
    a=p.parse_args();(fitting if a.stage=="fit" else held)(a.out)
