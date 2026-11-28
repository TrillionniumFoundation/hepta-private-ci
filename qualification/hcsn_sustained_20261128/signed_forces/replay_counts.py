"""Replay every previously fitted held current directly with tensor Gaussian transition probabilities."""
import json
from pathlib import Path
import sys
import numpy as np
import torch
from population import BoundaryPopulation
from allen import MODES,sha


@torch.no_grad()
def replay(m,mode,drive,times):
    grid=m.grid;reset=m.reset_weights
    dtype=grid.dtype
    v=torch.as_tensor(drive,dtype=dtype)
    t=torch.as_tensor(times,dtype=dtype)
    base=m.prices.mu-.70*v
    P=m.prices.p.P0*(1+.28*v)
    E,L=m.priced_channels(P)
    E=E/20.;L=L/20.
    b=(m.prices.boundary(P)/m.prices.B0).log()
    baseline=m.physical_passage(grid,m.dt,None)
    mass=reset.expand(len(v),-1).clone();r=torch.zeros_like(v)
    values=torch.zeros(len(v),2,dtype=dtype)
    cumulative=torch.zeros_like(v)
    maxerr=0.
    for tick in range(int(t.ceil().max())):
        if mode=="nonfinancial":
            total=mass.sum(1)
            pos=torch.where(total>0,(mass*grid).sum(1)/total,.30)
            e=pos/(.30+pos) if tick else torch.zeros_like(pos)
            l=(mass*baseline).sum(1) if tick else torch.zeros_like(pos)
            mu=base+.65*e.tanh()*(.30-pos)-.65*l.tanh()
        else:
            mu=base+m.signed_drift(mass[:,None,:],values[:,None,:])[:,0]
        shift=(-b/m.dt) if tick==0 else 0.
        new,flow=m.ramp_transport(mass,(mu+shift)[:,None])
        mass=new+r[:,None]*reset;r=flow
        maxerr=max(maxerr,float((mass.sum(1)+r-1).abs().max()))
        cumulative+=r*(t-tick).clamp(0,1)
        values[:,0]=(mass*E).sum(1) if mode in ("prices","equity") else 0.
        values[:,1]=(mass*L).sum(1) if mode in ("prices","loss") else 0.
    return cumulative.numpy(),maxerr


def main(folder):
    torch.set_num_threads(1)
    m=BoundaryPopulation(1,1,12,initial_physical_gain=.70,signed_force_gains=(.65,.65),boundary_path="linear_log")
    book=json.loads((folder/"allen_seal.json").read_text())
    held=json.loads((folder/"allen_held.json").read_text())
    scores={};new={}
    for cohort,cells in held.items():
        ids=sorted(cells)
        draws=np.random.default_rng(77591).integers(len(ids),size=(10000,len(ids)))
        errors={};new[cohort]={};qa={}
        for mode in MODES:
            dr=[];ticks=[];cached=[];y=[];groups=[]
            for i,sid in enumerate(ids):
                f=book[cohort]["specimens"][sid];a,b,c=f["fits"][mode]["parameters"]
                h=cells[sid];cur=np.asarray(h["current"])
                x=2*(cur-f["min_current"])/(f["max_current"]-f["min_current"])-1
                dr.extend(np.tanh(b*(x-a)));ticks.extend(np.array(h["duration"])*c)
                cached.extend(h["pred"][mode]);y.extend(h["count"]);groups.extend([i]*len(cur))
            p,mass=replay(m,mode,dr,ticks)
            dx=p-cached
            errs=np.bincount(groups,weights=np.abs(p-y))/np.bincount(groups)
            errors[mode]=errs
            qa[mode]=dict(max_raw_count_error=float(np.max(np.abs(dx))),mean_abs=float(np.mean(np.abs(dx))),mass=mass)
            new[cohort][mode]=dict(ids=ids,group=groups,exact_counts=p.tolist())
            print(cohort,mode,qa[mode],flush=True)
        scores[cohort]=dict(qa=qa,models={})
        for mode,mae in errors.items():
            d=errors["prices"]-mae
            scores[cohort]["models"][mode]=dict(cell_mae=float(mae.mean()),delta=float(d.mean()),ci95=np.quantile(d[draws].mean(1),[.025,.975]).tolist())
    out=folder/"allen_direct_held.json";out.write_text(json.dumps(new,separators=(",",":"),allow_nan=False))
    (folder/"allen_direct_verified.json").write_text(json.dumps(dict(cohorts=scores,source_seal=sha(folder/"allen_seal.json"),
                held_direct_sha256=sha(out)),indent=2)+"\n")
if __name__=="__main__":main(Path(sys.argv[1]))
