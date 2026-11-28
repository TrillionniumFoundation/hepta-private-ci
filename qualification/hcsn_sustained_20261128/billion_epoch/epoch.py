"""Full-data, one-epoch billion-parameter audiovisual comparison with native restarts."""
import argparse
import fcntl
import hashlib
import json
import os
import resource
import shutil
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import torch
from torch.nn import functional as F

ARMS=("literal","sdpa")
SEEDS=(137,311,557)
HASHES={"src/encoder.py":"1c5ee669c47adaca3bec2ae3def64aec117596c8628345beb300e143628824df",
        "src/hcsn_temporal.py":"1c5ee332f549e3d9ffbff21bfeeef0e181d34e0606e5c27b38bcc66a48ae5eec",
        "src/law4.npz":"de7378f3c170750fb16d1280bcaa376a8904a207da32d268cac82525469e2ea4",
        "data/data.npz":"18423277257e2e487521d83a8c116bc7cf5599411f4ff769e569bd849beae6ad"}
TARGET=312


def sha(p):
    with p.open("rb") as f:return hashlib.file_digest(f,"sha256").hexdigest()


def write(p,value):
    tmp=p.with_suffix(".tmp")
    tmp.write_text(json.dumps(value,indent=1,allow_nan=False)+"\n");tmp.replace(p)


def read(p):return json.loads(p.read_text())


def rss():return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024


def available():
    vals=dict(s.split(":",1) for s in Path("/proc/meminfo").read_text().splitlines())
    return int(vals["MemAvailable"].split()[0])*1024


def yielding(source,out,launch=False):
    # Respect the original shared GPU's actual execution. This procedure never stops another user process.
    note=source/"recovery-8559/progress.json";start=time.monotonic()
    while True:
        gpu=note.is_file() and read(note).get("state")=="executing"
        room=available()>((34 if launch else 7)*2**30) and shutil.disk_usage(out).free>((42 if launch else 17)*2**30)
        if not gpu and room:return time.monotonic()-start
        time.sleep(30)


def event(p,**v):
    with p.open("a") as f:f.write(json.dumps({"at":time.time(),**v},allow_nan=False)+"\n")


class Data:
    def __init__(self,source):
        with np.load(source/"data/data.npz") as f:
            fold=f["split"]
            self.tr,self.dv,self.te=(np.flatnonzero(fold==i) for i in range(3))
            self.names=f["ids"];self.actors=np.array([s.split("_")[0] for s in self.names])
            self.v=torch.from_numpy(f["images"]);audio=f["audio"]
            mu=audio[self.tr].mean((0,1),dtype=np.float64).astype(np.float32)
            sd=audio[self.tr].std((0,1),dtype=np.float64).clip(.01).astype(np.float32)
            self.a=torch.from_numpy((audio-mu)/sd);self.y=torch.from_numpy(f["labels"]).long()
            self.tokens=torch.from_numpy(f["tokens"]).long();self.words=int(self.tokens.max())+1
        if tuple(len(v) for v in (self.tr,self.dv,self.te))!=(4984,1147,1311):raise ValueError("split sizes")
        by=[set(self.actors[u]) for u in (self.tr,self.dv,self.te)]
        if list(map(len,by))!=[61,14,16] or len(set.union(*by))!=91:raise ValueError("actor split")


def model(source,arm,seed,words):
    from encoder import AVText
    net=AVText(arm,4096,seed,words,source/"src/law4.npz")
    n=sum(p.numel() for p in net.parameters())
    if n!={"literal":1016475200,"sdpa":1011757056}[arm]:raise ValueError(n)
    return net


@torch.no_grad()
def scoring(net,d,rows,source,loc,variants):
    net.eval()
    # Each variant preserves actor, labels, sample order and fixed text gallery.
    other=rows.copy()
    for actor in sorted(set(d.actors[rows])):
        locs=np.flatnonzero(d.actors[rows]==actor)
        perm=np.random.default_rng(int(actor)+6312).permutation(locs)
        other[perm]=rows[np.roll(perm,1)]
    t=time.perf_counter();paused=0.
    with torch.autocast("cpu",dtype=torch.bfloat16):
        text=torch.cat([net.encode(net.text(b)) for b in d.tokens.split(16)]).float()
        arrays={}
        for name in (("aligned","audio_swapped","video_swapped","both_swapped") if variants else ("aligned",)):
            pred=[]
            for i in range(0,len(rows),16):
                paused+=yielding(source,loc)
                s=rows[i:i+16];o=other[i:i+16]
                v=d.v[o if name in ("video_swapped","both_swapped") else s]
                a=d.a[o if name in ("audio_swapped","both_swapped") else s]
                av=net.encode(net.front(v,a)).float()
                with torch.autocast("cpu",enabled=False):pred.append((12*(av@text.T)).numpy())
            arrays[name]=np.concatenate(pred)
    return arrays,time.perf_counter()-t-paused,paused


def metrics(a,y):
    z=a.astype(np.float64);z-=z.max(1,keepdims=True)
    l=np.log(np.exp(z).sum(1))-z[np.arange(len(y)),y]
    return {"nll":float(l.mean()),"top1":float((z.argmax(1)==y).mean())},l


def fit(source,out,arm,seed,d):
    from encoder import pair_loss
    key=f"{arm}-{seed}";loc=out/key;loc.mkdir(exist_ok=True)
    if (loc/"fit.json").is_file():return
    began=time.perf_counter()
    paused=yielding(source,out,True)
    net=model(source,arm,seed,d.words);opt=torch.optim.AdamW(net.parameters(),lr=.0001,weight_decay=.01,foreach=False)
    order=np.random.default_rng(seed+7369).permutation(d.tr)
    identity=hashlib.sha256(order.astype("<i8").tobytes()).hexdigest()
    assert len(np.unique(order))==4984
    cursor=loc/"epoch_state.pt"
    done=0;active=cpu=validation=0.;history=[]
    if cursor.is_file():
        ck=torch.load(cursor,map_location="cpu",weights_only=True,mmap=True)
        if ck["order"]!=identity or ck["arm"]!=arm or ck["seed"]!=seed:raise ValueError("checkpoint identity")
        net.load_state_dict(ck["model"]);opt.load_state_dict(ck["opt"])
        done=ck["step"];active=ck["active"];cpu=ck["cpu"];validation=ck["validation"];history=ck["history"]
        paused+=ck["paused"];del ck
    for step in range(done+1,TARGET+1):
        paused+=yielding(source,out)
        tic=time.perf_counter();c=time.process_time()
        wrap=order[(step-1)*16:step*16];labels=d.y[wrap]
        net.train();opt.zero_grad(set_to_none=True)
        with torch.autocast("cpu",dtype=torch.bfloat16):
            v,tx=net(d.v[wrap],d.a[wrap],d.tokens[labels]);loss=pair_loss(v,tx,labels)
        loss.backward();norm=torch.nn.utils.clip_grad_norm_(net.parameters(),1.,error_if_nonfinite=True);opt.step()
        elapsed=time.perf_counter()-tic;active+=elapsed;cpu+=time.process_time()-c
        row=dict(step=step,seen=min(step*16,len(order)),wall_s=elapsed,cumulative_training_s=active,
                 training_loss=float(loss.detach()),grad_norm=float(norm),peak_rss_bytes=rss())
        if step==1:
            row["gradient_scalar_count"]=sum(p.numel() for p in net.parameters() if p.grad is not None)
        event(loc/"steps.jsonl",**row)
        if step in (16,128,TARGET):
            z,t,pause=scoring(net,d,d.dv,source,out,False);paused+=pause;validation+=t
            score=loc/f"dev-{step}.npz";np.savez_compressed(score,ids=d.names[d.dv],labels=d.y[d.dv].numpy(),**z)
            ms,_=metrics(z["aligned"],d.y[d.dv].numpy())
            history.append(dict(step=step,metrics=ms,score_sha256=sha(score),seconds=t))
        if step%64==0 or step in (16,TARGET):
            tmp=cursor.with_suffix(".tmp")
            torch.save(dict(model=net.state_dict(),opt=opt.state_dict(),order=identity,arm=arm,seed=seed,step=step,
                  active=active,cpu=cpu,paused=paused,validation=validation,history=history),tmp)
            tmp.replace(cursor)
            write(loc/"progress.json",dict(arm=arm,seed=seed,step=step,training_s=active,data_order=identity,
                     history=history,peak_rss_bytes=rss(),checkpoint_bytes=cursor.stat().st_size))
            print(key,step,round(active,3),flush=True)
    if len(history)!=3:raise ValueError("development checkpoints missing")
    write(loc/"fit.json",dict(arm=arm,seed=seed,updates=TARGET,unique_examples=len(np.unique(order)),
            order_sha256=identity,training_wall_s=active,training_cpu_s=cpu,development_s=validation,
            paused_s=paused,invocation_wall_s=time.perf_counter()-began,end_checkpoint_bytes=cursor.stat().st_size,
            end_checkpoint_sha256=sha(cursor),parameters=sum(p.numel() for p in net.parameters()),history=history))


def cold(source,out,arm,seed,d,seal):
    key=f"{arm}-{seed}";loc=out/key
    if (loc/"cold.json").is_file():return
    yielding(source,out,True)
    cursor=loc/"epoch_state.pt";assert sha(cursor)==seal[key]["end_checkpoint_sha256"]
    n=model(source,arm,seed,d.words);ck=torch.load(cursor,map_location="cpu",weights_only=True,mmap=True)
    n.load_state_dict(ck["model"]);del ck
    zs,cost,paused=scoring(n,d,d.te,source,out,True)
    names=d.names[d.te];y=d.y[d.te].numpy()
    p=loc/"cold.npz";np.savez_compressed(p,ids=names,labels=y,**zs)
    write(loc/"cold.json",dict(score_sha256=sha(p),variants={k:metrics(v,y)[0] for k,v in zs.items()},cold_s=cost,paused_s=paused))


def main(source,out,mode=None,arm=None,seed=None):
    for name,checksum in HASHES.items():
        if sha(source/name)!=checksum:raise ValueError(name)
    sys.path.insert(0,str(source/"src"))
    torch.set_num_threads(1);torch.set_num_interop_threads(1)
    out.mkdir(exist_ok=True,parents=True)
    if mode in ("fit","cold"):
        d=Data(source)
        if mode=="fit":fit(source,out,arm,seed,d)
        else:cold(source,out,arm,seed,d,read(out/"seal.json"))
        return
    with (out/"study.lock").open("a") as guard:
        fcntl.flock(guard,fcntl.LOCK_EX|fcntl.LOCK_NB)
        if (out/"terminal.json").is_file():return
        if not (out/"session.json").exists():write(out/"session.json",dict(source_sha256=sha(Path(__file__)),
                    inputs=HASHES,torch=str(torch.__version__),device="cpu",opened_unix=time.time()))
        order=[(arm,s) for j,s in enumerate(SEEDS) for arm in (ARMS if j%2==0 else ARMS[::-1])]
        def child(kind,a,s):
            cmd=[sys.executable,"-u",__file__,str(source),str(out),"--mode",kind,"--arm",a,"--seed",str(s)]
            for retry in range(3):
                q=subprocess.run(cmd)
                if q.returncode==0:return
                if q.returncode not in (-9,-15,-1):raise RuntimeError(f"{kind}/{a}/{s}: {q.returncode}")
                time.sleep(30)
            raise RuntimeError("repeated interrupted process "+a)
        for a,s in order:child("fit",a,s)
        registered={}
        for a,s in order:
            key=f"{a}-{s}";loc=out/key;v=read(loc/"fit.json")
            assert v["updates"]==312 and v["unique_examples"]==4984 and sha(loc/"epoch_state.pt")==v["end_checkpoint_sha256"]
            registered[key]=dict(fit_sha256=sha(loc/"fit.json"),end_checkpoint_sha256=v["end_checkpoint_sha256"])
        if (out/"seal.json").exists() and read(out/"seal.json")!=registered:raise ValueError("seal changed")
        write(out/"seal.json",registered)
        for a,s in order:child("cold",a,s)
        d=Data(source);actors=d.actors[d.te];who,ix=np.unique(actors,return_inverse=True)
        draw=np.random.default_rng(66541).integers(len(who),size=(4000,len(who)));mass=np.bincount(ix);losses={};cells={}
        for a,s in order:
            key=f"{a}-{s}";loc=out/key;raw=read(loc/"cold.json");assert raw["score_sha256"]==sha(loc/"cold.npz")
            with np.load(loc/"cold.npz") as z:
                np.testing.assert_array_equal(z["ids"],d.names[d.te]);np.testing.assert_array_equal(z["labels"],d.y[d.te].numpy())
                losses[key]=metrics(z["aligned"],z["labels"])[1]
            cells[key]=dict(fit=read(loc/"fit.json"),cold=raw)
        diff=np.mean([losses[f"literal-{s}"]-losses[f"sdpa-{s}"] for s in SEEDS],0)
        sums=np.bincount(ix,weights=diff);ci=np.quantile(sums[draw].sum(1)/mass[draw].sum(1),[.025,.975])
        write(out/"terminal.json",dict(cells=cells,seal_sha256=sha(out/"seal.json"),literal_minus_sdpa_nll=float(diff.mean()),
                    actor_ci95=ci.tolist(),terminal_unix=time.time(),parameters_per_cell=[1016475200,1011757056]))


if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("source",type=Path);p.add_argument("output",type=Path)
    p.add_argument("--mode",choices=("fit","cold"));p.add_argument("--arm",choices=ARMS);p.add_argument("--seed",type=int)
    a=p.parse_args();main(a.source.resolve(),a.output.resolve(),a.mode,a.arm,a.seed)
