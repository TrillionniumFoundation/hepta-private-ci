"""Uncapped 20 s with joint wall and early-update validation; disjoint test windows."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ARMS = ("qvi_raw","qvi_centered","qvi_signed","qvi_joint","learned_centered",
        "fixed_centered","gru","lif","attention")
SEEDS=(601,1601,2601)
BUDGET=20.0


def fit(args):
    import torch
    import run
    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
    root=args.output/f"{args.arm}-{args.seed}"
    root.mkdir(exist_ok=False)
    data=run.load_data(args.data,["train","dev"])
    torch.manual_seed(args.seed)
    model=run.model_for(args.arm)
    gen=torch.Generator().manual_seed(11*args.seed)
    optimizer=torch.optim.Adam(model.parameters(),lr=.003)
    x,y,_,_=data["train"]
    selected=None
    selected_step=None
    best=float("inf")
    checkpoints=[]
    start=time.perf_counter()
    next_validation=0
    current=0
    schedules=(0.,3.,7.,12.,16.)
    early_steps={0,8,16,32,64,96,128}
    seen_steps=set()
    while time.perf_counter()-start < BUDGET:
        wall_due=next_validation<len(schedules) and time.perf_counter()-start>=schedules[next_validation]
        early_due=current in early_steps and current not in seen_steps
        if wall_due or early_due:
            seen_steps.add(current)
            report,_=run.evaluate(model,data["dev"])
            candidate={k:v.detach().cpu().clone() for k,v in model.state_dict().items()}
            elapsed=time.perf_counter()-start
            eligible=elapsed<=BUDGET
            checkpoints.append({"step":current,"seconds":elapsed,"brier":report["brier"],"eligible":eligible,"initial_step_schedule":early_due,"wall_schedule":wall_due})
            if eligible and report["brier"]<best:
                best=report["brier"];selected=candidate;selected_step=current
            while next_validation < len(schedules) and schedules[next_validation]<=elapsed:
                next_validation+=1
            continue
        model.train()
        rows=torch.randperm(len(y),generator=gen)[:12]
        optimizer.zero_grad(set_to_none=True)
        loss=torch.nn.functional.cross_entropy(model(x[:,rows])[-1],y[rows])
        loss.backward()
        norm=torch.nn.utils.clip_grad_norm_(model.parameters(),2.)
        if not torch.isfinite(loss) or not torch.isfinite(norm):
            raise ValueError("nonfinite training")
        optimizer.step()
        current+=1
    actual=time.perf_counter()-start
    if selected is not None:
        torch.save(selected,root/"selected.pt")
    run.write_new(root/"fit.json",dict(arm=args.arm,seed=args.seed,attempted_updates=current,
        elapsed_s=actual,selected_step=selected_step,validation=checkpoints,
        checkpoint_sha256=run.sha(root/"selected.pt") if selected is not None else None))


def launch(args):
    from datetime import datetime, timezone
    root=args.output
    root.mkdir(parents=True,exist_ok=False)
    script=Path(__file__).resolve()
    dig=lambda f:hashlib.sha256(f.read_bytes()).hexdigest()
    files=[script,script.with_name("run.py"),script.with_name("wallplus_protocol.md"),script.with_name("windows_plus.py")]
    slots=[(a,s) for s in SEEDS for a in ARMS]
    registration={"sources":{f.name:dig(f) for f in files},"slots":slots,
                  "utc":datetime.now(timezone.utc).isoformat(),"workers":args.workers,"budget_s":BUDGET}
    (root/"registration.json").write_text(json.dumps(registration,indent=2))
    cpus=sorted(os.sched_getaffinity(0))
    def work(lane):
        # Alternate physical IDs relative to the earlier separately scheduled campaign.
        core=cpus[-1-lane]
        for arm,seed in slots[lane::args.workers]:
            cmd=["taskset","-c",str(core),sys.executable,str(script),"fit","--data",str(args.data),
                 "--output",str(root),"--arm",arm,"--seed",str(seed)]
            start=time.perf_counter()
            with (root/f"{arm}-{seed}.log").open("x") as log:
                p=subprocess.run(cmd,stdout=log,stderr=subprocess.STDOUT)
            rc={"arm":arm,"seed":seed,"exit":p.returncode,"affinity_cpu":core,
                "launch_to_exit_s":time.perf_counter()-start}
            (root/f"{arm}-{seed}.receipt.json").write_text(json.dumps(rc))
            print(rc,flush=True)
            if p.returncode:raise ValueError("failed slot")
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        list(pool.map(work,range(args.workers)))
    if registration["sources"]!={f.name:dig(f) for f in files}:
        raise ValueError("executable source changed")
    sealed={}
    for arm,seed in slots:
        d=root/f"{arm}-{seed}"
        meta=json.loads((d/"fit.json").read_text())
        sig=meta["checkpoint_sha256"]
        if sig is not None and dig(d/"selected.pt")!=sig: raise ValueError("checkpoint changed")
        sealed[d.name]={"model":sig,"fit":dig(d/"fit.json")}
    (root/"seal.json").write_text(json.dumps(sealed,sort_keys=True,indent=2))
    import run
    import torch
    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
    from windows_plus import disjoint_test
    test=disjoint_test(args.data)
    scores={};predictions={}
    for arm,seed in slots:
        d=root/f"{arm}-{seed}"
        if not sealed[d.name]["model"]:
            scores[d.name]=None
            continue
        model=run.model_for(arm)
        model.load_state_dict(torch.load(d/"selected.pt",weights_only=True))
        scores[d.name],predictions[d.name]=run.evaluate(model,test)
    run.write_new(root/"test.json",scores)
    run.write_new(root/"predictions.json",predictions)
    print("ALL_COMPLETE",flush=True)


if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("mode",choices=["fit","launch"])
    p.add_argument("--data",type=Path,required=True);p.add_argument("--output",type=Path,required=True)
    p.add_argument("--arm",choices=ARMS);p.add_argument("--seed",type=int,choices=SEEDS)
    p.add_argument("--workers",type=int,default=4)
    args=p.parse_args()
    fit(args) if args.mode=="fit" else launch(args)
