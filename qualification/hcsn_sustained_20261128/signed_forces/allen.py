"""Fit expected counts from causal signed feedback using only the existing Allen train splits."""
import argparse
import hashlib
import json
import math
from pathlib import Path
from zipfile import ZipFile

import numpy as np
from scipy.optimize import least_squares
from scipy.special import log_ndtr, ndtr
import torch

from population import BoundaryPopulation

MODES=("tonic","prices","equity","loss","nonfinancial")
COHORTS=("ephys_records","nwb_curve_records")
DRIVES=np.linspace(-1,1,401)
TOTAL_TICKS=1040


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream,"sha256").hexdigest()


def gaussian(model, mu):
    x=model.grid.numpy()
    c=model.cuts.numpy()
    width=model.prices.p.sigma*math.sqrt(model.dt)
    drift=mu[:,None]*model.dt
    tilt=-2*mu[:,None]*x/model.prices.var
    def log_bins(mean):
        lower=(np.r_[0.,c[:-1]]-mean[...,None])/width
        upper=(c-mean[...,None])/width
        right=lower>0
        hi=log_ndtr(np.where(right,-lower,upper))
        lo=log_ndtr(np.where(right,-upper,lower))
        return np.concatenate([hi+np.log(-np.expm1(lo-hi)),log_ndtr((mean-c[-1])/width)[...,None]],axis=-1)
    direct=log_bins(x+drift)
    image=log_bins(-x+drift)+tilt[...,None]
    alive=np.exp(direct)*(-np.expm1(np.minimum(0.,image-direct)))
    hit=ndtr((-x-drift)/width)+np.exp(tilt+log_ndtr((-x+drift)/width))
    combined=np.concatenate([alive,hit[...,None]],axis=-1)
    np.testing.assert_allclose(combined.sum(-1),1.,atol=2e-12,rtol=0)
    return combined


def simulate(model,v,mode,lookup=None):
    grid=model.grid.numpy()
    reset=model.reset_weights.numpy()
    with torch.no_grad():
        P=model.prices.p.P0*(1+.28*torch.from_numpy(v))
        b=(model.prices.boundary(P)/model.prices.B0).log().numpy()
        E,L=[x.numpy()/20. for x in model.priced_channels(P)]
    fixed_mu=model.prices.mu-.70*v
    hit0=gaussian(model,np.array([model.prices.mu]))[0,:,-1]
    mass=np.broadcast_to(reset,(len(v),len(grid))).copy()
    refractory=np.zeros(len(v))
    eq=np.zeros(len(v))
    loss=np.zeros(len(v))
    counts=np.zeros((len(v),TOTAL_TICKS+1))
    max_mass_error=0.
    def kernels(mu):
        if lookup is None:return gaussian(model,mu)
        axis,k=lookup
        if mu.min()<axis[0] or mu.max()>axis[-1]:raise ValueError("drift table domain")
        u=(mu-axis[0])/(axis[1]-axis[0])
        i=np.minimum(u.astype(int),len(axis)-2)
        return k[i]+(u-i)[:,None,None]*(k[i+1]-k[i])
    for step in range(1,TOTAL_TICKS+1):
        total=mass.sum(1)
        margin=np.divide((mass*grid).sum(1),total,out=np.full(len(total),.30),where=total>0)
        restore=eq if mode in ("prices","equity") else 0.
        panic=loss if mode in ("prices","loss") else 0.
        if mode=="nonfinancial" and step>1:
            restore=margin/(.30+margin)
            panic=(mass*hit0).sum(1)
        mu=fixed_mu+.65*np.tanh(np.maximum(restore,0))*(.30-margin)-.65*np.tanh(np.maximum(panic,0))
        if step==1:mu=mu-b/model.dt
        kernel=kernels(mu)
        out=np.einsum('di,dij->dj',mass,kernel)
        mass=out[:,:-1]+refractory[:,None]*reset
        refractory=out[:,-1]
        eq=(mass*E).sum(1)
        loss=(mass*L).sum(1)
        counts[:,step]=counts[:,step-1]+refractory
        max_mass_error=max(max_mass_error,float(np.max(np.abs(mass.sum(1)+refractory-1))))
    if max_mass_error>1e-10:raise ValueError(max_mass_error)
    return counts,max_mass_error


def interpolate(curve,v,t):
    x=(v+1)*(len(DRIVES)-1)/2
    if np.any((x<0)|(x>len(DRIVES)-1)|(t<0)|(t>TOTAL_TICKS)):raise ValueError("response interpolation")
    i=np.minimum(x.astype(int),len(DRIVES)-2); f=x-i
    j=np.minimum(t.astype(int),TOTAL_TICKS-1); g=t-j
    a0=curve[i,j];a1=curve[i+1,j];b0=curve[i,j+1];b1=curve[i+1,j+1]
    a=a0+f*(a1-a0);b=b0+f*(b1-b0)
    value=a+g*(b-a)
    grad_v=((1-g)*(a1-a0)+g*(b1-b0))*((len(DRIVES)-1)/2)
    return value,grad_v,b-a


def response(params,x,T,curve):
    theta,slope,ticks=params
    v=np.tanh(slope*(x-theta))
    pred,dv,dt=interpolate(curve,v,ticks*T)
    q=dv*(1-v*v)
    return pred,np.column_stack((-slope*q,(x-theta)*q,T*dt))


def fit(x,y,curve):
    best=None
    for theta in (-.7,0.,.7):
        for slope in (.5,2.,6.):
            x0=[theta,slope,np.clip(2.8*y.max(),8.,900.)]
            fit=least_squares(lambda p:response(p,x,np.ones(len(x)),curve)[0]-y,x0,
                        jac=lambda p:response(p,x,np.ones(len(x)),curve)[1],
                        bounds=([-3.,.05,1.],[3.,15.,1024.]),x_scale=[1.,2.,150.],
                        max_nfev=180,ftol=1e-9,xtol=1e-9,gtol=1e-9)
            ss=float(fit.fun@fit.fun)
            if best is None or ss<best["sse"]:
                best={"sse":ss,"parameters":fit.x.tolist(),"nfev":int(fit.nfev),"status":int(fit.status)}
    return best


def main(data,out):
    torch.set_num_threads(1)
    model=BoundaryPopulation(1,1,12,boundary_path="linear_log",signed_force_gains=(.65,.65))
    axis=np.linspace(-3.8,3.8,4097)
    lookup=(axis,gaussian(model,axis))
    curves={};qa={}
    for m in MODES:
        curves[m],err=simulate(model,DRIVES,m,lookup)
        # Include midpoint drives across the entire bounded interval and the central region.
        idx=np.array([0,13,44,77,106,131,152,174,193,200,209,223,241,260,289,315,342,367,390,399])
        mid=(DRIVES[idx]+DRIVES[idx+1])/2
        reduced,_=simulate(model,mid,m,lookup)
        exact,_=simulate(model,mid,m,None)
        interp=.5*(curves[m][idx]+curves[m][idx+1])
        qa[m]=dict(mass_error=err,drift_table_max_count=float(np.max(abs(reduced-exact))),
                    drive_table_max_count=float(np.max(abs(interp-exact))))
        print(m,qa[m],flush=True)
    book={}
    for cohort in COHORTS:
        fitted={}
        with ZipFile(data/(cohort+".zip")) as z:
            for fname in sorted(n for n in z.namelist() if n.startswith("fits/")):
                row=json.loads(z.read(fname))
                sid=str(row.get("specimen",row.get("specimen_id")))
                raw=np.asarray(row["train_amplitudes"],float)
                lo,hi=raw.min(),raw.max()
                x=2*(raw-lo)/(hi-lo)-1
                y=np.asarray(row.get("train_actual_counts",row.get("train_y")),float)
                fitted[sid]=dict(min_current=lo,max_current=hi,fits={m:fit(x,y,curves[m]) for m in MODES})
                if len(fitted)%12==0:print(cohort,len(fitted),flush=True)
        book[cohort]=dict(source_sha256=sha(data/(cohort+".zip")),specimens=fitted)
    seal=out/"allen_seal.json"
    seal.write_text(json.dumps(book,sort_keys=True,separators=(",",":"),allow_nan=False))
    data_out={};report={}
    for cohort in COHORTS:
        nwb=cohort.startswith("nwb");details={}
        with ZipFile(data/(cohort+".zip")) as z:
            held=json.loads(z.read("nwb_predictions.json" if nwb else "predictions.json"))
        for sid,row in sorted(held.items()):
            f=book[cohort]["specimens"][sid]
            cur=np.array(row["heldout_amplitudes"])
            y=np.array(row["mean_counts"])
            T=np.array([np.mean([w["duration"] for w in row["sweeps"] if int(round(w["I_pA"]))==int(a)]) for a in cur]) if nwb else np.array(row["duration_s"])
            if not np.isfinite(T).all():raise ValueError("durations")
            x=2*(cur-f["min_current"])/(f["max_current"]-f["min_current"])-1
            pred=row["mean_count_predictions" if nwb else "predictions"].copy()
            pred.update({m:response(f["fits"][m]["parameters"],x,T,curves[m])[0].tolist() for m in MODES})
            details[sid]=dict(current=cur.tolist(),duration=T.tolist(),count=y.tolist(),pred=pred)
        keys=next(iter(details.values()))["pred"].keys()
        errs={k:np.array([np.mean(np.abs(np.array(v["pred"][k])-v["count"])) for v in details.values()]) for k in keys}
        draw=np.random.default_rng(77591).integers(len(held),size=(10000,len(held)))
        report[cohort]={"cells":len(held),"levels":sum(len(r["count"]) for r in details.values()),"models":{}}
        for k,e in errs.items():
            d=errs["prices"]-e
            report[cohort]["models"][k]=dict(cell_mae=float(e.mean()),prices_minus=float(d.mean()),
                                        ci95=np.quantile(d[draw].mean(1),[.025,.975]).tolist())
        data_out[cohort]=details
    raw=out/"allen_held.json";raw.write_text(json.dumps(data_out,separators=(",",":"),allow_nan=False))
    (out/"allen_terminal.json").write_text(json.dumps(dict(source=sha(Path(__file__)),seal=sha(seal),held=sha(raw),
                    qa=qa,cohorts=report),indent=2,allow_nan=False)+"\n")
    print("finished",sha(raw),flush=True)


if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("data",type=Path);p.add_argument("output",type=Path)
    a=p.parse_args();main(a.data,a.output)
