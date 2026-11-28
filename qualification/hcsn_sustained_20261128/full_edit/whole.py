"""Whole-corpus paired HCSN direct construction and gradient training."""
import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

import numpy as np
import torch

from study import Data, HASHES, SEEDS, digest, inference, save_state, write_json
from direct import make_net, parameters, fit_forward
from calibrate import fit as calibrate, stats

NAMES=("forward","shuffled","head","same_site_bp","full_bp")
MODES=("raw","temperature_prior")
GATES=(4.1,3.6,3.0)


def loss_scores(scores,y,r,mode,prior):
    return stats(scores,y,r["beta"] if mode=="temperature_prior" else 1.,
                 prior if mode=="temperature_prior" else np.zeros_like(prior))


def fit_group(root,out,d,name,seed,prior):
    from encoder import pair_loss
    key=f"{name}-{seed}"
    loc=out/key
    loc.mkdir(exist_ok=True)
    fin=loc/"fits.json"
    if fin.exists():
        rr=json.loads(fin.read_text())
        if not all(digest(loc/r["weights"])==r["sha256"] for r in rr):
            raise ValueError("recovered weights "+key)
        return rr
    begin=time.perf_counter()
    net=make_net(root,d,seed)
    sites=parameters(net)
    if name=="same_site_bp":
        net.requires_grad_(False)
        for p in sites.values():p.requires_grad_(True)
    opt=None
    if name.endswith("_bp"):
        trainable=[p for p in net.parameters() if p.requires_grad]
        opt=torch.optim.AdamW(trainable,lr=.0003,weight_decay=.01,foreach=False)
    else:
        net.requires_grad_(False)
        trainable=list(sites.values()) if name!="head" else [sites["projection"]]
    opened=sum(p.numel() for p in trainable)
    rng=np.random.default_rng(seed+7369)
    records=[]
    fit_s=0.
    for epoch in range(1,5):
        tic=time.perf_counter()
        ids=rng.permutation(d.train)
        if opt is None:
            fit_forward(net,d,ids,name,seed)
        else:
            net.train()
            for start in range(0,len(ids),16):
                batch=ids[start:start+16]
                y=d.y[batch]
                opt.zero_grad(set_to_none=True)
                av,tx=net(d.v[batch],d.audio[batch],d.tokens[y])
                loss=pair_loss(av,tx,y)
                loss.backward()
                torch.nn.utils.clip_grad_norm_(trainable,1.,error_if_nonfinite=True)
                opt.step()
        fit_s+=time.perf_counter()-tic
        if epoch in (1,2,4):
            p=loc/f"epoch{epoch}.pt"
            save_state(p,net.state_dict())
            scores=inference(net,d,d.dev).double().numpy()
            ydev=d.y[d.dev].numpy()
            model=calibrate(scores,ydev,prior)
            rec=dict(epoch=epoch,fit_s=fit_s,weights=p.name,sha256=digest(p),beta=model["multiplier"],
                     training_examples=epoch*len(ids),unique_training_examples=len(ids),writable=opened,
                     model_parameters=sum(w.numel() for w in net.parameters()),
                     last_epoch_indices_sha256=hashlib.sha256(ids.astype("<i8").tobytes()).hexdigest())
            rec["dev"]={m:loss_scores(scores,ydev,rec,m,prior)[0] for m in MODES}
            rec["charged_to_development_s"]=time.perf_counter()-begin
            records.append(rec)
            packets=dict(ids=d.names[d.dev],scores=scores.astype(np.float32),y=ydev)
            np.savez_compressed(loc/f"dev-{epoch}.npz",**packets)
            print(key,epoch,rec["dev"]["raw"],round(fit_s,2),flush=True)
    write_json(fin,records)
    return records


def run(root,out):
    out.mkdir(exist_ok=True,parents=True)
    if (out/"terminal.json").is_file():
        return
    start=time.perf_counter()
    for path,sha in HASHES.items():
        if digest(root/path)!=sha:raise ValueError(path)
    sys.path.insert(0,str(root/"src"))
    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
    d=Data(root)
    counts=np.bincount(d.y[d.train].numpy(),minlength=72)
    prior=np.log(counts/counts.sum())
    prep=time.perf_counter()-start
    fits={}
    for j,s in enumerate(SEEDS):
        for i in range(len(NAMES)):
            n=NAMES[(i+j)%len(NAMES)]
            fits[f"{n}-{s}"]=fit_group(root,out,d,n,s,prior)
    picks={k:{m:min(rr,key=lambda r:(r["dev"][m]["nll"],r["epoch"]))["epoch"] for m in MODES} for k,rr in fits.items()}
    seal=out/"development_seal.json"
    registry=dict(fits=fits,picks=picks,source_sha256=digest(Path(__file__)),input_sha256=HASHES,train_counts=counts.tolist())
    if seal.exists() and json.loads(seal.read_text())!=registry:raise ValueError("seal changed")
    if not seal.exists():write_json(seal,registry)
    y=d.y[d.test].numpy()
    dloss={}
    held={}
    clocks={}
    gates={}
    for key,rr in fits.items():
        name,seed=key.rsplit("-",1)
        loc=out/key
        dloss[key],held[key],gates[key]={},{},{m:{} for m in MODES}
        cold_spent=0.
        for r in rr:
            epoch=r["epoch"]
            tic=time.perf_counter()
            if digest(loc/r["weights"])!=r["sha256"]:raise ValueError("cold fit hash")
            net=make_net(root,d,int(seed))
            net.load_state_dict(torch.load(loc/r["weights"],map_location="cpu",weights_only=True),strict=True)
            scores=inference(net,d,d.test).double().numpy()
            np.savez_compressed(loc/f"cold-{epoch}.npz",ids=d.names[d.test],y=y,scores=scores.astype(np.float32))
            held[key][str(epoch)]={}
            for m in MODES:
                val,loss=loss_scores(scores,y,r,m,prior)
                held[key][str(epoch)][m]=val
                if picks[key][m]==epoch:dloss[key][m]=loss
            cold_spent+=time.perf_counter()-tic
            for m in MODES:
                for gate in GATES:
                    if str(gate) not in gates[key][m] and max(r["dev"][m]["nll"],held[key][str(epoch)][m]["nll"])<=gate:
                        gates[key][m][str(gate)]=dict(epoch=epoch,optimization_s=r["fit_s"],
                            charged_through_validation_and_observed_cold_prefixes_s=prep+r["charged_to_development_s"]+cold_spent)
        clocks[key]=prep+rr[-1]["charged_to_development_s"]+cold_spent
    clusters=np.unique(d.actors[d.test],return_inverse=True)[1]
    mass=np.bincount(clusters)
    ix=np.random.default_rng(91363).integers(len(mass),size=(4000,len(mass)))
    contrasts={}
    for mode in MODES:
        contrasts[mode]={}
        for other in NAMES[1:]:
            delta=np.mean([dloss[f"forward-{s}"][mode]-dloss[f"{other}-{s}"][mode] for s in SEEDS],0)
            sums=np.bincount(clusters,weights=delta)
            ci=np.quantile(sums[ix].sum(1)/mass[ix].sum(1),[.025,.975])
            contrasts[mode][other]=dict(nll=float(delta.mean()),actor_ci95=ci.tolist())
    result=dict(seal_sha256=digest(seal),source_sha256=digest(Path(__file__)),torch=str(torch.__version__),
                cold=held,gates=gates,charged_s=clocks,selected=picks,forward_minus_control=contrasts,
                total_wall_s=time.perf_counter()-start,common_prep_s=prep)
    write_json(out/"terminal.json",result)
    print("terminal",digest(out/"terminal.json"),flush=True)


if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("root",type=Path);p.add_argument("output",type=Path)
    a=p.parse_args();run(a.root.resolve(),a.output.resolve())
