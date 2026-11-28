"""Finite-window and stationary renewal fits to fixed Allen current-clamp splits."""
import hashlib
import json
import math
import time
from functools import lru_cache
from pathlib import Path
from zipfile import ZipFile

import numpy as np
from scipy.optimize import least_squares
from scipy.special import log_ndtr, ndtr

ROOT=Path(__file__).resolve().parent
COHORTS=("ephys_records","nwb_curve_records")
MODES=("stationary","finite_fixed_noise","finite_fitted_noise")
LOW=(-3.,.1,.004,.15)
HIGH=(2.,350.,.12,16.)


def sha(p):
    with p.open("rb") as f:return hashlib.file_digest(f,"sha256").hexdigest()


def finite(I,T,theta,s,d,sigma):
    I,T=np.broadcast_arrays(np.asarray(I,float),np.asarray(T,float))
    j=np.arange(1,1+int(math.ceil(T.max()/d)),dtype=float)[None,:]
    remain=T[:,None]-(j-1)*d
    positive=remain>0
    t=np.where(positive,remain,1.)
    mu=-s*(I[:,None]-theta)
    # For very late, effectively impossible hits, keeping a whole extra
    # refractory term contributes zero and preserves derivatives at contact.
    width=sigma*np.sqrt(t)
    z1=(-j-mu*t)/width
    z2=(-j+mu*t)/width
    reflected=np.exp(np.minimum(0.,-2*mu*j/sigma**2+log_ndtr(z2)))
    # e^(-2*mu*j/sigma²) Phi(z2) is part of a probability in [0,1].
    density=np.exp(-.5*z1*z1)/math.sqrt(2*math.pi)
    F=ndtr(z1)+reflected
    F_mu=-2*j*reflected/sigma**2
    F_t=j*density/(t*width)
    F_sigma=2*j*density/(sigma*width)+4*mu*j*reflected/sigma**3
    S=lambda v:np.where(positive,v,0.).sum(1)
    return S(F),np.stack([S(s*F_mu),S(-(I[:,None]-theta)*F_mu),S(-(j-1)*F_t),S(F_sigma)],1)


def evaluate(mode,I,T,params):
    th,s,d=params[:3]
    if mode!="stationary":
        val,j=finite(I,T,th,s,d,2. if mode=="finite_fixed_noise" else params[3])
        return val,j[:,:len(params)]
    I=np.asarray(I);T=np.broadcast_to(T,I.shape)
    v=np.maximum(0,s*(I-th));den=1+d*v
    slope=np.where(v>0,T/den**2,0.)
    return T*v/den,np.stack([-s*slope,(I-th)*slope,-T*(v/den)**2],1)


def fit(mode,x,y):
    maximum=max(y.max(),1.)
    starts=[(-.65, max(1.,maximum/1.3), .012),
            (.10, max(3.,2*maximum), .006),(-.2, max(5.,1.4*maximum), .04)]
    best=None
    n=4 if mode=="finite_fitted_noise" else 3
    @lru_cache(maxsize=2)
    def cached(p):return evaluate(mode,x,np.ones(len(x)),p)
    for i,start in enumerate(starts):
        if n==4:start=(*start,(1.,3.,8.)[i])
        entry=np.clip(start,np.array(LOW[:n])+1e-6,np.array(HIGH[:n])-1e-6)
        f=least_squares(lambda p:cached(tuple(p))[0]-y,entry,
                jac=lambda p:cached(tuple(p))[1],bounds=(LOW[:n],HIGH[:n]),max_nfev=160,
                x_scale="jac",ftol=1e-8,xtol=1e-8,gtol=1e-8)
        loss=float(f.fun@f.fun)
        if best is None or loss<best["squared_error"]:
            best=dict(parameters=f.x.tolist(),squared_error=loss,scipy_status=int(f.status),nfev=f.nfev)
    return best


def jacobian_check():
    p=np.array([.19,7.3,.0364,2.43])
    x=np.array([-.8,-.15,.49,.91])
    times=np.array([.879,.943,1.0103,1.021])
    _,analytic=finite(x,times,*p)
    fd=[]
    for i in range(4):
        eps=5e-7*max(1.,abs(p[i]));dp=np.zeros(4);dp[i]=eps
        fd.append((finite(x,times,*(p+dp))[0]-finite(x,times,*(p-dp))[0])/(2*eps))
    diff=np.max(abs(analytic-np.stack(fd,1)),axis=0)
    if diff.max()>1e-5:raise ValueError(diff)
    return diff.tolist()


def main():
    checked=jacobian_check()
    book={}
    tic=time.perf_counter()
    for group in COHORTS:
        nw=group.startswith("nwb")
        path=ROOT/"data"/(group+".zip")
        rows={}
        with ZipFile(path) as z:
            for fname in sorted(f for f in z.namelist() if f.startswith("fits/")):
                r=json.loads(z.read(fname));sid=str(r["specimen" if nw else "specimen_id"])
                raw=np.asarray(r["train_amplitudes"])
                y=np.asarray(r["train_actual_counts" if nw else "train_y"])
                low,high=raw.min(),raw.max()
                x=2*(raw-low)/(high-low)-1
                rows[sid]=dict(low=float(low),high=float(high),modes={v:fit(v,x,y) for v in MODES})
                if len(rows)%12==0:print(group,len(rows),round(time.perf_counter()-tic),flush=True)
        book[group]=dict(archive_sha256=sha(path),fits=rows)
    assert not set(book[COHORTS[0]]["fits"]).intersection(book[COHORTS[1]]["fits"])
    seal=ROOT/"training_seal.json"
    seal.write_text(json.dumps(book,sort_keys=True,separators=(",",":"),allow_nan=False))
    cohorts={}
    details={}
    for group in COHORTS:
        nw=group.startswith("nwb")
        with ZipFile(ROOT/"data"/(group+".zip")) as z:
            cold=json.loads(z.read("nwb_predictions.json" if nw else "predictions.json"))
        scores={};details[group]={};metric_lists={}
        for sid,r in sorted(cold.items()):
            fitted=book[group]["fits"][sid]
            cur=np.array(r["heldout_amplitudes"]);y=np.asarray(r["mean_counts"])
            if nw:
                T=np.array([np.mean([v["duration"] for v in r["sweeps"] if int(round(v["I_pA"]))==int(a)]) for a in cur])
            else:T=np.array(r["duration_s"])
            if not np.isfinite(T).all() or np.any((T<.99)|(T>1.01)):raise ValueError("unexpected duration")
            xx=2*(cur-fitted["low"])/(fitted["high"]-fitted["low"])-1
            pred={k:vv for k,vv in r["mean_count_predictions" if nw else "predictions"].items()}
            for mode in MODES:
                pr,gr=evaluate(mode,xx,T,fitted["modes"][mode]["parameters"])
                pred[mode]=pr.tolist()
            for k,v in pred.items():
                err=np.abs(np.asarray(v)-y)
                metric_lists.setdefault(k,[]).append((float(err.mean()),
                    float(err[y==0].mean()) if (y==0).any() else None,
                    float(err[y>0].mean()) if (y>0).any() else None))
            details[group][sid]=dict(duration=T.tolist(),current=cur.tolist(),count=y.tolist(),pred=pred)
        n=len(cold);draw=np.random.default_rng(77591).integers(n,size=(10000,n))
        for name,vals in metric_lists.items():
            w=np.array([v[0] for v in vals]);row=dict(cell_mae=float(w.mean()))
            for i,label in [(1,"zero"),(2,"positive")]:
                vs=[v[i] for v in vals if v[i] is not None];row[label+"_cell_mae"]=float(np.mean(vs)) if vs else None
            for mode in MODES[1:]:
                difference=np.array([v[0] for v in metric_lists[mode]])-w
                row[mode+"_minus"]=float(difference.mean())
                row[mode+"_minus_ci95"]=np.quantile(difference[draw].mean(1),[.025,.975]).tolist()
            scores[name]=row
        cohorts[group]=dict(cells=n,levels=sum(len(r["mean_counts"]) for r in cold.values()),metrics=scores)
    f=ROOT/"held_predictions.json";f.write_text(json.dumps(details,separators=(",",":"),allow_nan=False))
    report=dict(cohorts=cohorts,archive_sha256={k:v["archive_sha256"] for k,v in book.items()},
                training_seal_sha256=sha(seal),held_predictions_sha256=sha(f),source_sha256=sha(Path(__file__)),
                jacobian_errors=checked,wall_s=time.perf_counter()-tic)
    (ROOT/"summary.json").write_text(json.dumps(report,indent=2,allow_nan=False)+"\n")
    print("terminal",report["wall_s"],flush=True)


if __name__=="__main__":main()
