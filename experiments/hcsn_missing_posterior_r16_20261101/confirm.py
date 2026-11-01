"""Fresh frozen-stream confirmation of a common missing-content calibration."""

import argparse
import json
from pathlib import Path
import resource
import time

import numpy as np
from scipy.special import softmax
from scipy.stats import beta

from experiments.hcsn_addressed_flow_20261101 import data
from .audit import HERE, OLD, ROOT, digest, independent, metrics
from .posterior import calibrate, infer


def run(out, source_commit):
    import torch
    from experiments.hcsn_addressed_flow_20261101.addressed_models import AddressedModel
    from experiments.hcsn_addressed_flow_20261101.typed_retention import install
    from experiments.hcsn_addressed_flow_20261101.study import predict

    if len(source_commit)!=40 or any(c not in "0123456789abcdef" for c in source_commit):
        raise ValueError("A root-verified remote source freeze is required")
    plan=json.loads((HERE/"CONFIRMATION_PROTOCOL.json").read_text())
    frozen=json.loads((HERE/"SOURCE_MANIFEST.json").read_text())
    if not all(digest(ROOT/p)==s for p,s in frozen["files"].items()):
        raise ValueError("Source drift before confirmation")
    if digest(OLD/"ALL_CHECKPOINTS.json")!=plan["candidate_manifest_sha256"]:
        raise ValueError("Candidate manifest changed")
    out.mkdir(parents=True,exist_ok=False)
    start,cpu=time.perf_counter(),time.process_time();torch.set_num_threads(1)
    (out/"FREEZE.json").write_text(json.dumps(dict(source_commit=source_commit,
        protocol_sha256=digest(HERE/"CONFIRMATION_PROTOCOL.json"),
        source_manifest_sha256=digest(HERE/"SOURCE_MANIFEST.json")),indent=2)+"\n")
    candidates=json.loads((OLD/"ALL_CHECKPOINTS.json").read_text());fits=candidates["fits"]
    expected={(t,c,s) for t in plan["tasks"] for c in plan["cores"] for s in plan["fit_seeds"]}
    if (len(fits)!=18 or {(r["task"],r["core"],r["seed"]) for r in fits}!=expected
            or candidates["failed"] or any(r["status"]!="completed" for r in fits)):
        raise ValueError("Incomplete fixed checkpoint set")
    checkpoints={}
    records, references, proper, read_rows=[],[],[],[]
    rng=np.random.default_rng(plan["bootstrap_seed"])
    for task in plan["tasks"]:
        arrays=data.batch(task,plan["episodes_per_task"],plan["confirmation_seed"],"confirm","missing")
        normal=data.batch(task,plan["nonmissing_episodes_per_task"],plan["nonmissing_seed"],"confirm","base")
        query=arrays["y"]>=0;labels=arrays["y"][query];available=arrays["target_available"][query]
        first=arrays["x"].shape[1]-4
        exact=np.zeros((*query.shape,8))
        for row in range(len(arrays["x"])):
            p=infer(task,arrays["x"][row,:first],arrays["observed"][row,:first])
            for t in np.flatnonzero(query[row]):exact[row,t]=p.query(arrays["x"][row,t])
            if row<plan["independent_reference_prefixes_per_task"]:
                other,count=independent(task,arrays["x"][row,:first],arrays["observed"][row,:first])
                error=float(np.abs(p.by_address()-other).max())
                if error>1e-14:raise AssertionError("Independent reference mismatch")
                references.append(dict(task=task,episode=row,latent_worlds=count,error=error))
        np.savez_compressed(out/f"{task}_inputs.npz",**arrays,reference=exact[query])
        paired={core:[] for core in plan["cores"]}
        for fit in (r for r in fits if r["task"]==task):
            core,seed=fit["core"],fit["seed"]
            checkpoint=ROOT/"frozen_weights"/OLD.relative_to(ROOT)/fit["checkpoint"]
            if digest(checkpoint)!=fit["checkpoint_sha256"]:raise AssertionError("Checkpoint changed")
            checkpoints[str(checkpoint.relative_to(ROOT))]=fit["checkpoint_sha256"]
            model=install(AddressedModel(core)).eval()
            model.load_state_dict(torch.load(checkpoint,weights_only=True,map_location="cpu"))
            begin=time.process_time();logits=predict(model,arrays);model_cpu=time.process_time()-begin
            before=softmax(logits.astype(float),axis=-1)
            begin=time.process_time();after=calibrate(task,arrays["x"],arrays["observed"],before);repair_cpu=time.process_time()-begin
            original=predict(model,normal);base=softmax(original.astype(float),axis=-1)
            if not np.array_equal(base,calibrate(task,normal["x"],normal["observed"],base)):
                raise AssertionError("Nonmissing output changed")
            known=query & (exact.max(-1)==1)
            if not np.array_equal(before[known],after[known]):raise AssertionError("Known posterior row changed")
            selected=after[query];old=before[query]
            if np.max(abs(selected.sum(1)-1))>1e-12 or np.any(selected[np.arange(len(labels)),labels]<=0):
                raise AssertionError("Invalid corrected probability")
            brier=np.square(old-np.eye(8)[labels]).sum(1)-np.square(selected-np.eye(8)[labels]).sum(1)
            nll=np.log(selected[np.arange(len(labels)),labels])-np.log(old[np.arange(len(labels)),labels])
            paired[core].append(np.stack((brier.reshape(-1,4).mean(1),nll.reshape(-1,4).mean(1)),-1))
            accept=(selected.max(1)>=plan["abstention_threshold"]).reshape(-1,4)
            correct=(selected.argmax(1)==labels).reshape(-1,4)
            tested=accept.any(1);success=np.all(correct | ~accept,axis=1)[tested]
            lower=float(beta.ppf(.05/18,int(success.sum()),int((~success).sum())+1)) if success.any() else 0.
            path=out/f"{task}_{core}_{seed}.npz"
            np.savez_compressed(path,logits=logits[query],corrected=selected,labels=labels,
                available=available,brier_reduction=brier,nll_reduction=nll)
            records.append(dict(task=task,core=core,seed=seed,before=metrics(old,labels,available),
                after=metrics(selected,labels,available),abstention_episode_lower=lower,
                abstention_pass=lower>.99,checkpoint_sha256=fit["checkpoint_sha256"],
                raw_sha256=digest(path),model_cpu_seconds=model_cpu,repair_cpu_seconds=repair_cpu))
        indices=rng.integers(len(arrays["x"]),size=(plan["bootstrap_replicates"],len(arrays["x"])))
        for core,values in paired.items():
            episode_delta=np.mean(values,axis=0)
            bootstrap=episode_delta[indices].mean(1)
            for col,name in enumerate(("brier","log_loss")):
                lo=float(np.quantile(bootstrap[:,col],plan["family_alpha"]/plan["primary_tests"]))
                floor=plan["minimal_brier_reduction" if col==0 else "minimal_log_loss_reduction"]
                proper.append(dict(task=task,core=core,metric=name,mean_reduction=float(episode_delta[:,col].mean()),
                    lower=lo,floor=floor,passed=lo>floor,independent_episodes=len(episode_delta)))
        stop,read,prices,removed=data.read_opportunity(task,plan["read_episodes_per_task"],plan["read_seed"],"confirm")
        gains,choices,stops,reads=[],[],[],[];first=stop["x"].shape[1]-4
        for row in range(len(prices)):
            p=infer(task,stop["x"][row,:first],stop["observed"][row,:first]);gains.append(p.value_of_read())
            choices.append(gains[-1]>prices[row])
            q=p.acquire(read["x"][row,first+1])
            queries=stop["x"][row,first:];targets=stop["y"][row,first:]
            stops.append(np.mean(np.array([p.query(x).argmax() for x in queries])==targets))
            reads.append(np.mean(np.array([q.query(x).argmax() for x in queries])==targets))
        gains,stops,reads=map(np.asarray,(gains,stops,reads));choice=np.asarray(choices)
        if not np.all(reads==1):raise AssertionError("Actual READ did not recover all four values")
        np.savez_compressed(out/f"{task}_read.npz",**stop,read_x=read["x"],price=prices,removed=removed,
            predicted_gain=gains,action_read=choice,stop_quality=stops,read_quality=reads)
        read_rows.append(dict(task=task,episodes=len(prices),actual_read_accuracy=float(reads.mean()),
            stop_accuracy=float(stops.mean()),read_rate=float(choice.mean()),
            utility=float((np.where(choice,reads,stops)-choice*prices).mean())))
        print(json.dumps(dict(task=task,completed_models=len(records))),flush=True)
    unchanged=all(digest(ROOT/p)==s for p,s in frozen["files"].items())
    weights_unchanged=len(checkpoints)==18 and all(digest(ROOT/p)==s for p,s in checkpoints.items())
    counts=dict(records=len(records),proper=len(proper),read_tasks=len(read_rows),reference=len(references))
    if counts!=dict(records=18,proper=12,read_tasks=3,reference=48):
        raise AssertionError("Required confirmation matrix is incomplete")
    summary=dict(source_commit=source_commit,base_commit=plan["base_commit"],records=records,
        independent_reference=references,proper_scores=proper,read_results=read_rows,
        observer_validity_pass=True,source_unchanged=unchanged,checkpoint_unchanged=weights_unchanged,
        checkpoint_hashes=checkpoints,counts=counts,
        calibration_pass=all(r["passed"] for r in proper),
        abstention_pass=all(r["abstention_pass"] for r in records),read_pass=True,
        all_scoped_gates_passed=unchanged and weights_unchanged and all(r["passed"] for r in proper) and all(r["abstention_pass"] for r in records),
        cpu_seconds=time.process_time()-cpu,wall_seconds=time.perf_counter()-start,
        peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,energy_joules=None,
        scope=plan["scope"],independent_worlds=3072,fixed_checkpoints=18,training_repeated=False)
    (out/"SUMMARY.json").write_text(json.dumps(summary,indent=2,sort_keys=True,allow_nan=False)+"\n")
    return summary


if __name__=="__main__":
    parser=argparse.ArgumentParser();parser.add_argument("--out",type=Path,required=True);parser.add_argument("--source-commit",required=True)
    args=parser.parse_args();result=run(args.out,args.source_commit)
    print(json.dumps({k:result[k] for k in ("all_scoped_gates_passed","calibration_pass","abstention_pass","read_pass")}))
