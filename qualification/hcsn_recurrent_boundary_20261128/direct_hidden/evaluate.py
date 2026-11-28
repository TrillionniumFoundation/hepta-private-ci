"""Open the complete sealed panel, release held scores and independently replay mechanisms."""
from argparse import ArgumentParser
from hashlib import sha256
import json
from pathlib import Path
import time
import numpy as np
import torch
from model import Network,make_table
from train import DATA,load_data,digest,local_scores


def numpy_logits(x,weights,gain,kind,disconnected=False):
    source=x.astype(float)
    table=weights["table"].astype(float)
    for k in (0,1):
        z=source@weights[f"layers.{k}.weight"].astype(float).T+weights[f"layers.{k}.bias"]
        m=np.zeros_like(z[:,0]);wire=[]
        for f in z.transpose(1,0,2):
            v=np.tanh(f+m);lb=np.log1p(gain*v)
            index=(v+1)*((len(table)-1)/2);ix=np.floor(index).astype(int).clip(0,len(table)-2)
            q=table[ix]+(index-ix)[:,:,None]*(table[ix+1]-table[ix])
            e,l,h=q.transpose(2,0,1);margin=np.log(1.12)-lb
            m=np.zeros_like(m) if kind=="no_memory" else .35*m-.32*np.tanh(e)*(.15-margin)+.38*np.tanh(l)-.25*h
            wire.append(np.zeros_like(lb) if k==0 and disconnected else lb/gain)
        source=np.stack(wire,1)
    return source.reshape(len(x),-1)@weights["out.weight"].astype(float).T+weights["out.bias"]


def run(out):
    seals={p.name:json.loads(p.read_text()) for p in sorted(out.glob("*-seal.json"))}
    assert len(seals)==24
    manifest={name:digest(out/name) for name in seals}
    (out/"panel.json").write_text(json.dumps(manifest,indent=2)+"\n")
    x,y,actors,(tr,dev,ix)=load_data(DATA)
    x=torch.tensor(x,dtype=torch.float32)
    rows={};sp=[];worst=0;per={};summary={};count=0
    for name,stud in seals.items():
        table,gain,_=make_table(stud["kind"]);net=Network(stud["kind"],table,gain)
        ids=[]
        for cell in stud["rows"]:
            key=cell["key"];path=out/(key+".npz")
            assert digest(path)==cell["weights"]
            with np.load(path) as f:w={k:a.copy() for k,a in f.items()}
            net.load_state_dict({k:torch.from_numpy(a) for k,a in w.items()})
            t=time.perf_counter()
            with torch.no_grad():
                z=net(x[ix]).numpy()
            native=time.perf_counter()-t
            with torch.no_grad():
                orig=net(x[dev]).numpy()
                off=net(x[ix],disconnect=True).numpy()
            assert sha256(orig.tobytes()).hexdigest()==cell["dev_sha"]
            assert np.ptp(off,axis=0).max()==0
            ref=numpy_logits(x[ix].numpy(),w,gain,stud["kind"])
            ref_dev=numpy_logits(x[dev].numpy(),w,gain,stud["kind"])
            maxerr=float(max(np.max(abs(ref-z)),np.max(abs(ref_dev-orig))))
            worst=max(worst,maxerr)
            nll,hit=local_scores(z.astype(float),y[ix]);offloss,offhit=local_scores(off.astype(float),y[ix])
            file=out/(key+"-scores.npz")
            np.savez_compressed(file,dev=orig,held=z)
            rows[key]=dict(development=cell["dev"],held=float(nll.mean()),top1=float(hit.mean()),cold_s=native,
                           completed_path=cell["elapsed"]+native,fit_wall=stud["fit_wall"],
                           scores=digest(file),replay_max_abs=maxerr,disconnected_held=float(offloss.mean()),
                           disconnected_top1=float(offhit.mean()),actor_count=len(np.unique(actors[ix])))
            ids.append(key);per[key]=nll
            count+=z.size+orig.size
        best=stud["best"]
        assert best==min(ids,key=lambda k:rows[k]["development"])
        subset=summary.setdefault(stud["kind"]+"-"+stud["method"],{})
        subset[str(stud["seed"])]=dict(best=best,**rows[best],gates={threshold:(
                  dict(key=k,cold=rows[k]["held"],passed=rows[k]["held"]<=float(threshold),
                       seconds=rows[k]["completed_path"]) if k else None)
                  for threshold,k in stud["gate_first"].items()})
    actors=actors[ix];actor_keys=np.unique(actors)
    rig=np.random.default_rng(277344);picks=rig.integers(0,len(actor_keys),(10000,len(actor_keys)))
    sizes=np.array([(actors==a).sum() for a in actor_keys])
    pairs={}
    for left,right in [("financial-direct","financial-bp"),("financial-five","financial-bp"),
                       ("financial-direct","smooth-direct"),("financial-five","smooth-five"),
                       ("financial-bp","smooth-bp"),("financial-five","no_memory-five")]:
        diff=np.mean([per[summary[left][str(s)]["best"]]-per[summary[right][str(s)]["best"]]
                      for s in (137,311,557)],axis=0)
        by=np.array([sum(diff[actors==a]) for a in actor_keys])
        interval=np.quantile(by[picks].sum(1)/sizes[picks].sum(1),[.025,.975]).tolist()
        pairs[f"{left} minus {right}"]=dict(nll=float(diff.mean()),actor_interval=interval)
    assert worst<.004
    return dict(seal=digest(out/"panel.json"),models=len(rows),native_floats=count,
                max_numpy_difference=worst,rows=rows,summary=summary,pairs=pairs)
if __name__=="__main__":
    p=ArgumentParser();p.add_argument("out",type=Path);a=p.parse_args();torch.set_num_threads(1)
    r=run(a.out);(a.out/"terminal.json").write_text(json.dumps(r,indent=2)+"\n")
    print(r["models"],r["native_floats"],r["max_numpy_difference"])
    for k,arms in r["summary"].items():
        print(k,np.mean([a["held"] for a in arms.values()]),np.mean([a["top1"] for a in arms.values()]),
              [round(a["fit_wall"]+a["cold_s"],3) for a in arms.values()],
              [sum(bool(a["gates"][g] and a["gates"][g]["passed"]) for a in arms.values()) for g in ("4.1","3.75")])
    print(r["pairs"])
