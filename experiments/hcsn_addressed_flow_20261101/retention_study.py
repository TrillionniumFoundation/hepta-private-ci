"""Version-one-informed retention repair with a new prospective confirmation.

Original negative evidence is immutable. Same-checkpoint interventions below
are explicitly development diagnostics; formal results require fresh training,
remote source freeze, all-checkpoint freeze and previously unused seed73117.
"""

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
import hashlib
import json
import multiprocessing
from pathlib import Path
import resource
import time
import traceback

import numpy as np
import torch
from torch.nn import functional as F

from . import data, study, typed_retention
from .analyze import bootstrap


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
CORES = ("flow", "diagonal")
SEEDS = (17, 29, 43)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text())


def write(path, value):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with Path(path).open("x") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False); stream.write("\n")


def sources():
    result = study.source_hashes()
    for name in ("typed_retention.py", "retention_study.py", "analyze.py", "STATISTICAL_PLAN.json"):
        result[str((HERE / name).relative_to(ROOT))] = digest(HERE / name)
    return result


def new_model(task, core, seed):
    return typed_retention.install(study.new_model(task, "addressed_" + core, seed))


def diagnostic(run, out):
    """DEV only; original checkpoints never updated or selected by these scores."""
    directory = out / "diagnostic001"; directory.mkdir(parents=True, exist_ok=False)
    source = sources(); wall, cpu = time.perf_counter(), time.process_time()
    candidates = study.fit_records(run); rows = []
    for task in data.CONTENT_TASKS:
        for core in CORES:
            record = next(r for r in candidates if (r["task"],r["arm"],r["seed"]) == (task,"addressed_"+core,17))
            checkpoint = run / record["checkpoint"]
            if digest(checkpoint) != record["checkpoint_sha256"]: raise ValueError("Original checkpoint changed")
            original = study.new_model(task,"addressed_"+core,17).eval()
            original.load_state_dict(torch.load(checkpoint,weights_only=True,map_location="cpu"))
            typed = study.new_model(task,"addressed_"+core,17).eval()
            typed.load_state_dict(original.state_dict()); typed_retention.install(typed)
            original_control, typed_control = [], []
            h1 = original.control.register_forward_hook(lambda m,i,o: original_control.append(o.detach().clone()))
            h2 = typed.control.register_forward_hook(lambda m,i,o: typed_control.append(o.detach().clone()))
            for condition in ("base","long_tokens_128","matched_silence_128","resample"):
                arrays = data.batch(task,256,912217,"dev",condition)
                before, after = study.predict(original,arrays), study.predict(typed,arrays)
                mask = arrays["y"] >= 0
                old = (before.argmax(-1)[mask] == arrays["y"][mask]).reshape(256,4)
                new = (after.argmax(-1)[mask] == arrays["y"][mask]).reshape(256,4)
                file = directory / f"{task}_{core}_{condition}.npz"
                np.savez_compressed(file,before=before[mask],after=after[mask],labels=arrays["y"][mask])
                rows.append(dict(task=task,core=core,condition=condition,seed=17,
                    before_accuracy=float(old.mean()),before_all4=float(old.all(-1).mean()),
                    after_accuracy=float(new.mean()),after_all4=float(new.all(-1).mean()),
                    checkpoint_sha256=record["checkpoint_sha256"],raw_sha256=digest(file)))
            if len(original_control) != len(typed_control) or any(not torch.equal(a,b) for a,b in zip(original_control,typed_control)):
                raise AssertionError("Typed mask changed physical policy inputs")
            h1.remove();h2.remove()
            gates = typed.roles(torch.eye(4)).sigmoid().detach().numpy()
            if np.any(gates[[1,2,3],0] != 0) or np.any(gates[[0,1,2],1] != 0):
                raise AssertionError("Ineligible event wrote memory")
    report = dict(scope="Post-hoc DEV diagnosis; not independent confirmation or retrained evidence",
        source_hashes=source,source_unchanged=source==sources(),raw_input_and_physical_policy_unchanged=True,
        original_candidate_sha256=digest(run/"ALL_CHECKPOINTS.json"),rows=rows,
        cpu_seconds=time.process_time()-cpu,wall_seconds=time.perf_counter()-wall)
    write(directory/"SUMMARY.json",report);return report


def freeze(run, out):
    out.mkdir(parents=True,exist_ok=True)
    plan = dict(schema="hcsn.typed.retention.v1",source_hashes=sources(),original_run=str(run),
        original_candidate_sha256=digest(run/"ALL_CHECKPOINTS.json"),
        design_origin="Explicitly informed by version-one confirmation: repeated observed distractors overwrite content",
        intervention="WRITE alone eligible for content; BRIDGE alone eligible for relation; raw policy input unchanged",
        interpretation="Shared typed-event semantics prior; any gain is not itself evidence of analytical dynamics",
        tasks=list(data.CONTENT_TASKS),cores=list(CORES),seeds=list(SEEDS),steps=600,batch=24,
        optimizer="AdamW",learning_rate=.003,weight_decay=.0001,gradient_clip=1.,
        selection="Final step only; fresh initialization; no transferred checkpoint or confirmation selection",
        train_seed="Identical version-one train namespace, seed*10000+step and shared addressed initialization",
        confirmation_seed=73117,confirmation_episodes=1024,conditions=list(data.CONDITIONS),
        confirmation="New synthetic draws after all checkpoints freeze; not an independent new task distribution",
        gates=dict(all4=.95,required_conditions=[c for c in data.CONDITIONS if c!="missing"],
                   missing="Report available-query accuracy separately; unavailable original targets are not recoverable by a write mask",
                   resampling=1e-4),
        intervals=read(HERE/"STATISTICAL_PLAN.json")["intervals"],
        primary_effect="Typed addressed Flow minus typed addressed diagonal, base all-four; three-task family intervals",
        latency=dict(batch_sizes=[1,24],warmup=3,repeats=9,conditions=["base","long_tokens_128"]),
        energy_joules=None,gpu=None)
    snapshot = out/"sources";snapshot.mkdir()
    for name in plan["source_hashes"]:
        target=snapshot/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes((ROOT/name).read_bytes())
    write(out/"PROTOCOL.json",plan)
    return dict(protocol_sha256=digest(out/"PROTOCOL.json"),source_hashes=plan["source_hashes"])


def fit(out_string,task,core,seed,protocol):
    torch.set_num_threads(1);out=Path(out_string);folder=out/"fits"/f"{task}_{core}_{seed}";folder.mkdir(parents=True)
    wall,cpu=time.perf_counter(),time.process_time()
    try:
        if sources()!=protocol["source_hashes"]:raise ValueError("Source changed after freeze")
        model=new_model(task,core,seed)
        optimizer=torch.optim.AdamW(model.parameters(),lr=protocol["learning_rate"],weight_decay=protocol["weight_decay"])
        stream_hash=hashlib.sha256()
        with (folder/"LOSS.jsonl").open("x") as stream:
            for step in range(protocol["steps"]):
                arrays=data.batch(task,protocol["batch"],seed*10000+step,"train")
                for key in ("x","dt","observed","y"):stream_hash.update(np.ascontiguousarray(arrays[key]).tobytes())
                x,dt,observed,y=[torch.from_numpy(arrays[k]) for k in ("x","dt","observed","y")]
                optimizer.zero_grad(set_to_none=True);output=model(x,dt,observed)
                loss=F.cross_entropy(output.flatten(0,1),y.flatten(),ignore_index=-100);loss.backward()
                norm=torch.nn.utils.clip_grad_norm_(model.parameters(),protocol["gradient_clip"],error_if_nonfinite=True)
                optimizer.step();stream.write(json.dumps(dict(step=step+1,loss=float(loss.detach()),norm=float(norm)))+"\n")
        checkpoint=folder/"checkpoint.pt";torch.save(model.state_dict(),checkpoint)
        result=dict(task=task,core=core,seed=seed,status="completed",steps=protocol["steps"],
            checkpoint=str(checkpoint.relative_to(out)),checkpoint_sha256=digest(checkpoint),
            input_stream_sha256=stream_hash.hexdigest(),final_loss=float(loss.detach()),resources=model.resource_shape(arrays["x"].shape[1]))
    except Exception as error:
        (folder/"FAILURE.txt").write_text(traceback.format_exc());result=dict(task=task,core=core,seed=seed,status="failed",error=str(error))
    result.update(cpu_seconds=time.process_time()-cpu,wall_seconds=time.perf_counter()-wall)
    write(folder/"FIT.json",result);return result


def train(out,protocol,source_commit,workers):
    if len(source_commit or "")!=40 or any(c not in "0123456789abcdef" for c in source_commit):raise ValueError("Remote source commit required")
    wall,cpu=time.perf_counter(),time.process_time();children=resource.getrusage(resource.RUSAGE_CHILDREN)
    protocol_hash=digest(out/"PROTOCOL.json")
    write(out/"TRAINING_SOURCE.json",dict(source_commit=source_commit,protocol_sha256=protocol_hash))
    rows=[]
    with ProcessPoolExecutor(max_workers=workers,mp_context=multiprocessing.get_context("spawn")) as pool:
        futures={pool.submit(fit,str(out),task,core,seed,protocol):(task,core,seed) for task in data.CONTENT_TASKS for core in CORES for seed in SEEDS}
        for future in as_completed(futures):
            try:row=future.result()
            except Exception as error:
                task,core,seed=futures[future];row=dict(task=task,core=core,seed=seed,status="failed",error=str(error),traceback=traceback.format_exc())
            rows.append(row);print(json.dumps(row),flush=True)
    after=resource.getrusage(resource.RUSAGE_CHILDREN)
    manifest=dict(fits=sorted(rows,key=lambda r:(r["task"],r["core"],r["seed"])),source_commit=source_commit,
        protocol_sha256=protocol_hash,failed=sum(r["status"]!="completed" for r in rows),
        source_unchanged=sources()==protocol["source_hashes"],protocol_unchanged=protocol_hash==digest(out/"PROTOCOL.json"),
        parent_cpu_seconds=time.process_time()-cpu,children_cpu_seconds=after.ru_utime+after.ru_stime-children.ru_utime-children.ru_stime,
        wall_seconds=time.perf_counter()-wall,cost_scope="Parent plus children phase CPU; fit timers nested, do not add twice")
    write(out/"ALL_CHECKPOINTS.json",manifest)
    return dict(failed=manifest["failed"],source_unchanged=manifest["source_unchanged"],
        protocol_unchanged=manifest["protocol_unchanged"],candidate_freeze_sha256=digest(out/"ALL_CHECKPOINTS.json"))


def evaluate(out,protocol,candidate_sha):
    if candidate_sha!=digest(out/"ALL_CHECKPOINTS.json"):raise ValueError("Exact all-candidate freeze required")
    candidate=read(out/"ALL_CHECKPOINTS.json");training=read(out/"TRAINING_SOURCE.json")
    expected={(t,c,s) for t in data.CONTENT_TASKS for c in CORES for s in SEEDS}
    if (candidate["failed"] or not candidate["source_unchanged"] or not candidate["protocol_unchanged"]
            or candidate["protocol_sha256"]!=digest(out/"PROTOCOL.json")
            or training!={"source_commit":candidate["source_commit"],"protocol_sha256":candidate["protocol_sha256"]}
            or len(candidate["fits"])!=18 or {(r["task"],r["core"],r["seed"]) for r in candidate["fits"]}!=expected):
        raise ValueError("Candidate identity or completeness failed")
    for row in candidate["fits"]:
        if digest(out/row["checkpoint"])!=row["checkpoint_sha256"]:raise ValueError("Checkpoint changed")
    for task in data.CONTENT_TASKS:
        for seed in SEEDS:
            if len({r["input_stream_sha256"] for r in candidate["fits"] if r["task"]==task and r["seed"]==seed})!=1:
                raise ValueError("Unmatched training streams")
    wall,cpu=time.perf_counter(),time.process_time();folder=out/"confirmation";folder.mkdir()
    rows=[];raw={}
    for fit_row in candidate["fits"]:
        task,core,seed=(fit_row[k] for k in ("task","core","seed"));model=new_model(task,core,seed).eval()
        model.load_state_dict(torch.load(out/fit_row["checkpoint"],weights_only=True,map_location="cpu"))
        for condition in protocol["conditions"]:
            arrays=data.batch(task,protocol["confirmation_episodes"],protocol["confirmation_seed"],"confirm",condition)
            output=study.predict(model,arrays);mask=arrays["y"]>=0
            selected=output[mask];y=arrays["y"][mask];correct=(selected.argmax(-1)==y).reshape(len(output),4)
            available=arrays.get("target_available",mask)[mask].reshape(len(output),4)
            path=folder/f"{task}_{core}_{seed}_{condition}.npz"
            np.savez_compressed(path,logits=selected,target=y,prediction=selected.argmax(-1),
                episode_id=np.where(mask)[0],query_position=np.where(mask)[1],available=available)
            row=dict(task=task,core=core,seed=seed,condition=condition,accuracy=float(correct.mean()),all4=float(correct.all(-1).mean()),
                available_accuracy=float(correct[available].mean()) if available.any() else None,
                unavailable_accuracy=float(correct[~available].mean()) if (~available).any() else None,
                raw_file=path.name,raw_sha256=digest(path),checkpoint_sha256=fit_row["checkpoint_sha256"],
                data_sha256={k:hashlib.sha256(np.ascontiguousarray(v).tobytes()).hexdigest() for k,v in arrays.items()})
            if condition=="base":base=output
            if condition=="resample":row["resampling_error"]=float(np.max(np.abs(output[:,1::2]-base)))
            if condition in protocol["latency"]["conditions"]:row["latency"]=study._latency(model,arrays,protocol)
            rows.append(row);raw[task,core,seed,condition]=correct
            write(path.with_suffix(".json"),row)
        print(json.dumps(dict(task=task,core=core,seed=seed,conditions=len(protocol["conditions"]))),flush=True)
    effects=[];rng=np.random.default_rng(protocol["intervals"]["seed"])
    identities={(r["task"],r["core"],r["seed"],r["condition"]):r["data_sha256"] for r in rows}
    for task in data.CONTENT_TASKS:
        for condition in protocol["conditions"]:
            for seed in SEEDS:
                if identities[task,"flow",seed,condition]!=identities[task,"diagonal",seed,condition]:
                    raise ValueError("Confirmation episodes differ between paired cores")
            delta=np.stack([np.stack((raw[task,"flow",seed,condition].mean(-1)-raw[task,"diagonal",seed,condition].mean(-1),
                raw[task,"flow",seed,condition].all(-1).astype(float)-raw[task,"diagonal",seed,condition].all(-1)),-1) for seed in SEEDS])
            intervals=bootstrap(delta,rng,protocol["intervals"],primary=condition=="base")
            intervals[0]["primary_family_interval"]=None
            lo,hi=intervals[0]["interval95"]
            intervals[0]["interpretation"]="positive" if lo>0 else "negative" if hi<0 else "not_distinguished_from_zero"
            effects.append(dict(task=task,condition=condition,accuracy=intervals[0],all4=intervals[1]))
    gates={core:all(r["all4"]>=protocol["gates"]["all4"] for r in rows if r["core"]==core and r["condition"] in protocol["gates"]["required_conditions"]) for core in CORES}
    summary=dict(records=rows,effects=effects,retention_gates=gates,candidate_freeze_sha256=candidate_sha,
        source_commit=candidate["source_commit"],source_hashes=protocol["source_hashes"],source_unchanged=sources()==protocol["source_hashes"],
        cpu_seconds=time.process_time()-cpu,wall_seconds=time.perf_counter()-wall,energy_joules=None,
        interpretation="New synthetic confirmation after a version-one-informed shared typed-semantics repair; no analytical-gain presumption",
        uncertainty="Only three training seeds; constant/zero-event bootstrap intervals do not imply population certainty")
    write(folder/"SUMMARY.json",summary);return dict(records=len(rows),retention_gates=gates,source_unchanged=summary["source_unchanged"])


def main():
    parser=argparse.ArgumentParser();parser.add_argument("--mode",choices=("diagnose","freeze","train","evaluate"),required=True)
    parser.add_argument("--out",type=Path,required=True);parser.add_argument("--original-run",type=Path)
    parser.add_argument("--source-commit");parser.add_argument("--workers",type=int,default=2)
    parser.add_argument("--candidate-freeze-sha256");args=parser.parse_args();torch.set_num_threads(1)
    if args.mode=="diagnose":result=diagnostic(args.original_run,args.out)
    elif args.mode=="freeze":result=freeze(args.original_run,args.out)
    else:
        protocol=read(args.out/"PROTOCOL.json")
        if sources()!=protocol["source_hashes"]:raise ValueError("Scientific source changed after freeze")
        result=train(args.out,protocol,args.source_commit,args.workers) if args.mode=="train" else evaluate(args.out,protocol,args.candidate_freeze_sha256)
    print(json.dumps(result,sort_keys=True),flush=True)
    return 1 if result.get("failed",0) or result.get("source_unchanged") is False or result.get("protocol_unchanged") is False else 0


if __name__=="__main__":raise SystemExit(main())
