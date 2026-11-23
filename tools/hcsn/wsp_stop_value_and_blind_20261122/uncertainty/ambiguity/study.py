"""Compare fixed edits, task-conditioned edits and fee-robust policies on exact source checkpoints."""
import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

FEE_GRID = (1., 1.25, 1.5, 2., 3.)
TOL = 1e-10


def forward(g, action, transition_tilt=0.):
    occ=np.zeros(len(action));occ[g["initial"]]=1.
    reward=fee=mass=0.
    for i in g["order"]:
        weight=occ[i]
        if not weight: continue
        a=action[i]
        if a in (0,4,5):
            reward+=weight*g["terminal"][i][a];mass+=weight
        else:
            edges=g["edges"][i][a-1]
            probabilities=[p*(1.+transition_tilt*(2*k/(len(edges)-1)-1)) if len(edges)>1 else p
                           for k,(p,_,_) in enumerate(edges)]
            normalization=sum(probabilities) if transition_tilt else 1.
            for pr,(_,j,price) in zip(probabilities,edges):
                flow=weight*pr/normalization
                occ[j]+=flow;fee+=flow*price
    if abs(mass-1)>1e-9:raise ArithmeticError("forward mass")
    return np.array((reward,fee))


def fee_value(rc,mult):
    return float(rc[0]-mult*rc[1])


def worst_gain(rc,keep):
    return min(fee_value(rc-keep,x) for x in (1.,2.))


def select_cell(w,bound,keep,curve):
    cuts,nominal=curve(w,bound)
    extra={**w,"fee":2*w["fee"]}
    doubled_cuts,doubled=curve(extra,bound)
    if not np.array_equal(cuts,doubled_cuts): raise ArithmeticError("different policies at different settlement")
    limits=np.r_[-bound,cuts,bound]
    mid=(limits[:-1]+limits[1:])/2
    mask=(mid>limits[:-1])&(mid<limits[1:])
    shifts={}
    for name,gains in (("TASK_NOMINAL",nominal-fee_value(keep,1.)),
                       ("TASK_BAND",np.minimum(nominal-fee_value(keep,1.),doubled-fee_value(keep,2.)))):
        best=gains[mask].max()
        if best<=TOL: shifts[name]=0.;continue
        idx=np.flatnonzero(mask & (gains>=best-1e-12));winner=idx[np.argmin(np.abs(mid[idx]))];shifts[name]=float(mid[winner])
    return shifts,int(mask.sum())


def main():
    cli=argparse.ArgumentParser(description=__doc__)
    cli.add_argument("baseline",type=Path,help="original 22 Nov ET evidence archive, extracted")
    cli.add_argument("previous",type=Path,help="extracted previous stop/continuation study incl native parity.py")
    cli.add_argument("binary",type=Path)
    cli.add_argument("out",type=Path)
    cli.add_argument("--entropy")
    args=cli.parse_args()
    if os.environ.get("OPENBLAS_NUM_THREADS")!="1":raise ValueError("single-thread run required")
    root=args.baseline.resolve();prev=args.previous.resolve();out=args.out
    out.mkdir(parents=True,exist_ok=False)
    sys.path.insert(0,str(root/"neuron"));sys.path.insert(0,str(prev));sys.path.insert(0,str(prev/"native"))
    from experiment import vg,digest,canonical,head,model_with_head,pin,read,save,context,checked,exact_radius
    from stop_bias import curve,groups,adam_edit,stacked
    from parity import encode
    from public_sampling import public_world
    from advantage_veto import guarded
    now=time.process_time();wall=time.monotonic()
    primary=root/"neuron/pinned/PROTOCOL_FROZEN.json"
    if pin(primary)["sha256"]!="adca7eed0c7dc63a5d884fc44f8e8431d7dae56eb44d0566d522eb8dae405d10":raise ValueError("wrong baseline")
    protocol=read(primary);ctx=context(protocol)
    former=read(prev/"records/study/FITS.json")
    old=read(prev/"records/veto/WORLDS.json")["cases"]
    old_rows=read(prev/"records/veto/ROWS.json")
    used=set(protocol["known_schedule_hashes"])
    for ph in ("selection","confirmation"):
        hist=read(root/"neuron/pinned/evidence/run"/f"{ph}_attempt001/output/WORLDS_FROZEN.json")
        used.update(w["schedule_sha256"] for ds in hist["groups"].values() for group in ds.values() for w in group["worlds"])
    used.update(w["fingerprint"] for w in read(root/"neuron/run/WORLDS.json")["cases"])
    for f in [root/"fullbp/run/WORLDS.json",prev/"records/study/WORLDS.json",prev/"records/veto/WORLDS.json"]:
        used.update(w["schedule"] for w in read(f)["cases"])
    method=dict(version=1,source=pin(__file__)["sha256"],binary=pin(args.binary)["sha256"],old_fits=pin(prev/"records/study/FITS.json")["sha256"],
        objective="max min delta against KEEP at fees 1 and 2; one common interval multiplier; fixed branch probabilities and payoffs",
        arms=["KEEP","SHARED_DIRECT","SHARED_ADAM","TASK_NOMINAL","TASK_BAND","TASK_ADAM","OTHER_TASK_BAND","NOMINAL_ALL",
              "BAND_ONE_DIRECT","BAND_BACK_DIRECT","BAND_ONE_ALL","BAND_BACK_ALL"],
        old_worlds=len(old),new_per_fit_domain=8,excluded=len(used),stress={"fee_outside":3,"branch_tilt":.40},
        controls="separately score reusing same checkpoint's preceding alternate-mate patch, no holdout adjustment; fork at root data, known simulator, no market inference",
        verification="store and reopen exact edited JSON for selected task patch; independent forward occupancy vs native reverse DP at both endpoints; legacy counterexample retained")
    seal=save(out/"METHOD.json",method)["sha256"]
    entropy=bytes.fromhex(args.entropy) if args.entropy else os.urandom(32)
    fresh=[]
    for fit in protocol["fit_ids"]:
        for domain in ("iid","ood"):
            seed=int(digest(entropy+canonical(["robust-scalar-v1",seal,fit,domain]).encode()),16);rng=np.random.default_rng(seed)
            for i in range(8):
                pub=public_world(rng,protocol["public_domains"][domain],protocol["public_domains"]["prior_distances"],f"fee_{fit}_{domain}_{i}")
                key=digest(canonical({k:pub[k] for k in protocol["schedule_fields"]}).encode())
                if key in used:raise ValueError("reused schedule")
                used.add(key); fresh.append(dict(fit=fit,domain=domain,world=i,schedule=key,public=pub))
    save(out/"WORLDS.json",dict(cases=fresh,entropy=entropy.hex(),method=seal))
    models={fit:read(checked(root/"neuron/inputs",protocol["fits"][str(fit)]["model"])["path"]) for fit in protocol["fit_ids"]}
    costs={k:0. for k in ("native_wall","scalar_curves_cpu","task_adam_cpu","restore_checks_cpu")}
    records=[];largest_cross_error=0.;largest_legacy_error=0.;forced_keeps=0
    for population,cases in [("previous",old),("fresh",fresh)]:
        for cidx in range(0,len(cases),2):
            pair=[]
            for ix in (cidx,cidx+1):
                case=cases[ix];fit=case["fit"];pub=case["public"];base=models[fit];anchor=head(base)
                g=vg.build(ctx,pub,base,protocol["state_cap"],lambda:None)
                x,_=vg.semantic_inputs(ctx,pub,ctx.NumpyPolicy(base),g["states"],lambda:None); H=vg.strict_hidden(base,x)
                mask=np.asarray(g["masks"]); scores=vg.strict_scores(anchor,H)[0]
                def act(shift):
                    rows=anchor.copy();rows[:3,-1]+=shift
                    return np.where(mask,vg.strict_scores(rows,H)[0],-np.inf).argmax(1)
                keep=act(0.)
                rc0=forward(g,keep)
                w=groups(g,scores);bound=min(.25,exact_radius(anchor)["numeric_radius"]/np.sqrt(3))*(1-1e-12)
                start=time.process_time();shifts,cells=select_cell(w,bound,rc0,curve);costs["scalar_curves_cpu"]+=time.process_time()-start
                start=time.process_time();shifts["TASK_ADAM"]=adam_edit(stacked([w]),bound)[0];costs["task_adam_cpu"]+=time.process_time()-start
                shifts.update(KEEP=0.,SHARED_DIRECT=former[str(fit)]["shifts"]["EXACT"],SHARED_ADAM=former[str(fit)]["shifts"]["ADAM"])
                arms={a:act(d) for a,d in shifts.items()}
                start=time.process_time()
                offered=shifts["TASK_BAND"]
                m=anchor.copy();m[:3,-1]+=offered
                candidate,norm=model_with_head(base,m,"Q")
                key=digest(canonical(candidate).encode());path=out/"models"/(key+".json.gz")
                if not path.exists(): save(path,candidate)
                restored=read(path)
                if digest(canonical(restored).encode())!=key:raise ValueError("candidate content changed")
                observed=np.where(mask,vg.strict_scores(head(restored),H)[0],-np.inf).argmax(1)
                if not np.array_equal(observed,arms["TASK_BAND"]):raise ValueError("stored model forward disagrees")
                propose_gain=worst_gain(forward(g,observed),rc0)
                if offered and propose_gain<=TOL:
                    forced_keeps+=1;shifts["TASK_BAND"]=0.;arms["TASK_BAND"]=keep
                else:arms["TASK_BAND"]=observed
                costs["restore_checks_cpu"]+=time.process_time()-start
                wire=encode(g,dict(KEEP=keep,EXACT=arms["SHARED_DIRECT"],REVERSE=act(-shifts["SHARED_DIRECT"])))
                start=time.monotonic();run=subprocess.run([args.binary.resolve(),"--fee-band","1","2"],input=wire,capture_output=True,check=True)
                costs["native_wall"]+=time.monotonic()-start;native={}
                for line in run.stdout.decode().splitlines():
                    name,v1,v2,vector=line.split();a=np.frombuffer(vector.encode(),np.uint8)-48
                    if len(a)!=len(keep) or not mask[np.arange(len(a)),a].all():raise ValueError("illegal native action")
                    native[name]=(float(v1),float(v2));arms[name]=a
                if set(native)!={"BAND_ONE_DIRECT","BAND_BACK_DIRECT","BAND_ONE_ALL","BAND_BACK_ALL"}:raise ValueError("incomplete native arms")
                term=np.asarray(g["terminal"]);tick=np.array([s["tick"] for s in g["states"]])
                arms["NOMINAL_ALL"]=guarded(mask,term,g["edges"],g["order"],tick,keep,{"EXACT":arms["SHARED_DIRECT"],"REVERSE":arms["SHARED_DIRECT"]})["ALL_VPI"]
                sc={}
                for name,a in arms.items():
                    rc=forward(g,a);tilted=forward(g,a,method["stress"]["branch_tilt"]);sc[name]=[float(rc[0]),float(rc[1]),*tilted.tolist()]
                    if name in native:
                        discrepancy=max(abs(fee_value(rc,m)-v) for m,v in zip((1,2),native[name]))
                        largest_cross_error=max(largest_cross_error,discrepancy)
                        if discrepancy>1e-9 or worst_gain(rc,rc0)<-1e-9:raise ValueError("independent policy comparison")
                if population=="previous":
                    old_row=old_rows[ix]
                    if old_row["schedule"]!=case["schedule"]:raise ValueError("old schedule mismatch")
                    legacy_error=abs(fee_value(np.array(sc["NOMINAL_ALL"][:2]),1.)-old_row["arms"]["ALL_VPI"]["value"])
                    largest_legacy_error=max(largest_legacy_error,legacy_error)
                    if legacy_error>1e-9:raise ValueError("prior integration mismatch")
                pair.append((g,H,mask,anchor,dict(pop=population,fit=fit,domain=case["domain"],schedule=case["schedule"],
                    states=len(keep),cells=cells,shifts=shifts,offered=offered,candidate_canonical_sha=key,
                    activation="KEEP" if shifts["TASK_BAND"]==0 else "TASK_ONLY",arms=sc)))
            if pair[0][-1]["fit"]!=pair[1][-1]["fit"] or pair[0][-1]["domain"]!=pair[1][-1]["domain"]:raise ValueError("mate identity")
            for i,(g,H,mask,anchor,row) in enumerate(pair):
                other=pair[1-i][-1];new_head=anchor.copy();new_head[:3,-1]+=other["shifts"]["TASK_BAND"]
                a=np.where(mask,vg.strict_scores(new_head,H)[0],-np.inf).argmax(1)
                row["mate"]=other["schedule"];row["arms"]["OTHER_TASK_BAND"]=[*forward(g,a).tolist(),*forward(g,a,.4).tolist()]
                records.append(row)
    save(out/"ROWS.json",records)
    summary={}
    for pop in ("previous","fresh"):
        for domain in ("iid","ood","all"):
            rows=[r for r in records if r["pop"]==pop and (domain=="all" or r["domain"]==domain)]
            metrics={}
            for arm in method["arms"]:
                delta=np.array([r["arms"][arm] for r in rows])-np.array([r["arms"]["KEEP"] for r in rows])
                conditions={str(f):delta[:,0]-f*delta[:,1] for f in FEE_GRID}
                conditions["worst_band"]=np.minimum(conditions["1.0"],conditions["2.0"])
                conditions["tilt_fee2"]=delta[:,2]-2*delta[:,3]
                metrics[arm]={key:dict(mean=float(v.mean()),worst=float(v.min()),gain=int((v>TOL).sum()),loss=int((v < -TOL).sum())) for key,v in conditions.items()}
            summary[pop+"_"+domain]=metrics
    save(out/"SUMMARY.json",summary)
    save(out/"COST.json",dict(**costs,harness_cpu_s=time.process_time()-now,wall_s=time.monotonic()-wall,
        native_comparisons=len(records)*4*2,max_cross_error=largest_cross_error,max_previous_error=largest_legacy_error,
        postwrite_fallbacks=forced_keeps,states=sum(r["states"] for r in records),cases=len(records),
        touched_weights="three F64 Q biases per nonzero task-conditioned edit; full private artifacts saved only off Git"))
if __name__=="__main__":
    main()
