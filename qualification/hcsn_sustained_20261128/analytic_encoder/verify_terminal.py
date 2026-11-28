"""Independent NumPy re-score of every full-resolution six-layer endpoint and actor interval."""
import hashlib
import json
from pathlib import Path
import sys

import numpy as np


def sha(p):
    with p.open("rb") as f:return hashlib.file_digest(f,"sha256").hexdigest()


def read(p):return json.loads(p.read_text())


def verify(root,source):
    t=read(root/"terminal.json");s=read(root/"seal.json")
    if sha(root/"seal.json")!=t["seal_sha256"] or len(s)!=15:raise ValueError("seal")
    with np.load(source/"data/data.npz") as f:
        dv=np.flatnonzero(f["split"]==1);te=np.flatnonzero(f["split"]==2);ids,y=f["ids"],f["labels"]
    ndev=ncold=0;losses={};weights=0
    def scores(z,labels,truth):
        v=z.astype(float)
        if v.shape!=(len(labels),72) or not np.isfinite(v).all():raise ValueError("size")
        v-=v.max(1,keepdims=True)
        ell=np.exp(v).sum(1);ell=np.log(ell)-v[np.arange(len(v)),labels]
        np.testing.assert_allclose([ell.mean(),(v.argmax(1)==labels).mean()],[truth["nll"],truth["top1"]],atol=2e-12)
        return ell
    for key,fit in s.items():
        for tag,r in fit["history"].items():
            loc=root/key
            if tag=="pass" and (r["distinct"]!=4984 or r["step"]!=312 or r["seen"]!=4984):raise ValueError("full pass")
            if tag=="clock" and not r["active_s"]>=60:raise ValueError("clock")
            if sha(loc/r["file"])!=r["sha256"] or sha(loc/r["dev_file"])!=r["dev_sha256"]:raise ValueError("weights or dev")
            weights+=1
            with np.load(loc/r["dev_file"]) as f:
                np.testing.assert_array_equal(f["ids"],ids[dv]);np.testing.assert_array_equal(f["labels"],y[dv])
                scores(f["scores"],y[dv],r["development"]);ndev+=f["scores"].size
            path=loc/f"cold-{tag}.npz";rec=t["results"][key][tag]
            if sha(path)!=rec["score_sha256"]:raise ValueError("cold hash")
            with np.load(path) as f:
                np.testing.assert_array_equal(f["ids"],ids[te]);np.testing.assert_array_equal(f["labels"],y[te])
                for variant,truth in rec["variants"].items():
                    losses[key,tag,variant]=scores(f[variant],y[te],truth);ncold+=f[variant].size
    actors=np.array([n.split("_")[0] for n in ids[te]])
    unique,idx=np.unique(actors,return_inverse=True);mass=np.bincount(idx)
    draw=np.random.default_rng(431904).integers(0,len(unique),(4000,len(unique)));contrasts=0
    for tag,rows in t["actor_ci"].items():
        for name,expected in rows.items():
            if name.endswith("-minus-aligned"):
                arm,var=name.removesuffix("-minus-aligned").split("-",1);other=arm
            else:
                arm,other=name.split("-minus-");var="aligned"
            delta=np.mean([losses[f"{arm}-{seed}",tag,var]-losses[f"{other}-{seed}",tag,"aligned"] for seed in (137,311,557)],0)
            sums=np.bincount(idx,weights=delta)
            ci=np.quantile(sums[draw].sum(1)/mass[draw].sum(1),[.025,.975])
            np.testing.assert_allclose([delta.mean(),*ci],expected,atol=2e-12);contrasts+=1
    if (weights,ndev,ncold)!=(30,30*1147*72,114*1311*72):raise ValueError("coverage")
    return dict(verified=True,weight_endpoints=weights,dev_logits=ndev,cold_logits=ncold,actor_contrasts=contrasts,
                terminal_sha256=sha(root/"terminal.json"),selection_sha256=sha(root/"seal.json"))


if __name__=="__main__":
    a,b=map(Path,sys.argv[1:]);r=verify(a,b);(a/"verification.json").write_text(json.dumps(r,indent=2)+"\n");print(r,flush=True)
