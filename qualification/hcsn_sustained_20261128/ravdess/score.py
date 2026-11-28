"""Source-frozen external emotion scoring for original, analytic and sustained models."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time

import numpy as np
import torch
from torch.nn import functional as F

SEEDS=(137,311,557)


def digest(path):
    with path.open("rb") as f:return hashlib.file_digest(f,"sha256").hexdigest()


def load(path):return json.loads(path.read_text())


def write(path,obj):
    tmp=path.with_suffix(".tmp")
    tmp.write_text(json.dumps(obj,indent=2,allow_nan=False)+"\n");tmp.replace(path)


def losses(scores,y):
    return np.logaddexp.reduce(scores,axis=1)-scores[np.arange(len(y)),y]


def measure(z,y):
    ell=losses(z,y);correct=(z.argmax(1)==y)
    return dict(nll=float(ell.mean()),top1=float(correct.mean()),balanced_accuracy=float(np.mean([
        correct[y==i].mean() for i in range(6)]))),ell,correct


def features(v,a):
    tile=v.astype("float32").reshape(len(v),12,4,7,4,7).mean((3,5))/127.5-1
    v=tile.reshape(len(v),12,16)
    return np.concatenate([v.mean(1),v.std(1),a.mean(1),a.std(1)],axis=1).astype("float64")


def source_only_control(src,external):
    start=time.perf_counter()
    with np.load(src/"data/data.npz") as d:
        x=features(d["images"],d["audio"]);fold=d["split"];y=d["labels"]%6
    tr=fold==0;dev=fold==1
    mean=x[tr].mean(0);sd=x[tr].std(0).clip(1e-4)
    xx=(x-mean)/sd
    gram=xx[tr].T@xx[tr]
    prior=np.bincount(y[tr],minlength=6)/tr.sum()
    xty=xx[tr].T@(np.eye(6)[y[tr]]-prior)
    base=gram.trace()/len(gram)
    estimates=[]
    for alpha in (.0001,.01,1.):
        weight=np.linalg.solve(gram+np.eye(len(gram))*base*alpha,xty)
        for scale in (1.,4.,16.,64.):
            z=(xx[dev]@weight+prior)*scale
            estimates.append((float(losses(z,y[dev]).mean()),alpha,scale,weight))
    dev_nll,alpha,scale,w=min(estimates,key=lambda v:v[:3])
    frozen=dict(alpha=alpha,scale=scale,dev_nll=dev_nll,prior=prior.tolist(),
                weight_sha256=hashlib.sha256(w.tobytes()).hexdigest(),source_fit_s=time.perf_counter()-start)
    with np.load(external) as d:
        xnew=(features(d["video"],d["audio"])-mean)/sd
    return frozen,{"ridge":(xnew@w+prior)*scale,
                   "class_prior":np.broadcast_to(np.log(prior),(len(xnew),6)),
                   "uniform":np.zeros((len(xnew),6),dtype=float)}


def specifications(kind,study,analytic):
    if kind=="full":
        root=study/"whole_edit"
        r=load(root/"development_seal.json")
        if digest(root/"development_seal.json")!=load(root/"terminal.json")["seal_sha256"]:raise ValueError("full seal")
        models=[]
        for arm in ("forward","same_site_bp","full_bp"):
            for seed in SEEDS:
                k=f"{arm}-{seed}";epoch=r["picks"][k]["raw"]
                row=next(v for v in r["fits"][k] if v["epoch"]==epoch)
                models.append((arm,"raw_dev_best",seed,root/k/row["weights"],row["sha256"]))
        return models
    if kind=="analytic":
        root=analytic/"run";r=load(root/"seal.json")
        if digest(root/"seal.json")!=load(root/"terminal.json")["seal_sha256"]:raise ValueError("analytic seal")
        return [(grp["arm"],tag,grp["seed"],root/k/row["file"],row["sha256"])
                for k,grp in r.items() for tag,row in grp["history"].items()]
    root=study/"run";r=load(root/"seal.json")
    if digest(root/"seal.json")!=load(root/"terminal.json")["seal_sha256"]:raise ValueError("sustained seal")
    return [(arm,"raw_dev_best",seed,root/f"{arm}-{seed}"/r[f"{arm}-{seed}"]["best"]["file"],
            r[f"{arm}-{seed}"]["best"]["sha256"]) for arm in ("literal","smooth","lif","sdpa") for seed in SEEDS]


@torch.no_grad()
def score(net,v,a,tokens):
    net.eval()
    prompts=net.encode(net.text(tokens))
    result=[]
    for ix in np.array_split(np.arange(len(v)),(len(v)+31)//32):
        embedding=net.encode(net.front(v[ix],a[ix]))
        result.append((12*embedding@prompts.T).numpy())
    z=np.concatenate(result)
    if z.shape!=(1056,72) or not np.isfinite(z).all():raise ValueError("external gallery")
    return z


def run(root,src,study,analytic,kind):
    # Use the already validated six-layer source for original and analytic arms.
    sys.path[:0]=[str(analytic),str(study)]
    from encoder import AVText
    from encoder_adapter import AnalyticAVText
    from study import Data,HASHES
    for name,want in HASHES.items():
        if digest(src/name)!=want:raise ValueError("source "+name)
    prepared=load(root/"prepared.json");datafile=root/"external.npz"
    if digest(datafile)!=prepared["prepared_sha256"]:raise ValueError("external archive")
    out=root/("scores-"+kind);out.mkdir(exist_ok=True)
    if (out/"terminal.json").is_file():return
    d=Data(src)
    with np.load(src/"data/data.npz") as f:
        raw=f["audio"][d.train]
        mu=raw.mean((0,1),dtype=np.float64).astype(np.float32)
        sd=raw.std((0,1),dtype=np.float64).clip(.01).astype(np.float32)
    with np.load(datafile) as a:
        names=a["ids"];v=torch.from_numpy(a["video"]);au=torch.from_numpy((a["audio"]-mu)/sd);y=a["y"].astype(int)
    actors=np.array([int(k.split("-")[-1]) for k in names])
    if len(np.unique(actors))!=24 or len(y)!=1056 or np.bincount(y).tolist()!=[192,192,192,192,96,192]:
        raise ValueError("cohort counts")
    specs=specifications(kind,study,analytic)
    n={"full":9,"analytic":30,"sustained":12}[kind]
    if len(specs)!=n:raise ValueError("incomplete weight set")
    identities={f"{arm}-{tag}-{seed}":{"path":str(p),"sha256":want} for arm,tag,seed,p,want in specs}
    for _,_,_,p,want in specs:
        if digest(p)!=want:raise ValueError("model identity "+str(p))
    write(out/"source_models.json",identities)
    fit,control=source_only_control(src,datafile)
    cm={k:measure(val,y)[0] for k,val in control.items()}
    with (out/"controls.npz").open("wb") as file:np.savez_compressed(file,ids=names,y=y,**control)
    st={};ell={};ok={}
    grouped={}
    for arm,tag,seed,p,want in specs:
        tic=time.perf_counter()
        model=(AnalyticAVText(96,seed,d.words,src/"src/law4.npz",learn_contract=arm=="learn",continuous=arm=="ramp")
               if kind=="analytic" and arm in ("exact","learn","ramp") else
               AVText(arm if arm in ("literal","smooth","lif","sdpa") else "literal",96,seed,d.words,src/"src/law4.npz"))
        model.load_state_dict(torch.load(p,weights_only=True,map_location="cpu"),strict=True)
        z=score(model,v,au,d.tokens)
        emission=np.logaddexp.reduce(z.astype(np.float64).reshape(len(y),12,6),axis=1)
        k=f"{arm}-{tag}-{seed}";grouped.setdefault((arm,tag),[]).append(k)
        m,ell[k],ok[k]=measure(emission,y)
        f=out/(k+".npz")
        with f.open("wb") as file:np.savez_compressed(file,ids=names,labels=y,source_gallery=z,emotion_logits=emission)
        st[k]=dict(metrics=m,weight_sha256=want,external_scores_sha256=digest(f),elapsed_s=time.perf_counter()-tic)
        print(kind,k,round(m["nll"],5),round(m["balanced_accuracy"],4),flush=True)
    who,ix=np.unique(actors,return_inverse=True);draw=np.random.default_rng(413126).integers(0,len(who),(4000,len(who)))
    counts=np.bincount(ix)
    def ci(delta):
        sums=np.bincount(ix,weights=delta)
        return [float(delta.mean()),*np.quantile(sums[draw].sum(1)/counts[draw].sum(1),[.025,.975]).tolist()]
    means={};pairs={}
    for (arm,tag),keys in grouped.items():
        keys=sorted(keys)
        base=sorted(grouped["same_site_bp" if kind=="full" else "sdpa",tag])
        means[arm+"-"+tag]={k:float(np.mean([st[n]["metrics"][k] for n in keys])) for k in ("nll","top1","balanced_accuracy")}
        pairs[arm+"-"+tag]=dict(nll=ci(np.mean([ell[a]-ell[b] for a,b in zip(keys,base)],0)),
                                 top1=ci(np.mean([ok[a].astype(float)-ok[b] for a,b in zip(keys,base)],0)))
    write(out/"terminal.json",dict(group=kind,external_sha256=digest(datafile),source_selection_sha256=digest(out/"source_models.json"),
          actual_full_gallery_logits=n*1056*72,class_counts=np.bincount(y).tolist(),actor_count=len(who),
          means=means,models=st,against_reference= pairs,controls=cm,source_only_ridge=fit))
    print("complete",kind,means,flush=True)


if __name__=="__main__":
    p=argparse.ArgumentParser()
    for name in ("root","source","study","analytic"):p.add_argument(name,type=Path)
    p.add_argument("kind",choices=("full","analytic","sustained"));a=p.parse_args()
    torch.set_num_threads(1);torch.set_num_interop_threads(1)
    run(a.root,a.source,a.study,a.analytic,a.kind)
