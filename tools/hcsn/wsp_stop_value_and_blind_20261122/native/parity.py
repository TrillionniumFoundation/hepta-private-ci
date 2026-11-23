"""Run the native worker against every action and payoff in the prospective veto study."""
import argparse
import subprocess
import sys
import time
from pathlib import Path

import numpy as np


def encode(graph, policies):
    states=graph["states"]
    lines=[f"HEPTA_DAG_V1 {len(states)} {graph['initial']}"]
    for i,st in enumerate(states):
        mask=sum((1<<a) for a,ok in enumerate(graph["masks"][i]) if ok)
        term=graph["terminal"][i]
        row=[st["tick"],mask,*[float(term[a]) for a in (0,4,5)],*[int(policies[a][i]) for a in ("KEEP","EXACT","REVERSE")]]
        for branches in graph["edges"][i]:
            row.append(len(branches))
            for p,j,fee in branches:
                row.extend([float(p),int(j),float(fee)])
        lines.append(" ".join(map(str,row)))
    return ("\n".join(lines)+"\n").encode()


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("archive",type=Path)
    ap.add_argument("study",type=Path)
    ap.add_argument("veto",type=Path)
    ap.add_argument("binary",type=Path)
    ap.add_argument("output",type=Path)
    ap.add_argument("--rustc",default="rustc")
    args=ap.parse_args()
    root=args.archive.resolve()
    binary=args.binary.resolve()
    sys.path.insert(0,str(root/"neuron"))
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
    from experiment import vg,canonical,digest,head,model_with_head,checked,context,read,save,pin
    from advantage_veto import guarded
    begin=time.monotonic()
    p=read(root/"neuron/pinned/PROTOCOL_FROZEN.json")
    ctx=context(p)
    fits=read(args.study/"FITS.json")
    cases=read(args.veto/"WORLDS.json")["cases"]
    prior=read(args.veto/"ROWS.json")
    if len(cases)!=80 or len(prior)!=80:
        raise ValueError("complete original 80 worlds required")
    models={}
    for fit in p["fit_ids"]:
        base=read(checked(root/"neuron/inputs",p["fits"][str(fit)]["model"])["path"])
        mm={"KEEP":base}
        for arm in ("EXACT","REVERSE"):
            rows=head(base).copy()
            rows[:3,48]+=fits[str(fit)]["shifts"][arm]
            mm[arm]=model_with_head(base,rows,"Q")[0]
        if any(digest(canonical(m).encode())!=fits[str(fit)]["models"][a] for a,m in mm.items()):
            raise ValueError("mismatched candidate")
        models[fit]=mm
    seen=set()
    comparisons=0
    action_decisions=0
    branch_counts={}
    max_difference=0.
    native_time=0.
    records=[]
    for case,archived in zip(cases,prior,strict=True):
        key=case["schedule"]
        if key!=archived["schedule"] or key in seen:
            raise ValueError("schedule identity")
        seen.add(key)
        fit=case["fit"];pub=case["public"];base=models[fit]["KEEP"]
        graph=vg.build(ctx,pub,base,p["state_cap"],lambda:None)
        x,_=vg.semantic_inputs(ctx,pub,ctx.NumpyPolicy(base),graph["states"],lambda:None)
        h=vg.strict_hidden(base,x)
        mask=np.asarray(graph["masks"])
        actors={a:np.where(mask,vg.strict_scores(head(m),h)[0],-np.inf).argmax(1) for a,m in models[fit].items()}
        reference=guarded(mask,np.asarray(graph["terminal"]),graph["edges"],graph["order"],
                          np.array([s["tick"] for s in graph["states"]]),actors["KEEP"],actors)
        for row in graph["edges"]:
            for group in row:
                branch_counts[str(len(group))]=branch_counts.get(str(len(group)),0)+1
        wire=encode(graph,actors)
        native_start=time.monotonic()
        process=subprocess.run([str(binary)],input=wire,stdout=subprocess.PIPE,stderr=subprocess.PIPE,check=True,timeout=20)
        native_time+=time.monotonic()-native_start
        returned=set()
        for line in process.stdout.decode().splitlines():
            name,value,actions=line.split()
            if name not in reference or name in returned or len(actions)!=len(h):
                raise ValueError("native result identity")
            returned.add(name)
            observed=np.frombuffer(actions.encode("ascii"),dtype=np.uint8)-ord("0")
            if not np.array_equal(observed,reference[name]):
                raise ValueError(f"action mismatch {name}, world {key}")
            difference=abs(float(value)-archived["arms"][name]["value"])
            if not np.isfinite(difference) or difference>1e-9:
                raise ValueError("native payoff mismatch")
            max_difference=max(max_difference,difference)
            action_decisions+=len(observed)
            comparisons+=1
        if returned!=set(reference):
            raise ValueError("missing native arm")
        records.append(dict(schedule=key,input_sha256=digest(wire),output_sha256=digest(process.stdout),
                            states=len(h),arms=len(returned)))
    save(args.output,dict(compiler=subprocess.check_output([args.rustc,"--version"],text=True).strip(),
         rust_src_sha256=pin(Path(__file__).with_name("advantage_veto.rs"))["sha256"],
         native_binary_sha256=pin(binary)["sha256"],harness_sha256=pin(__file__)["sha256"],
         studies=dict(veto_rows=pin(args.veto/"ROWS.json")["sha256"],veto_worlds=pin(args.veto/"WORLDS.json")["sha256"]),
         worlds=len(records),states=sum(r["states"] for r in records),arm_world_values=comparisons,
         checked_actions=action_decisions,branch_counts=branch_counts,max_payoff_error=max_difference,
         native_wall_including_IPC=native_time,total_wall=time.monotonic()-begin,records=records,
         scope="research DAG/control policy ABI, independently implemented native backups on shared input laws and actor proposals"))
if __name__=="__main__":
    main()
