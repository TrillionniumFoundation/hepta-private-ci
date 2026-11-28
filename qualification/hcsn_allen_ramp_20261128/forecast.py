"""Fit, select, seal and cold-score conditional event hazards in real-time units."""
import argparse
import ctypes
from pathlib import Path
import hashlib
import json
import subprocess
import time
import numpy as np
from scipy.optimize import minimize
from scipy.special import log_ndtr
from scipy.signal import lfilter
ROOT=Path(__file__).resolve().parent
EPS=1e-10;DT=.002
ARMS={"dual":[50,100,200],"equity":[50,100,200],"loss":[50,100,200],"no_price":[50,100,200],"lif":[5,15,40],"glm":[0],"constant":[0]}
MODES={"dual":0,"equity":1,"loss":2,"no_price":3}
def sha(p):
    with p.open("rb") as f:return hashlib.file_digest(f,"sha256").hexdigest()
def put(p,x):
    raw=(json.dumps(x,sort_keys=True,indent=2,allow_nan=False)+"\n").encode()
    if p.exists() and p.read_bytes()!=raw:raise ValueError("immutable receipt "+str(p))
    if not p.exists():p.write_bytes(raw)
def kernel(grid):
    d=np.linspace(-5.,5.,4097)[:,None,None];x=grid[None,:,None]
    q=np.r_[0.,(grid[:-1]+grid[1:])/2][None,None,:]
    s=.23*np.sqrt(.25);dr=d*.25
    l0=log_ndtr((x+dr-q)/s);l1=-2*d*x/.23**2+log_ndtr((-x+dr-q)/s)
    tail=np.exp(l0)*(-np.expm1(np.minimum(0.,l1-l0)))
    live=np.concatenate((tail[:,:,:-1]-tail[:,:,1:],tail[:,:,-1:]),-1)
    hit=np.exp(log_ndtr((-x-dr)/s))+np.exp(-2*d*x/.23**2+log_ndtr((-x+dr)/s))
    v=np.concatenate((live,hit),-1)
    assert v.min()>-1e-12 and np.abs(v.sum(-1)-1).max()<1e-11
    return np.ascontiguousarray(np.clip(v,0,1))
class Model:
    def __init__(self,src,law):
        self.source=src
        assert sha(law)=="de7378f3c170750fb16d1280bcaa376a8904a207da32d268cac82525469e2ea4"
        with np.load(law) as f:self.s={k:np.ascontiguousarray(f[k],dtype=float) for k in f.files}
        self.table=kernel(self.s["grid"]);self.lib=ctypes.CDLL(str(ROOT/"physical.so"))
        F=np.ctypeslib.ndpointer(dtype=np.float64,flags="C_CONTIGUOUS");Y=np.ctypeslib.ndpointer(dtype=np.uint16,flags="C_CONTIGUOUS")
        self.lib.boundary_feature.argtypes=(ctypes.c_size_t,F,Y,F,F,F,F,F,ctypes.c_double,ctypes.c_double,ctypes.c_int,F)
        self.lib.boundary_feature.restype=ctypes.c_int;self.lib.lif_feature.argtypes=(ctypes.c_size_t,F,Y,ctypes.c_double,F)
        self.lib.lif_feature.restype=None;self.cache={}
    def traces(self,roster):
        out=[]
        for sid in roster:
            fold=self.source/str(sid);rec=json.loads((fold/"attempt-v2.json").read_text())
            assert sha(fold/"signals-v2.npz")==rec["signals_sha256"]
            with np.load(fold/"signals-v2.npz",allow_pickle=False) as f:
                for i,v in enumerate(rec["sweeps"]):
                    y=f[f"occupied_counts_{i}"].astype(np.uint16);x=f[f"current_bin_pA_{i}"].astype(float)
                    raw=f[f"stimulus_native_{i}"];times=f[f"spike_times_s_{i}"];width=int(round(v["rates_hz"]*DT))
                    assert np.array_equal(x.astype(np.float32),(raw.astype(float).reshape(-1,width).mean(1)*v["current_multiplier_pA"]).astype(np.float32))
                    assert np.array_equal(y,np.bincount(np.floor(times/DT).astype(int),minlength=len(y)))
                    out.append((sid,v["row"]["sweep_number"],x,y))
        return out
    def features(self,arm,opt,trace):
        sid,sweep,x,y=trace;key=(sid,sweep,arm,opt)
        if key in self.cache:return self.cache[key]
        arr=np.zeros(len(y));active=np.r_[True,y[:-1]==0]
        if arm in MODES:
            s=self.s
            rc=self.lib.boundary_feature(len(y),x,y,self.table,s["grid"],s["reset"],s["pmid"],s["pd"],float(s["kappa"].item()),opt,MODES[arm],arr)
            if rc:raise ValueError(("physical",rc))
            X=arr[:,None]
        elif arm=="lif":
            self.lib.lif_feature(len(y),x,y,opt,arr);X=arr[:,None]
        elif arm=="glm":
            raw=x/100.;lag=np.r_[0.,(y[:-1]>0).astype(float)]
            def filt(a,tau):
                d=np.exp(-2/tau);return lfilter([1-d],[1,-d],a)
            X=np.column_stack([raw,*[filt(raw,tau) for tau in (5,20,80)],*[filt(lag,tau) for tau in (5,20,80)]])
        else:X=np.empty((len(y),0))
        self.cache[key]=(X,active);return X,active
def features(model,data,arm,opt):
    pairs=[model.features(arm,opt,v) for v in data];X=np.vstack([v[0] for v in pairs]);active=np.concatenate([v[1] for v in pairs])
    y=np.concatenate([v[3]>0 for v in data]);ids=np.concatenate([np.full(len(v[3]),v[0]) for v in data])
    n=len(np.unique(ids));w=np.zeros(len(y))
    for sid in np.unique(ids):sel=ids==sid;w[sel]=1./(n*sel.sum())
    return X,active,y,w
def probability(eta):
    q=np.exp(np.clip(eta,-35,9));return np.clip(-np.expm1(-q),EPS,1-EPS)
def fit(model,data,arm,opt):
    X,active,y,weights=features(model,data,arm,opt);X=X[active];w=weights[active];y=y[active]
    mean=np.average(X,weights=w,axis=0);std=np.sqrt(np.maximum(1e-12,np.average((X-mean)**2,weights=w,axis=0)))
    Z=np.column_stack((np.ones(len(y)),(X-mean)/std));initial=np.zeros(Z.shape[1])
    initial[0]=np.log(-np.log1p(-np.clip(np.average(y,weights=w),1e-6,.99)))
    def objective(v):
        eta=Z@v;p=probability(eta);q=np.exp(np.clip(eta,-35,9))
        loss=np.dot(w,-np.where(y,np.log(p),np.log1p(-p)))
        grad=np.where(y,-q*np.exp(-q)/p,q)
        grad=np.where((p>EPS)&(p<1-EPS),grad,0.)
        ridge=1e-7*np.dot(v[1:],v[1:]);g=Z.T@(w*grad);g[1:]+=2.e-7*v[1:]
        return float(loss+ridge),g
    bounds=[(-30.,10.)]+[(0.,25.) if arm in (*MODES,"lif") else (-25.,25.) for _ in range(Z.shape[1]-1)]
    z=minimize(objective,initial,jac=True,method="L-BFGS-B",bounds=bounds,options=dict(maxiter=500,ftol=1e-13,gtol=1e-9,maxls=40))
    if not z.success:raise ValueError((arm,opt,z.message))
    return dict(arm=arm,opt=opt,mean=mean.tolist(),sd=std.tolist(),weights=z.x.tolist(),converged=bool(z.success),iterations=z.nit)
def predict(model,tr,reg):
    X,active=model.features(reg["arm"],reg["opt"],tr);v=np.array(reg["weights"])
    p=probability(v[0]+((X-np.asarray(reg["mean"]))/np.asarray(reg["sd"]))@v[1:]);p[~active]=EPS;return p
def score(p,y):
    y=y>0;loss=-np.where(y,np.log(p),np.log1p(-p))
    e=np.flatnonzero(y);n=int(e[0]+1) if len(e) else len(y)
    return np.array([loss.sum(),((p-y)**2).sum(),loss[:n].sum(),len(y),y.sum(),1.])
def combined(model,data,reg):
    out={};prob={}
    for tr in data:
        sid,sweep,x,y=tr;p=predict(model,tr,reg);prob[f"{sid}-{sweep}"]=p
        sc=score(p,y);out[sid]=out.get(sid,np.zeros(6))+sc
    return out,prob
def summarize(rows):
    v=np.array(list(rows.values()));return [float(np.mean(v[:,0]/(v[:,3]*DT))),float(np.mean(v[:,1]/v[:,3])),float(np.mean(v[:,2]/v[:,5]))]
def run(args):
    src=args.source;dest=args.out;dest.mkdir(exist_ok=True,parents=True);cohort=json.loads((src/"cohort.json").read_text())
    model=Model(src,args.law)
    if args.mode=="fit":
        tr=model.traces(cohort["train"]);dev=model.traces(cohort["dev"]);result={}
        for arm,options in ARMS.items():
            candidates=[]
            for opt in options:
                r=fit(model,tr,arm,opt);scores=summarize(combined(model,dev,r)[0]);candidates.append(dict(option=opt,nll_per_s=scores[0],fit=r))
            selected=min(candidates,key=lambda r:r["nll_per_s"])["option"]
            result[arm]=dict(candidates=candidates,selected=fit(model,tr+dev,arm,selected));print(arm,selected,flush=True)
        put(dest/"seal.json",dict(models=result,cohort_sha256=sha(src/"cohort.json"),law_sha256=sha(args.law),source_sha256=sha(Path(__file__)),c_sha256=sha(ROOT/"physical.c"),library_sha256=sha(ROOT/"physical.so")))
        return
    seal=json.loads((dest/"seal.json").read_text())
    assert seal["cohort_sha256"]==sha(src/"cohort.json") and seal["law_sha256"]==sha(args.law) and seal["source_sha256"]==sha(Path(__file__)) and seal["c_sha256"]==sha(ROOT/"physical.c") and seal["library_sha256"]==sha(ROOT/"physical.so")
    held=model.traces(cohort["held"]);all_rows={};summary={};proof={};bins=0;baseline=None
    for arm,reg in seal["models"].items():
        rows,prob=combined(model,held,reg["selected"]);all_rows[arm]={str(k):v.tolist() for k,v in rows.items()};summary[arm]=summarize(rows)
        for key,arr in prob.items():
            p=dest/(arm+"-"+key+".npz")
            if args.mode=="score" and not p.exists():np.savez_compressed(p,probability=arr)
            with np.load(p) as f:assert np.array_equal(arr,f["probability"])
            proof[p.name]=sha(p);bins+=len(arr)
    draws=np.random.default_rng(950183).integers(0,len(cohort["held"]),(10000,len(cohort["held"])))
    paired={}
    def rates(arm):
        v=np.array([all_rows[arm][str(sid)] for sid in cohort["held"]])
        return np.stack((v[:,0]/(v[:,3]*DT),v[:,1]/v[:,3],v[:,2]/v[:,5]),1)
    for arm in ARMS:
        if arm=="dual":continue
        diff=rates("dual")-rates(arm);paired[arm]=dict(delta=diff.mean(0).tolist(),ci95=np.quantile(diff[draws].mean(1),[.025,.975],axis=0).T.tolist())
    base=np.array(list(all_rows["constant"].values()));base_nll=base[:,0].sum();event_count=base[:,4].sum()
    bits={k:float((base_nll-np.asarray(list(v.values()))[:,0].sum())/(np.log(2)*event_count)) for k,v in all_rows.items()}
    trial=[dict(specimen=int(sid),sweep=int(sw),bins=len(y),spikes=int(y.sum()),occupied=int((y>0).sum())) for sid,sw,x,y in held]
    value=dict(seal_sha256=sha(dest/"seal.json"),metrics=summary,metrics_order=["mean_specimen_nll_per_second","mean_specimen_brier_per_bin","mean_specimen_first_or_censor_nll_per_trial"],nll_per_bin={k:v[0]*DT for k,v in summary.items()},pooled_bits_per_occupied_bin=bits,
               primary_superiority=all(paired[arm]["ci95"][0][1]<0 and paired[arm]["delta"][1]<0 for arm in ("lif","glm","no_price")),paired_dual_minus=paired,records=trial,specimen_sums=all_rows,raw_probability_files=proof,replayed_bins_across_arms=bins)
    put(dest/"terminal.json",value)
    if args.mode=="verify":put(dest/"cold_verification.json",dict(terminal_sha256=sha(dest/"terminal.json"),seal_sha256=sha(dest/"seal.json"),replayed_bins=bins,raw_predictions=len(proof),max_absolute_error=0.))
if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("mode",choices=["fit","score","verify"]);p.add_argument("source",type=Path);p.add_argument("law",type=Path);p.add_argument("out",type=Path)
    run(p.parse_args())
