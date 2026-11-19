"""Separate-process source-bound scorer for the finite synthetic Critic study.

Independent rational-payoff implementation: does not import candidate or use its
critic, fitted data, or reported efficacy. Future worlds are generated HERE only,
after the immutable prediction seal was written by a different executable.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from fractions import Fraction as F
from math import ceil
from pathlib import Path
from random import Random

ACTIONS=("stop","observe_0","observe_1")
ARMS=("no_search","fixed_depth_1","exact_tree","learned_critic")


def canonical(x):
    return json.dumps(x,sort_keys=True,separators=(",",":"),ensure_ascii=True,allow_nan=False)


def digest(x):
    return hashlib.sha256(canonical(x).encode()).hexdigest()


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def pct(p,idx,b):
    if idx is None:
        return p[0]*p[1]
    return F(0) if b==0 else p[1-idx]


def choose(p,idx=None,b=None):
    return pct(p,idx,b)>=F(1,2)


def payoff(row,choice,world):
    p=tuple(F(k) for k in row["prior"])
    cost=tuple(F(k) for k in row["cost"])
    if choice=="stop":
        predicted, acquisition=choose(p), F(0)
    else:
        which=int(choice[-1]);predicted=choose(p,which,world[which]);acquisition=cost[which]
    return (F(1) if predicted==bool(world[0] and world[1]) else F(-1))-acquisition


def optimal(row):
    p=tuple(F(k) for k in row["prior"])
    c=tuple(F(k) for k in row["cost"])
    u=[abs(2*p[0]*p[1]-1), 1-p[0]+p[0]*abs(2*p[1]-1)-c[0],
       1-p[1]+p[1]*abs(2*p[0]-1)-c[1]]
    return ACTIONS[max(range(3), key=lambda i:(u[i],-i))], max(u)


def score(future, seal, *, sealed_sha256, window, world_seed):
    if type(sealed_sha256) is not str or len(sealed_sha256)!=64 or digest(seal)!=sealed_sha256:
        raise ValueError("sealed content digest mismatch")
    if seal.get("schema")!="hepta.ndu-system2.paired-continuation.v1" or seal.get("authority")!="DENY_ALL" or seal.get("production_accepted") is not False or seal.get("future_labels_provided_to_critic") is not False:
        raise ValueError("unsupported permission or output schema")
    if window not in ("future_1","future_2") or type(world_seed) is not int or not 0<=world_seed<2**32:
        raise ValueError("independent world seed/window required")
    if type(future) is not list or not 1<=len(future)<=8192 or seal["source_only_future_inputs_sha256"].get(window)!=digest(future):
        raise ValueError("source-only future rows mismatch")
    if set(seal.get("predictions",{}))!={"future_1","future_2"} or set(seal.get("meters",{}))!={"future_1","future_2"}:
        raise ValueError("incomplete two-window candidate")
    all_ids=set();all_groups=set()
    ranges={"future_1":(10000,19999),"future_2":(20000,29999)}
    for r in future:
        if type(r) is not dict or set(r)!={"case_id","group_id","observed_at","split","prior","cost"} or r["split"]!=window:
            raise ValueError("future label leakage or corrupted row")
        if not ranges[window][0]<=r["observed_at"]<=ranges[window][1]:
            raise ValueError("future observation order")
        if r["case_id"] in all_ids or r["group_id"] in all_groups or digest([r["prior"],r["cost"]])!=r["group_id"]:
            raise ValueError("future source identity reused/tampered")
        all_ids.add(r["case_id"]);all_groups.add(r["group_id"])
        p=tuple(F(x) for x in r["prior"])
        c=tuple(F(x) for x in r["cost"])
        if any(not 0<x<1 for x in p) or any(not 0<=x<=1 for x in c):
            raise ValueError("future source domain")
    actions_by_arm=seal["predictions"][window]
    if set(actions_by_arm)!=set(ARMS):
        raise ValueError("missing predeclared baseline arm")
    result={}
    rng=Random(world_seed)
    worlds=[]
    for row in future:
        p=[F(x) for x in row["prior"]]
        worlds.append((int(rng.random()<float(p[0])),int(rng.random()<float(p[1]))))
    oracle_choices={row["case_id"]:optimal(row) for row in future}
    for arm in ARMS:
        acts=actions_by_arm[arm]
        if type(acts) is not dict or set(acts)!=all_ids or any(a not in ACTIONS for a in acts.values()):
            raise ValueError("missing/invalid sealed action")
        meter=seal["meters"][window][arm]
        if type(meter) is not dict or set(meter)!={"cpu_prediction_ns","legal_actions_compared","observation_action_count"}:
            raise ValueError("invalid measured action work")
        if type(meter["cpu_prediction_ns"]) is not int or meter["cpu_prediction_ns"]<=0 or meter["legal_actions_compared"]!=len(future)*(3 if arm in ("exact_tree","learned_critic") else 1) or meter["observation_action_count"]!=sum(a!="stop" for a in acts.values()):
            raise ValueError("inconsistent prospective resource inventory")
        if arm=="no_search" and any(a!="stop" for a in acts.values()):
            raise ValueError("no-search arm changed")
        if arm=="fixed_depth_1" and any(a!="observe_0" for a in acts.values()):
            raise ValueError("fixed-depth arm changed")
        if arm=="exact_tree" and any(acts[r["case_id"]]!=oracle_choices[r["case_id"]][0] for r in future):
            raise ValueError("exact Bellman arm was not exact")
        vals=[payoff(r,acts[r["case_id"]],w) for r,w in zip(future,worlds)]
        oracle_exp=[oracle_choices[r["case_id"]][1] for r in future]
        self_exp=[]
        for row in future:
            p=[F(x) for x in row["prior"]];c=[F(x) for x in row["cost"]]
            action=acts[row["case_id"]]
            if action=="stop": u=abs(2*p[0]*p[1]-1)
            elif action=="observe_0": u=1-p[0]+p[0]*abs(2*p[1]-1)-c[0]
            else: u=1-p[1]+p[1]*abs(2*p[0]-1)-c[1]
            self_exp.append(u)
        # Mean empirical realized utility and exact law-conditional policy value.
        result[arm]={"n":len(vals), "realized_mean":float(sum(vals,F(0))/len(vals)),
                     "expected_mean":float(sum(self_exp,F(0))/len(self_exp)),
                     "expected_regret_to_exact_tree":float(sum((x-y for x,y in zip(oracle_exp,self_exp)),F(0))/len(vals)),
                     "observed_inspections":meter["observation_action_count"],
                     "decision_cpu_ns":meter["cpu_prediction_ns"],
                     "paid_candidate_action_comparisons":meter["legal_actions_compared"]}
    learned=actions_by_arm["learned_critic"]
    pure=actions_by_arm["no_search"]
    oracle=actions_by_arm["exact_tree"]
    lr=[payoff(r,learned[r["case_id"]],w) for r,w in zip(future,worlds)]
    sr=[payoff(r,pure[r["case_id"]],w) for r,w in zip(future,worlds)]
    er=[payoff(r,oracle[r["case_id"]],w) for r,w in zip(future,worlds)]
    result["paired"]={"learned_vs_no_search_improved":sum(a>b for a,b in zip(lr,sr)),
                      "learned_vs_no_search_worsened":sum(a<b for a,b in zip(lr,sr)),
                      "learned_vs_exact_tree_improved":sum(a>b for a,b in zip(lr,er)),
                      "learned_vs_exact_tree_worsened":sum(a<b for a,b in zip(lr,er))}
    return {"schema":"hepta.ndu-system2.independent-paired-score.v1", "window":window,
            "future_public_sha256":digest(future),"sealed_prediction_sha256":sealed_sha256,
            "eval_world_seed_after_seal":world_seed,"n":len(future),"arms":result,
            "critics_have_independent_natural_task_utility":False,
            "end_to_end_real_model_accepted":False,"stochastic_fbsde_qualified":False,
            "production_accepted":False,"authority":"DENY_ALL"}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--seal",required=True)
    p.add_argument("--seal-sha256",required=True)
    p.add_argument("--future",required=True)
    p.add_argument("--window",choices=("future_1","future_2"),required=True)
    p.add_argument("--world-seed",type=int,required=True)
    p.add_argument("--score",required=True)
    args=p.parse_args()
    out=score(load(args.future), load(args.seal),sealed_sha256=args.seal_sha256,
              window=args.window, world_seed=args.world_seed)
    with Path(args.score).open('x',encoding='utf-8') as f:
        f.write(canonical(out)+'\n')
    print(canonical({"created":args.score,"n":out["n"],"authority":"DENY_ALL"}))

if __name__=="__main__":
    main()
