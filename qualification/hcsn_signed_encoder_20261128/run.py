"""Train registered signed-drift cells, freeze all choices and replay the original held arrays."""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import numpy as np
import torch

ROOT=Path(__file__).resolve().parent
ARMS=("signed","free","nonfinancial","noforce")
SEEDS=(137,311,557)
INPUTS={"src/encoder.py":"1c5ee669c47adaca3bec2ae3def64aec117596c8628345beb300e143628824df",
        "src/hcsn_temporal.py":"1c5ee332f549e3d9ffbff21bfeeef0e181d34e0606e5c27b38bcc66a48ae5eec",
        "src/law4.npz":"de7378f3c170750fb16d1280bcaa376a8904a207da32d268cac82525469e2ea4",
        "data/data.npz":"18423277257e2e487521d83a8c116bc7cf5599411f4ff769e569bd849beae6ad"}
STUDY="69e8cf12bcfcd414175250405ac08286901457377d76c1ad28f08d33a775dbc1"
def sha(p):
    with p.open("rb") as f:return hashlib.file_digest(f,"sha256").hexdigest()
def keep(path,write):
    path.parent.mkdir(exist_ok=True,parents=True)
    with tempfile.NamedTemporaryFile(dir=path.parent,delete=False) as f:
        tmp=Path(f.name)
        try:write(f)
        except BaseException:tmp.unlink();raise
    try:
        digest=sha(tmp)
        try:os.link(tmp,path)
        except FileExistsError:
            if sha(path)!=digest:raise ValueError("refusing to replace original "+str(path))
    finally:tmp.unlink(missing_ok=True)
    return digest
def note(p,v):return keep(p,lambda f:f.write((json.dumps(v,sort_keys=True,indent=2,allow_nan=False)+"\n").encode()))
def raw(p,z):return keep(p,lambda f:np.savez_compressed(f,logits=z.detach().cpu().numpy()))
def quality(z,y):
    a=z.detach().cpu().numpy().astype(float);y=y.numpy()
    return [float((np.logaddexp.reduce(a,axis=1)-a[np.arange(len(y)),y]).mean()),float((a.argmax(1)==y).mean())]
def initialize(a):
    sys.path[:0]=[str(ROOT),str(a.data/"src"),str(a.study.parent)]
    for n,h in INPUTS.items():
        if sha(a.data/n)!=h:raise ValueError(n)
    if sha(a.study)!=STUDY:raise ValueError("unregistered study")
    from study import Data
    torch.set_num_threads(1)
    return Data(a.data)
def fit(a):
    os.sched_setaffinity(0,{a.core})
    from network import make_model
    from study import inference
    from encoder import pair_loss
    data=a.ds;seed=a.seed;offset=SEEDS.index(seed)
    for arm in ARMS[offset:]+ARMS[:offset]:
        cell=a.out/f"{arm}-{seed}";cell.mkdir(exist_ok=True,parents=True)
        if (cell/"development.json").exists():continue
        # An interrupted attempt always retains its own directory. Full attempts receive different identities.
        names=[d for d in cell.glob("attempt-*") if d.is_dir()]
        attempt=cell/f"attempt-{len(names)+1:02d}";attempt.mkdir()
        setup=time.perf_counter()
        n=make_model(a.data,arm,seed,data.words)
        opt=torch.optim.AdamW(n.parameters(),lr=.0003,weight_decay=.01,foreach=False)
        setup=time.perf_counter()-setup
        rng=np.random.default_rng(seed+47198);order=np.empty(0,int);idx=0
        steps=samples=0;active=cpu=0.;hist={}
        cpu_id=list(os.sched_getaffinity(0))
        while set(hist)!={"epoch1","time60"}:
            if idx==len(order):order=rng.permutation(data.train);idx=0
            ids=order[idx:idx+16];idx+=len(ids)
            toc=time.perf_counter();c0=time.process_time()
            y=data.y[ids];opt.zero_grad(set_to_none=True);n.train()
            av,text=n(data.v[ids],data.audio[ids],data.tokens[y])
            loss=pair_loss(av,text,y);loss.backward();grad=torch.nn.utils.clip_grad_norm_(n.parameters(),1.,error_if_nonfinite=True);opt.step()
            active+=time.perf_counter()-toc;cpu+=time.process_time()-c0
            samples+=len(ids);steps+=1
            labs=[]
            if steps==312:
                assert samples==4984
                labs.append("epoch1")
            if active>=60 and "time60" not in hist:labs.append("time60")
            if labs:
                toc=time.perf_counter();z=inference(n,data,data.dev)
                wp=attempt/f"step{steps}.pt";sp=attempt/f"step{steps}-dev.npz"
                row=dict(steps=steps,samples=samples,active_s=active,cpu_s=cpu,setup_s=setup,
                         weight=wp.relative_to(cell).as_posix(),weight_sha=keep(wp,lambda f:torch.save(n.state_dict(),f)),
                         development_scores=sp.relative_to(cell).as_posix(),development_sha=raw(sp,z),
                         quality=quality(z,data.y[data.dev]),cpu_affinity=cpu_id,loss=float(loss.detach()),gradient_norm=float(grad))
                row["scoring_and_persistence_s"]=time.perf_counter()-toc
                for lab in labs:
                    hist[lab]=row
                    note(attempt/(lab+".json"),row)
                print(arm,seed,labs,steps,round(active,2),row["quality"],flush=True)
        note(cell/"development.json",hist)
def derive(a):
    from network import make_model
    from study import inference
    data=a.ds
    sel={}
    for arm in ARMS:
        for seed in SEEDS:
            key=f"{arm}-{seed}";cell=a.out/key
            hist=json.loads((cell/"development.json").read_bytes())
            if set(hist)!={"epoch1","time60"}:raise ValueError("incomplete stage")
            for label,r in hist.items():
                if sha(cell/r["weight"])!=r["weight_sha"] or sha(cell/r["development_scores"])!=r["development_sha"]:raise ValueError(key)
                if label=="epoch1" and (r["steps"]!=312 or r["samples"]!=4984):raise ValueError(label)
                if label=="time60" and r["active_s"]<60:raise ValueError(label)
            sel[key]=hist
    seal=note(a.out/"seal.json",sel)
    losses={};metrics={};checks=0
    for arm in ARMS:
        for seed in SEEDS:
            key=f"{arm}-{seed}";cell=a.out/key
            for label,r in sel[key].items():
                n=make_model(a.data,arm,seed,data.words)
                n.load_state_dict(torch.load(cell/r["weight"],weights_only=True,map_location="cpu"))
                dz=inference(n,data,data.dev)
                with np.load(cell/r["development_scores"]) as f:
                    if not np.array_equal(dz.numpy(),f["logits"]):raise ValueError("development replay")
                z=inference(n,data,data.test)
                file=cell/(label+"-held.npz");h=raw(file,z)
                n2=make_model(a.data,arm,seed,data.words)
                n2.load_state_dict(torch.load(cell/r["weight"],weights_only=True,map_location="cpu"))
                replay=inference(n2,data,data.test)
                if not np.array_equal(z.numpy(),replay.numpy()):raise ValueError("cold replay")
                x=z.numpy().astype(float);y=data.y[data.test].numpy()
                v=np.stack((np.logaddexp.reduce(x,axis=1)-x[np.arange(len(y)),y],(x.argmax(1)==y).astype(float)))
                losses[key,label]=v
                metrics[key,label]=dict(held_file=file.relative_to(a.out).as_posix(),held_sha=h,nll=float(v[0].mean()),top1=float(v[1].mean()),steps=r["steps"],active_s=r["active_s"],cpu_s=r["cpu_s"])
                checks+=z.numel()+dz.numel()
    actors=data.actors[data.test]
    groups=[np.flatnonzero(actors==q) for q in np.unique(actors)]
    draws=np.random.default_rng(731014).integers(0,len(groups),(4000,len(groups)))
    w=np.array([np.bincount(x,minlength=len(groups)) for x in draws]);den=w@np.array(list(map(len,groups)))
    contrasts={}
    for label in ("epoch1","time60"):
        for control in ARMS[1:]:
            dif=np.mean([losses[f"signed-{s}",label]-losses[f"{control}-{s}",label] for s in SEEDS],0)
            sums=np.array([dif[:,group].sum(1) for group in groups])
            ci=np.quantile((w@sums)/den[:,None],[.025,.975],axis=0).T
            contrasts[label+"/signed-minus-"+control]=dict(mean=dif.mean(1).tolist(),actor95=ci.tolist())
    means={lab:{arm:np.mean([losses[f"{arm}-{s}",lab].mean(1) for s in SEEDS],0).tolist() for arm in ARMS} for lab in ("epoch1","time60")}
    note(a.out/"terminal.json",dict(seal_sha256=seal,metrics={k+"/"+lab:v for (k,lab),v in metrics.items()},
                                    means=means,contrasts=contrasts,replayed_scores=checks,actors=len(groups),
                                    signed_superiority=all(v["actor95"][0][1]<0 for v in contrasts.values())))
def choose_cpus():
    allowed=os.sched_getaffinity(0);cores={}
    for i in sorted(allowed):
        link=Path(f"/sys/devices/system/cpu/cpu{i}/topology/thread_siblings_list").read_text().strip()
        cores.setdefault(link,i)
    def snapshot():
        rows={}
        for line in Path("/proc/stat").read_text().splitlines():
            v=line.split()
            if v and v[0].startswith("cpu") and v[0][3:].isdigit():
                t=list(map(int,v[1:]));rows[int(v[0][3:])]=(sum(t[:8]),t[3]+t[4])
        return rows
    first=snapshot();time.sleep(.6);second=snapshot()
    def idle(link):
        ids=list(map(int,link.split(",")))
        total=sum(second[i][0]-first[i][0] for i in ids)
        return sum(second[i][1]-first[i][1] for i in ids)/max(1,total)
    return [cores[k] for k in sorted(cores,key=idle,reverse=True)[:3]]
if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("mode",choices=["run","cell","score"]);p.add_argument("data",type=Path);p.add_argument("study",type=Path);p.add_argument("out",type=Path);p.add_argument("--seed",type=int);p.add_argument("--core",type=int)
    a=p.parse_args();a.out.mkdir(parents=True,exist_ok=True)
    a.ds=initialize(a)
    if a.mode=="cell":fit(a)
    elif a.mode=="score":derive(a)
    else:
        with (a.out/"lock").open("a") as f:
            fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)
            if (a.out/"terminal.json").exists():sys.exit(0)
            note(a.out/"recipe.json",dict(sources={n:sha(ROOT/n) for n in ("run.py","network.py","force_kernel.py","PROTOCOL.md")},inputs=INPUTS,study=STUDY,torch=str(torch.__version__),arms=list(ARMS),seeds=list(SEEDS)))
            cores=choose_cpus()
            jobs=[subprocess.Popen([sys.executable,"-u",str(Path(__file__)),"cell",str(a.data),str(a.study),str(a.out),"--seed",str(s),"--core",str(c)]) for s,c in zip(SEEDS,cores)]
            if any(rc!=0 for rc in [j.wait() for j in jobs]):raise RuntimeError("training worker failed")
            derive(a)
