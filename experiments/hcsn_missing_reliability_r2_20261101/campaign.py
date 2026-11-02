"""Prospective observation-law fit, development audit, then published confirmation."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import time

import numpy as np
import torch

from experiments.hcsn_missing_answers_20261101 import campaign as r1
from .posterior import VisiblePosterior, CERTAIN, INITIAL_UNKNOWN, FINAL_AMBIGUOUS

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
R1=ROOT/"experiments/hcsn_missing_answers_20261101/results/run001"
TASKS=("mqar","selective","binding")
CONDITIONS=("base","missing","long_tokens_128","missing_tokens_128")


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def load(path):return json.loads(Path(path).read_text())


def save(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    with path.open("x") as f:json.dump(value,f,indent=2,sort_keys=True,allow_nan=False);f.write("\n")


def sources():
    result=r1.sources()
    for name in ("campaign.py","posterior.py","__init__.py"):
        p=HERE/name;result[str(p.relative_to(ROOT))]=sha(p)
    return result


def freeze(out):
    out.mkdir(parents=True,exist_ok=False)
    protocol=dict(schema="hcsn.missing-reliability.r2.v1",frozen_utc=datetime.now(timezone.utc).isoformat(),
        source_hashes=sources(),r1_candidate_sha256=sha(R1/"ALL_CHECKPOINTS.json"),r1_calibration_sha256=sha(R1/"ALL_CALIBRATIONS.json"),
        tasks=list(TASKS),cores=["flow","diagonal"],model_seeds=[17,29,43],
        fit=dict(task="selective",seed=421051,episodes=4096,split="train",condition="missing",
            parameter="q=P(old value | ambiguous erased final update)",estimator="Jeffreys Binomial posterior mean (retained+.5)/(ambiguous+1)"),
        development=dict(seed=172051,episodes=1024,split="dev",conditions=["base","missing"]),
        confirmation=dict(seed=173071,episodes=1024,split="confirm",conditions=list(CONDITIONS)),
        input_contract="forward(x,dt,observed) only; declared task law fixed at construction; y used only fit/scorer, availability only scorer",
        prior="Four distinct original values; Selective adds two distinct fresh values on distinct keys; exactly zero or one erased WRITE; fixed8-slot original prelude after binding bridges",
        readout="Ordinary visible-event parser, shared by Flow/Diagonal; bypasses neural content state and cannot establish its value",
        exact_reference="Same ordinary parser with exactq=2/3; output matches fitted law up to finite train smoothing",
        policy=dict(certain=True,unknown_initial=False,ambiguous_final="Fixed one-quarter blake2b subset of visible semantic state + query + preregistered salt; no IDs/rows/splits/targets/future",
            rationale="Designed after R1 failure: certainty-only known coverage80% at population boundary; quarter ambiguity has ideal correctness34/35 and known coverage85%",
            selection="No dev temperature/threshold search, no post-dev policy change"),
        gates=dict(accepted_correctness_min=.95,accepted_known_coverage_min=.8,known_accuracy_min=.95,nonmissing_all4_min=.95),
        branch_metrics=["certain","initial_unknown","final_ambiguous"],
        uncertainty="Query observations paired within episodes; same shared posterior reused across six core/seed pairs; no multiplication of independent sample size",
        scope_limits=["Not resample-qualified: every unobserved slot is a registered erased WRITE, not a clock subdivision placeholder",
            "Fixed observable prelude/update stage contract; no arbitrary unknown generator or multiple erasure claim",
            "Class-law-known symbolic posterior adapter, not a trained neural uncertainty mechanism or analytical-core advantage"],
        runtime=dict(python=platform.python_version(),numpy=np.__version__,torch=torch.__version__,threads=1),
        all_blockers_closed=False,production_activation=False)
    save(out/"PROTOCOL.json",protocol)
    return dict(protocol_sha256=sha(out/"PROTOCOL.json"),source_hashes=protocol["source_hashes"])


def input_checks(out,protocol):
    rows=[]
    for task in TASKS:
        arrays=r1.batch(task,32,421079,"train","missing")
        model=VisiblePosterior(task);full=model.forward(arrays["x"],arrays["dt"],arrays["observed"])
        order=np.random.default_rng(421081).permutation(32)
        perm=model.forward(arrays["x"][order],arrays["dt"][order],arrays["observed"][order])
        for key in full:assert np.array_equal(perm[key],full[key][order])
        first=arrays["x"].shape[1]-4
        prefix=model.forward(arrays["x"][:,:first+1],arrays["dt"][:,:first+1],arrays["observed"][:,:first+1])
        changed=arrays["x"].copy();changed[:,first+1:]=changed[:,first+1:][:,::-1]
        suffix=model.forward(changed,arrays["dt"],arrays["observed"])
        long=r1.batch(task,32,421079,"train","missing_tokens_128")
        filler=model.forward(long["x"],long["dt"],long["observed"])
        for key in full:
            assert np.array_equal(full[key][:,first],prefix[key][:,-1])
            assert np.array_equal(full[key][:,first],suffix[key][:,first])
            assert np.array_equal(full[key][:,-4:],filler[key][:,-4:])
        rows.append(dict(task=task,prefix=True,future_suffix=True,batch_permutation=True,interference_invariant=True))
    save(out/"CAUSAL_INPUT_CHECKS.json",dict(passed=True,rows=rows,fixtures="Train-only seeds421079/421081; no dev/confirm draw",source_hashes=protocol["source_hashes"]))


def fit(out):
    protocol=load(out/"PROTOCOL.json")
    if sources()!=protocol["source_hashes"]:raise ValueError("Source changed after freeze")
    cpu,wall=time.process_time(),time.perf_counter();stage=protocol["fit"]
    arrays=r1.batch(stage["task"],stage["episodes"],stage["seed"],stage["split"],stage["condition"])
    prediction=VisiblePosterior(stage["task"]).forward(arrays["x"],arrays["dt"],arrays["observed"])
    ambiguous=prediction["group"]==FINAL_AMBIGUOUS
    retained=int(np.sum(arrays["y"][ambiguous]==prediction["visible_old"][ambiguous]));count=int(ambiguous.sum())
    q=(retained+.5)/(count+1)
    path=out/"TRAIN_RAW.npz"
    np.savez_compressed(path,labels=arrays["y"][ambiguous],visible_old=prediction["visible_old"][ambiguous],
        episode=np.where(ambiguous)[0],position=np.where(ambiguous)[1])
    candidate=dict(q=q,retained=retained,ambiguous_queries=count,exact_reference_q=2/3,
        protocol_sha256=sha(out/"PROTOCOL.json"),source_hashes=protocol["source_hashes"],
        raw_sha256=sha(path),data_sha256={k:hashlib.sha256(np.ascontiguousarray(v).tobytes()).hexdigest() for k,v in arrays.items()},
        body_cpu_seconds=time.process_time()-cpu,body_wall_seconds=time.perf_counter()-wall)
    save(out/"CANDIDATE.json",candidate);input_checks(out,protocol)
    return dict(candidate_sha256=sha(out/"CANDIDATE.json"),q=q,count=count)


def metrics(p,y,available,accepted,group):
    correct=p.argmax(-1)==y;confidence=p.max(-1);nll=-np.log(p[np.arange(len(y)),y].clip(1e-15));brier=((p-np.eye(8)[y])**2).sum(-1)
    result=dict(accuracy=float(correct.mean()),all4=float(correct.reshape(-1,4).all(-1).mean()),
        nll=float(nll.mean()),brier=float(brier.mean()),accepted_correctness=float(correct[accepted].mean()) if accepted.any() else None,
        coverage=float(accepted.mean()),accepted_known_coverage=float(accepted[available].mean()),
        accepted_unavailable_rate=float(accepted[~available].mean()) if (~available).any() else None,
        known_accuracy=float(correct[available].mean()),branches={})
    for name,mask in (("unavailable",~available),("certain",group==CERTAIN),("initial_unknown",group==INITIAL_UNKNOWN),("final_ambiguous",group==FINAL_AMBIGUOUS)):
        result["branches"][name]=dict(count=int(mask.sum()),accuracy=float(correct[mask].mean()),nll=float(nll[mask].mean()),
            brier=float(brier[mask].mean()),confidence=float(confidence[mask].mean()),accepted_count=int((accepted&mask).sum()),
            accepted_correct=int((accepted&mask&correct).sum())) if mask.any() else None
    return result


def stage(out,name,publication=None,candidate_sha=None):
    protocol=load(out/"PROTOCOL.json");candidate=load(out/"CANDIDATE.json")
    if sources()!=protocol["source_hashes"] or sha(R1/"ALL_CHECKPOINTS.json")!=protocol["r1_candidate_sha256"]:
        raise ValueError("Scientific source or historical candidate changed")
    if name=="confirmation" and (candidate_sha!=sha(out/"CANDIDATE.json") or len(publication or "")!=40):
        raise ValueError("Published exact candidate identity required")
    folder=out/name;folder.mkdir(exist_ok=False)
    save(folder/"STARTED.json",dict(source_hashes=protocol["source_hashes"],candidate_sha256=sha(out/"CANDIDATE.json"),publication_commit=publication))
    cpu,wall=time.process_time(),time.perf_counter();rows=[];stage=protocol[name]
    neural=load(R1/"ALL_CHECKPOINTS.json")["fits"]
    calibrations=load(R1/"ALL_CALIBRATIONS.json")
    if sha(R1/"ALL_CALIBRATIONS.json")!=protocol["r1_calibration_sha256"]:raise ValueError("R1 calibration changed")
    cal={(r["task"],r["core"],r["seed"]):r["calibration"] for r in calibrations["records"] if r["version"]=="missing_trained"}
    for task in TASKS:
        for condition in stage["conditions"]:
            arrays=r1.batch(task,stage["episodes"],stage["seed"],stage["split"],condition);mask=arrays["y"]>=0
            y=arrays["y"][mask];available=arrays.get("target_available",mask)[mask]
            pred=VisiblePosterior(task,candidate["q"]).forward(arrays["x"],arrays["dt"],arrays["observed"])
            exact=VisiblePosterior(task).forward(arrays["x"],arrays["dt"],arrays["observed"])
            p,accepted,group,visible_old=[pred[k][mask] for k in ("probabilities","accepted","group","visible_old")]
            raw=folder/f"{task}_{condition}_shared.npz"
            np.savez_compressed(raw,probabilities=p,exact_probabilities=exact["probabilities"][mask],labels=y,
                available=available,accepted=accepted,group=group,visible_old=visible_old)
            data_sha={k:hashlib.sha256(np.ascontiguousarray(v).tobytes()).hexdigest() for k,v in arrays.items()}
            common=dict(task=task,condition=condition,raw_file=raw.name,raw_sha256=sha(raw),data_sha256=data_sha)
            m=metrics(p,y,available,accepted,group)
            reference=metrics(exact["probabilities"][mask],y,available,exact["accepted"][mask],group)
            rows.append(dict(**common,version="ordinary_exact_law",core=None,seed=None,metrics=reference))
            if name=="development":
                rows.append(dict(**common,version="fitted_shared_posterior",core=None,seed=None,metrics=m));continue
            for fitrow in [r for r in neural if r["task"]==task]:
                core,seed=fitrow["core"],fitrow["seed"];checkpoint=R1/fitrow["checkpoint"]
                if sha(checkpoint)!=fitrow["checkpoint_sha256"]:raise ValueError("Historical weights changed")
                model=r1.model(core,seed).eval();model.load_state_dict(torch.load(checkpoint,weights_only=True,map_location="cpu"))
                logits=r1.study.predict(model,arrays)[mask]
                probability=r1.probabilities(logits,cal[task,core,seed]["temperature"])
                old_accept=probability.max(-1)>=cal[task,core,seed]["threshold"]
                oldraw=folder/f"{task}_{condition}_{core}_{seed}_neural.npz";np.savez_compressed(oldraw,logits=logits)
                rows.append(dict(**common,version="r1_neural",core=core,seed=seed,metrics=metrics(probability,y,available,old_accept,group),
                    neural_raw_file=oldraw.name,neural_raw_sha256=sha(oldraw),calibration=cal[task,core,seed],checkpoint_sha256=fitrow["checkpoint_sha256"]))
                rows.append(dict(**common,version="shared_posterior_readout",core=core,seed=seed,metrics=m,
                    checkpoint_sha256=fitrow["checkpoint_sha256"],mechanism="Shared visible-event readout bypasses neural content; identical across core/seed"))
            print(json.dumps(dict(task=task,condition=condition,rows=len(rows))),flush=True)
    result=dict(records=rows,source_unchanged=sources()==protocol["source_hashes"],candidate_sha256=sha(out/"CANDIDATE.json"),
        body_cpu_seconds=time.process_time()-cpu,body_wall_seconds=time.perf_counter()-wall,
        publication_commit=publication,exact_reference="Ordinary exact-law parser receives same raw prefix/prior; no neural core needed",
        energy_joules=None,all_blockers_closed=False,production_activation=False)
    save(folder/"SUMMARY.json",result)
    return dict(records=len(rows),source_unchanged=result["source_unchanged"],summary_sha256=sha(folder/"SUMMARY.json"))


def main():
    p=argparse.ArgumentParser();p.add_argument("mode",choices=("freeze","fit","development","confirmation"));p.add_argument("--out",type=Path,required=True)
    p.add_argument("--publication");p.add_argument("--candidate-sha");a=p.parse_args();torch.set_num_threads(1)
    result=freeze(a.out) if a.mode=="freeze" else fit(a.out) if a.mode=="fit" else stage(a.out,a.mode,a.publication,a.candidate_sha)
    print(json.dumps(result,sort_keys=True),flush=True)


if __name__=="__main__":main()
