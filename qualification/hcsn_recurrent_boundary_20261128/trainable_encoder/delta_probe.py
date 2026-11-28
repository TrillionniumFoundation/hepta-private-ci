"""Event-driven paired finite-write and scalar-BP study on original six-layer checkpoints."""
import argparse
from hashlib import sha256
import fcntl
import json
import os
from pathlib import Path
import sys
import time
import numpy as np
import torch
from torch.nn import functional as F

ARMS=("parent","forward_grid","scalar_bp")
SEEDS=(137,311,557)
RUNGS=("epoch1","time120","time900","time2600")
BETAS=(1.,0.,-.25,.25,.5,.75,1.25)
SOURCE_HASH="69e8cf12bcfcd414175250405ac08286901457377d76c1ad28f08d33a775dbc1"


def file_hash(p):
    with p.open("rb") as f:
        return __import__("hashlib").file_digest(f,"sha256").hexdigest()


def write_json(p,x):
    t=p.with_suffix(".partial")
    t.write_text(json.dumps(x,indent=2,allow_nan=False)+"\n")
    t.replace(p)


def release(p,arrays):
    if p.is_file():
        with np.load(p) as data:
            if set(data.files)!=set(arrays) or any(not np.array_equal(data[k],v) for k,v in arrays.items()):
                raise ValueError("conflicting observation at "+p.name)
    else:
        tmp=p.with_name(p.name+".partial")
        with tmp.open("wb") as f:np.savez_compressed(f,**arrays)
        tmp.replace(p)
    return file_hash(p)


class Interpolated(torch.nn.Module):
    def __init__(self,original,alternate):
        super().__init__()
        self.base=original.base
        with np.load(alternate) as z:
            self.register_buffer("base_mark",torch.tensor(z["mark"],dtype=original.mark.dtype))
            self.register_buffer("base_price",torch.tensor(z["prices"],dtype=original.prices.dtype))
        self.register_buffer("delta_mark",original.mark.detach()-self.base_mark)
        self.register_buffer("delta_price",original.prices.detach()-self.base_price)
        self.beta=torch.nn.Parameter(torch.ones((),dtype=original.mark.dtype))

    def at(self,x):
        mark=self.base_mark+self.beta*self.delta_mark
        prices=self.base_price+self.beta*self.delta_price
        value=(x+1.)*((len(mark)-1)/2)
        i=value.long().clamp(0,len(mark)-2)
        v=value-i
        return torch.lerp(mark[i],mark[i+1],v),torch.lerp(prices[i],prices[i+1],v[...,None,None])


def net_from(root,home,data,seed,weights):
    from network import make_model
    model=make_model(root,home,"returning",seed,data)
    model.load_state_dict(torch.load(weights,map_location="cpu",weights_only=True))
    for param in model.parameters():param.requires_grad_(False)
    model.law=Interpolated(model.law,home/"tables"/"irreversible.npz")
    model.eval()
    return model


def set_beta(net,b):
    with torch.no_grad():net.law.beta.fill_(float(b))


def logits(net,data,ids):
    t=net.encode(net.text(data.tokens))
    a=net.encode(net.front(data.v[ids],data.audio[ids]))
    return 12*(a@t.T)


def loss(net,data,ids):
    return F.cross_entropy(logits(net,data,ids),data.y[ids])


def stats(z,y):
    a=z.astype(np.float64)
    return dict(nll=float((np.logaddexp.reduce(a,axis=1)-a[np.arange(len(y)),y]).mean()),
                accuracy=float((a.argmax(1)==y).mean()))


def fit(root,home,output,data,seed,rung,row):
    from study import inference
    key=f"{seed}-{rung}"
    weight=home/"run"/f"returning-{seed}"/row["file"]
    if file_hash(weight)!=row["weight_sha"]:raise ValueError("parent digest")
    before=time.perf_counter()
    train=np.random.default_rng(817253).choice(data.train,256,replace=False)
    net=net_from(root,home,data,seed,weight)
    common=time.perf_counter()-before
    # Return-parent endpoint equality is a numerical intervention check, including the final score.
    parent_z=inference(net,data,data.dev).numpy()
    with np.load(home/"run"/f"returning-{seed}"/row["score_file"]) as original:
        error=float(np.max(np.abs(parent_z-original["logits"])))
        if error>3e-4:raise ValueError(f"beta=1 differs from parent by {error}")
    before=time.perf_counter()
    sample=train[:32]
    set_beta(net,.537)
    grad=float(torch.autograd.grad(loss(net,data,sample),net.law.beta)[0])
    # A sequence of finite differences reveals scale dependence of FP32 and crossed knots.
    fd={}
    with torch.no_grad():
        for eps in (.01,.003,.001):
            set_beta(net,.537+eps); high=float(loss(net,data,sample))
            set_beta(net,.537-eps); low=float(loss(net,data,sample))
            fd[str(eps)]=(high-low)/(2*eps)
    gradient_s=time.perf_counter()-before
    times={"parent":0.}
    betas={"parent":1.}
    before=time.perf_counter()
    train_loss={}
    with torch.no_grad():
        for b in BETAS:
            set_beta(net,b)
            z=inference(net,data,train)
            train_loss[str(b)]=float(F.cross_entropy(z,data.y[train]))
    betas["forward_grid"]=min(BETAS,key=lambda b:train_loss[str(b)])
    times["forward_grid"]=time.perf_counter()-before
    before=time.perf_counter()
    set_beta(net,1.)
    opt=torch.optim.Adam([net.law.beta],lr=.07)
    rng=np.random.default_rng(59623)
    for _ in range(20):
        ids=train[rng.choice(len(train),32,replace=False)]
        opt.zero_grad(set_to_none=True)
        objective=loss(net,data,ids)
        objective.backward()
        if not torch.isfinite(net.law.beta.grad):raise ValueError("nonfinite gradient")
        opt.step()
        with torch.no_grad():net.law.beta.clamp_(-.25,1.25)
    betas["scalar_bp"]=float(net.law.beta.detach())
    times["scalar_bp"]=time.perf_counter()-before
    records={}
    for arm in ARMS:
        set_beta(net,betas[arm])
        before=time.perf_counter()
        z=inference(net,data,data.dev).numpy()
        sha=release(output/f"{key}-{arm}-dev.npz",{"logits":z})
        records[arm]=dict(beta=betas[arm],score_sha=sha,fit_s=times[arm],evaluation_s=time.perf_counter()-before,
                          common_s=common,dev=stats(z,data.y[data.dev].numpy()))
    report=dict(seed=seed,rung=rung,parent=row,records=records,calibration_grid=train_loss,
                derivative=grad,fd=fd,gradient_check_s=gradient_s,beta_one_parent_error=error)
    write_json(output/(key+".json"),report)
    print(key,{k:y["dev"]["nll"] for k,y in records.items()},flush=True)


def finalize(root,home,output,data):
    from study import inference
    main=home/"run"
    panel=json.loads((main/"seal.json").read_text())
    own={f"{s}-{r}":json.loads((output/f"{s}-{r}.json").read_text()) for s in SEEDS for r in RUNGS}
    seal={"main_seal":file_hash(main/"seal.json"),"sources":{k:file_hash(home/k) for k in
          ("delta_probe.py","network.py","train.py","study.py")},"rows":own}
    if (output/"seal.json").exists():
        if json.loads((output/"seal.json").read_text())!=seal:raise ValueError("seal changed")
    else:write_json(output/"seal.json",seal)
    rows={}
    for s in SEEDS:
        for r in RUNGS:
            key=f"{s}-{r}"
            a=own[key]
            expected=panel[f"returning-{s}"]["history"][r]
            if expected!=a["parent"]:raise ValueError("original selection changed")
            weights=main/f"returning-{s}"/expected["file"]
            if file_hash(weights)!=expected["weight_sha"]:raise ValueError("original weights changed")
            net=net_from(root,home,data,s,weights)
            for label,rec in a["records"].items():
                if file_hash(output/f"{key}-{label}-dev.npz")!=rec["score_sha"]:raise ValueError("development changed")
                set_beta(net,rec["beta"])
                before=time.perf_counter()
                z=inference(net,data,data.test).numpy()
                fn=f"{key}-{label}-held.npz"
                checked=release(output/fn,{"logits":z})
                rows[f"{key}-{label}"]=dict(file=fn,sha=checked,held=stats(z,data.y[data.test].numpy()),cost=rec["common_s"]+
                      rec["fit_s"]+rec["evaluation_s"]+time.perf_counter()-before)
    actors=data.actors[data.test];y=data.y[data.test].numpy()
    groups=[np.where(actors==a)[0] for a in np.unique(actors)]
    draw=np.random.default_rng(812453).integers(0,len(groups),(4000,len(groups)))
    den=np.array(list(map(len,groups)))[draw].sum(1)
    paired={}
    for rung in RUNGS:
        for lhs,rhs in (("forward_grid","parent"),("scalar_bp","parent"),("forward_grid","scalar_bp")):
            dif=[]
            for s in SEEDS:
                vals=[]
                for arm in (lhs,rhs):
                    with np.load(output/rows[f"{s}-{rung}-{arm}"]["file"]) as raw:
                        z=raw["logits"].astype(float)
                    vals.append(np.logaddexp.reduce(z,axis=1)-z[np.arange(len(y)),y])
                dif.append(vals[0]-vals[1])
            diff=np.mean(dif,0)
            by=np.array([diff[g].sum() for g in groups])
            paired[f"{rung}-{lhs}-minus-{rhs}"]=dict(mean=float(diff.mean()),interval=np.quantile(by[draw].sum(1)/den,[.025,.975]).tolist())
    write_json(output/"terminal.json",dict(own_seal=file_hash(output/"seal.json"),models=rows,paired=paired))
    print("terminal",file_hash(output/"terminal.json"),flush=True)


def main(home,source):
    if file_hash(home/"study.py")!=SOURCE_HASH:raise ValueError("wrong registered source")
    sys.path[:0]=[str(home),str(source/"src")]
    from study import Data,HASHES
    for name,h in HASHES.items():
        if file_hash(source/name)!=h:raise ValueError(name)
    torch.set_num_threads(1)
    output=home/"scalar-edits"
    output.mkdir(exist_ok=True)
    with (output/"job.lock").open("a") as f:
        fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)
        data=Data(source)
        while True:
            for rung in RUNGS:
                for s in SEEDS:
                    p=home/"run"/f"returning-{s}"/"progress.json"
                    if (output/f"{s}-{rung}.json").exists() or not p.is_file():continue
                    row=json.loads(p.read_text())["history"].get(rung)
                    if row:fit(source,home,output,data,s,rung,row)
            if (home/"run"/"seal.json").is_file() and all((output/f"{s}-{r}.json").is_file() for s in SEEDS for r in RUNGS):
                finalize(source,home,output,data)
                break
            time.sleep(30)


if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("study",type=Path);p.add_argument("source",type=Path)
    a=p.parse_args();main(a.study.resolve(),a.source.resolve())
