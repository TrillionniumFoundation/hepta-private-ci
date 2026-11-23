"""Prospective own-model rollback of a proposed hard action at each decision state."""
import argparse
import itertools
import os
import sys
import time
from pathlib import Path

import numpy as np


def sign_flip(xs):
    s = np.array(list(itertools.product((-1.,1.),repeat=len(xs))))
    return float(np.mean(np.abs((s*xs).mean(1))>=abs(np.mean(xs))-1e-14))


def policy_values(order,term,edges,act):
    """Backward continuation under the original actor. No optimal action labels."""
    value=np.zeros(len(act))
    for i in reversed(order):
        a=act[i]
        if a in (0,4,5):
            value[i]=term[i,a]
        else:
            value[i]=sum(pr*(value[j]-fee) for pr,j,fee in edges[i][a-1])
    return value


def action_values(term,edges,v):
    values=term.copy()
    for i,row in enumerate(edges):
        for col,branches in enumerate(row,1):
            if branches:
                values[i,col]=sum(pr*(v[j]-fee) for pr,j,fee in branches)
    return values


def guarded(masks,term,edges,order,ticks,actor,proposals):
    count=len(actor)
    rows=np.arange(count)
    if abs(term).max()>1+1e-12:
        raise ValueError("terminal bounds")
    maxfee=max([fee for row in edges for actions in row for _,_,fee in actions]+[0.])
    lo=-np.ones(count)-(max(ticks)-ticks)*maxfee
    hi=np.ones(count)
    policies={}
    def veto(name,action,upper,lower):
        accept=(action!=actor)&(lower[rows,action]>upper[rows,actor]+1e-10)
        policies[name]=np.where(accept,action,actor)
    direct=proposals["EXACT"]
    reverse=proposals["REVERSE"]
    policies.update(KEEP=actor,EXACT_RAW=direct,REVERSE_RAW=reverse)
    for horizon in (1,2):
        lower=action_values(term,edges,lo)
        upper=action_values(term,edges,hi)
        veto(f"EXACT_H{horizon}",direct,upper,lower)
        lo,hi=lower[rows,actor],upper[rows,actor]
    base_v=policy_values(order,term,edges,actor)
    q=action_values(term,edges,base_v)
    if max(abs(base_v-q[rows,actor]))>1e-10 or (base_v<lo-1e-10).any() or (base_v>hi+1e-10).any():
        raise ArithmeticError("parent value interval")
    veto("EXACT_VPI",direct,q,q)
    veto("REVERSE_VPI",reverse,q,q)
    best=np.where(masks,q,-np.inf).argmax(1)
    veto("ALL_VPI",best,q,q)
    for a in ("EXACT_H1","EXACT_H2","EXACT_VPI","REVERSE_VPI","ALL_VPI"):
        gain=q[rows,policies[a]]-base_v
        if gain.min() < -1e-10:
            raise ArithmeticError("state-level improvement guarantee")
    return policies


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("archive",type=Path)
    ap.add_argument("study",type=Path)
    ap.add_argument("out",type=Path)
    ap.add_argument("--entropy")
    args=ap.parse_args()
    root=args.archive.resolve(); study=args.study; out=args.out
    sys.path.insert(0,str(root/"neuron"))
    from verify import forward_payoff
    from experiment import vg,canonical,digest,head,model_with_head,checked,context,read,save,pin
    from public_sampling import public_world
    out.mkdir(parents=True,exist_ok=False)
    t=time.process_time()
    p=read(root/"neuron/pinned/PROTOCOL_FROZEN.json")
    ctx=context(p)
    f=read(study/"FITS.json")
    old=read(study/"WORLDS.json")
    used=set(p["known_schedule_hashes"])
    for phase in ("selection","confirmation"):
        prev=read(root/"neuron/pinned/evidence/run"/f"{phase}_attempt001/output/WORLDS_FROZEN.json")
        used.update(w["schedule_sha256"] for ds in prev["groups"].values() for group in ds.values() for w in group["worlds"])
    used.update(w["fingerprint"] for w in read(root/"neuron/run/WORLDS.json")["cases"])
    used.update(w["schedule"] for w in read(root/"fullbp/run/WORLDS.json")["cases"])
    used.update(w["schedule"] for w in old["cases"])
    initial=len(used)
    arm_names=("KEEP","EXACT_RAW","EXACT_H1","EXACT_H2","EXACT_VPI","REVERSE_RAW","REVERSE_VPI","ALL_VPI")
    seal=save(out/"METHOD.json",dict(script=pin(__file__)["sha256"],prior_model_seal=old["seal"],
             arms=arm_names,source_fit_file=pin(study/"FITS.json")["sha256"],noscore=True,
             comparison="stratified own-law task value and cost, 8 worlds per fit/domain, five fits",
             tolerances=dict(accept=1e-10,conservation=1e-9),historical_exclusions=initial))["sha256"]
    models={}
    for fit in p["fit_ids"]:
        meta=f[str(fit)]
        base=read(checked(root/"neuron/inputs",p["fits"][str(fit)]["model"])["path"])
        models[fit]={"KEEP":base}
        for a in ("EXACT","REVERSE"):
            rows=head(base).copy()
            rows[:3,48]+=meta["shifts"][a]
            models[fit][a]=model_with_head(base,rows,"Q")[0]
        for a,m in models[fit].items():
            if digest(canonical(m).encode())!=meta["models"][a]:
                raise ValueError("candidate changed")
    entropy=bytes.fromhex(args.entropy) if args.entropy else os.urandom(32)
    cases=[]
    for fit in p["fit_ids"]:
        for domain in ("iid","ood"):
            rng=np.random.default_rng(int(digest(entropy+canonical(["veto-v1",seal,fit,domain]).encode()),16))
            for i in range(8):
                public=public_world(rng,p["public_domains"][domain],p["public_domains"]["prior_distances"],f"vet_{fit}_{domain}_{i}")
                key=digest(canonical({k:public[k] for k in p["schedule_fields"]}).encode())
                if key in used:
                    raise ValueError("schedule collision")
                used.add(key)
                cases.append(dict(fit=fit,domain=domain,world=i,schedule=key,public=public))
    save(out/"WORLDS.json",dict(cases=cases,entropy=entropy.hex(),seal=seal))
    records=[]
    worst_flow_error=0.
    gate_cpu=0.
    min_absolute=1.
    for row in cases:
        fit=row["fit"]; pub=row["public"];base=models[fit]["KEEP"]
        g=vg.build(ctx,pub,base,p["state_cap"],lambda:None)
        x,_=vg.semantic_inputs(ctx,pub,ctx.NumpyPolicy(base),g["states"],lambda:None)
        H=vg.strict_hidden(base,x)
        mask=np.asarray(g["masks"])
        actors={a:np.where(mask,vg.strict_scores(head(m),H)[0],-np.inf).argmax(1) for a,m in models[fit].items()}
        term=np.asarray(g["terminal"]);ticks=np.array([s["tick"] for s in g["states"]])
        start=time.process_time()
        policies=guarded(mask,term,g["edges"],g["order"],ticks,actors["KEEP"],actors)
        gate_cpu+=time.process_time()-start
        metrics={}
        for a in arm_names:
            policy=policies[a]
            if not mask[np.arange(len(policy)),policy].all():
                raise ArithmeticError("illegal selected action")
            scores=np.zeros_like(term)
            scores[np.arange(len(policy)),policy]=1.
            report,detail=vg.evaluate(g,scores)
            difference=abs(report["utility"]-forward_payoff(g,scores))
            worst_flow_error=max(worst_flow_error,difference)
            if difference>1e-9:
                raise ArithmeticError("payoff discrepancy")
            metrics[a]=dict(value=report["utility"],optimum=report["optimal_utility"],
                            changed_states=int(sum(policy!=actors["KEEP"])),
                            expected_changed_decisions=float(detail["occupancy"]@(policy!=actors["KEEP"])),
                            cost=report["expected_expense"],decisions=report["expected_decisions"])
        d=min(metrics[a]["value"]-metrics["KEEP"]["value"] for a in arm_names if a not in ("EXACT_RAW","REVERSE_RAW"))
        if d<-1e-9:
            raise ArithmeticError("negative known-law world")
        min_absolute=min(min_absolute,d)
        records.append(dict(fit=fit,domain=row["domain"],schedule=row["schedule"],states=len(H),arms=metrics))
    save(out/"ROWS.json",records)
    def summary(domain,arm):
        ss=[r for r in records if r["domain"]==domain]
        d=np.array([r["arms"][arm]["value"]-r["arms"]["KEEP"]["value"] for r in ss])
        fds=[np.mean([v for r,v in zip(ss,d) if r["fit"]==fit]) for fit in p["fit_ids"]]
        return dict(mean_delta=d.mean(),worst=d.min(),better=int((d>1e-10).sum()),worse=int((d < -1e-10).sum()),
                    tail_losses=int((d<-.05).sum()),mean_utility=np.mean([r["arms"][arm]["value"] for r in ss]),
                    changed_states=sum(r["arms"][arm]["changed_states"] for r in ss),
                    per_fit_delta=fds,sign_flip=sign_flip(fds))
    save(out/"SUMMARY.json",{d:{a:summary(d,a) for a in arm_names} for d in ("iid","ood")})
    save(out/"VERIFIED.json",dict(worlds=len(cases),forward_values=len(cases)*len(arm_names),max_flow_error=worst_flow_error,
         states=sum(r["states"] for r in records),minimum_guarded_world_delta=min_absolute,
         guard_cpu_seconds=gate_cpu,full_cpu_seconds=time.process_time()-t,seal=seal,
         resources="exhaustively materializes finite own-law state graphs; guard timing excludes graph, actor and feature construction"))

if __name__=="__main__":
    main()
