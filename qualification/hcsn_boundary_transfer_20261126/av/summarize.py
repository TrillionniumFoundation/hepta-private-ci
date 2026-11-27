"""Verify the sealed raw records and recompute audiovisual endpoints from per-clip scores."""
import argparse
import hashlib
import itertools
import json
from pathlib import Path

import numpy as np

def read(p):
    return json.loads(p.read_text())

def digest(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()

def score(p,y,g):
    ids=np.arange(len(y))
    hits=p.argmax(1)==y
    return {"accuracy":float(np.mean([hits[g==a].mean() for a in np.unique(g)])),
            "brier":float(np.square(p-np.eye(6)[y]).sum(1).mean()),
            "ce":float(-np.log(np.maximum(p[ids,y],1e-12)).mean()),
            "actor_accuracy":{str(a):float(hits[g==a].mean()) for a in np.unique(g)}}

def main(src):
    parents=src/"results"
    readouts=src/"readouts"
    phys=src/"phys"
    arms="centered raw joint signed learned fixed attention gru lif diagonal linear".split()
    controls=arms[6:]
    seeds=(6101,6102,6103)
    seal=read(parents/"seal.json")
    assert len(seal)==len(arms)*len(seeds)
    rows={}
    for arm,s in itertools.product(arms,seeds):
        stem=f"{arm}-{s}"
        path=parents/stem
        assert seal[stem]=={"weights":digest(path/"weights.pt"),"fit":digest(path/"fit.json")}
        fit=read(path/"fit.json")
        test=read(path/"test.json")
        assert digest(path/"predictions.npz")==test["predictions"]
        with np.load(path/"predictions.npz") as z:
            r=score(z["p"],z["y"],z["actor"])
            assert len(z["clip"])==len(set(z["clip"]))==72 and len(set(z["actor"]))==6
        for k in ("accuracy","ce","brier"):
            assert abs(test["scores"][k]-r[k])<2e-6
        cold=read(parents/(stem+"-fit-process.json"))
        conf=read(parents/(stem+"-confirm-process.json"))
        assert cold["returncode"]==conf["returncode"]==0
        dev=next(v for v in fit["trace"] if v["step"]==fit["best_step"])
        rows[stem]=dict(**r,fit_seconds=cold["wall_seconds"],test_seconds=conf["wall_seconds"],
            dev_ce=dev["ce"],dev_target_seconds=fit["quality_dev_seconds"],best_step=fit["best_step"])
    def group(arm):
        rs=[rows[f"{arm}-{s}"] for s in seeds]
        o={k:float(np.mean([r[k] for r in rs])) for k in ("accuracy","brier","ce","fit_seconds","dev_ce","test_seconds")}
        o["per_seed_accuracy"]=[r["accuracy"] for r in rs]
        o["quality_seconds"]=[r["dev_target_seconds"] for r in rs]
        return o
    table={arm:group(arm) for arm in arms}
    best=min(controls,key=lambda a:table[a]["dev_ce"])
    per_seed_best=[min(controls,key=lambda a:rows[f"{a}-{s}"]["dev_ce"]) for s in seeds]
    delta=np.array([[r1-r0 for r1,r0 in zip(rows[f"centered-{s}"]["actor_accuracy"].values(),rows[f"raw-{s}"]["actor_accuracy"].values())] for s in seeds])
    d=delta.mean(0)
    primary={"delta_accuracy_by_seed":delta.mean(1).tolist(),"delta_accuracy_by_actor":d.tolist(),
             "accuracy_ci95":np.percentile(d[np.array(list(itertools.product(range(len(d)),repeat=len(d))))].mean(1),[2.5,97.5]).tolist(),
             "brier_delta":table["centered"]["brier"]-table["raw"]["brier"]}
    primary["pass"]=bool((delta.mean(1)>0).all() and sum(d>0)>=4 and primary["brier_delta"]<=0)
    rt={r["stem"]:r for r in read(readouts/"confirm.json")["rows"]}
    tr={r["stem"]:r for r in read(readouts/"fit.json")["rows"]}
    rs=read(readouts/"readout_seal.json")
    conditional={}
    for a in ("centered","raw","gru","hybrid"):
        summary={}
        agree=True
        gs=[]
        for s in seeds:
            preds={}
            for method in ("direct","bp"):
                k=f"{a}-{s}-{method}"
                assert rs[k]==digest(readouts/(k+".npz"))==tr[k]["weights"]
                f=readouts/(k+"-predictions.npz")
                assert digest(f)==rt[k]["predictions"]
                with np.load(f) as z:
                    preds[method]=z["p"]
                    out=score(z["p"],z["y"],z["actor"])
                assert abs(out["brier"]-rt[k]["results"]["brier"])<1e-7
                summary.setdefault(method,[]).append(dict(**out,seconds=tr[k]["exclusive_fit_seconds"],
                    seconds_with_parent=tr[k]["exclusive_fit_seconds"]+tr[k]["parent_feature_seconds"]+tr[k]["parent_fit_seconds"]))
            agree=bool(agree and np.array_equal(preds["direct"].argmax(1),preds["bp"].argmax(1)))
            gs.append(abs(summary["direct"][-1]["brier"]-summary["bp"][-1]["brier"]))
        conditional[a]={"equal_quality":bool(agree and max(gs)<=1e-4),"max_brier_gap":max(gs),
                         "methods":{m:{k:float(np.mean([v[k] for v in vals])) for k in ("accuracy","brier","seconds","seconds_with_parent")} for m,vals in summary.items()}}
    deltas=[]
    for actor in sorted(rt["hybrid-6101-direct"]["results"]["actor_accuracy"]):
        deltas.append(float(np.mean([rt[f"hybrid-{s}-direct"]["results"]["actor_accuracy"][actor]-
                    rt[f"gru-{s}-direct"]["results"]["actor_accuracy"][actor] for s in seeds])))
    hy=conditional["hybrid"]["methods"]["direct"]
    gr=conditional["gru"]["methods"]["direct"]
    hybrid_pass=hy["accuracy"]>gr["accuracy"] and hy["brier"]<gr["brier"] and min(deltas)>=-.05
    fit=read(phys/"fit.json")
    ps=read(phys/"seal.json")
    assert ps=={"fit":digest(phys/"fit.json"),"parents_seal":digest(parents/"seal.json")}
    pt=read(phys/"test.json")
    assert pt["predictions"]==digest(phys/"predictions.npz") and pt["selection"]==digest(phys/"seal.json")
    edits={}
    for arm in ("keep","inverse","matched","wide"):
        st={}
        for s in seeds:
            k=f"{arm}-{s}"
            assert digest(phys/(k+".pt"))==fit[k]["weights"]
            actual=pt["scores"][k]
            with np.load(phys/"predictions.npz") as z:
                sel=z["y"]<4
                assert abs(score(z[k][sel],z["y"][sel],z["actors"][sel])["ce"]-actual["ce"])<2e-6
            st[str(s)]={k2:fit[k][k2] for k2 in ("selected","max_raw_cost_change","selection_seconds")}
            st[str(s)].update(target_ce_gain=pt["scores"][f"keep-{s}"]["ce"]-actual["ce"],
                              declined_or_infeasible=sum(r.get("status")=="infeasible" or r.get("protected_damage",0)>.05 for r in fit[k]["history"]))
        edits[arm]=dict(**pt["summary"][arm],selection=st)
    return {"architecture":table,"rows":rows,"primary":primary,"best_conventional_by_mean_dev_ce":best,
            "best_conventional_by_seed_dev_ce":per_seed_best,"conditional":conditional,"hybrid_gate":hybrid_pass,
            "hybrid_actor_delta":deltas,"physical_edits":edits}
if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("archive_dir",type=Path)
    p.add_argument("output",type=Path)
    args=p.parse_args()
    args.output.write_text(json.dumps(main(args.archive_dir),sort_keys=True,indent=2)+"\n")
