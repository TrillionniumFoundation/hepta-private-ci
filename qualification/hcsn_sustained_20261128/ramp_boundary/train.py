"""Sealed paired small-network sensitivity trial for jump and continuously moving barriers."""
import hashlib
import json
from pathlib import Path
import time

import numpy as np
import torch
from torch.nn import functional as F
from population import ContinuousSpikingNetwork

SEEDS=(314,159,271)
ARMS=("step","linear_log","linear_physical")
ROOT=Path("digits")
ROOT.mkdir(exist_ok=True)


def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()


def store(p,z):
    temp=p.with_suffix(".tmp")
    temp.write_text(json.dumps(z,indent=2,allow_nan=False)+"\n")
    temp.replace(p)


def dataset():
    src=Path("digits01.npz")
    assert sha(src)=="64e0d2d6eefdf5690076708a08bc4ef38a2a8d996158f0c455386fdaf6ae255f"
    with np.load(src) as f:
        x=torch.from_numpy(f["images"].astype(float)/16).transpose(0,1)
        y=torch.from_numpy(f["labels"].astype(np.int64))
    rng=np.random.default_rng(20261128)
    tr=[];dv=[];te=[]
    for label in (0,1):
        rows=rng.permutation(np.flatnonzero(y==label))
        n,m=int(.64*len(rows)),int(.80*len(rows))
        tr.extend(rows[:n]);dv.extend(rows[n:m]);te.extend(rows[m:])
    return x,y,np.array(tr),np.array(dv),np.array(te)


def network(arm,seed):
    torch.manual_seed(seed)
    return ContinuousSpikingNetwork(8,3,2,12,"priced",False,True,
            .15 if arm=="linear_physical" else None,"step" if arm=="step" else "linear_log")


def measure(z,y):
    loss=np.logaddexp.reduce(z,axis=1)-z[np.arange(len(y)),y]
    acc=[(z[y==j].argmax(1)==j).mean() for j in (0,1)]
    return dict(nll=float(loss.mean()),balanced_accuracy=float(np.mean(acc))),loss


@torch.no_grad()
def score(model,x,y,ids):
    model.eval()
    scores=torch.cat([model(x[:,r])[0][-1] for r in np.array_split(ids,int(np.ceil(len(ids)/8)))]).numpy()
    if not np.isfinite(scores).all():raise ValueError("scores")
    return scores,measure(scores,y[ids].numpy())[0]


def main():
    torch.set_num_threads(1);torch.set_num_interop_threads(1)
    x,y,tr,dv,te=dataset()
    if len(te)!=73:raise ValueError("test fold")
    fit={}
    for seed in SEEDS:
        schedule=np.random.default_rng(seed).choice(tr,(64,8))
        for arm in ARMS:
            key=f"{arm}-{seed}"
            loc=ROOT/key;loc.mkdir(exist_ok=True)
            model=network(arm,seed)
            opt=torch.optim.AdamW(model.parameters(),lr=.016,weight_decay=.001)
            marks=[];work=0.
            for step in range(65):
                if step in (0,8,16,32,64):
                    _,m=score(model,x,y,dv)
                    path=loc/f"step-{step}.pt";torch.save(model.state_dict(),path)
                    marks.append(dict(step=step,training_s=work,sha256=sha(path),file=path.name,**m))
                if step==64:break
                tic=time.perf_counter()
                model.train();opt.zero_grad(set_to_none=True);rows=schedule[step]
                logits=model(x[:,rows])[0][-1];loss=F.cross_entropy(logits,y[rows])
                loss.backward()
                for p in model.parameters():
                    if p.grad is not None and not torch.isfinite(p.grad).all():raise ValueError("nonfinite "+key)
                opt.step()
                work+=time.perf_counter()-tic
            best=min(marks,key=lambda m:(m["nll"],m["step"]))
            fit[key]=dict(selected=best,final=marks[-1],candidates=marks)
            print(key,marks[-1]["training_s"],best["step"],flush=True)
    store(ROOT/"seal.json",fit)
    raw={};results={};losses={}
    for seed in SEEDS:
        for arm in ARMS:
            key=f"{arm}-{seed}";results[key]={}
            model=network(arm,seed)
            for kind in ("selected","final"):
                r=fit[key][kind];w=ROOT/key/r["file"]
                assert sha(w)==r["sha256"]
                model.load_state_dict(torch.load(w,weights_only=True))
                z,m=score(model,x,y,te)
                nm=f"{key}-{kind}"
                raw[nm]=z
                losses[nm]=measure(z,y[te].numpy())[1]
                results[key][kind]=dict(**m,step=r["step"])
    pred=ROOT/"scores.npz"
    np.savez_compressed(pred,ids=te,labels=y[te].numpy(),**raw)
    ci={}
    rng=np.random.default_rng(87291)
    ix=rng.integers(0,len(te),(4000,len(te)))
    for arm in ARMS[1:]:
        dif=np.mean([losses[f"{arm}-{s}-selected"]-losses[f"step-{s}-selected"] for s in SEEDS],0)
        ci[arm]=[float(dif.mean()),*np.quantile(dif[ix].mean(1),[.025,.975]).tolist()]
    mean={arm:{m:float(np.mean([results[f"{arm}-{s}"]["selected"][m] for s in SEEDS]))
                    for m in ("nll","balanced_accuracy")} for arm in ARMS}
    store(ROOT/"terminal.json",dict(results=results,selected_means=mean,selected_minus_step_nll_ci95=ci,
                                   seal_sha256=sha(ROOT/"seal.json"),scores_sha256=sha(pred),split=list(map(len,(tr,dv,te))),
                                   torch=str(torch.__version__)))
    print("complete",mean,ci,flush=True)

if __name__=="__main__":main()
