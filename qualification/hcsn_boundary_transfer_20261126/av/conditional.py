"""Profile conditional readouts over actual sealed encoder features."""
import time
START=time.perf_counter()
import argparse
import json
from pathlib import Path

import numpy as np
import torch
from torch.nn import functional as F
from study import Encoder, SEEDS, data, evaluate, metrics, record, sha

DESIGNS={"raw":("raw",),"centered":("centered",),"gru":("gru",),"hybrid":("centered","gru")}
LAMBDAS=(.01,.1,1.,10.,100.)

def features(parent, inputs, seed, part, envelope):
    cache={}
    costs={}
    for arm in ("raw","centered","gru"):
        begin=time.perf_counter()
        weights=parent/f"{arm}-{seed}"/"weights.pt"
        if sha(weights)!=envelope[f"{arm}-{seed}"]["weights"]:
            raise ValueError("unsealed encoder")
        model=Encoder(arm,seed)
        model.load_state_dict(torch.load(weights,weights_only=True,map_location="cpu"))
        rows=[]
        hook=model.head.register_forward_pre_hook(lambda module,args:rows.append(args[0].detach().clone()))
        try:
            evaluate(model,inputs)
        finally:
            hook.remove()
        cache[arm]=torch.cat(rows).double()
        costs[arm]=time.perf_counter()-begin
    return cache,costs

def solve(z, y, penalty, method):
    if method=="direct":
        gram=z.T@z/len(z)+penalty*torch.eye(z.shape[1],dtype=z.dtype)
        return torch.linalg.solve(gram,z.T@y/len(z))
    w=torch.zeros(z.shape[1],y.shape[1],dtype=z.dtype,requires_grad=True)
    opt=torch.optim.LBFGS([w],lr=1,max_iter=150,line_search_fn="strong_wolfe",
                          tolerance_grad=1e-10,tolerance_change=1e-14)
    def objective():
        opt.zero_grad()
        loss=(z@w-y).square().sum(1).mean()+penalty*w.square().sum()
        loss.backward()
        return loss
    opt.step(objective)
    return w.detach()

def run(args):
    torch.set_num_threads(1)
    out=args.out
    out.mkdir(exist_ok=True)
    parents=json.loads((args.parent/"seal.json").read_text())
    if args.stage=="confirm":
        locked=json.loads((out/"readout_seal.json").read_text())
    phase_rows=[]
    for seed in SEEDS:
        roles=("train","dev") if args.stage=="fit" else ("test",)
        sets={s:data(args.data,s) for s in roles}
        fs={}; fc={}
        for s in roles:
            fs[s],fc[s]=features(args.parent,sets[s],seed,s,parents)
        record(out/f"features-{seed}-{args.stage}.json",fc)
        for design,parts in DESIGNS.items():
            zs={s:torch.cat([fs[s][a] for a in parts],dim=1) for s in roles}
            if args.stage=="fit":
                mean=zs["train"].mean(0)
                scale=zs["train"].std(0,unbiased=False).clamp_min(1e-6)
                zn=(zs["train"]-mean)/scale
                y=F.one_hot(sets["train"][1],6).double()
                bias=y.mean(0)
            methods=("bp","direct") if seed%2 else ("direct","bp")
            for method in methods:
                stem=f"{design}-{seed}-{method}"
                path=out/(stem+".npz")
                if args.stage=="fit":
                    start=time.perf_counter()
                    trace=[]
                    best=float("inf")
                    for lam in LAMBDAS:
                        w=solve(zn,y-bias,lam,method)
                        probs=(((zs["dev"]-mean)/scale)@w+bias).softmax(1)
                        score=metrics(probs,sets["dev"][1],sets["dev"][2])["brier"]
                        trace.append({"penalty":lam,"dev_brier":score})
                        if score<best:
                            best=score
                            keep=w.clone()
                            chosen=lam
                    np.savez(path,w=keep.numpy(),bias=bias.numpy(),mean=mean.numpy(),scale=scale.numpy())
                    row=dict(stem=stem,features=list(parts),trace=trace,selected=chosen,
                             exclusive_fit_seconds=time.perf_counter()-start,
                             parent_feature_seconds=sum(fc[s][a] for s in roles for a in parts),
                             parent_fit_seconds=sum(json.loads((args.parent/f"{a}-{seed}-fit-process.json").read_text())["wall_seconds"] for a in parts),
                             weights=sha(path))
                else:
                    if sha(path)!=locked[stem]:
                        raise ValueError("unsealed weights")
                    with np.load(path) as fitted:
                        w,b,m,s=[torch.from_numpy(fitted[k]) for k in ["w","bias","mean","scale"]]
                    probs=(((zs["test"]-m)/s)@w+b).softmax(1)
                    score=metrics(probs,sets["test"][1],sets["test"][2])
                    pred=out/(stem+"-predictions.npz")
                    np.savez_compressed(pred,p=probs.numpy(),y=sets["test"][1].numpy(),
                                       actor=sets["test"][2],clip=sets["test"][3])
                    row=dict(stem=stem,results=score,predictions=sha(pred))
                phase_rows.append(row)
    if args.stage=="fit":
        record(out/"readout_seal.json",{r["stem"]:r["weights"] for r in phase_rows})
    record(out/(args.stage+".json"),{"rows":phase_rows,"wall_seconds":time.perf_counter()-START})

if __name__=="__main__":
    a=argparse.ArgumentParser()
    a.add_argument("stage",choices=("fit","confirm"))
    for k in ("data","parent","out"):
        a.add_argument(k,type=Path)
    run(a.parse_args())
