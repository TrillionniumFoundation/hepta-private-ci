"""One frozen four-group TRAIN build, reusing bound bases/data without generators."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import traceback

import numpy as np

from content_block.evidence import Evidence
from content_block.learning import BlockAdam, compile_library, heads_step, heads_work
from content_control.run import observe, service, snapshot as prior_sources
from data import prepare_decoded_observer, render
from independent.accounting import WorkLedger
from independent.learning import CachedObjective, CONTENT_PARAMETERS, setup_work, step_work
from independent.native_adam import setup_work as optimizer_setup
from independent.run import cpu_clock, save_model, write_json
from model import JointModel


ROOT=Path(__file__).resolve().parents[1]
PRIOR=ROOT/"runs/content-control-train-r2-20261023"
GROUPS=("H_joint","A_joint","H_alt","A_alt")
SEEDS,LRS=(11,23,47),(.001,.003,.01)
CAP=12_000_000_000
PROGRESS={}


def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def identity():
    sources=prior_sources()
    for p in sorted((ROOT/"content_block").iterdir()):
        if p.suffix in (".py",".c") or p.name=="PROTOCOL.md":
            sources[p.relative_to(ROOT).as_posix()]=sha(p)
    files=[PRIOR/"build.json",PRIOR/"train-inputs.npz",PRIOR/"train-result.json"]
    files += [PRIOR/f"base-{s}.npz" for s in SEEDS]
    files += [ROOT/"content_control/retained-files.json"]
    return {"sources":sources,"inputs":{p.relative_to(ROOT).as_posix():sha(p) for p in files}}


def build(out,freeze):
    frozen=json.loads(Path(freeze).read_text())
    if frozen["identity"]!=identity(): raise ValueError("frozen identity changed")
    out=Path(out)
    out.mkdir(parents=True,exist_ok=False)
    old=json.loads((PRIOR/"build.json").read_text())
    manifest=json.loads((ROOT/"content_control/retained-files.json").read_text())["files"]
    for path,digest in frozen["identity"]["inputs"].items():
        if path in manifest and manifest[path]["sha256"]!=digest:
            raise ValueError("prior saved artifact does not match its retained manifest")
    shared=WorkLedger("shared-block",CAP)
    PROGRESS["shared"]=shared
    shared.record("inherited_preparation",units=old["shared_ledger"]["consumed_units"],inherited_builds=1)
    compiled=compile_library(out/"build/adam.so")
    shared.record("masked_compile",compiler_invocations=1)
    with np.load(PRIOR/"train-inputs.npz",allow_pickle=False) as data:
        fit={"full":data["fit_full"].copy(),"labels":data["fit_labels"].copy()}
        inner={"full":data["inner_full"].copy(),"labels":data["inner_labels"].copy()}
    bases,observers={},{}
    for seed in SEEDS:
        bases[seed]=JointModel.load(PRIOR/f"base-{seed}.npz")
        shared.charge_kernel("observer_setup","decoded_observer",**setup_work(bases[seed].dimensions,"A"))
        observers[seed]=prepare_decoded_observer(bases[seed])
    calibration_out=out/"calibration"
    calibration_out.mkdir()
    take=np.linspace(0,len(fit["full"])-1,64,dtype=int)
    _,_,calibration=service(bases[11],bases[11],{"full":fit["full"][take]},"full",shared,calibration_out,11)
    actual_shared_cpu=cpu_clock()
    inherited_cpu=old["common_cpu"]
    shared_cpu=inherited_cpu+actual_shared_cpu
    ledgers,costs,candidates,models={},{},{},{}
    for group in GROUPS:
        ledger=WorkLedger(group,CAP)
        ledger.attribute_shared(shared)
        ledgers[group]=ledger
        PROGRESS[group]=ledger
        costs[group]={"shared_cpu":shared_cpu,"active_cpu":0.}
        candidates[group]=[]
    selected,reports,raw={},{},{}
    status=0
    try:
        if shared_cpu>10: raise RuntimeError("shared complete CPU cap exceeded")
        for ri,(seed,li) in enumerate((s,j) for s in SEEDS for j in range(3)):
            for group in GROUPS[ri%4:]+GROUPS[:ri%4]:
                begin,ledger=cpu_clock(),ledgers[group]
                model=bases[seed].clone()
                initial={k:model.params[k].copy() for k in CONTENT_PARAMETERS}
                ledger.charge_kernel("optimizer_setup","masked_adam_bind",**optimizer_setup(model))
                optimizer=BlockAdam(model,compiled["library"])
                evidence=Evidence(optimizer,ledger)
                objective=CachedObjective(group[0],model,ledger=ledger,optimizer=evidence)
                joint_work=step_work(model.dimensions,group[0],64)
                head_work=heads_work(model.dimensions,group[0],64)
                alternate=group.endswith("_alt")
                pair_units=ledger.estimate_kernel(**joint_work)+ledger.estimate_kernel(**(head_work if alternate else joint_work))
                quota_units=(CAP-shared.consumed_units-500_000_000)//9
                quota_cpu=(10-shared_cpu-2)/9
                rng=np.random.default_rng(seed+10000+li)
                start,unit_start=cpu_clock(),ledger.consumed_units
                losses=[]
                while (cpu_clock()-start<quota_cpu-.01
                       and ledger.consumed_units-unit_start+pair_units+2*sum(v.size for v in initial.values())<=quota_units):
                    for position in range(2):
                        idx=rng.integers(len(fit["labels"]),size=64)
                        x,y=fit["full"][idx],fit["labels"][idx]
                        if alternate and position==1:
                            loss=heads_step(objective,model,x,y,LRS[li],ledger)
                        else:
                            loss=objective.step(model,x,y,LRS[li],ledger=ledger)
                            ledger.record("search_train",joint_steps=1,encoder_updates=1,head_updates=1)
                        losses.append(loss)
                if not losses: raise RuntimeError("no affordable complete update pair")
                train_cpu,train_units=cpu_clock()-start,ledger.consumed_units-unit_start
                clocks={k:model._moments[k][2] for k in CONTENT_PARAMETERS}
                expected={k:len(losses)//2 if alternate and k in CONTENT_PARAMETERS[:2] else len(losses) for k in CONTENT_PARAMETERS}
                if clocks!=expected: raise RuntimeError("per-parameter clocks disagree with executed schedule")
                ledger.model_forward("search_validation",rows=len(inner["labels"]),input_dim=202,hidden=32,classes=12)
                p,q=model.forward(inner["full"])
                metrics=observe(p,q,inner["labels"],observers[seed],ledger,"search_validation")
                name=f"{group}-{seed}-{LRS[li]}"
                folder=out/name
                folder.mkdir()
                np.savez_compressed(folder/"validation.npz",**metrics)
                ledger.record("search_validation",serialized_bytes=(folder/"validation.npz").stat().st_size)
                artifact=save_model(model,folder/"model.npz",ledger,"candidate_export")
                evidence.save(folder/"updates-and-moments.npz",model,initial,losses)
                row={"name":name,"seed":seed,"lr":LRS[li],"updates":len(losses),"update_types":evidence.counts,
                    "clocks":clocks,"first_head_skip":evidence.skip,"validation":{k:float(v.mean()) for k,v in metrics.items()},
                    "training_cpu":train_cpu,"training_units":train_units,"pair_units":pair_units,
                    "quota_units":quota_units,"quota_cpu":quota_cpu,"artifact":artifact}
                candidates[group].append(row)
                models[name]=model
                write_json(folder/"candidate.json",row)
                costs[group]["active_cpu"]+=cpu_clock()-begin
                if shared_cpu+costs[group]["active_cpu"]>10: raise RuntimeError(group+" complete CPU cap exceeded")
        for group in GROUPS:
            lr=max(LRS,key=lambda rate:np.mean([r["validation"]["task_utility"] for r in candidates[group] if r["lr"]==rate]))
            selected[group]={"lr":lr,"path":"full"}
            reports[group],raw[group]=[],[]
        for si,seed in enumerate(SEEDS):
            for group in GROUPS[si:]+GROUPS[:si]:
                begin,ledger=cpu_clock(),ledgers[group]
                name=f"{group}-{seed}-{selected[group]['lr']}"
                model,base,folder=models[name],bases[seed],out/name
                p,q,served=service(model,base,inner,"full",ledger,folder,seed)
                metrics=observe(p,q,inner["labels"],observers[seed],ledger,"selected_observation")
                bad=base.clone()
                bad.params["decoder"]=np.roll(bad.params["decoder"],1,axis=0)
                ledger.charge_kernel("negative_control","observer",**setup_work(bad.dimensions,"A"))
                corrupted=observe(p,q,inner["labels"],prepare_decoded_observer(bad),ledger,"negative_control")
                loaded=JointModel.load(folder/"model.npz")
                x=np.concatenate((np.clip(.02+.91*render(9),0,1).reshape(-1),np.eye(4)[1],np.eye(3)[1],np.eye(3)[2]))[None,:]
                hp,hq,external=service(loaded,loaded,{"full":x},"full",ledger,folder,seed,external=True)
                ledger.model_forward("reload_check",rows=1,input_dim=202,hidden=32,classes=12)
                pp,qq=model.forward(x)
                if not np.array_equal(hp,pp) or not np.array_equal(hq,qq): raise RuntimeError("reload mismatch")
                reports[group].append({"seed":seed,"service":served,"external":external,"reload_exact":True,
                    "means":{k:float(v.mean()) for k,v in metrics.items()},
                    "decoder_corruption_drop":float((metrics["task_utility"]-corrupted["task_utility"]).mean())})
                raw[group].append({k:v.tolist() for k,v in metrics.items()})
                costs[group]["active_cpu"]+=cpu_clock()-begin
        scheduler=max(0.,cpu_clock()-actual_shared_cpu-sum(c["active_cpu"] for c in costs.values()))
        for group in GROUPS:
            costs[group]["scheduler_cpu"]=scheduler
            costs[group]["complete_cpu"]=shared_cpu+costs[group]["active_cpu"]+scheduler
            if costs[group]["complete_cpu"]>10: raise RuntimeError(group+" complete CPU cap exceeded at tail")
        write_json(out/"train-result.json",{"scope":"TRAIN exploratory only","selected":selected,"reports":reports,"per_row":raw})
    except Exception:
        status=1
        write_json(out/"failure.json",{"traceback":traceback.format_exc(),"exit_code":status})
    receipt={"execution_exit_code":status,"freeze_sha256":sha(freeze),"identity":frozen["identity"],
        "prior_build_sha256":sha(PRIOR/"build.json"),"inherited_shared_snapshot":old["shared_ledger"],
        "inherited_shared_cpu":inherited_cpu,"new_actual_shared_cpu":actual_shared_cpu,
        "complete_shared_cpu":shared_cpu,"shared_ledger":shared.snapshot(),"compiler":compiled,
        "costs":costs,"ledgers":{g:l.snapshot() for g,l in ledgers.items()},"candidates":candidates,
        "inner_rows_source_ids":old["inner_rows_source_ids"],"fit_source_ids":old["fit_source_ids"],
        "inner_source_ids":old["inner_source_ids"],"calibration":calibration,
        "actual_new_build_cpu_before_receipt":cpu_clock(),"formal_test_opened":False,
        "environment":{"cwd":os.getcwd(),"hostname":platform.node(),"python":platform.python_version(),
            "numpy":np.__version__,"threads":{k:os.getenv(k) for k in ("OPENBLAS_NUM_THREADS","OMP_NUM_THREADS","MKL_NUM_THREADS")}},
        "unpriced_primitives":"allocation/copy,IO/hash/PNG/JSON and checks outside kernels; actual CPU includes them",
        "administration":"final lossless JSON archival/descriptive analysis reported separately, never budget credits"}
    write_json(out/"build.json",receipt)
    print(json.dumps({"exit_code":status,"costs":costs,"out":str(out)}))
    return status


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("action",choices=("freeze","train"))
    parser.add_argument("--out",required=True)
    parser.add_argument("--freeze")
    args=parser.parse_args()
    if args.action=="freeze":
        write_json(args.out,{"identity":identity(),"source_commit":subprocess.check_output(["git","rev-parse","HEAD"],text=True).strip(),"scope":"TRAIN only"})
    else:
        try: code=build(args.out,args.freeze)
        except Exception:
            if Path(args.out).is_dir():
                write_json(Path(args.out)/"early-failure.json",{"traceback":traceback.format_exc(),"cpu_seconds":cpu_clock(),
                    "partial_ledgers":{k:v.snapshot() for k,v in PROGRESS.items()}})
            raise
        raise SystemExit(code)
