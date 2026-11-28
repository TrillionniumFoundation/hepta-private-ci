"""Recompute every development and cold score, selected model and paired-actor contrast."""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np


def digest(p):
    with p.open("rb") as f:return hashlib.file_digest(f,"sha256").hexdigest()


def verify(root):
    t=json.loads((root/"terminal.json").read_text())
    seal=json.loads((root/"development_seal.json").read_text())
    if digest(root/"development_seal.json")!=t["seal_sha256"]:
        raise ValueError("terminal/dev seal")
    freq=np.asarray(seal["train_counts"]);prior=np.log(freq/freq.sum())
    assert freq.sum()==4984
    ls={}
    idxs={}
    n=0
    for k,rr in seal["fits"].items():
        ls[k]={}
        for row in rr:
            p=root/k
            if digest(p/row["weights"])!=row["sha256"]:
                raise ValueError(k+" "+row["weights"])
            for split in ("dev","cold"):
                with np.load(p/f"{split}-{row['epoch']}.npz") as a:
                    z,ids,y=a["scores"].astype(np.float64),a["ids"],a["y"]
                assert z.shape==((1147 if split=="dev" else 1311),72)
                if split not in idxs:idxs[split]=(ids,y)
                else:
                    np.testing.assert_array_equal(ids,idxs[split][0]);np.testing.assert_array_equal(y,idxs[split][1])
                for mode in ("raw","temperature_prior"):
                    x=z.copy() if mode=="raw" else z*row["beta"]+prior
                    x-=x.max(1,keepdims=True)
                    loss=np.log(np.exp(x).sum(1))-x[np.arange(len(y)),y]
                    rec=row["dev"][mode] if split=="dev" else t["cold"][k][str(row["epoch"])][mode]
                    np.testing.assert_allclose([loss.mean(),(x.argmax(1)==y).mean()],[rec["nll"],rec["top1"]],atol=1e-11,rtol=1e-11)
                    pick=min(rr,key=lambda v:(v["dev"][mode]["nll"],v["epoch"]))["epoch"]
                    assert pick==seal["picks"][k][mode]==t["selected"][k][mode]
                    if split=="cold" and row["epoch"]==pick:ls[k][mode]=loss
            n+=1
    assert n==45 and len(ls)==15
    dev_set={v.split("_")[0] for v in idxs["dev"][0]}
    who,inv=np.unique([v.split("_")[0] for v in idxs["cold"][0]],return_inverse=True)
    assert len(who)==16 and len(dev_set)==14 and not dev_set.intersection(who)
    mass=np.bincount(inv)
    draw=np.random.default_rng(91363).integers(len(who),size=(4000,len(who)))
    for mode,arms in t["forward_minus_control"].items():
        for arm,r in arms.items():
            d=np.mean([ls[f"forward-{s}"][mode]-ls[f"{arm}-{s}"][mode] for s in (137,311,557)],0)
            sums=np.bincount(inv,weights=d)
            ci=np.quantile(sums[draw].sum(1)/mass[draw].sum(1),[.025,.975])
            np.testing.assert_allclose([d.mean(),*ci],[r["nll"],*r["actor_ci95"]],atol=1e-11,rtol=1e-11)
    return dict(verified=True,candidates=n,score_files=2*n,dev_plus_cold_finite_logits=n*72*(1147+1311),
                weight_hashes=n,actor_contrasts=8,terminal_sha256=digest(root/"terminal.json"))


if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("directory",type=Path)
    a=p.parse_args();j=verify(a.directory)
    with (a.directory/"verification.json").open("w") as f:json.dump(j,f,indent=2);f.write("\n")
    print(json.dumps(j))
