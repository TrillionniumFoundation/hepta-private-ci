"""Re-evaluate serialized task readouts and robust policy decisions under independent finite laws."""
import argparse
import hashlib
import os
import subprocess
import sys
import time
from pathlib import Path
import numpy as np

TOL=1e-10


def probabilities(edges, tilt):
    p=np.array([e[0] for e in edges]);z=np.linspace(-1,1,len(edges)) if len(edges)>1 else np.zeros(1)
    v=p*(1+tilt*z)
    return v/v.sum()


def make_law(graph, twists, fees):
    blocks=[]
    for i,actions in enumerate(graph["edges"]):
        row=[]
        for k,edges in enumerate(actions):
            p=probabilities(edges,twists[i,k]) if edges else []
            row.append([(float(v),j,c*fees[i,k,h]) for h,(v,(_,j,c)) in enumerate(zip(p,edges))])
        blocks.append(row)
    return {**graph,"edges":blocks}


def independent_minimum(g, policy):
    """Choose the adverse probability for every legal action using child minima."""
    v=np.zeros((len(policy),));witness=np.zeros((len(policy),3))
    for i in reversed(g["order"]):
        values=np.array(g["terminal"][i],copy=True)
        for a,edges in enumerate(g["edges"][i],1):
            if not edges:continue
            x=[v[j]-3*price for _,j,price in edges]
            vals=[float(probabilities(edges,t)@x) for t in (-.4,.4)]
            pick=int(vals[1]<vals[0]); values[a]=vals[pick]; witness[i,a-1]=(-.4,.4)[pick]
        v[i]=values[policy[i]] if policy is not None else values[np.asarray(g["masks"][i])].max()
    return v,witness


def upper_and_lower_opt(g,policy):
    """Lower bound achieved by this policy; upper bound by one adversary against every policy."""
    v,witness=independent_minimum(g,policy)
    fees=np.full((len(policy),3,3),3.)
    fixed=make_law(g,witness,fees)
    upper=np.zeros(len(policy))
    for i in reversed(g["order"]):
        vals=np.array(g["terminal"][i],copy=True)
        for a,edges in enumerate(fixed["edges"][i],1):
            if edges: vals[a]=sum(p*(upper[j]-c) for p,j,c in edges)
        upper[i]=vals[np.asarray(g["masks"][i])].max()
    return v,upper


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("baseline",type=Path);ap.add_argument("previous",type=Path)
    ap.add_argument("sweep",type=Path);ap.add_argument("binary",type=Path);ap.add_argument("out",type=Path)
    ap.add_argument("--entropy")
    a=ap.parse_args();out=a.out;out.mkdir(parents=True,exist_ok=False)
    sys.path[:0]=[str(a.baseline.resolve()/"neuron"),str(a.previous.resolve()),str(a.previous.resolve()/"native"),
                  str(Path(__file__).resolve().parent)]
    from study import forward,select_cell
    from experiment import vg,digest,canonical,head,model_with_head,pin,read,save,context,checked,exact_radius
    from stop_bias import curve,groups
    from parity import encode
    from public_sampling import public_world
    start=time.monotonic();cpu=time.process_time();native_wall=0.;max_witness_gap=0.;max_negative_bound_violation=0.;max_native_dp_error=0.
    protocol=read(a.baseline/"neuron/pinned/PROTOCOL_FROZEN.json");ctx=context(protocol)
    old=read(a.sweep/"WORLDS.json")["cases"]
    used=set(protocol["known_schedule_hashes"])
    for ph in ("selection","confirmation"):
        h=read(a.baseline/"neuron/pinned/evidence/run"/f"{ph}_attempt001/output/WORLDS_FROZEN.json")
        used.update(w["schedule_sha256"] for ds in h["groups"].values() for group in ds.values() for w in group["worlds"])
    used.update(w["fingerprint"] for w in read(a.baseline/"neuron/run/WORLDS.json")["cases"])
    for f in [a.baseline/"fullbp/run/WORLDS.json",a.previous/"records/study/WORLDS.json",a.previous/"records/veto/WORLDS.json",a.sweep/"WORLDS.json"]:
        used.update(w["schedule"] for w in read(f)["cases"])
    seal=save(out/"METHOD.json",dict(source=pin(__file__)["sha256"],binary=pin(a.binary)["sha256"],sweep=pin(Path(__file__).with_name("study.py"))["sha256"],
        uncertainty=dict(fee=[1,3],tilt=[-.4,.4],rectangular="one independent tilt per state/action and fees within interval per branch; topology, observations, fixed terminal rewards"),
        method="exact maximin finite DP with independent attaining adversary/upper bound; pointwise relative-dominance refinement; own-world sparse proposals admitted only by paired lower bound at root",
        samples=dict(previous=len(old),fresh=80,exclusions=len(used)),test="four corners plus independently randomized state/action/edge law; no sample deletion or market claim"))["sha256"]
    entropy=bytes.fromhex(a.entropy) if a.entropy else os.urandom(32);fresh=[]
    for fit in protocol["fit_ids"]:
        for d in ("iid","ood"):
            rng=np.random.default_rng(int(digest(entropy+canonical([seal,fit,d]).encode()),16))
            for j in range(8):
                pub=public_world(rng,protocol["public_domains"][d],protocol["public_domains"]["prior_distances"],f"uncert_{fit}_{d}_{j}")
                key=digest(canonical({k:pub[k] for k in protocol["schedule_fields"]}).encode())
                if key in used:raise ValueError("historical collision")
                used.add(key);fresh.append(dict(fit=fit,domain=d,world=j,schedule=key,public=pub))
    save(out/"WORLDS.json",dict(seal=seal,entropy=entropy.hex(),cases=fresh))
    models={f:read(checked(a.baseline/"neuron/inputs",protocol["fits"][str(f)]["model"])["path"]) for f in protocol["fit_ids"]}
    records=[]
    for population,cases in (("old",old),("fresh",fresh)):
        for case in cases:
            base=models[case["fit"]];pub=case["public"];anchor=head(base)
            g=vg.build(ctx,pub,base,protocol["state_cap"],lambda:None)
            x,_=vg.semantic_inputs(ctx,pub,ctx.NumpyPolicy(base),g["states"],lambda:None);h=vg.strict_hidden(base,x);mask=np.asarray(g["masks"])
            raw=vg.strict_scores(anchor,h)[0];keep=np.where(mask,raw,-np.inf).argmax(1)
            rc=forward(g,keep);bound=min(.25,exact_radius(anchor)["numeric_radius"]/np.sqrt(3))*(1-1e-12)
            shifts,_=select_cell(groups(g,raw),bound,rc,curve);shift=shifts["TASK_BAND"]
            matrix=anchor.copy();matrix[:3,-1]+=shift;m,norm=model_with_head(base,matrix,"Q")
            key=digest(canonical(m).encode());path=out/"models"/(key+".json.gz")
            if not path.exists():save(path,m)
            saved=read(path);assert digest(canonical(saved).encode())==key
            cand=np.where(mask,vg.strict_scores(head(saved),h)[0],-np.inf).argmax(1)
            wire=encode(g,dict(KEEP=keep,EXACT=cand,REVERSE=keep))
            t=time.monotonic();p=subprocess.run([a.binary.resolve(),"--uncertainty","1","3","0.4"],input=wire,capture_output=True,check=True)
            native_wall+=time.monotonic()-t;arms={};meta={}
            for line in p.stdout.decode().splitlines():
                name,lo,hi,lb,vec=line.split();act=np.frombuffer(vec.encode(),np.uint8)-48
                assert len(act)==len(keep) and mask[np.arange(len(act)),act].all()
                arms[name]=act;meta[name]=dict(lo=float(lo),hi=float(hi),lb=float(lb))
            assert set(arms)=={"BASE","PROPOSAL","MAXIMIN","DOMINANT"} and np.array_equal(arms["BASE"],keep) and np.array_equal(arms["PROPOSAL"],cand)
            arms["WEIGHT_APPROVED"]=cand if meta["PROPOSAL"]["lb"]>TOL else keep
            arms["MAXIMIN_APPROVED"]=arms["MAXIMIN"] if meta["MAXIMIN"]["lb"]>TOL else keep
            lower,upper=upper_and_lower_opt(g,arms["MAXIMIN"])
            gap=float(np.max(abs(lower-upper)));err=abs(lower[g["initial"]]-meta["MAXIMIN"]["lo"])
            if gap>1e-9 or err>1e-9:raise ArithmeticError("attaining adversary or robust optimum disagreement")
            max_witness_gap=max(max_witness_gap,gap);max_native_dp_error=max(max_native_dp_error,err)
            rand=np.random.default_rng(int(case["schedule"][:16],16));size=(len(keep),3)
            scenarios={}
            for label,tilt,fee in (("m1minus",-.4,1.),("m1plus",.4,1.),("m3minus",-.4,3.),("m3plus",.4,3.),("nominal",0.,1.),("rect",None,None)):
                twists=rand.uniform(-.4,.4,size) if tilt is None else np.full(size,tilt)
                fees=rand.uniform(1.,3.,(*size,3)) if fee is None else np.full((*size,3),fee)
                law=make_law(g,twists,fees)
                vals={}
                for name,act in arms.items():
                    rew,cost=forward(law,act);vals[name]=float(rew-cost)
                    if name in meta and (vals[name]<meta[name]["lo"]-1e-9 or vals[name]>meta[name]["hi"]+1e-9):
                        raise ArithmeticError("fixed law outside robust value interval")
                for name in meta:
                    miss=meta[name]["lb"]-(vals[name]-vals["BASE"])
                    max_negative_bound_violation=max(max_negative_bound_violation,miss)
                    if miss>1e-9:raise ArithmeticError("paired lower bound violated")
                if min(vals[n]-vals["BASE"] for n in ("DOMINANT","WEIGHT_APPROVED","MAXIMIN_APPROVED")) < -1e-9:raise ArithmeticError("guaranteed policy failed")
                scenarios[label]=vals
            records.append(dict(pop=population,fit=case["fit"],domain=case["domain"],world=case["schedule"],states=len(keep),
                model=key,shift=shift,operator_data=meta,approved_weight=meta["PROPOSAL"]["lb"]>TOL,
                approved_maximin=meta["MAXIMIN"]["lb"]>TOL,saddle_gap=gap,scenarios=scenarios))
    save(out/"ROWS.json",records)
    summary={}
    for pop in ("fresh","old"):
        rows=[r for r in records if r["pop"]==pop]
        outarms={}
        for name in arms:
            deltas=np.array([[v[name]-v["BASE"] for v in r["scenarios"].values()] for r in rows])
            dn=np.array([r["scenarios"]["nominal"][name]-r["scenarios"]["nominal"]["BASE"] for r in rows]);worst=deltas.min(axis=1)
            lb=np.array([r["operator_data"][name]["lb"] for r in rows]) if name in meta else None
            outarms[name]=dict(n=len(dn),nominal=float(dn.mean()),nominal_pos=int((dn>TOL).sum()),nominal_neg=int((dn < -TOL).sum()),
                all_six_strict=int((worst>TOL).sum()),any_negative=int((worst < -TOL).sum()),worst=float(worst.min()),
                strict_all_laws_lower=None if lb is None else int((lb>TOL).sum()))
        summary[pop]=dict(arms=outarms,strict_weight=sum(r["approved_weight"] for r in rows),
               strict_maximin=sum(r["approved_maximin"] for r in rows),n=len(rows))
    save(out/"SUMMARY.json",summary);save(out/"VERIFICATION.json",dict(max_saddle_gap=max_witness_gap,
       max_robust_optimum_error=max_native_dp_error,max_lower_bound_violation=max_negative_bound_violation,
       native_wall_s=native_wall,total_wall_s=time.monotonic()-start,harness_cpu_s=time.process_time()-cpu,
       states=sum(r["states"] for r in records),worlds=len(records),forward_passes=len(records)*6*6))
if __name__=="__main__":
    main()
