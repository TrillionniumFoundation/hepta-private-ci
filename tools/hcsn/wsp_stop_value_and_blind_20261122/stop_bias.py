"""Fit and test a common WAIT/READ/REPAIR bias on immutable Hepta checkpoints."""
import argparse
import itertools
import os
import sys
import time
from pathlib import Path

import numpy as np
from scipy.special import expit


def groups(g, scores):
    """Each scalar shift chooses between one frozen terminal and one continuation."""
    mask = np.asarray(g["masks"])
    terminal = np.array([0, 4, 5])
    stop = terminal[np.where(mask[:,terminal],scores[:,terminal],-np.inf).argmax(1)]
    options = np.where(mask[:,1:4],scores[:,1:4],-np.inf)
    go = 1 + options.argmax(1)
    rows = np.arange(len(go))
    margin = scores[rows,stop] - options.max(1)
    payoff = np.asarray(g["terminal"])[rows,stop]
    branches = np.zeros((len(go),3))
    dest = np.zeros((len(go),3),dtype=int)
    fee = np.zeros(len(go))
    for i, action in enumerate(go):
        for k,(probability,after,cost) in enumerate(g["edges"][i][action-1]):
            branches[i,k],dest[i,k] = probability,after
            fee[i] += probability*cost
    return dict(margin=margin,stop=stop,go=go,payoff=payoff,branches=branches,dest=dest,fee=fee,
                tick=np.array([s["tick"] for s in g["states"]]),root=g["initial"])


def curve(world, bound):
    """Exact backward hard payoff on each open interval of this world's switch points."""
    thresholds = np.unique(world["margin"][(world["margin"]>-bound)&(world["margin"]<bound)])
    limits = np.r_[-bound, thresholds, bound]
    # Evaluate the interval by its index to avoid rounded midpoints on adjacent floats.
    switch_index = np.searchsorted(thresholds,world["margin"],side="left")+1
    switch_index[world["margin"]<=-bound]=0
    switch_index[world["margin"]>=bound]=len(limits)
    cells = np.arange(len(limits)-1)
    value = np.zeros((len(world["go"]),len(cells)))
    for i in np.argsort(-world["tick"],kind="stable"):
        value[i,:] = world["payoff"][i]
        offset = switch_index[i]
        if offset == len(limits) or offset >= len(cells):
            continue
        value[i,offset:] = -world["fee"][i]
        for p,after in zip(world["branches"][i],world["dest"][i]):
            if p:
                value[i,offset:] += p*value[after,offset:]
    return thresholds,value[world["root"]]


def exact_edit(worlds, bound, keep_value):
    cuts, levels = zip(*(curve(w,bound) for w in worlds))
    union = np.unique(np.concatenate(cuts))
    jumps = np.zeros(len(union))
    for thresholds,values in zip(cuts,levels):
        jumps[np.searchsorted(union,thresholds)] += np.diff(values)
    means = (sum(v[0] for v in levels)+np.r_[0,np.cumsum(jumps)])/len(levels)
    limits = np.r_[-bound,union,bound]
    mids = (limits[:-1]+limits[1:])/2
    usable = (mids>limits[:-1]) & (mids<limits[1:])
    best = max(keep_value,means[usable].max())
    if keep_value>=best-1e-12:
        shift=0.
        predicted=keep_value
    else:
        eligible=np.flatnonzero(usable & (means>=best-1e-12))
        i=eligible[np.argmin(np.abs(mids[eligible]))]
        shift,predicted=mids[i],means[i]
    return float(shift),dict(open_cells=len(means),representable_midpoints=int(usable.sum()),
                              best_mean=best,predicted_selected_mean=predicted,
                              near_best_rule="smallest absolute midpoint within 1e-12, KEEP first")


def stacked(worlds):
    out={}
    for k in ("margin","payoff","branches","fee","tick"):
        out[k]=np.concatenate([w[k] for w in worlds])
    starts=np.cumsum([0]+[len(w["go"]) for w in worlds[:-1]])
    out["dest"]=np.concatenate([w["dest"]+s for w,s in zip(worlds,starts)])
    out["roots"]=np.array([w["root"] for w in worlds])+starts
    out["levels"]=[np.flatnonzero(out["tick"]==i) for i in sorted(set(out["tick"]),reverse=True)]
    return out


def soft_value(w,b,temp):
    probability=expit((b-w["margin"])/temp)
    derivative=probability*(1-probability)/temp
    values=np.zeros_like(probability)
    gradients=np.zeros_like(probability)
    for rows in w["levels"]:
        dest=w["dest"][rows]
        trans=w["branches"][rows]
        adv=np.sum(trans*values[dest],axis=1)-w["fee"][rows]-w["payoff"][rows]
        values[rows]=w["payoff"][rows]+probability[rows]*adv
        gradients[rows]=derivative[rows]*adv+probability[rows]*np.sum(trans*gradients[dest],axis=1)
    return float(values[w["roots"]].mean()),float(gradients[w["roots"]].mean())


def adam_edit(w,bound):
    b=m=v=0.
    temp=.05
    val,grad=soft_value(w,b,temp)
    fd=(soft_value(w,1e-5,temp)[0]-soft_value(w,-1e-5,temp)[0])/2e-5
    if abs(fd-grad)>1e-6:
        raise ArithmeticError("soft derivative")
    best=(val,b)
    trace=[]
    for t in range(1,65):
        m=.9*m+.1*grad
        v=.999*v+.001*grad*grad
        b=float(np.clip(b+.02*(m/(1-.9**t))/(np.sqrt(v/(1-.999**t))+1e-8),-bound,bound))
        val,grad=soft_value(w,b,temp)
        if val>best[0]+1e-14:
            best=(val,b)
        trace.append(dict(step=t,b=b,soft_value=val,gradient=grad))
    return best[1],dict(temperature=temp,initial_gradient_check_abs=abs(fd-soft_value(w,0,temp)[1]),
                         trace=trace,maximum_soft_value=best[0])


def sign_flip(d):
    signs=np.array(list(itertools.product((-1.,1.),repeat=len(d))))
    return float(np.mean(np.abs((signs*np.array(d)).mean(axis=1))>=abs(np.mean(d))-1e-14))


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("archive_root",type=Path,help="unpacked Hepta_WSP_Evidence_20261122_ET")
    ap.add_argument("output",type=Path)
    ap.add_argument("--entropy",help="hex from completed run to replay")
    args=ap.parse_args()
    if os.environ.get("OPENBLAS_NUM_THREADS")!="1":
        raise RuntimeError("set OPENBLAS_NUM_THREADS=1")
    root=args.archive_root.resolve()
    src=root/"neuron/pinned"
    sys.path.insert(0,str(src))
    from study_io import checked,context,gen_items
    from data_contract import canonical,digest,exact_radius,head,model_with_head,pin,read,save
    from public_sampling import public_world
    import value_graph as vg
    out=args.output
    out.mkdir(parents=True,exist_ok=False)
    p=read(src/"PROTOCOL_FROZEN.json")
    if pin(src/"PROTOCOL_FROZEN.json")["sha256"]!="adca7eed0c7dc63a5d884fc44f8e8431d7dae56eb44d0566d522eb8dae405d10":
        raise ValueError("unexpected protocol")
    ctx=context(p)
    began=time.process_time()
    arms=("KEEP","EXACT","ADAM","REVERSE","FULL_BP")
    method=dict(arms=arms,originals=p["fit_ids"],worlds_per_fit_domain=16,
                score="equal-world mean initial expected utility using candidate's hard policy",
                primary="EXACT - KEEP per checkpoint, separately by IID/OOD; 5-fit sign flip",
                tail="individual loss exceeding 0.05 disqualifies deployment",
                scalar="same shift on the three continuation biases; one free scalar",
                radius="min(0.25, original Q Frobenius radius/sqrt(3)), rounded inward",
                search="all open breakpoint cells with representable midpoints plus unchanged model",
                gradient="Adam 64 steps, lr=.02, beta=.9/.999, temperature=.05, best GEN soft value",
                full_bp="existing independent 4324-parameter baseline trained on same GEN, different objective",
                script_sha=pin(__file__)["sha256"],input_sha=pin(src/"PROTOCOL_FROZEN.json")["sha256"],
                python=sys.version,numpy=np.__version__)
    save(out/"METHOD.json",method)
    originals={}
    models={}
    fit_records={}
    former=read(root/"fullbp/run/FIT.json")
    for fit in p["fit_ids"]:
        base,items=gen_items(p,root/"neuron/inputs",fit)
        originals[fit]=base
        anchor=head(base)
        bound=min(.25,exact_radius(anchor)["numeric_radius"]/np.sqrt(3))*(1-1e-12)
        start=time.process_time()
        gs=[vg.strict_scores(anchor,it["H"])[0] for it in items]
        ws=[groups(it["graph"],s) for it,s in zip(items,gs)]
        keep=np.mean([vg.evaluate(it["graph"],s)[0]["utility"] for it,s in zip(items,gs)])
        common=time.process_time()-start
        start=time.process_time()
        direct,stats=exact_edit(ws,bound,keep)
        exact_cost=time.process_time()-start
        start=time.process_time()
        adam,adam_stats=adam_edit(stacked(ws),bound)
        adam_cost=time.process_time()-start
        shifts={"KEEP":0.,"EXACT":direct,"ADAM":adam,"REVERSE":-direct}
        trained={}
        totals={}
        norm={}
        for name,b in shifts.items():
            rows=anchor.copy()
            rows[:3,48]+=b
            model,n=model_with_head(base,rows,"Q")
            trained[name]=model
            norm[name]=n["numeric_delta_norm"]
            totals[name]=np.mean([vg.evaluate(it["graph"],vg.strict_scores(head(model),it["H"])[0])[0]["utility"]
                                  for it in items])
        if abs(totals["EXACT"]-stats["predicted_selected_mean"])>1e-10 or totals["EXACT"]<keep-1e-10:
            raise ArithmeticError("serialized hard policy failed finite sweep check")
        full_file=root/"fullbp/run/models"/f"{fit}_full_bp.json.gz"
        if digest(canonical(read(full_file)).encode())!=former[str(fit)]["model_hashes"]["FULL_BP"]:
            raise ValueError("unbound BP model")
        trained["FULL_BP"]=read(full_file)
        models[fit]=trained
        fit_records[fit]=dict(parent_sha256=p["fits"][str(fit)]["model"]["sha256"],
             full_bp_file_sha256=pin(full_file)["sha256"], bound=bound,shifts=shifts,norm=norm,
             models={a:digest(canonical(m).encode()) for a,m in trained.items()},
             states=sum(len(x["H"]) for x in items),exact=stats,adam=adam_stats,gen_utility=totals,
             common_cpu_seconds=common,exact_cpu_seconds=exact_cost,adam_cpu_seconds=adam_cost)
    save(out/"FITS.json",fit_records)
    seal=digest(canonical({str(f):r["models"] for f,r in fit_records.items()}).encode())
    save(out/"MODEL_SEAL.json",dict(model_hash=seal,method_hash=pin(out/"METHOD.json")["sha256"]))
    used=set(p["known_schedule_hashes"])
    for phase in ("selection","confirmation"):
        hist=read(src/"evidence/run"/f"{phase}_attempt001/output/WORLDS_FROZEN.json")
        for by_domain in hist["groups"].values():
            for group in by_domain.values():
                used.update(w["schedule_sha256"] for w in group["worlds"])
    for rel,key in [("neuron/run/WORLDS.json","fingerprint"),("fullbp/run/WORLDS.json","schedule")]:
        used.update(w[key] for w in read(root/rel)["cases"])
    previous=len(used)
    entropy=bytes.fromhex(args.entropy) if args.entropy else os.urandom(32)
    cases=[]
    for fit in p["fit_ids"]:
        for domain in ("iid","ood"):
            seed=int(digest(entropy+canonical(["exact-stop-bias-v1",seal,fit,domain]).encode()),16)
            rng=np.random.default_rng(seed)
            for idx in range(method["worlds_per_fit_domain"]):
                public=public_world(rng,p["public_domains"][domain],p["public_domains"]["prior_distances"],
                                    f"stopbias_{fit}_{domain}_{idx}")
                key=digest(canonical({k:public[k] for k in p["schedule_fields"]}).encode())
                if key in used:
                    raise ValueError("historical schedule collision")
                used.add(key)
                cases.append(dict(fit=fit,domain=domain,index=idx,public=public,schedule=key))
    save(out/"WORLDS.json",dict(cases=cases,excluded=previous,entropy=entropy.hex(),seal=seal))
    eval_begin=time.process_time()
    results=[]
    for row in cases:
        fit=row["fit"];base=originals[fit];public=row["public"]
        g=vg.build(ctx,public,base,p["state_cap"],lambda:None)
        x,_=vg.semantic_inputs(ctx,public,ctx.NumpyPolicy(base),g["states"],lambda:None)
        hidden=vg.strict_hidden(base,x)
        metrics={}
        for arm in arms:
            model=models[fit][arm]
            h=vg.strict_hidden(model,x) if arm=="FULL_BP" else hidden
            scores=vg.strict_scores(head(model),h)[0]
            rep,_=vg.evaluate(g,scores)
            metrics[arm]={k:rep[k] for k in ("utility","optimal_utility","terminal_mass","PDI_residual",
                "expected_terminal_reward","expected_expense","expected_decisions",
                "terminal_gap_contribution","continuation_gap_contribution")}
        results.append(dict(fit=fit,domain=row["domain"],world=row["index"],schedule=row["schedule"],
                            states=len(x),arms=metrics))
    save(out/"ROWS.json",results)
    summary={}
    for domain in ("iid","ood"):
        group=[r for r in results if r["domain"]==domain]
        summary[domain]={}
        for arm in arms:
            def paired(r,control):
                return r["arms"][arm]["utility"]-r["arms"][control]["utility"]
            byfit={other:[np.mean([paired(r,other) for r in group if r["fit"]==f]) for f in p["fit_ids"]]
                   for other in ("KEEP","ADAM","FULL_BP")}
            diffs=[paired(r,"KEEP") for r in group]
            summary[domain][arm]=dict(utility=np.mean([r["arms"][arm]["utility"] for r in group]),
                delta=np.mean(diffs),tail_losses=sum(d<-.05 for d in diffs),worst=min(diffs),
                per_fit_difference=byfit,sign_flip={c:sign_flip(ds) for c,ds in byfit.items()})
    save(out/"SUMMARY.json",summary)
    save(out/"COST.json",dict(work=vg.WORK,cpu_seconds=time.process_time()-began,
         evaluation_cpu_seconds=time.process_time()-eval_begin,
         excluded_costs="historical training, graph generation and full-BP fitting; decision cost shown independently"))

if __name__=="__main__":
    main()
