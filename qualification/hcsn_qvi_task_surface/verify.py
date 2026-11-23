"""Post-confirmation replay of the nine supplementary physical-obstacle policies."""
import argparse
import itertools
import json
from pathlib import Path

import numpy as np
import torch

from qualification.hcsn_qvi_retrieval import verify as audit
from .model import TaskSurface


def replay(data,evidence):
    here=Path(__file__).parent
    base=here.with_name("hcsn_qvi_retrieval")
    plan=audit.load(base/"protocol.json")
    cases=list(itertools.product(plan["methods"],plan["seed"]))
    sealpath=evidence/"selection_seal.json"
    seal=audit.load(sealpath)
    names={f"task_surface-{m}-{s}.json" for m,s in cases}
    audit.require(set(seal["files"])==names and seal["cases"]==[list(p) for p in cases],
                  "supplement is not fully sealed")
    for n,h in seal["files"].items():
        audit.require(audit.digest(evidence/"fit"/n)==h,"sealed fit bytes differ")
    for n,h in seal["sources"].items():
        audit.require(audit.digest(here.parent/n)==h,"sealed source bytes differ")
    manifest=audit.load(base/"data_manifest.json")
    shards={k:audit.read_shard(data,k,manifest,manifest["clock"]) for k in manifest["splits"]}
    audit.require(len(set.union(*(s["source_hashes"] for s in shards.values())))==191,"source aliases")
    cost=plan["cost"]
    edges,values=audit.finite_bellman(shards["train"],cost)
    y=audit.teacher(shards["train"],cost)
    raw=shards["train"]["x"]
    mu=raw.mean((0,1))
    std=np.maximum(raw.std((0,1)),1e-8)
    total={"fit":0.,"confirm":0.}
    checked=0
    results={}
    torch.set_num_threads(1)
    torch.use_deterministic_algorithms(True)
    for method,seed in cases:
        name=f"task_surface-{method}-{seed}"
        f=audit.load(evidence/"fit"/(name+".json"))
        c=audit.load(evidence/"confirm"/(name+".json"))
        audit.require(f["sources"]==seal["sources"] and c["selection_seal"]==audit.digest(sealpath)
                      and c["fit_hash"]==seal["files"][name+".json"],"provenance mismatch")
        for phase,out in (("fit",f),("confirm",c)):
            times=audit.process_cost(evidence,phase,name)
            total[phase]+=times["wall_seconds"]
            audit.require(out["method"]==method and out["seed"]==seed and out["mode"]=="task_surface",
                          "unexpected arm identity")
        for n in shards:
            audit.require((c if n=="test" else f)[n+"_hash"]==shards[n]["hash"],"wrong evaluation input")
        audit.require(c["query_id"]==shards["test"]["query_id"].tolist()
                      and c["actor"]==shards["test"]["group"].tolist(),"wrong episode order")
        for x,z in [(f["mean"],mu),(f["scale"],std),(f["finite_edges"],edges),(f["finite_q"],values)]:
            audit.same(x,z)
        torch.manual_seed(seed)
        model=TaskSurface(raw.shape[-1],edges,values)
        radius=0.9*min(float(model.task[3]-model.nominal_boundary-model.flow.centers[0]),
                       float(model.flow.centers[-1]-model.task[3]+model.nominal_boundary))
        bases={}
        for n,s in shards.items():
            bins=audit.margin_bins(s,edges)
            t=np.arange(bins.shape[1])[None,:]
            advantage=values[t,bins,:2].max(2)-values[t,bins,2]
            normalized=np.tanh(advantage)
            normalized[:,-1]=1
            margin=torch.from_numpy(s["x"][:,:,-2])
            observed=model.task_boundaries(margin)
            audit.same(observed.numpy(),float(model.nominal_boundary)+radius*normalized)
            bases[n]=(margin,torch.from_numpy((s["x"]-mu)/std),torch.from_numpy(s["dt"]))
        cache={}
        def features(n,theta):
            k=(n,tuple(theta))
            if k not in cache:
                mg,x,dt=bases[n]
                with torch.no_grad():
                    physical=model.features_with_edit(torch.tensor(theta,dtype=torch.float64),x,dt,mg)
                    cache[k]=torch.cat((x,physical),dim=-1).numpy()
            return cache[k]
        def score(n,theta,head):
            mat=features(n,theta)
            return audit.evaluate(mat@head[:-1]+head[-1],shards[n],cost)
        keep=[0.,0.]
        keep_head=audit.regression(features("train",keep),y,plan["training"]["ridge"])
        audit.same(keep_head,f["keep_head"])
        keep_retain=score("retain",keep,keep_head)
        best,idx,head0=-np.inf,None,None
        for i,r in enumerate(f["fit"]["attempts"]):
            if "error" in r:
                continue
            theta=r["theta"]
            head=audit.regression(features("train",theta),y,plan["training"]["ridge"])
            dev,retain=score("dev",theta,head),score("retain",theta,head)
            rec,=r["diagnostics"]
            audit.compare_metrics(dev,rec["dev"],episodes=False)
            audit.compare_metrics(retain,rec["retain"],episodes=False)
            delta=audit.min_actor(retain,keep_retain)
            audit.same(delta,rec["worst_retain_delta"])
            allowed=delta>=-.05-1e-12
            audit.require(allowed==r["allowed"],"retention selection differs")
            if allowed and dev["utility"]>best+1e-12:
                best,idx,head0=dev["utility"],i,head
            checked+=1
        audit.require(idx==f["fit"]["selected_index"] and f["theta"]==f["fit"]["attempts"][idx]["theta"],
                      "selected candidate differs")
        audit.same(head0,f["head"])
        selected=score("test",f["theta"],np.asarray(f["head"]))
        unchanged=score("test",keep,np.asarray(f["keep_head"]))
        audit.compare_metrics(selected,c["chosen"],episodes=True)
        audit.compare_metrics(unchanged,c["keep"],episodes=True)
        controls=audit.controls(shards["test"],edges,values,cost)
        for n,metrics in controls.items():
            audit.compare_metrics(metrics,c["controls"][n],episodes=True)
        audit.same(c["worst_actor_delta"],audit.min_actor(selected,unchanged))
        audit.same(c["worst_vs_common_stop"],audit.min_actor(selected,controls["immediate_stop"]))
        ok=selected["utility"]>=.6 and selected["r1"]>=.7 and audit.min_actor(selected,unchanged)>=-.05-1e-12
        audit.require(ok==c["success"],"supplemental acceptance differs")
        results[name]=dict(passed=bool(ok),utility=selected["utility"],r1=selected["r1"])
    return dict(passed=True,arms=results,candidates_replayed=checked,cold_child_seconds=total,
                qualification="Replay using original finite flow with independently reconstructed task Bellman and threshold, affine readouts, action trajectories, utilities and retention.")


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("data",type=Path)
    parser.add_argument("evidence",type=Path)
    args=parser.parse_args()
    print(json.dumps(replay(args.data,args.evidence),allow_nan=False,sort_keys=True))
