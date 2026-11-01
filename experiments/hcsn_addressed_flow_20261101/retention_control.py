"""Prospective READ/STOP 2x2 extension for the typed retention candidates.

Uses the unchanged causal environment, feature extraction and paired-execution
algorithm, with new policy train/dev and confirmation streams. Never loads a
version-one checkpoint or reuses version-one control outcome conclusions.
"""

import argparse
import hashlib
import json
from pathlib import Path
import time

import numpy as np
import torch

from . import control_study, data, retention_study
from .analyze import bootstrap


HERE=Path(__file__).resolve().parent
ROOT=HERE.parent.parent
SEEDS=(17,29,43)
CORES=("diagonal","flow")


def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def read(path):return json.loads(Path(path).read_text())


def write(path,value):
    Path(path).parent.mkdir(parents=True,exist_ok=True)
    with Path(path).open("x") as stream:
        json.dump(value,stream,indent=2,sort_keys=True,allow_nan=False);stream.write("\n")


def sources():
    result=retention_study.sources()
    result[str(Path(__file__).resolve().relative_to(ROOT))]=digest(__file__)
    return result


def freeze(run,out):
    out.mkdir(parents=True,exist_ok=False)
    protocol=dict(schema="hcsn.typed.retention.control.v1",source_hashes=sources(),
        retention_protocol_sha256=digest(run/"PROTOCOL.json"),
        candidate_sha256=digest(run/"ALL_CHECKPOINTS.json"),
        candidate_source_commit=read(run/"ALL_CHECKPOINTS.json")["source_commit"],
        tasks=list(data.CONTENT_TASKS),cores=list(CORES),seeds=list(SEEDS),
        policy_seed=117101,confirmation_seed=118101,training_episodes=384,development_episodes=512,confirmation_episodes=1024,
        ridge_penalty=.01,thresholds=[-1.,.02,.08,.16,.24,.32,1.],
        algorithm="Exact original paired execution/features, shared pooled ridge gain regression, development-selected fixed price threshold",
        candidate="Requires complete remotely frozen 18-fit typed-retention checkpoint manifest before calibration",
        features="First observed query prediction, elapsed prefix time and missing-observation fraction only; no future logits or labels",
        objective="Mean four-query correctness minus quoted READ price",
        action="Actual delayed raw-event READ with0.1time then re-query, or STOP; both continuations retained offline",
        effects=["B-A","D-C","C-A","D-B","(D-C)-(B-A)"],
        arms=dict(A="typed diagonal, lightweight",B="typed diagonal, common value",C="typed Flow, lightweight",D="typed Flow, common value"),
        intervals=read(HERE/"STATISTICAL_PLAN.json")["intervals"],
        cost="Symbolic price, policy calibration CPU, actual counterfactual execution CPU, feature extraction and selection CPU kept separate",
        limitations=["New synthetic draws for a version-one-informed semantics revision", "Only three training seeds; degenerate bootstrap is not population certainty",
                     "Restricted one-opportunity READ/STOP, not general WAIT/RESET or production economic superiority"],energy_joules=None,gpu=None)
    for name in protocol["source_hashes"]:
        target=out/"sources"/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes((ROOT/name).read_bytes())
    write(out/"PROTOCOL.json",protocol)
    return dict(protocol_sha256=digest(out/"PROTOCOL.json"),source_hashes=protocol["source_hashes"])


def candidates(run,protocol,candidate_sha):
    if (digest(run/"PROTOCOL.json")!=protocol["retention_protocol_sha256"]
            or digest(run/"ALL_CHECKPOINTS.json")!=candidate_sha or candidate_sha!=protocol["candidate_sha256"]):
        raise ValueError("Typed-retention candidate or protocol identity mismatch")
    manifest=read(run/"ALL_CHECKPOINTS.json")
    expected={(t,c,s) for t in data.CONTENT_TASKS for c in CORES for s in SEEDS}
    records={(r["task"],r["core"],r["seed"]):r for r in manifest["fits"]}
    if (manifest["failed"] or not manifest["source_unchanged"] or not manifest["protocol_unchanged"]
            or manifest["protocol_sha256"]!=protocol["retention_protocol_sha256"]
            or manifest["source_commit"]!=protocol["candidate_source_commit"]
            or set(records)!=expected or len(manifest["fits"])!=18):raise ValueError("Incomplete typed-retention candidate")
    for row in records.values():
        if digest(run/row["checkpoint"])!=row["checkpoint_sha256"]:raise ValueError("Typed checkpoint changed")
    return records


def model_for(run,row):
    model=retention_study.new_model(row["task"],row["core"],row["seed"])
    model.load_state_dict(torch.load(run/row["checkpoint"],weights_only=True,map_location="cpu"))
    return model.eval()


def train(run,out,protocol,candidate_sha,source_commit):
    if len(source_commit or "")!=40 or any(c not in "0123456789abcdef" for c in source_commit):raise ValueError("Remote control source commit required")
    records=candidates(run,protocol,candidate_sha);wall,cpu=time.perf_counter(),time.process_time()
    protocol_hash=digest(out/"PROTOCOL.json")
    write(out/"CALIBRATION_SOURCE.json",dict(source_commit=source_commit,protocol_sha256=protocol_hash,candidate_sha256=candidate_sha))
    policies={};checkpoints={};archives=[]
    for task in data.CONTENT_TASKS:
        train_rows=[];dev_rows=[]
        for core in CORES:
            for seed in SEEDS:
                record=records[task,core,seed];model=model_for(run,record);key=f"{task}_{core}_{seed}"
                checkpoints[key]=record["checkpoint_sha256"]
                for split,count,dest in (("train",protocol["training_episodes"],train_rows),("dev",protocol["development_episodes"],dev_rows)):
                    row=control_study.paired(model,task,split,count,protocol["policy_seed"])
                    path=out/"calibration"/f"{key}_{split}.npz";path.parent.mkdir(parents=True,exist_ok=True)
                    with path.open("xb") as stream:np.savez_compressed(stream,**row)
                    archives.append(dict(file=str(path.relative_to(out)),sha256=digest(path)));dest.append(row)
        x=np.concatenate([r["features"] for r in train_rows])
        gain=np.concatenate([r["read_quality"]-r["stop_quality"] for r in train_rows])
        penalty=np.eye(x.shape[1])*protocol["ridge_penalty"];penalty[0,0]=0
        coef=np.linalg.solve(x.T@x+penalty,x.T@gain)
        utilities=[float(np.mean([np.mean(r["stop_quality"]+(r["price"]<threshold)*(r["read_quality"]-r["stop_quality"]-r["price"])) for r in dev_rows])) for threshold in protocol["thresholds"]]
        selected=int(np.argmax(utilities))
        policies[task]=dict(value_coefficients=coef.tolist(),lightweight_threshold=protocol["thresholds"][selected],
            development_utilities=utilities,thresholds=protocol["thresholds"],ridge_penalty=protocol["ridge_penalty"],
            training_rows=len(x),independent_training_episodes=protocol["training_episodes"],
            pairing="Six models reuse paired episodes; not2304 independent trajectories")
    freeze=dict(schema="hcsn.typed.retention.control.freeze.v1",source_hashes=sources(),source_commit=source_commit,
        protocol_sha256=protocol_hash,candidate_sha256=candidate_sha,checkpoint_sha256=checkpoints,policies=policies,calibration_archives=archives,
        cpu_seconds=time.process_time()-cpu,wall_seconds=time.perf_counter()-wall,
        source_unchanged=sources()==protocol["source_hashes"],protocol_unchanged=digest(out/"PROTOCOL.json")==protocol_hash)
    write(out/"POLICY_FREEZE.json",freeze)
    return dict(policy_freeze_sha256=digest(out/"POLICY_FREEZE.json"),source_unchanged=freeze["source_unchanged"],protocol_unchanged=freeze["protocol_unchanged"])


def evaluate(run,out,protocol,policy_sha):
    if digest(out/"POLICY_FREEZE.json")!=policy_sha:raise ValueError("Remote policy freeze digest required")
    frozen=read(out/"POLICY_FREEZE.json")
    if (frozen["source_hashes"]!=sources() or frozen["protocol_sha256"]!=digest(out/"PROTOCOL.json")
            or not frozen["source_unchanged"] or not frozen["protocol_unchanged"]):raise ValueError("Control freeze changed")
    records=candidates(run,protocol,frozen["candidate_sha256"]);wall,cpu=time.perf_counter(),time.process_time()
    results=[];raw={};folder=out/"confirmation";folder.mkdir()
    for task in data.CONTENT_TASKS:
        policy=frozen["policies"][task]
        for core in CORES:
            for seed in SEEDS:
                key=f"{task}_{core}_{seed}";record=records[task,core,seed]
                if frozen["checkpoint_sha256"][key]!=record["checkpoint_sha256"]:raise ValueError("Frozen checkpoint differs")
                row=control_study.paired(model_for(run,record),task,"confirm",protocol["confirmation_episodes"],protocol["confirmation_seed"])
                start=time.process_time();gain=np.clip(row["features"]@np.asarray(policy["value_coefficients"]),-1.,1.);value=gain>row["price"]
                value_cpu=time.process_time()-start;start=time.process_time();lightweight=row["price"]<policy["lightweight_threshold"];lightweight_cpu=time.process_time()-start
                stats={}
                for name,choice in dict(lightweight=lightweight,value=value,always_read=np.ones(len(value),bool),never_read=np.zeros(len(value),bool)).items():
                    quality=np.where(choice,row["read_quality"],row["stop_quality"]);utility=quality-choice*row["price"]
                    row[name+"_action_read"]=choice;row[name+"_utility"]=utility
                    stats[name]=dict(accuracy=float(quality.mean()),utility=float(utility.mean()),read_rate=float(choice.mean()),
                        all4=float(np.where(choice,row["read_all4"],row["stop_all4"]).mean()))
                row["predicted_gain"]=gain;row["episode_id"]=np.arange(protocol["confirmation_episodes"])
                path=folder/f"{key}.npz"
                with path.open("xb") as stream:np.savez_compressed(stream,**row)
                result=dict(task=task,core=core,seed=seed,policies=stats,checkpoint_sha256=record["checkpoint_sha256"],
                    policy_freeze_sha256=policy_sha,raw_file=path.name,raw_sha256=digest(path),
                    value_controller_cpu_seconds=value_cpu,lightweight_controller_cpu_seconds=lightweight_cpu,
                    feature_cpu_seconds=float(row["feature_cpu_seconds"]))
                write(path.with_suffix(".json"),result);results.append(result);raw[task,core,seed]=row
    rng=np.random.default_rng(protocol["intervals"]["seed"]);effects=[]
    for task in data.CONTENT_TASKS:
        delta=[]
        for seed in SEEDS:
            ordinary,flow=raw[task,"diagonal",seed],raw[task,"flow",seed]
            for name in ("episode_id","labels","price","removed_step"):
                if not np.array_equal(ordinary[name],flow[name]):raise ValueError("Control trajectories are unpaired")
            a,b=ordinary["lightweight_utility"],ordinary["value_utility"];c,d=flow["lightweight_utility"],flow["value_utility"]
            delta.append(np.stack((b-a,d-c,c-a,d-b,(d-c)-(b-a)),-1))
        intervals=bootstrap(np.stack(delta),rng,protocol["intervals"])
        effects.extend(dict(task=task,effect=name,**result) for name,result in zip(protocol["effects"],intervals,strict=True))
    summary=dict(records=results,effects=effects,policy_freeze_sha256=policy_sha,candidate_sha256=frozen["candidate_sha256"],
        source_commit=frozen["source_commit"],source_hashes=sources(),source_unchanged=sources()==protocol["source_hashes"],
        cpu_seconds=time.process_time()-cpu,wall_seconds=time.perf_counter()-wall,energy_joules=None,
        cost_scope="Both actual counterfactual trajectories plus feature/selection work; not deployment policy cost",limitations=protocol["limitations"])
    write(folder/"SUMMARY.json",summary);return dict(records=len(results),source_unchanged=summary["source_unchanged"])


def main():
    parser=argparse.ArgumentParser();parser.add_argument("--mode",choices=("freeze","train","evaluate"),required=True)
    parser.add_argument("--run",type=Path,required=True);parser.add_argument("--out",type=Path,required=True)
    parser.add_argument("--source-commit");parser.add_argument("--candidate-sha256");parser.add_argument("--policy-sha256")
    args=parser.parse_args();torch.set_num_threads(1)
    if args.mode=="freeze":result=freeze(args.run,args.out)
    else:
        protocol=read(args.out/"PROTOCOL.json")
        if sources()!=protocol["source_hashes"]:raise ValueError("Frozen sources changed")
        result=train(args.run,args.out,protocol,args.candidate_sha256,args.source_commit) if args.mode=="train" else evaluate(args.run,args.out,protocol,args.policy_sha256)
    print(json.dumps(result,sort_keys=True),flush=True)
    return 1 if result.get("source_unchanged") is False or result.get("protocol_unchanged") is False else 0


if __name__=="__main__":raise SystemExit(main())
