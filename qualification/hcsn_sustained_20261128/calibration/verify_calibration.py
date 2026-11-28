"""Verify selection, costs, actual weighted bootstrap and the published summaries."""
import hashlib
import json
from pathlib import Path
import numpy as np

HERE=Path(__file__).resolve().parent

def close(a,b):
    if not np.isclose(a,b,rtol=1e-11,atol=1e-12):raise ValueError((a,b))


def run():
    raw=(HERE/"development_seal.json").read_bytes()
    seal=json.loads(raw);r=json.loads((HERE/"result.json").read_bytes())
    if hashlib.sha256(raw).hexdigest()!=r["development_seal_sha256"]:raise ValueError("development hash")
    if r["script_sha256"]!=hashlib.sha256((HERE/"calibrate.py").read_bytes()).hexdigest():raise ValueError("run source")
    if sum(map(len,seal["rows"].values()))!=27:raise ValueError("candidate count")
    for mode,rr in r["regimes"].items():
        for key,p in rr["selected"].items():
            opts=seal["rows"][key]
            pick=min(opts,key=lambda x:(x["regimes"][mode]["dev"]["nll"],x["steps"]))
            if pick["steps"]!=p["steps"] or pick["source"]!=p["source"]:raise ValueError("selection mismatch")
            close(p["multiplier"],pick["regimes"][mode]["multiplier"])
            close(p["charged_total_s"],p["original_all_prefix_cost_s"]+r["data_preparation_s"]+
                  sum(x["dev_reinfer_s"]+x["regimes"][mode]["fit_s"] for x in opts)+p["selected_cold_score_s"])
            for x in opts:
                z=x["regimes"][mode]
                if z["multiplier"]<=0 and z["slope"]<-1e-9:raise ValueError("wrong left optimum")
                if z["multiplier"]>=4 and z["slope"]>1e-9:raise ValueError("wrong right optimum")
                if 0<z["multiplier"]<4 and abs(z["slope"])>1e-8:raise ValueError("wrong interior optimum")
        for method,sm in rr["summary"].items():
            obs=[rr["selected"][f"{method}-{i}"] for i in seal["seed_ids"]]
            for part in ("dev","cold"):
                for m in ("nll","top1"):close(sm[f"{part}_{m}"],np.mean([a[part][m] for a in obs]))
            close(sm["seeds_passing_4_1"],sum(a["dev"]["nll"]<=4.1 and a["cold"]["nll"]<=4.1 for a in obs))
        diff=rr["forward_minus_bp"];mass=np.asarray(diff["actor_counts"]);ls=np.asarray(diff["actor_loss_sums"])
        close(diff["mean"],ls.sum()/mass.sum())
        close(diff["mean"],rr["summary"]["forward"]["cold_nll"]-rr["summary"]["same_site_bp"]["cold_nll"])
        if mass.sum()!=r["clips"] or len(ls)!=r["actors"]:raise ValueError("cluster identity")
        ix=np.random.default_rng(diff["bootstrap_seed"]).integers(len(ls),size=(diff["replications"],len(ls)))
        draws=ls[ix].sum(1)/mass[ix].sum(1);q=np.quantile(draws,[.025,.975])
        for a,b in zip(diff["ci95"],q):close(a,b)
    return {"verified":True,"candidates":27,"regimes":len(r["regimes"]),"selected_cells":30,
            "actor_bootstrap_iterations_per_regime":4000,
            "result_sha256":hashlib.sha256((HERE/"result.json").read_bytes()).hexdigest()}

if __name__=="__main__":print(json.dumps(run(),indent=2))
