"""Open-loop hard-threshold leaky integrate-and-fire comparison and censored onset diagnostics."""
import argparse,ctypes,json
from pathlib import Path
import numpy as np
from scipy.optimize import minimize
from scipy.signal import lfilter
from forecast import ROOT,EPS,DT,Model,score,summarize,sha,put
TAU=(5,15,40);THETA=(20,40,60,80,100,130,160,200,250,320,400,600,800)
class OpenLoop:
    def __init__(self):
        self.lib=ctypes.CDLL(str(ROOT/"hard_lif.so"));self.f=self.lib.deterministic_lif
        self.f.argtypes=(ctypes.c_size_t,np.ctypeslib.ndpointer(dtype=np.float64,flags="C_CONTIGUOUS"),ctypes.c_double,ctypes.c_double,np.ctypeslib.ndpointer(dtype=np.uint8,flags="C_CONTIGUOUS"));self.f.restype=None;self.cache={}
    def one(self,tr,tau,theta):
        sid,sw,x,y=tr;key=sid,sw,tau,theta
        if key not in self.cache:
            events=np.zeros(len(x),dtype=np.uint8);self.f(len(x),x,tau,theta,events);kernel=lfilter([1.],[1.,-np.exp(-2./6)],events.astype(float));self.cache[key]=events,kernel
        return self.cache[key]
def fit(openloop,tr,tau,theta):
    hs=[];ys=[];ws=[];ids={t[0] for t in tr};sizes={i:sum(len(t[3]) for t in tr if t[0]==i) for i in ids}
    for t in tr:
        hs.append(openloop.one(t,tau,theta)[1]);ys.append(t[3]>0);ws.append(np.full(len(t[3]),1./(len(ids)*sizes[t[0]])))
    h=np.concatenate(hs);y=np.concatenate(ys);w=np.concatenate(ws)
    def fun(v):
        b,g=np.exp(v);q=b+g*h;p=np.clip(-np.expm1(-q),EPS,1.-EPS)
        raw=-np.where(y,np.log(p),np.log1p(-p));grad=np.where(y,-np.exp(-q)/p,1.)
        grad=np.where((p>EPS)&(p<1-EPS),grad,0.);grad*=w
        return np.dot(w,raw),np.array([b*grad.sum(),g*np.dot(h,grad)])
    r=minimize(fun,[-6.,-2.],jac=True,method="L-BFGS-B",bounds=[(-23,2),(-23,3)],options=dict(maxiter=300,ftol=1e-13,gtol=1e-11))
    if not r.success:raise ValueError(r.message)
    return dict(tau=tau,threshold=theta,log_amplitudes=r.x.tolist())
def evaluate(model,tr,reg):
    rows={};signals={};b,g=np.exp(reg["log_amplitudes"])
    for item in tr:
        sid,sw,x,y=item;events,h=model.one(item,reg["tau"],reg["threshold"]);p=np.clip(-np.expm1(-b-g*h),EPS,1.-EPS)
        rows[sid]=rows.get(sid,np.zeros(6))+score(p,y);signals[f"{sid}-{sw}"]=(p,events)
    return rows,signals
def run(mode):
    src=ROOT/"source";out=ROOT/"hard-lif";out.mkdir(exist_ok=True);source=json.loads((src/"cohort.json").read_text());data=Model(src,ROOT/"law4.npz");m=OpenLoop()
    if mode=="fit":
        tr=data.traces(source["train"]);dev=data.traces(source["dev"]);c=[]
        for tau in TAU:
            for theta in THETA:
                reg=fit(m,tr,tau,theta);v=summarize(evaluate(m,dev,reg)[0]);c.append(dict(setup=reg,development=v))
        best=min(c,key=lambda v:v["development"][0])["setup"];final=fit(m,tr+dev,best["tau"],best["threshold"])
        put(out/"seal.json",dict(candidates=c,selected=final,protocol_sha256=sha(ROOT/"HARD_LIF.md"),cohort_sha256=sha(src/"cohort.json"),python_sha256=sha(Path(__file__)),c_sha256=sha(ROOT/"hard_lif.c"),library_sha256=sha(ROOT/"hard_lif.so")))
        return
    from seal_exchange import await_joint
    await_joint(ROOT)
    seal=json.loads((out/"seal.json").read_text());assert sha(Path(__file__))==seal["python_sha256"] and sha(ROOT/"hard_lif.so")==seal["library_sha256"] and sha(src/"cohort.json")==seal["cohort_sha256"]
    te=data.traces(source["held"]);rows,signals=evaluate(m,te,seal["selected"]);pfiles={};onsets=[]
    for sid,sw,x,y in te:
        k=f"{sid}-{sw}";p,events=signals[k];dest=out/(k+".npz")
        if mode=="score" and not dest.exists():np.savez_compressed(dest,probability=p,hard_events=events)
        with np.load(dest) as f:assert np.array_equal(f["probability"],p) and np.array_equal(f["hard_events"],events)
        pfiles[dest.name]=sha(dest);iy=np.flatnonzero(y);ie=np.flatnonzero(events)
        obs=float((iy[0]+1)*DT) if len(iy) else None;pred=float((ie[0]+1)*DT) if len(ie) else None;duration=len(y)*DT
        onsets.append(dict(specimen=sid,sweep=sw,observed_first_bin_end=obs,hard_first_bin_end=pred,duration=duration,absolute_error_silence_at_end=abs((obs if obs is not None else duration)-(pred if pred is not None else duration)),hard_emissions=int(events.sum())))
    main=json.loads((ROOT/"results/terminal.json").read_text());dual=main["specimen_sums"]["dual"];ids=source["held"]
    diff=np.array([dual[str(k)][2]/dual[str(k)][5]-rows[k][2]/rows[k][5] for k in ids])
    rng=np.random.default_rng(950183);draw=rng.integers(0,len(ids),(10000,len(ids)))
    o=dict(seal_sha256=sha(out/"seal.json"),source_terminal_sha256=sha(ROOT/"results/terminal.json"),metrics=summarize(rows),records=onsets,raw_archives=pfiles,
           first_dual_minus_hard_mean_nll=float(diff.mean()),first_dual_minus_hard_specimen95=np.quantile(diff[draw].mean(1),[.025,.975]).tolist(),
           mean_specimen_absolute_onset_error_silence_at_end=float(np.mean([np.mean([t["absolute_error_silence_at_end"] for t in onsets if t["specimen"]==sid]) for sid in ids])),
           false_onset=sum(t["observed_first_bin_end"] is None and t["hard_first_bin_end"] is not None for t in onsets),missed_onset=sum(t["observed_first_bin_end"] is not None and t["hard_first_bin_end"] is None for t in onsets))
    put(out/"terminal.json",o)
    if mode=="verify":put(out/"verification.json",dict(replayed_files=len(pfiles),terminal_sha256=sha(out/"terminal.json"),exact=True))
if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("mode",choices=["fit","score","verify"]);run(p.parse_args().mode)
