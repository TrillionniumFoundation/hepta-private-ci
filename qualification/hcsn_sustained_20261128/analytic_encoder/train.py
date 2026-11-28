"""Paired, complete-resolution full-pass and time-matched audiovisual comparison."""
import argparse
import fcntl
import json
from pathlib import Path
import sys
import time

import numpy as np
import torch
from encoder_adapter import AnalyticAVText
from encoder import AVText,pair_loss

ARMS=("lookup","exact","learn","ramp","sdpa")
SEEDS=(137,311,557)


def net_for(root,data,arm,seed):
    asset=root/"src/law4.npz"
    if arm in ("lookup","sdpa"):
        return AVText("literal" if arm=="lookup" else arm,96,seed,data.words,asset)
    return AnalyticAVText(96,seed,data.words,asset,learn_contract=arm=="learn",continuous=arm=="ramp")


def metrics(scores,y):
    z=np.asarray(scores,dtype=np.float64)
    if z.shape!=(len(y),72) or not np.isfinite(z).all():raise ValueError("gallery scores")
    ell=np.logaddexp.reduce(z,axis=1)-z[np.arange(len(y)),y]
    return dict(nll=float(ell.mean()),top1=float(np.mean(z.argmax(1)==y))),ell


def fit(root,data,out,arm,seed):
    from study import digest,save_state,write_json,inference
    dst=out/f"{arm}-{seed}";dst.mkdir(exist_ok=True)
    info=dst/"fit.json"
    if info.is_file():return json.loads(info.read_text())
    tic=time.perf_counter()
    model=net_for(root,data,arm,seed)
    opt=torch.optim.AdamW(model.parameters(),lr=.0003,weight_decay=.01,foreach=False)
    setup=time.perf_counter()-tic
    active=cpu=0.;step=seen=epoch=0;history={};law_first={}
    rng=np.random.default_rng(seed+7369)
    while len(history)<2:
        order=rng.permutation(data.train)
        if len(np.unique(order))!=4984:raise ValueError("training fold")
        epoch+=1
        for start in range(0,len(order),16):
            rows=order[start:start+16];y=data.y[rows]
            ts=time.perf_counter();cs=time.process_time()
            model.train();opt.zero_grad(set_to_none=True)
            av,tx=model(data.v[rows],data.audio[rows],data.tokens[y])
            loss=pair_loss(av,tx,y);loss.backward()
            norm=torch.nn.utils.clip_grad_norm_(model.parameters(),1.,error_if_nonfinite=True)
            if step==0 and arm=="learn":
                law_first={k:float(v.grad) for k,v in model.law.named_parameters()}
                if not all(np.isfinite(v) and abs(v)>0 for v in law_first.values()):raise ValueError(law_first)
            opt.step()
            active+=time.perf_counter()-ts;cpu+=time.process_time()-cs;step+=1;seen+=len(rows)
            tags=[]
            if step==312:tags.append("pass")
            if active>=60. and "clock" not in history:tags.append("clock")
            if tags:
                ts=time.perf_counter();p=dst/f"step-{step}.pt";save_state(p,model.state_dict());save_s=time.perf_counter()-ts
                ts=time.perf_counter();z=inference(model,data,data.dev).numpy();dev_s=time.perf_counter()-ts
                dp=dst/f"dev-{step}.npz";np.savez_compressed(dp,ids=data.names[data.dev],labels=data.y[data.dev].numpy(),scores=z)
                measure,_=metrics(z,data.y[data.dev].numpy())
                coeff={}
                if arm=="learn":
                    coeff={k:v for k,v in zip(("sigma","premium"),[float(b*np.exp(.7*np.tanh(float(v.detach()))))
                               for b,v in zip((.23,.01),(model.law.raw_sigma,model.law.raw_premium))])}
                rec=dict(step=step,seen=seen,distinct=min(seen,len(data.train)),active_s=active,cpu_s=cpu,
                         development=measure,dev_file=dp.name,dev_sha256=digest(dp),dev_s=dev_s,save_s=save_s,
                         file=p.name,sha256=digest(p),last_grad=float(norm),learned_contract=coeff)
                for tag in tags:history[tag]=rec
                print(arm,seed,tags,step,round(active,2),round(measure["nll"],5),flush=True)
                if len(history)==2:break
    result=dict(arm=arm,seed=seed,parameters=sum(p.numel() for p in model.parameters()),setup_s=setup,
                law_first_gradient=law_first,history=history)
    write_json(info,result)
    return result


@torch.no_grad()
def gallery(model,data,rows,audio_index,video_index):
    model.eval()
    tx=model.encode(model.text(data.tokens))
    chunks=[]
    for jj in np.array_split(np.arange(len(rows)),(len(rows)+31)//32):
        av=model.encode(model.front(data.v[video_index[jj]],data.audio[audio_index[jj]]))
        chunks.append(12.*(av@tx.T))
    return torch.cat(chunks).numpy()


def run(root,support,out):
    sys.path.append(str(support))
    from study import Data,HASHES,digest,write_json
    for name,identity in HASHES.items():
        if digest(root/name)!=identity:raise ValueError(name)
    if not Path("verified.json").is_file():raise ValueError("analytic implementation verification required")
    torch.set_num_threads(1);torch.set_num_interop_threads(1)
    out.mkdir(exist_ok=True,parents=True)
    with (out/"lock").open("a") as guard:
        fcntl.flock(guard,fcntl.LOCK_EX|fcntl.LOCK_NB)
        if (out/"terminal.json").is_file():return
        data=Data(root)
        fits={}
        for i,s in enumerate(SEEDS):
            for a in ARMS[i:]+ARMS[:i]:
                fits[f"{a}-{s}"]=fit(root,data,out,a,s)
        for key,rr in fits.items():
            for step in rr["history"].values():
                if digest(out/key/step["file"])!=step["sha256"]:raise ValueError("seal weight")
        seal=out/"seal.json"
        if seal.is_file():
            if json.loads(seal.read_text())!=fits:raise ValueError("frozen endpoints changed")
        else:write_json(seal,fits)
        rows=data.test
        other=rows.copy()
        for actor in np.unique(data.actors[rows]):
            indices=np.flatnonzero(data.actors[rows]==actor)
            perm=np.random.default_rng(int(actor)+6312).permutation(indices)
            other[perm]=rows[np.roll(perm,1)]
        result={};ell={}
        for key,rec in fits.items():
            arm=rec["arm"];seed=rec["seed"];dst=out/key
            for endpoint,r in rec["history"].items():
                tic=time.perf_counter()
                scores=dst/f"cold-{endpoint}.npz"
                if not scores.is_file():
                    n=net_for(root,data,arm,seed)
                    p=dst/r["file"]
                    if digest(p)!=r["sha256"]:raise ValueError("cold hash")
                    n.load_state_dict(torch.load(p,weights_only=True,map_location="cpu"))
                    zz={name:gallery(n,data,rows,au,vi) for name,au,vi in
                        (("aligned",rows,rows),("audio_swapped",other,rows),("video_swapped",rows,other))}
                    if arm!="sdpa":
                        with torch.no_grad():
                            for m in n.mixer[1:]:m.wire.weight.zero_()
                        zz["no_wire"]=gallery(n,data,rows,rows,rows)
                    tmp=scores.with_suffix(".tmp")
                    with tmp.open("wb") as file:np.savez_compressed(file,ids=data.names[rows],labels=data.y[rows].numpy(),**zz)
                    tmp.replace(scores)
                    write_json(dst/f"cold-{endpoint}.json",dict(elapsed_s=time.perf_counter()-tic,score_sha256=digest(scores)))
                meta=json.loads((dst/f"cold-{endpoint}.json").read_text())
                if digest(scores)!=meta["score_sha256"]:raise ValueError("cold archive")
                with np.load(scores) as z:
                    np.testing.assert_array_equal(z["ids"],data.names[rows]);np.testing.assert_array_equal(z["labels"],data.y[rows].numpy())
                    obs={}
                    for v in z.files:
                        if v in ("ids","labels"):continue
                        obs[v],ell[key,endpoint,v]=metrics(z[v],z["labels"])
                result.setdefault(key,{})[endpoint]=dict(variants=obs,**meta)
        who,ix=np.unique(data.actors[rows],return_inverse=True)
        draws=np.random.default_rng(431904).integers(0,len(who),(4000,len(who)))
        counts=np.bincount(ix)
        def ci(delta):
            ss=np.bincount(ix,weights=delta)
            return [float(delta.mean()),*np.quantile(ss[draws].sum(1)/counts[draws].sum(1),[.025,.975]).tolist()]
        comparisons={};means={}
        for endpoint in ("pass","clock"):
            comparisons[endpoint]={};means[endpoint]={}
            for a in ARMS:
                means[endpoint][a]={m:float(np.mean([result[f"{a}-{s}"][endpoint]["variants"]["aligned"][m]
                                              for s in SEEDS])) for m in ("nll","top1")}
                for b in ("lookup","sdpa"):
                    comparisons[endpoint][a+"-minus-"+b]=ci(np.mean([
                        ell[f"{a}-{s}",endpoint,"aligned"]-ell[f"{b}-{s}",endpoint,"aligned"] for s in SEEDS],0))
                for variant in result[f"{a}-137"][endpoint]["variants"]:
                    if variant=="aligned":continue
                    comparisons[endpoint][a+"-"+variant+"-minus-aligned"]=ci(np.mean([
                        ell[f"{a}-{s}",endpoint,variant]-ell[f"{a}-{s}",endpoint,"aligned"] for s in SEEDS],0))
        write_json(out/"terminal.json",dict(seal_sha256=digest(seal),means=means,results=result,actor_ci=comparisons))
        print("terminal",means,flush=True)


if __name__=="__main__":
    cmd=argparse.ArgumentParser()
    for name in ("source","support","out"):cmd.add_argument(name,type=Path)
    p=cmd.parse_args();run(p.source,p.support,p.out)
