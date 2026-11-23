"""Replay the 15 economy-encoder fits and confirmed episode decisions independently."""
import argparse
import json
from pathlib import Path

import numpy as np
import torch

from qualification.hcsn_qvi_retrieval import verify as audit


def maps(mode, seed):
    # PyTorch only supplies the specified seeded normal stream. Evaluation,
    # derivatives and regression below use NumPy, independently of training.
    g=torch.Generator().manual_seed(seed)
    shapes={"audio":[], "lif":[(8,9)], "attention":[(8,9)]*3+[(9,9)]}[mode]
    return [(torch.randn(size,generator=g,dtype=torch.float64)/np.sqrt(size[0])).numpy()
            for size in shapes]


def independent_features(x, dt, params, matrices, derivatives=False):
    n,times,_=x.shape
    if not matrices:
        return x,None
    a,b=params
    y=np.empty((n,times,9))
    jac=np.zeros((n,times,9,2))
    if len(matrices)==1:
        current=x@matrices[0]+a
        level=.5*np.exp(b)
        voltage=np.zeros((n,9))
        dv=np.zeros((n,9,2))
        for t in range(times):
            decay=np.exp(-dt[:,t,None])
            pre=decay*voltage+current[:,t]
            fire=(pre>=level).astype(float)
            y[:,t]=fire
            if derivatives:
                du=dv*decay[:,:,None]
                du[:,:,0]+=1
                dm=du.copy()
                dm[:,:,1]-=level
                s=1/(1+np.exp(np.clip(-4*(pre-level),-600,600)))
                dz=(4*s*(1-s))[:,:,None]*dm
                jac[:,t]=dz
                dv=du-level*dz
                dv[:,:,1]-=level*fire
            voltage=pre-level*fire
    else:
        wq,wk,wv,wo=matrices
        query,keys,values=x@wq,x@wk,x@wv
        clock=dt.cumsum(1)
        for t in range(times):
            lag=clock[:,t,None]-clock[:,:t+1]
            logits=(query[:,t,None]*keys[:,:t+1]).sum(2)/3+a*lag
            exp=np.exp(logits-logits.max(1,keepdims=True))
            p=exp/exp.sum(1,keepdims=True)
            value=(p[:,:,None]*values[:,:t+1]).sum(1)@wo
            y[:,t]=np.tanh(value+b)
            if derivatives:
                dprob=p*(lag-(p*lag).sum(1,keepdims=True))
                dv=(dprob[:,:,None]*values[:,:t+1]).sum(1)@wo
                derivative=1-y[:,t]**2
                jac[:,t,:,0]=derivative*dv
                jac[:,t,:,1]=derivative
    return np.concatenate((x,y),axis=-1),jac


def cost_for(evidence,phase,stem):
    directory=evidence/phase
    cost=audit.load(directory/(stem+".cost.json"))
    audit.require(cost["returncode"]==0 and cost["log_sha256"]==audit.digest(directory/(stem+".log"))
                  and cost["output_sha256"]==audit.digest(directory/(stem+".json")),"invalid cold child")
    audit.require(cost["wall_seconds"]>0 and cost["child_cpu_seconds"]>0,"cost missing")
    return cost["wall_seconds"]


def replay(data,evidence,fit_only=False):
    here=Path(__file__).parent
    base=here.with_name("hcsn_qvi_retrieval")
    plan=audit.load(here/"protocol.json")
    main=audit.load(base/"protocol.json")
    manifest=audit.load(base/"data_manifest.json")
    cases=[(m,method,s) for m,methods in plan["arms"].items() for method in methods for s in plan["seeds"]]
    sealpath=evidence/"selection_seal.json"
    seal=audit.load(sealpath)
    stems={f"{mode}-{method}-{seed}.json" for mode,method,seed in cases}
    audit.require(set(seal["files"])==stems and seal["arms"]==list(map(list,cases)),"incomplete selection")
    for name,h in seal["sources"].items():
        audit.require(audit.digest(here.parent/name)==h,"sealed source differs")
    for name,h in seal["files"].items():
        audit.require(audit.digest(evidence/"fit"/name)==h,"sealed fit differs")
    if not fit_only:
        # Do not unseal test unless all fifteen frozen confirmation processes finished.
        for name in stems:
            cost_for(evidence,"confirm",name[:-5])
    names=("train","dev","retain") if fit_only else ("train","dev","retain","test")
    shards={n:audit.read_shard(data,n,manifest,manifest["clock"]) for n in names}
    raw=shards["train"]["x"]
    mu,scale=raw.mean((0,1)),np.maximum(raw.std((0,1)),1e-8)
    norm={n:(s["x"]-mu)/scale for n,s in shards.items()}
    target=audit.teacher(shards["train"],main["cost"])
    totals={"fit":0., "confirm":0.}
    steps=0
    count=0
    results={}
    for mode,method,seed in cases:
        stem=f"{mode}-{method}-{seed}"
        fname=stem+".json"
        fit=audit.load(evidence/"fit"/fname)
        totals["fit"]+=cost_for(evidence,"fit",stem)
        audit.require(fit["sources"]==seal["sources"] and (fit["mode"],fit["method"],fit["seed"])==(mode,method,seed),"wrong fit")
        audit.require(fit["loaded_shards"]=={n:shards[n]["hash"] for n in ("train","dev","retain")},"fit data mismatch")
        audit.same(mu,fit["mean"]);audit.same(scale,fit["scale"])
        mats=maps(mode,seed)
        frozen=sum(m.size for m in mats)
        nhead=(18 if mats else 9)*3
        nouter=2 if mats else 0
        expected_counts={"frozen_projections":frozen,"nonlinear_coordinates":nouter,
                         "outer_trainable":2 if method=="bp" else 0,"svd_trainable":nhead,
                         "total_model":frozen+nouter+nhead,"total_fitted_or_BP_eligible":nhead+(2 if method=="bp" else 0)}
        audit.require(fit["params"]==expected_counts,"parameter counts differ")
        def features(n,theta,deriv=False):
            return independent_features(norm[n],shards[n]["dt"],theta,mats,deriv)
        def score(n,theta,head):
            h,_=features(n,theta)
            return audit.evaluate(h@head[:-1]+head[-1],shards[n],main["cost"])
        report=fit["fit"]
        audit.require(not report["errors"] and report["cost"]["backward_calls"]==(4 if method=="bp" else 0),"missing outer work")
        expected=np.zeros(nouter)
        m=np.zeros_like(expected);v=m.copy()
        attempts=report["attempts"]
        audit.require(len(attempts)==(5 if method=="bp" else 1),"unexpected candidate count")
        best=-np.inf
        best_index=None
        for i,row in enumerate(attempts):
            theta=np.asarray(row["theta"])
            audit.same(expected,theta)
            need_grad=method=="bp" and i<4
            h,jac=features("train",theta,need_grad)
            head=audit.regression(h,target,.001)
            loss_res=h@head[:-1]+head[-1]-target
            audit.same(row["train_objective"],np.mean(np.sum(loss_res**2,axis=-1))+.001*np.sum(head[:-1]**2))
            if i==0:
                keep_head=head.copy()
                keep_theta=theta.copy()
                keep_retain=score("retain",theta,head)
                audit.same(head,fit["keep_head"]);audit.same(theta,fit["keep_theta"])
            dev,ret=score("dev",theta,head),score("retain",theta,head)
            rec,=row["diagnostics"]
            audit.compare_metrics(dev,rec["dev"],episodes=False)
            audit.compare_metrics(ret,rec["retain"],episodes=False)
            delta=audit.min_actor(ret,keep_retain)
            audit.same(delta,rec["worst_retain_delta"])
            allowed=delta>=-.05-1e-12
            audit.require(allowed==row["allowed"],"retention gate differs")
            if allowed and dev["utility"]>best+1e-12:
                best,best_index,chosen_theta,chosen_head=dev["utility"],i,theta.copy(),head.copy()
            if need_grad:
                # Envelope gradient. LIF has the registered surrogate derivative,
                # attention its exact smooth first derivative. No autograd calls.
                scores_grad=np.einsum("ntjk,ja->ntak",jac,head[8:-1])
                grad=2*(loss_res[:,:,:,None]*scores_grad).sum(2).mean((0,1))
                order=i+1
                m=.9*m+.1*grad;v=.999*v+.001*grad**2
                expected=theta-.075*(m/(1-.9**order))/(np.sqrt(v/(1-.999**order))+1e-8)
                expected*=min(1,.35/max(1e-30,np.linalg.norm(expected)))
                steps+=1
            count+=1
        audit.require(best_index==report["selected_index"],"selected candidate differs")
        audit.same(best,report["selected_utility"]);audit.same(chosen_theta,fit["theta"])
        audit.same(chosen_head,fit["head"])
        if fit_only:
            continue
        confirmed=audit.load(evidence/"confirm"/fname)
        totals["confirm"]+=cost_for(evidence,"confirm",stem)
        audit.require(confirmed["seal_sha256"]==audit.digest(sealpath) and confirmed["fit_sha256"]==seal["files"][fname]
                      and confirmed["test_hash"]==shards["test"]["hash"],"confirmation provenance mismatch")
        audit.require(confirmed["query_id"]==shards["test"]["query_id"].tolist() and
                      confirmed["group"]==shards["test"]["group"].tolist(),"test episode order mismatch")
        chosen=score("test",chosen_theta,chosen_head)
        keep=score("test",keep_theta,keep_head)
        audit.compare_metrics(chosen,confirmed["chosen"],episodes=True)
        audit.compare_metrics(keep,confirmed["keep"],episodes=True)
        delta=audit.min_actor(chosen,keep)
        audit.same(delta,confirmed["worst_actor_delta"])
        ok=chosen["utility"]>=.60 and chosen["r1"]>=.70 and delta>=-.05-1e-12
        audit.require(ok==confirmed["success"],"success gate mismatch")
        results[stem]={"utility":chosen["utility"],"r1":chosen["r1"],"success":bool(ok)}
    return {"passed":True,"scope":"fit only" if fit_only else "fit and sealed test",
            "models":len(cases),"candidates":count,"outer_steps":steps,"outcomes":results,
            "cold_child_wall_seconds":totals,"audit_sha256":audit.digest(Path(__file__)),
            "selection_seal_sha256":audit.digest(sealpath)}


if __name__=="__main__":
    cli=argparse.ArgumentParser(description=__doc__)
    cli.add_argument("data",type=Path)
    cli.add_argument("evidence",type=Path)
    cli.add_argument("--fit-only",action="store_true")
    args=cli.parse_args()
    print(json.dumps(replay(args.data,args.evidence,args.fit_only),allow_nan=False,sort_keys=True))
