"""Independently bind every source, weight, development and cold array; recompute endpoints."""
import argparse
import hashlib
import json
from pathlib import Path
import numpy as np


def sha(path):
    with path.open("rb") as f:
        return hashlib.file_digest(f,"sha256").hexdigest()


def read(path):
    return json.loads(path.read_text())


def score(z,y):
    if z.shape!=(len(y),72) or not np.isfinite(z).all():
        raise ValueError("incomplete or invalid score array")
    zz=z.astype("float64")
    return np.logaddexp.reduce(zz,axis=1)-zz[np.arange(len(y)),y], (zz.argmax(1)==y)


def verify(out,source):
    if sha(source)!="18423277257e2e487521d83a8c116bc7cf5599411f4ff769e569bd849beae6ad":
        raise ValueError("input digest")
    with np.load(source,allow_pickle=False) as z:
        dev_y=z["labels"][z["split"]==1]
        y=z["labels"][z["split"]==2]
        ids=z["ids"][z["split"]==2]
        actors=np.asarray([s.split("_")[0] for s in ids])
    terminal=read(out/"terminal.json")
    if sha(out/"seal.json")!=terminal["seal_sha"] or sha(out/"held-identities.npz")!=terminal["identities_sha"]:
        raise ValueError("changed seal")
    with np.load(out/"held-identities.npz") as a:
        assert np.array_equal(a["labels"],y) and np.array_equal(a["ids"],ids) and np.array_equal(a["actors"],actors)
    panel=read(out/"seal.json")
    recipe=read(out/"recipe.json")
    assert set(panel)==set(terminal["panels"])=={f"{a}-{s}" for a in recipe["arms"] for s in recipe["seeds"]}
    records={}
    cold_sums={}
    upperr=0.
    score_count=0
    clock=0.
    elapsed={}
    for key,choice in panel.items():
        cell=out/key
        actual=terminal["panels"][key]
        refs=choice["history"]
        assert set(refs)=={"epoch1",*(f"time{int(t)}" for t in recipe["rungs"])}
        assert refs["epoch1"]["step"]==312 and refs["epoch1"]["samples"]==4984
        expected={str(r["step"]) for r in refs.values()}
        if key.startswith("returning-"):
            expected.add("no_wire")
        if set(actual)!=expected:
            raise ValueError("cold endpoint coverage")
        for lab,r in refs.items():
            assert sha(cell/r["file"])==r["weight_sha"] and sha(cell/r["score_file"])==r["score_sha"]
            if lab.startswith("time") and r["active"]<int(lab[4:]):
                raise ValueError("incomplete active time")
            with np.load(cell/r["score_file"]) as a:
                dev_l,dev_a=score(a["logits"],dev_y)
                score_count+=a["logits"].size
            upperr=max(upperr,abs(dev_l.mean()-r["development"]["nll"]),abs(dev_a.mean()-r["development"]["top1"]))
        rows={}
        for step,record in actual.items():
            assert sha(cell/record["file"])==record["sha"]
            with np.load(cell/record["file"]) as a:
                losses,acc=score(a["logits"],y)
                score_count+=a["logits"].size
            upperr=max(upperr,abs(losses.mean()-record["quality"]["nll"]),abs(acc.mean()-record["quality"]["top1"]))
            rows[step]=np.stack((losses,acc))
        order=sorted(refs,key=lambda l:refs[l]["step"])
        assert choice["best"]==min(order,key=lambda l:refs[l]["development"]["nll"])
        gates={}
        for g,selected in choice["gates"].items():
            assert selected==next((l for l in order if refs[l]["development"]["nll"]<=float(g)),None)
            hit=selected is not None and float(rows[str(refs[selected]["step"])][0].mean())<=float(g)
            gates[g]=dict(pass_both=bool(hit),selected=selected,
                          optimization_s=refs[selected]["active"] if hit else None)
        records[key]=dict(gates=gates)
        for label in (*refs,"best"):
            k=choice["best"] if label=="best" else label
            cold_sums[key,label]=rows[str(refs[k]["step"])]
        if "no_wire" in rows:
            cold_sums[key,"no_wire"]=rows["no_wire"]
        clock+=refs["time2600"]["active"]
    assert upperr<3e-5
    rng=np.random.default_rng(93623)
    clusters=[np.flatnonzero(actors==s) for s in np.unique(actors)]
    draws=rng.integers(0,len(clusters),(4000,len(clusters)))
    N=np.array(list(map(len,clusters)))[draws].sum(1)
    contrasts={}
    for label in ("epoch1","time120","time900","time2600","best"):
        for control in (*[a for a in recipe["arms"] if a!="returning"], "no_wire"):
            if control=="no_wire" and label!="best":
                continue
            paired=np.mean([cold_sums[f"returning-{s}",label]-
                            (cold_sums[f"returning-{s}","no_wire"] if control=="no_wire"
                             else cold_sums[f"{control}-{s}",label]) for s in recipe["seeds"]],axis=0)
            group=np.stack([paired[:,ix].sum(1) for ix in clusters],1)
            contrasts[f"{label}-returning-minus-{control}"]=dict(mean=paired.mean(1).tolist(),
                         actor_95=np.quantile(group[:,draws].sum(2)/N,[.025,.975],axis=1).T.tolist())
    summary={}
    for a in recipe["arms"]:
        summary[a]={lab:np.mean([cold_sums[f"{a}-{s}",lab].mean(1) for s in recipe["seeds"]],axis=0).tolist()
                    for lab in ("epoch1","time120","time900","time2600","best")}
    result=dict(seal_sha=terminal["seal_sha"],terminal_sha=sha(out/"terminal.json"),verified_cells=len(panel),
                max_nll_or_accuracy_error=float(upperr),scores_read=score_count,active_s=clock,
                summary=summary,matched_gates=records,paired_contrasts=contrasts)
    final=out/"verification.json"
    tmp=out/"verification.json.tmp"
    tmp.write_text(json.dumps(result,indent=2,allow_nan=False)+"\n")
    tmp.replace(final)
    print(json.dumps({k:v for k,v in result.items() if k not in ('summary','matched_gates','paired_contrasts')}),flush=True)


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("run",type=Path)
    parser.add_argument("source",type=Path)
    args=parser.parse_args()
    verify(args.run,args.source)
