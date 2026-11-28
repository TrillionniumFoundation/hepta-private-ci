"""Resumable single-worker experiment with original logits retained at each endpoint."""
import argparse
from contextlib import contextmanager
import fcntl
from hashlib import sha256
import json
import os
from pathlib import Path
import sys
import time
import numpy as np
import torch
from torch.nn import functional as F

ARMS=("stationary","irreversible","returning","lif","sdpa")
SEEDS=(137,311,557)
RUNGS=(120.,900.,2600.)
GATES=(4.1,3.6,3.)
HERE=Path(__file__).resolve().parent
PARENT_HASH="69e8cf12bcfcd414175250405ac08286901457377d76c1ad28f08d33a775dbc1"


def sha(p):
    with p.open("rb") as f:
        return __import__("hashlib").file_digest(f,"sha256").hexdigest()


def write(path,data):
    tmp=path.with_name(path.name+".tmp")
    with tmp.open("wb") as f:
        if path.suffix==".json":
            f.write((json.dumps(data,indent=2,allow_nan=False)+"\n").encode())
        elif path.suffix==".npz":
            np.savez_compressed(f,**data)
        else:
            torch.save(data,f)
    tmp.replace(path)


def read(path):
    return json.loads(path.read_text())


def bind(path,obj):
    if path.exists():
        if read(path)!=obj:
            raise ValueError(f"conflicting evidence at {path.name}")
    else:
        write(path,obj)


def stable_scores(path,scores):
    logits=scores.detach().cpu().numpy()
    if path.exists():
        with np.load(path) as a:
            if not np.array_equal(a["logits"],logits):
                raise ValueError("different scores at same endpoint")
    else:
        write(path,dict(logits=logits))
    return sha(path)


def quality(scores,y):
    return dict(nll=F.cross_entropy(scores,y).item(),top1=(scores.argmax(1)==y).float().mean().item())


def one_stage(root,out,data,arm,seed,end):
    from network import make_model
    from encoder import pair_loss
    from study import inference
    cell=out/f"{arm}-{seed}"
    cell.mkdir(exist_ok=True)
    model=make_model(root,HERE,arm,seed,data)
    opt=torch.optim.AdamW(model.parameters(),lr=.0003,weight_decay=.01,foreach=False)
    rng=np.random.default_rng(seed+64761)
    order=np.empty(0,dtype=int)
    index=steps=samples=0
    active=cpu=overhead=0.
    hist={}
    cursor=cell/"resume.pt"
    if cursor.exists():
        old=torch.load(cursor,map_location="cpu",weights_only=False)
        if old["identity"]!=(arm,seed):
            raise ValueError("cursor belongs to another model")
        model.load_state_dict(old["model"])
        opt.load_state_dict(old["optimizer"])
        rng.bit_generator.state=old["rng"]
        order,index=old["order"],old["index"]
        steps,samples,active,cpu,overhead,hist=(old[k] for k in ("steps","samples","active","cpu","overhead","history"))
    def save():
        write(cursor,dict(identity=(arm,seed),model=model.state_dict(),optimizer=opt.state_dict(),
                          rng=rng.bit_generator.state,order=order,index=index,steps=steps,samples=samples,
                          active=active,cpu=cpu,overhead=overhead,history=hist))
        write(cell/"progress.json",dict(arm=arm,seed=seed,steps=steps,samples=samples,active=active,
                                        cpu=cpu,overhead=overhead,history=hist,utc_unix=time.time()))
    def goal():
        return active>=end and (steps>=312 if end==RUNGS[-1] else True)
    last_save=time.perf_counter()
    while not goal():
        if index>=len(order):
            order=rng.permutation(data.train)
            index=0
        ids=order[index:index+16]
        index+=len(ids)
        tic=time.perf_counter()
        c0=time.process_time()
        y=data.y[ids]
        opt.zero_grad(set_to_none=True)
        model.train()
        av,txt=model(data.v[ids],data.audio[ids],data.tokens[y])
        loss=pair_loss(av,txt,y)
        loss.backward()
        gradient=torch.nn.utils.clip_grad_norm_(model.parameters(),1.,error_if_nonfinite=True)
        opt.step()
        delta=time.perf_counter()-tic
        active+=delta
        cpu+=time.process_time()-c0
        steps+=1
        samples+=len(ids)
        tags=[f"time{int(t)}" for t in RUNGS if active>=t and f"time{int(t)}" not in hist]
        if steps==312:
            if samples!=len(data.train):
                raise ValueError("incorrect full-pass sample count")
            tags.append("epoch1")
        if tags:
            tic=time.perf_counter()
            with torch.no_grad():
                z=inference(model,data,data.dev)
            path=cell/f"step{steps}.pt"
            write(path,model.state_dict())
            dev=cell/f"step{steps}-dev.npz"
            devsha=stable_scores(dev,z)
            overhead+=time.perf_counter()-tic
            result=dict(step=steps,samples=samples,active=active,cpu=cpu,validation_io=overhead,
                        file=path.name,weight_sha=sha(path),development=quality(z,data.y[data.dev]),
                        score_file=dev.name,score_sha=devsha,loss=float(loss.detach()),grad=float(gradient))
            for lab in tags:
                hist[lab]=result
            print(arm,seed,tags,steps,samples,z.shape,result["development"],flush=True)
        if tags or time.perf_counter()-last_save>=45.:
            save()
            last_save=time.perf_counter()
    save()


def seal_panel(out):
    panel={}
    for arm in ARMS:
        for seed in SEEDS:
            key=f"{arm}-{seed}"
            hist=read(out/key/"progress.json")["history"]
            if set(hist)!={"epoch1",*(f"time{int(t)}" for t in RUNGS)}:
                raise ValueError("incomplete checkpoints")
            for row in hist.values():
                if sha(out/key/row["file"])!=row["weight_sha"] or sha(out/key/row["score_file"])!=row["score_sha"]:
                    raise ValueError("invalid freeze identity")
            ordered=sorted(hist,key=lambda k:hist[k]["step"])
            chosen=min(ordered,key=lambda k:hist[k]["development"]["nll"])
            gates={str(g):next((k for k in ordered if hist[k]["development"]["nll"]<=g),None) for g in GATES}
            panel[key]=dict(history=hist,best=chosen,gates=gates)
    bind(out/"seal.json",panel)
    return panel


def cold(root,out,data,panel):
    from network import make_model
    from study import inference
    rows=data.test
    metrics={}
    for arm in ARMS:
        for seed in SEEDS:
            key=f"{arm}-{seed}"
            cell=out/key
            spec=panel[key]
            model=make_model(root,HERE,arm,seed,data)
            scores={}
            for row in spec["history"].values():
                step=str(row["step"])
                if step in scores:
                    continue
                if sha(cell/row["file"])!=row["weight_sha"]:
                    raise ValueError("weights changed after seal")
                model.load_state_dict(torch.load(cell/row["file"],map_location="cpu",weights_only=True))
                tic=time.perf_counter()
                z=inference(model,data,rows)
                name=f"step{step}-held.npz"
                digest=stable_scores(cell/name,z)
                scores[step]=dict(file=name,sha=digest,wall=time.perf_counter()-tic,
                                  quality=quality(z,data.y[rows]))
                if arm=="returning" and row==spec["history"][spec["best"]]:
                    with torch.no_grad():
                        for layer in list(model.mixer)[1:]:
                            layer.wire.weight.zero_()
                    z=inference(model,data,rows)
                    name=f"step{step}-held-nowire.npz"
                    scores["no_wire"]=dict(file=name,sha=stable_scores(cell/name,z),
                                           quality=quality(z,data.y[rows]))
            metrics[key]=scores
    write(out/"held-identities.npz",dict(actors=data.actors[rows],labels=data.y[rows].numpy(),ids=data.names[rows]))
    write(out/"terminal.json",dict(seal_sha=sha(out/"seal.json"),identities_sha=sha(out/"held-identities.npz"),
                                    panels=metrics,utc_unix=time.time()))


def run(root,out,study_file):
    if sha(study_file)!=PARENT_HASH:
        raise ValueError("wrong shared data/score helpers")
    sys.path.insert(0,str(study_file.parent))
    sys.path.insert(0,str(root/"src"))
    from study import Data,HASHES
    for name,expected in HASHES.items():
        if sha(root/name)!=expected:
            raise ValueError(f"wrong input {name}")
    tables=read(HERE/"tables"/"tables.json")
    for row in tables.values():
        if sha(HERE/"tables"/row["file"])!=row["sha256"]:
            raise ValueError("table digest mismatch")
    torch.set_num_threads(1)
    out.mkdir(exist_ok=True,parents=True)
    with (out/"worker.lock").open("a") as guard:
        fcntl.flock(guard,fcntl.LOCK_EX|fcntl.LOCK_NB)
        recipe=dict(sources={str(p.name):sha(p) for p in (Path(__file__),HERE/"network.py",study_file)},
                    inputs=HASHES,tables=tables,arms=list(ARMS),seeds=list(SEEDS),rungs=list(RUNGS),
                    torch=str(torch.__version__))
        bind(out/"recipe.json",recipe)
        if (out/"terminal.json").is_file():
            return
        tic=time.perf_counter()
        data=Data(root)
        with (out/"sessions.jsonl").open("a") as f:
            f.write(json.dumps(dict(boot_unix=time.time(),load_wall=time.perf_counter()-tic,pid=os.getpid()))+"\n")
        for target in RUNGS:
            for j,seed in enumerate(SEEDS):
                for arm in (*ARMS[j:],*ARMS[:j]):
                    one_stage(root,out,data,arm,seed,target)
        cold(root,out,data,seal_panel(out))


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    for name in ("root","out","source_study"):
        parser.add_argument(name,type=Path)
    a=parser.parse_args()
    run(a.root.resolve(),a.out.resolve(),a.source_study.resolve())
