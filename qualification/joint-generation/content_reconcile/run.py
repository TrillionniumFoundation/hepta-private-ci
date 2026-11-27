"""One frozen fixed-model TRAIN decoding probe; no optimizer or formal split."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import traceback

import numpy as np
from PIL import Image

from content_control.run import snapshot as previous_sources
from content_reconcile.policy import TAUS, compile_joint, repair
from content_reconcile.scoring import ce_rows, metrics, greedy_metrics
from content_reconcile.service import PROFILES, IDENTITY_ALIASES, execute
from data import prepare_decoded_observer
from independent.accounting import BudgetExceeded, WorkLedger
from independent.evaluation import full_reference_work
from independent.inference import FrozenGenerator
from independent.learning import setup_work
from independent.run import cpu_clock, write_json
from model import JointModel


ROOT=Path(__file__).resolve().parents[1]
PRIOR=ROOT/"runs/content-control-train-r2-20261023"
FAMILIES=("H","A")
SEEDS=(11,23,47)
PROGRESS={}


def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def identity():
    sources=previous_sources()
    for path in sorted((ROOT/"content_reconcile").iterdir()):
        if path.suffix==".py" or path.name in ("PROTOCOL.md","CALLS.json"):
            sources[path.relative_to(ROOT).as_posix()]=sha(path)
    paths=[PRIOR/"build.json",PRIOR/"train-inputs.npz",PRIOR/"train-result.json",ROOT/"content_control/retained-files.json"]
    paths += [PRIOR/f"{family}-{seed}-0.01/model.npz" for family in FAMILIES for seed in SEEDS]
    return {"sources":sources,"inputs":{p.relative_to(ROOT).as_posix():sha(p) for p in paths}}


def make_calls():
    entries=[]
    for si,seed in enumerate(SEEDS):
        families=FAMILIES[si%2:]+FAMILIES[:si%2]
        for family in families:
            fi=FAMILIES.index(family)
            for ti in range(3):
                choices=PROFILES[2*ti:2*ti+2]
                if (si+ti+fi)%2:choices=choices[::-1]
                for profile in choices:
                    pi=next(j for j,p in enumerate(PROFILES) if p==profile)
                    entries.append({"family":family,"model_seed":seed,"profile":profile[0],"tau":profile[1],"form":profile[2],
                        "requests":64,"sampler_seed":1_000_000+fi*100_000+seed+pi*1000,
                        "aliases":list(IDENTITY_ALIASES) if profile[0]=="identity" else []})
    return {"calls":entries,"calls_per_family":18,"requests_per_family":1152,"total_calls":36,"total_requests":2304,
        "explicit_Q_infinity_calls_per_family":3,"identity_calls_per_family":3,"additional_alias_calls":0,
        "quality_rows_per_model":768,"greedy_rows_are_offline_metadata_not_extra_service_requests":True}


def build(out,freeze):
    frozen=json.loads(Path(freeze).read_text())
    if identity()!=frozen["identity"]:raise ValueError("source/input identity changed")
    calls=json.loads((ROOT/"content_reconcile/CALLS.json").read_text())
    if calls!=make_calls():raise ValueError("call plan changed")
    out=Path(out);out.mkdir(parents=True,exist_ok=False)
    Image.preinit()  # Same lazy PNG plugin setup needed by save; no image render.
    old=json.loads((PRIOR/"build.json").read_text())
    old_result=json.loads((PRIOR/"train-result.json").read_text())
    saved_manifest=json.loads((ROOT/"content_control/retained-files.json").read_text())["files"]
    for path,digest in frozen["identity"]["inputs"].items():
        if path in saved_manifest and saved_manifest[path]["sha256"]!=digest:raise ValueError("saved artifact mismatch")
    shared=WorkLedger("probe-shared",250_000_000);PROGRESS["shared"]=shared
    models,generators,observers,model_bindings={},{},{},{}
    with np.load(PRIOR/"train-inputs.npz",allow_pickle=False) as data:
        inner_x=data["inner_full"].copy();labels=data["inner_labels"].copy();fit_x=data["fit_full"].copy()
    take=np.linspace(0,len(fit_x)-1,64,dtype=int)
    runtime_x=fit_x[take]
    model_folder=out/"models";model_folder.mkdir()
    for family in FAMILIES:
        for seed in SEEDS:
            path=PRIOR/f"{family}-{seed}-0.01/model.npz"
            model=JointModel.load(path);models[family,seed]=model
            generators[family,seed]=FrozenGenerator(model,prepare_low=False)
            target=model_folder/f"{family}-{seed}.npz"
            try:os.link(path,target)
            except OSError:shutil.copyfile(path,target)
            shared.record("export",model_bytes_referenced=target.stat().st_size)
            model_bindings[f"{family}-{seed}"]={"file":target.relative_to(out).as_posix(),"sha256":sha(target),"digest":model.digest()}
    reward_contrasts={}
    for seed in SEEDS:
        h,a=models["H",seed],models["A",seed]
        if any(not np.array_equal(h.params[k],a.params[k]) for k in ("decoder","decoder_bias")):
            raise ValueError("H/A decoders differ within model seed")
        shared.charge_kernel("R_recovery","original_observer",**setup_work(h.dimensions,"A"))
        observer=prepare_decoded_observer(h);observers[seed]=observer
        ys,ks=np.where(~np.eye(12,dtype=bool))
        wrong_text=observer.reward[ys,ks,ks]-observer.reward[ys,ys,ks]
        wrong_image=observer.reward[ys,ks,ks]-observer.reward[ys,ks,ys]
        shared.charge_kernel("R_recovery","fixed_reward_contrasts",scalar_ops=2*len(ys),compare_ops=144)
        reward_contrasts[str(seed)]={"wrong_vs_text_only_minmax":[float(wrong_text.min()),float(wrong_text.max())],
            "wrong_vs_image_only_minmax":[float(wrong_image.min()),float(wrong_image.max())]}
        np.savez_compressed(out/f"R-{seed}.npz",reward=observer.reward,text_sem=observer.observations[0],
                            image_sem=observer.observations[1],distances=observer.observations[3],
                            wrong_vs_text_only=wrong_text,wrong_vs_image_only=wrong_image)
        shared.record("R_recovery",serialized_bytes=(out/f"R-{seed}.npz").stat().st_size)
    write_json(out/"behavior.json",{"profile":"code-pair-reconcile-probe-v1","rule":"diagonal-joint-support-v1","rho":1.5,
        "greedy":"original-head-argmax-then-reconcile-v1","decoder":"original-rowwise-PNG","models":model_bindings,"calls":calls})
    common_cpu=cpu_clock()
    ledgers,costs,quality,service_reports={},{},{},{}
    for family in FAMILIES:
        inherited=old["ledgers"][family]["consumed_units"]
        ledger=WorkLedger(family+"-probe",min(12_000_000_000,inherited+250_000_000))
        ledger.record("inherited_nine_candidate_build",units=inherited,inherited_candidates=9)
        ledger.attribute_shared(shared)
        ledgers[family]=ledger;PROGRESS[family]=ledger
        costs[family]={"inherited_CPU":old["costs"][family]["complete_cpu"],"new_common_CPU":common_cpu,"active_CPU":0.}
        quality[family]={};service_reports[family]=[]

    def guard(family):
        cost=costs[family]
        if cost["new_common_CPU"]+cost["active_CPU"]>3 or sum(cost.values())>10:
            raise RuntimeError(family+" added/complete CPU cap exceeded")

    status=0;partial={};runtime_done=[]
    try:
        for family in FAMILIES:guard(family)
        for si,seed in enumerate(SEEDS):
            for family in FAMILIES[si%2:]+FAMILIES[:si%2]:
                start=cpu_clock();ledger=ledgers[family];generator=generators[family,seed];observer=observers[seed]
                key=f"{family}-{seed}"
                try:
                    envelope=75_000*len(inner_x)
                    if envelope>ledger.remaining_units:raise BudgetExceeded("complete offline-law phase cannot fit")
                    unit_before=ledger.consumed_units
                    p,q=generator.forward_full(inner_x,ledger)
                    original_greedy=np.column_stack((p.argmax(1),q.argmax(1)))
                    ledger.charge_kernel("greedy","original_argmax",compare_ops=22*len(p))
                    np.savez_compressed(out/f"heads-{key}.npz",p=p,q=q,original_greedy=original_greedy)
                    ledger.record("capture",serialized_bytes=(out/f"heads-{key}.npz").stat().st_size)
                    reward=observer.reward[labels]
                    arrays={};summaries={}
                    for tau in TAUS:
                        joint,original,dest,actions=compile_joint(p,q,tau,ledger,"quality_Q")
                        scored=metrics(joint,reward,labels,observer,ledger,"quality_observation")
                        for action,name in ((0,"KEEP"),(1,"TRUST_TEXT"),(2,"TRUST_IMAGE")):
                            scored["action_"+name+"_mass"]=np.sum(original.reshape(len(p),144)*(actions==action),axis=1)
                        ledger.charge_kernel("quality_observation","action_mass",scalar_ops=6*len(p)*144-3*len(p),compare_ops=3*len(p)*144)
                        if tau!="infinity":
                            path_reward=np.take_along_axis(reward.reshape(len(p),144),dest,axis=1)
                            path_ce,path_raw=ce_rows(path_reward,original.reshape(len(p),144),ledger,"path_CE_parity")
                            successes=((observer.observations[0][None,:,None]==labels[:,None,None])
                                &(observer.observations[1][None,None,:]==labels[:,None,None])).reshape(len(p),144)
                            path_joint=np.sum(original.reshape(len(p),144)*np.take_along_axis(successes,dest,axis=1),axis=1)
                            ledger.charge_kernel("path_CE_parity","path_success",scalar_ops=2*len(p)*144-len(p),compare_ops=24*len(p))
                            repaired_greedy,greedy_action=repair(p,q,original_greedy,tau,ledger,"greedy_repair")
                        else:
                            path_ce=scored["ce"];path_joint=scored["joint_success"];path_raw=scored["raw_reward"]
                            repaired_greedy=original_greedy;greedy_action=np.zeros(len(p),dtype=np.int8)
                        parity={"max_CE_error":float(np.max(np.abs(path_ce-scored["ce"]))),
                            "max_joint_error":float(np.max(np.abs(path_joint-scored["joint_success"]))),
                            "max_raw_reward_error":float(np.max(np.abs(path_raw-scored["raw_reward"]))),
                            "max_mass_error":float(np.max(np.abs(joint.sum((1,2))-1)))}
                        if max(parity.values())>1e-12:raise RuntimeError("static/two-stage exact-law mismatch")
                        greedy_result=greedy_metrics(repaired_greedy,labels,observer,ledger,"greedy_observation")
                        arrays[tau+"/Q"]=joint
                        arrays[tau+"/destination"]=dest
                        arrays[tau+"/action_map"]=actions
                        arrays[tau+"/greedy_pair"]=repaired_greedy
                        arrays[tau+"/greedy_action"]=greedy_action
                        arrays.update({tau+"/"+name:value for name,value in scored.items()})
                        arrays[tau+"/path_ce"]=path_ce
                        arrays[tau+"/path_joint_success"]=path_joint
                        arrays[tau+"/path_raw_reward"]=path_raw
                        arrays[tau+"/greedy_joint_success"]=greedy_result["joint_success"]
                        arrays.update({tau+"/greedy_"+name:value for name,value in greedy_result.items() if name!="joint_success"})
                        summaries[tau]={"means":{name:float(value.mean()) for name,value in scored.items()},
                            "greedy_joint_success":float(greedy_result["joint_success"].mean()),"parity":parity}
                    legacy=old_result["per_row"][family][SEEDS.index(seed)]
                    for current,previous in (("infinity/raw_reward","task_utility"),("infinity/joint_success","joint_success"),
                                             ("infinity/greedy_joint_success","greedy_joint_success")):
                        if not np.allclose(arrays[current],legacy[previous],rtol=0,atol=1e-12):raise RuntimeError("identity differs from saved TRAIN endpoints")
                    if not np.allclose(1-arrays["infinity/semantic_disagreement"],legacy["consistency"],rtol=0,atol=1e-12):
                        raise RuntimeError("identity consistency differs from saved TRAIN endpoints")
                    np.savez_compressed(out/f"quality-{key}.npz",**arrays)
                    ledger.record("quality_export",serialized_bytes=(out/f"quality-{key}.npz").stat().st_size)
                    quality[family][str(seed)]=summaries
                    if ledger.consumed_units-unit_before>envelope:raise RuntimeError("offline-law inventory exceeds its admission envelope")
                finally:costs[family]["active_CPU"]+=cpu_clock()-start
                guard(family)
        for call in calls["calls"]:
            family,seed=call["family"],call["model_seed"]
            start=cpu_clock();ledger=ledgers[family]
            try:
                profile=next(p for p in PROFILES if p[0]==call["profile"])
                envelope=64*2*full_reference_work(generators[family,seed])
                if envelope>ledger.remaining_units:raise BudgetExceeded("complete runtime batch cannot fit")
                report=execute(generators[family,seed],runtime_x,profile,call["sampler_seed"])
                report.update(family=family,model_seed=seed)
                # Preserve actual batch kernels in the family ledger; validate cap
                # before the work is attributed, never duplicate identity aliases.
                ledger.record("actual_service",units=report["work_units"],service_requests=report["rows"],service_calls=1,
                              png_renders=report["rows"])
                write_json(out/f"service-{family}-{seed}-{profile[0]}.json",report)
                service_reports[family].append({k:v for k,v in report.items() if k not in ("outputs","original_pairs","actions","final_pairs","ledger")})
                runtime_done.append(call)
            finally:costs[family]["active_CPU"]+=cpu_clock()-start
            guard(family)
        scheduler=max(0.,cpu_clock()-common_cpu-sum(c["active_CPU"] for c in costs.values()))
        for family in FAMILIES:
            costs[family]["scheduler_CPU"]=scheduler
            costs[family]["added_CPU"]=common_cpu+costs[family]["active_CPU"]+scheduler
            costs[family]["complete_CPU"]=costs[family]["inherited_CPU"]+costs[family]["added_CPU"]
            if costs[family]["added_CPU"]>3 or costs[family]["complete_CPU"]>10:raise RuntimeError("final added/complete CPU cap exceeded")
            if sum(r["rows"] for r in service_reports[family])!=1152:raise RuntimeError("1152-request plan not completed")
        write_json(out/"quality-summary.json",quality)
    except Exception:
        status=1;partial={"traceback":traceback.format_exc()}
        write_json(out/"failure.json",partial)
    receipt={"execution_exit_code":status,"costs":costs,"ledgers":{f:l.snapshot() for f,l in ledgers.items()},
        "shared_ledger":shared.snapshot(),"quality":quality,"service":service_reports,"calls_completed":runtime_done,
        "fixed_reward_contrasts":reward_contrasts,
        "identity":frozen["identity"],"freeze_sha256":sha(freeze),"actual_new_CPU_before_receipt":cpu_clock(),
        "scope":"fixed-model TRAIN joint decoding, not training/dynamic-system confirmation","formal_data_opened":False,
        "limits":{"added_CPU":3,"added_units":250_000_000,"complete_CPU":10,"complete_units":12_000_000_000},
        "environment":{"cwd":os.getcwd(),"numpy":np.__version__,"host":os.uname().nodename,
            "threads":{k:os.getenv(k) for k in ("OPENBLAS_NUM_THREADS","OMP_NUM_THREADS","MKL_NUM_THREADS")}},
        "administration":"final lossless result archival and later descriptive summaries recorded separately; no budget credits",
        "unpriced_primitives":"validation/memory/IO/hash/PNG/JSON and exact-integer operand complexity use actual CPU and byte/call counters"}
    write_json(out/"build.json",receipt)
    print(json.dumps({"exit_code":status,"costs":costs,"calls_completed":len(runtime_done)}))
    return status


if __name__=="__main__":
    parser=argparse.ArgumentParser();parser.add_argument("action",choices=("plan","freeze","run"))
    parser.add_argument("--out",required=True);parser.add_argument("--freeze")
    args=parser.parse_args()
    if args.action=="plan":write_json(args.out,make_calls())
    elif args.action=="freeze":
        write_json(args.out,{"identity":identity(),"source_commit":subprocess.check_output(["git","rev-parse","HEAD"],text=True).strip()})
    else:
        try:code=build(args.out,args.freeze)
        except Exception:
            if Path(args.out).is_dir():write_json(Path(args.out)/"startup-failure.json",{"traceback":traceback.format_exc(),
                "actual_CPU":cpu_clock(),"partial_ledgers":{k:v.snapshot() for k,v in PROGRESS.items()}})
            raise
        raise SystemExit(code)
