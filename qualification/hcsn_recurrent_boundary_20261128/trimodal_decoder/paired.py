"""Interleave genuine updates for all five learners; save real equal-time and equal-token endpoints."""
from argparse import ArgumentParser
from hashlib import sha256
from pathlib import Path
import json
import os
import time
import torch
import torch.nn.functional as F
import numpy as np
from train import ARMS,SEEDS,BATCH,evaluate
from data import streams,START
from network import architecture


def run(folder,seed,cpu,original):
    os.sched_setaffinity(0,{cpu});torch.set_num_threads(1)
    x,y,(tr,dev,held),_,modes,V,words=streams()
    arms={}
    for k in ARMS:
        t=time.perf_counter();net,width,error=architecture(V,k,seed)
        opt=torch.optim.AdamW(net.parameters(),lr=.002,weight_decay=.01)
        arms[k]=dict(model=net,opt=opt,width=width,error=error,setup=time.perf_counter()-t,
                     wall=0.,cpu=0.,steps=0,examples=0,targets=0,rows=[],rungs=set())
    rng=torch.Generator().manual_seed(seed)
    batch_id=0;affinity_changes=0
    while any(len(v["rungs"])<4 for v in arms.values()):
        for batch in torch.as_tensor(tr)[torch.randperm(len(tr),generator=rng)].split(BATCH):
            order=batch_id%len(ARMS);batch_id+=1
            for k in ARMS[order:]+ARMS[:order]:
                state=arms[k]
                if len(state["rungs"])==4:continue
                if os.sched_getaffinity(0)!={cpu}:
                    affinity_changes+=1;os.sched_setaffinity(0,{cpu})
                net,opt=state["model"],state["opt"]
                st=time.perf_counter();pr=time.process_time()
                scores=net(x[batch])[:,START:]
                targets=y[batch]
                loss=F.cross_entropy(scores.reshape(-1,V),targets.flatten(),ignore_index=-100)
                opt.zero_grad(set_to_none=True);loss.backward();torch.nn.utils.clip_grad_norm_(net.parameters(),1.);opt.step()
                state["cpu"]+=time.process_time()-pr;state["wall"]+=time.perf_counter()-st
                state["steps"]+=1;state["examples"]+=len(batch);state["targets"]+=int((targets!=-100).sum())
                reached=state["rungs"];ex=state["examples"]
                conditions=[("epoch1",ex==len(tr)),("epoch5",ex==5*len(tr)),
                            ("wall60",state["wall"]>=60),("cpu60",state["cpu"]>=60)]
                labels=[l for l,ok in conditions if ok and l not in reached]
                if not labels:continue
                reached.update(labels)
                nll,lp,choice=evaluate(net,x,y,dev,modes)
                f=folder/(f"{k}-{seed}-"+"-".join(labels)+".npz")
                weights={key:v.detach().cpu().numpy() for key,v in net.state_dict().items()}
                np.savez_compressed(f,**weights)
                recovered=None;orig_score=None
                if "epoch1" in labels:
                    old=json.loads((original/f"{k}-{seed}-seal.json").read_text())
                    prior=next(r for r in old["rows"] if "epoch1" in r["labels"])
                    with np.load(original/prior["weights"]) as reference:
                        recovered=max(float(np.max(abs(weights[key]-reference[key]))) for key in weights)
                    with np.load(original/prior["dev_file"]) as reference:
                        orig_score=float(np.max(abs(lp-reference["logp"])))
                    if recovered!=0 or orig_score!=0:raise ValueError((k,seed,recovered,orig_score))
                ds=folder/(f.stem+"-dev.npz");np.savez_compressed(ds,logp=lp,pred=choice)
                state["rows"].append(dict(labels=labels,steps=state["steps"],examples=ex,targets=state["targets"],
                    update_s=state["wall"],update_cpu=state["cpu"],dev=nll,weights=f.name,sha256=sha256(f.read_bytes()).hexdigest(),
                    dev_file=ds.name,dev_sha=sha256(ds.read_bytes()).hexdigest(),epoch_weight_error=recovered,
                    epoch_dev_error=orig_score))
                print(k,seed,labels,state["steps"],state["cpu"],nll,flush=True)
    for k,state in arms.items():
        net=state["model"];rows=state["rows"]
        best=min(rows,key=lambda v:np.mean(v["dev"]))["weights"]
        seal=dict(arm=k,seed=seed,best=best,width=state["width"],params=sum(p.numel() for p in net.parameters()),
                  setup_s=state["setup"],rows=rows,table_error=state["error"],vocabulary=V,
                  cpu_affinity=cpu,affinity_adjustments=affinity_changes,train_conditional=len(tr))
        (folder/f"{k}-{seed}-seal.json").write_text(json.dumps(seal,indent=2)+"\n")
if __name__=="__main__":
    a=ArgumentParser();a.add_argument("folder",type=Path);a.add_argument("seed",type=int);a.add_argument("cpu",type=int);a.add_argument("original",type=Path)
    p=a.parse_args();p.folder.mkdir(exist_ok=True,parents=True);run(p.folder,p.seed,p.cpu,p.original)
