"""Run the registered scheduling sensitivity with a matched minibatch and round-robin arms."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import numpy as np
import torch
from run import ARMS,SEEDS,initialize,sha,keep,raw,note,quality,choose_cpus

LABELS=("epoch1","wall60","cpu60")

def record(a,arm,net,state,label):
    from study import inference
    folder=a.out/f"{arm}-{a.seed}"
    step=state["steps"];weight=folder/f"step{step}.pt";dev=folder/f"step{step}-dev.npz"
    logits=inference(net,a.ds,a.ds.dev)
    row=dict(steps=step,samples=state["samples"],wall_s=state["wall"],cpu_s=state["cpu"],
             core=a.core,pre_rebinds=state["pre_rebinds"],post_changes=state["post_changes"],
             weight=weight.name,weight_sha=keep(weight,lambda f:torch.save(net.state_dict(),f)),
             dev=dev.name,dev_sha=raw(dev,logits),development=quality(logits,a.ds.y[a.ds.dev]))
    note(folder/(label+".json"),row);state["history"][label]=row
    print(arm,a.seed,label,step,round(state["wall"],2),round(state["cpu"],2),flush=True)

def panel(a):
    from network import make_model
    from encoder import pair_loss
    ds=a.ds;active={}
    for arm in ARMS:
        net=make_model(a.data,arm,a.seed,ds.words)
        opt=torch.optim.AdamW(net.parameters(),lr=.0003,weight_decay=.01,foreach=False)
        active[arm]=(net,opt,dict(steps=0,samples=0,wall=0.,cpu=0.,pre_rebinds=0,post_changes=0,history={}))
    rng=np.random.default_rng(a.seed+47198);perm=np.empty(0,dtype=int);cursor=0;round_index=SEEDS.index(a.seed)
    while any(set(s["history"])!=set(LABELS) for n,o,s in active.values()):
        if cursor==len(perm):perm=rng.permutation(ds.train);cursor=0
        ids=perm[cursor:cursor+16];cursor+=len(ids)
        for arm in ARMS[round_index%4:]+ARMS[:round_index%4]:
            net,opt,state=active[arm]
            if len(state["history"])==len(LABELS):continue
            assigned={a.core}
            if os.sched_getaffinity(0)!=assigned:
                state["pre_rebinds"]+=1;os.sched_setaffinity(0,assigned)
            wall=time.perf_counter();cpu=time.process_time()
            y=ds.y[ids];opt.zero_grad(set_to_none=True);net.train()
            av,txt=net(ds.v[ids],ds.audio[ids],ds.tokens[y]);loss=pair_loss(av,txt,y)
            loss.backward();torch.nn.utils.clip_grad_norm_(net.parameters(),1.,error_if_nonfinite=True);opt.step()
            state["wall"]+=time.perf_counter()-wall;state["cpu"]+=time.process_time()-cpu
            state["steps"]+=1;state["samples"]+=len(ids)
            state["post_changes"]+=int(os.sched_getaffinity(0)!=assigned)
            labels=[]
            if state["steps"]==312:
                assert state["samples"]==4984;labels.append("epoch1")
            for key,threshold in [("wall60","wall"),("cpu60","cpu")]:
                if not key in state["history"] and state[threshold]>=60:labels.append(key)
            for label in labels:record(a,arm,net,state,label)
        round_index+=1

def evaluate(a):
    from network import make_model
    from study import inference
    sel={};losses={};views=0
    for arm in ARMS:
        for seed in SEEDS:
            key=f"{arm}-{seed}";folder=a.out/key;sel[key]={}
            for label in LABELS:
                r=json.loads((folder/(label+".json")).read_text())
                assert sha(folder/r["weight"])==r["weight_sha"] and sha(folder/r["dev"])==r["dev_sha"]
                sel[key][label]=r
    seal=note(a.out/"seal.json",sel);rows={}
    for key,all_rows in sel.items():
        arm,seed=key.split("-");folder=a.out/key
        for label,r in all_rows.items():
            net=make_model(a.data,arm,int(seed),a.ds.words)
            w=torch.load(folder/r["weight"],weights_only=True,map_location="cpu");net.load_state_dict(w)
            z=inference(net,a.ds,a.ds.dev)
            with np.load(folder/r["dev"]) as f:assert np.array_equal(z.numpy(),f["logits"])
            held=inference(net,a.ds,a.ds.test);path=folder/(label+"-held.npz");h=raw(path,held)
            newnet=make_model(a.data,arm,int(seed),a.ds.words);newnet.load_state_dict(torch.load(folder/r["weight"],weights_only=True,map_location="cpu"))
            assert np.array_equal(held.numpy(),inference(newnet,a.ds,a.ds.test).numpy())
            y=a.ds.y[a.ds.test].numpy();logits=held.numpy().astype(float)
            metric=np.stack((np.logaddexp.reduce(logits,axis=1)-logits[np.arange(len(y)),y],(logits.argmax(1)==y).astype(float)))
            losses[key,label]=metric;views+=held.numel()+z.numel()
            res=dict(held_sha256=h,quality=metric.mean(1).tolist(),cpu_s=r["cpu_s"],wall_s=r["wall_s"],steps=r["steps"],pre_rebinds=r["pre_rebinds"],post_changes=r["post_changes"])
            if label=="epoch1":
                prior=a.original/key;old=json.loads((prior/"development.json").read_text())["epoch1"]
                old_w=torch.load(prior/old["weight"],weights_only=True,map_location="cpu")
                old_held=prior/"epoch1-held.npz"
                res["all_epoch1_tensors_exact"]=all(torch.equal(w[n],old_w[n]) for n in w)
                with np.load(old_held) as f:res["all_original_held_exact"]=bool(np.array_equal(held.numpy(),f["logits"]))
            rows[key+"/"+label]=res
    actors=a.ds.actors[a.ds.test];group=[np.flatnonzero(actors==v) for v in np.unique(actors)]
    draws=np.random.default_rng(731014).integers(0,len(group),(4000,len(group)))
    count=np.array([np.bincount(x,minlength=len(group)) for x in draws]);den=count@np.array(list(map(len,group)))
    contrasts={};means={}
    for label in LABELS:
        means[label]={arm:np.mean([losses[f"{arm}-{s}",label].mean(1) for s in SEEDS],0).tolist() for arm in ARMS}
        for arm in ARMS[1:]:
            diff=np.mean([losses[f"signed-{s}",label]-losses[f"{arm}-{s}",label] for s in SEEDS],0)
            grouped=np.array([diff[:,g].sum(1) for g in group]);ci=np.quantile(count@grouped/den[:,None],[.025,.975],axis=0).T
            contrasts[label+"/signed-minus-"+arm]=dict(mean=diff.mean(1).tolist(),actor95=ci.tolist())
    note(a.out/"terminal.json",dict(seal_sha256=seal,metrics=rows,means=means,contrasts=contrasts,replayed_scores=views))
if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("data",type=Path);p.add_argument("study",type=Path);p.add_argument("out",type=Path);p.add_argument("original",type=Path)
    p.add_argument("--seed",type=int);p.add_argument("--core",type=int);a=p.parse_args();a.out.mkdir(exist_ok=True,parents=True)
    a.ds=initialize(a)
    if a.seed:panel(a)
    else:
        cores=choose_cpus();note(a.out/"protocol.json",dict(cores=cores,seeds=SEEDS,source_sha256=sha(Path(__file__)),protocol_sha256=sha(Path(__file__).with_name("TIMING_CONFIRMATION.md"))))
        runners=[subprocess.Popen([sys.executable,"-u",*sys.argv,"--seed",str(s),"--core",str(c)]) for s,c in zip(SEEDS,cores)]
        assert all(x==0 for x in [p.wait() for p in runners]);evaluate(a)
