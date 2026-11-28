"""Named new 11M caption fits with immutable free-generation selections and recoverable state."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import fcntl
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import numpy as np
import torch
from torch.nn import functional as F
from model import Captioner

ARMS=("literal","smooth","lif","sdpa")
SEEDS=(109,271,463)
GATES=(60,300,900)
EXPECTED=dict(input_sha="0dd797425012a31bf3274b5cb32fa0597f829fdfa60cca21b7ee071fc9aeb523",
              vocabulary_sha="f93de33e0a04f322ca49b15059c0174f526d53efbf6ca59586431a0094573f8c",
              rows_sha="80c9f4256fef2cf37031660858dd90f07d1bb554535a0545a46e744d00f508d2",
              pixel_sha="d79c414bb32c3ffb88f1714c20b6bdb531a68a7a95999370c86aea7367b768b1")


def sha(p):
    with p.open("rb") as f:return hashlib.file_digest(f,"sha256").hexdigest()


def read(p):return json.loads(p.read_text())


def write(p,obj):
    tmp=p.with_suffix(".tmp");tmp.write_text(json.dumps(obj,indent=2,allow_nan=False)+"\n");tmp.replace(p)


def save(p,obj):
    tmp=p.with_suffix(".saving");torch.save(obj,tmp);tmp.replace(p)


class Dataset:
    def __init__(self,root):
        meta=read(root/"data.json")
        for k,v in EXPECTED.items():
            if meta[k]!=v:raise ValueError("source identity "+k)
        if sha(root/"law4.npz")!="de7378f3c170750fb16d1280bcaa376a8904a207da32d268cac82525469e2ea4":raise ValueError("law")
        self.pix=np.load(meta["pixels"],mmap_mode="r")
        with np.load(root/"data.npz") as z:
            self.x=z["inputs"];self.y=z["targets"];self.tr=z["train"];self.dv=z["development"];self.te=z["test"]
        if (len(self.tr),len(self.dv),len(self.te))!=(6311,128,964):raise ValueError("cohort")
        self.vocab=meta["vocab_size"]
    def batch(self,rows,images=None):
        return (torch.from_numpy(self.pix[rows if images is None else images]),
                torch.from_numpy(self.x[rows].astype(np.int64)),torch.from_numpy(self.y[rows].astype(np.int64)))


@torch.no_grad()
def token_loss(net,d,ids,images=None):
    net.eval();all_loss=[];all_count=[]
    for i in range(0,len(ids),8):
        pix,t,y=d.batch(ids[i:i+8],None if images is None else images[i:i+8])
        z=net(pix,t)
        loss=F.cross_entropy(z.transpose(1,2),y,ignore_index=0,reduction="none")
        all_loss.extend(loss.double().sum(1).tolist());all_count.extend((y!=0).sum(1).tolist())
    a,b=np.array(all_loss),np.array(all_count)
    return float(a.sum()/b.sum()),a,b


def fit(root,arm,seed):
    loc=root/"training"/f"{arm}-{seed}";loc.mkdir(exist_ok=True,parents=True)
    if (loc/"fit.json").is_file():return
    began=time.perf_counter();d=Dataset(root)
    net=Captioner(arm,seed,d.vocab,root/"law4.npz")
    opt=torch.optim.AdamW(net.parameters(),lr=.0005,weight_decay=.01,foreach=False)
    count=sum(p.numel() for p in net.parameters())
    if count!=(10860512 if arm=="sdpa" else 11101984):raise ValueError(count)
    setup=time.perf_counter()-began
    rng=np.random.default_rng(seed);seen=np.zeros(len(d.pix),dtype=bool)
    wall=cpu=overhead=0.;step=tokens=0;hist=[]
    state=loc/"resume.pt"
    if state.exists():
        pending=torch.load(state,map_location="cpu",weights_only=True)
        if (pending["arm"],pending["seed"])!=(arm,seed):raise ValueError("restart mismatch")
        net.load_state_dict(pending["net"]);opt.load_state_dict(pending["opt"]);rng.bit_generator.state=json.loads(pending["rng"])
        wall,cpu,overhead,step,tokens,hist=(pending[k] for k in ("wall","cpu","overhead","step","tokens","hist"))
        seen=pending["seen"].numpy();del pending
    due=wall+95
    while len(hist)<len(GATES):
        tic=time.perf_counter();tpc=time.process_time()
        ids=rng.choice(d.tr,8,replace=False);seen[ids]=True
        pix,t,y=d.batch(ids);net.train();opt.zero_grad(set_to_none=True)
        z=net(pix,t);loss=F.cross_entropy(z.flatten(0,1),y.flatten(),ignore_index=0)
        loss.backward();grad=torch.nn.utils.clip_grad_norm_(net.parameters(),1,error_if_nonfinite=True);opt.step()
        wall+=time.perf_counter()-tic;cpu+=time.process_time()-tpc;step+=1;tokens+=int((y!=0).sum())
        mark=wall>=GATES[len(hist)]
        if mark:
            start=time.perf_counter()
            dev,losses,counts=token_loss(net,d,d.dv);path=loc/f"end-{GATES[len(hist)]}.pt";save(path,net.state_dict())
            pre=loc/f"dev-{GATES[len(hist)]}.npz";np.savez_compressed(pre,ids=d.dv,loss=losses,counts=counts)
            overhead+=time.perf_counter()-start
            hist.append(dict(gate=GATES[len(hist)],step=step,tokens=tokens,unique_training=int(seen.sum()),
                     active_wall_s=wall,cpu_s=cpu,validation_and_save_s=overhead,dev_nll=dev,
                     file=path.name,sha256=sha(path),dev_file=pre.name,dev_sha256=sha(pre),grad_norm=float(grad)))
            print(arm,seed,hist[-1]["gate"],step,round(dev,4),flush=True)
        if mark or wall>=due:
            save(state,dict(net=net.state_dict(),opt=opt.state_dict(),rng=json.dumps(rng.bit_generator.state),
                 seen=torch.from_numpy(seen.copy()),arm=arm,seed=seed,wall=wall,cpu=cpu,overhead=overhead,
                 step=step,tokens=tokens,hist=hist))
            write(loc/"progress.json",dict(arm=arm,seed=seed,step=step,active_s=wall,tokens=tokens,history=hist))
            due=wall+95
    write(loc/"fit.json",dict(arm=arm,seed=seed,parameters=count,setup_s=setup,history=hist,
                              distinct_imgs=int(seen.sum()),training_tokens=tokens,actual_steps=step))


def controller(root):
    with (root/"fitness.lock").open("a") as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        if (root/"selection.json").exists():return
        order=[(a,s) for i,s in enumerate(SEEDS) for a in ARMS[i:]+ARMS[:i]]
        def cell(item):
            arm,seed=item
            for i in range(3):
                r=subprocess.run([sys.executable,"-u",str(Path(__file__).resolve()),str(root),"--arm",arm,"--seed",str(seed)])
                if r.returncode==0:return
                if r.returncode not in (-9,-15):raise RuntimeError((arm,seed,r.returncode))
                time.sleep(30)
            raise RuntimeError(item)
        with ThreadPoolExecutor(max_workers=2) as pool:list(pool.map(cell,order))
        selected={}
        for arm,seed in order:
            name=f"{arm}-{seed}";loc=root/"training"/name
            rec=read(loc/"fit.json")
            if [v["gate"] for v in rec["history"]]!=list(GATES):raise ValueError("all gates")
            for v in rec["history"]:
                if sha(loc/v["file"])!=v["sha256"] or sha(loc/v["dev_file"])!=v["dev_sha256"]:raise ValueError("identity")
            selected[name]=dict(best=min(rec["history"],key=lambda v:(v["dev_nll"],v["gate"])),
                                final=rec["history"][-1],fit_sha256=sha(loc/"fit.json"))
        write(root/"selection.json",selected)
        print("sealed",sha(root/"selection.json"),flush=True)


if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("root",type=Path);p.add_argument("--arm",choices=ARMS);p.add_argument("--seed",type=int)
    a=p.parse_args();torch.set_num_threads(1);torch.set_num_interop_threads(1)
    if a.arm:fit(a.root,a.arm,a.seed)
    else:controller(a.root)
