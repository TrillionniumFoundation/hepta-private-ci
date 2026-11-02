"""Freeze, dev-select one simple price cutoff, then execute paid READ confirmation."""

import argparse
from collections import defaultdict
from datetime import datetime, timezone
import gzip
import hashlib
import json
from pathlib import Path
import time

import numpy as np
import torch

from experiments.hcsn_missing_answers_20261101 import campaign as r1
from experiments.hcsn_missing_reliability_r2_20261101.posterior import VisiblePosterior
from . import provider,worlds

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
R1=ROOT/"experiments/hcsn_missing_answers_20261101/results/run001"
R2=ROOT/"experiments/hcsn_missing_reliability_r2_20261101/results/run001"
TASKS=("mqar","selective","binding")


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def load(path):return json.loads(Path(path).read_text())


def save(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    with path.open("x") as f:json.dump(value,f,indent=2,sort_keys=True,allow_nan=False);f.write("\n")


def zipped(path,value):
    with Path(path).open("xb") as f:
        with gzip.GzipFile(fileobj=f,mode="wb",mtime=0) as z:z.write(json.dumps(value,sort_keys=True,separators=(",",":"),allow_nan=False).encode())


def sources():
    result=r1.sources()
    for p in [HERE/n for n in ["campaign.py","provider.py","worlds.py","__init__.py"]]+[R2.parents[1]/"posterior.py"]:
        result[str(p.relative_to(ROOT))]=sha(p)
    return result


def freeze(out):
    out.mkdir(parents=True,exist_ok=False)
    protocol=dict(schema="hcsn.paid-read-repair.r2.v1",frozen_utc=datetime.now(timezone.utc).isoformat(),source_hashes=sources(),
        q=load(R2/"CANDIDATE.json")["q"],r2_candidate_sha256=sha(R2/"CANDIDATE.json"),r1_candidate_sha256=sha(R1/"ALL_CHECKPOINTS.json"),
        tasks=list(TASKS),cores=["flow","diagonal"],model_seeds=[17,29,43],policies=list(provider.POLICIES),
        development=dict(seed=172117,episodes=128,split="dev",condition="missing",cutoffs=[-1.,.02,.08,.16,.32,.64],selection="Maximum ordinary exact-law executed-continuation utility; ties use lower price cutoff; one cutoff per task"),
        confirmation=dict(seed=173117,episodes=64,split="confirm",primary=list(worlds.PRIMARY),secondary=list(worlds.SECONDARY)),
        read=dict(request="Only an already-ingested observed-missing slot index",response="Actual original rawWRITE and original source timestamp; never label/posterior/dependency",
            wait=.1,billing="Once per acquired slot per policy/world session, cached repeats charge/wait zero",source_clock="READwait <=.2, next source gap>=.25; replay subtracts elapsedwait, rejects overlap instead of dropping events",
            semantics="Retrospective internal reconstruction after acquisition, not changing prior environment actions; all actual neural replays counted"),
        control="R2 visible-prefix confidence<.95; observable multiple slots or parser rejection causes all-visible-missing READ fallback. No condition/familyID/availability/label to controller",
        conservative_secondary="always_read is applied to every cohort and reads all visible missing slots, then uses generictyped replay; it never relies on unknown hidden-law certification",
        secondary_limits="confidence_read may miss observationally indistinguishable shifted hidden writes; qualify only conservative always_read on secondary, report other outcomes without hidden-family routing",
        answer="FrozenR1 neural argmax after actual causal prefix reconstruction; ordinary exact-law/generictyped reference receives same acquired bytes and actions",
        utility="Mean of four emitted answers correct, minus total actual READ fees; all policies emit four answers. No dilution by abstention. Symbolic fees/waits separate from CPU.",
        prices=[.02,.08,.16,.32,.64],gates=dict(conditional_answer_accuracy_min=.95,conditional_coverage_min=.8,known_accuracy_min=.95,nonmissing_all4_min=.95),
        branches="Original pre-acquisition visible-prefix ambiguity on qualified primary; secondary additionally evaluation-only final-target availability. Neither used as controller oracle.",
        execution="Shared executed provider trace per policy/world reused as matched information across6 frozen core/seed arms and ordinary reference; no duplicated service executions claimed. Neural cache reuses exact hashed prefix arrays only.",
        artifact_scope="Query logits, source-world arrays, executed provider traces, replay pool hashes and model-call ledger; target<15MB",
        all_blockers_closed=False,production_activation=False)
    save(out/"PROTOCOL.json",protocol)
    return dict(protocol_sha256=sha(out/"PROTOCOL.json"),source_hashes=protocol["source_hashes"])


def prepare(out):
    protocol=load(out/"PROTOCOL.json")
    if sources()!=protocol["source_hashes"]:raise ValueError("Source drift")
    stage=protocol["development"];rows=[];selected={};actual_requests=0
    for task in TASKS:
        full,partial,prices=worlds.batch(task,stage["episodes"],stage["seed"],stage["split"],stage["condition"])
        labels=full["y"][:,-4:];traces=[];read_util=[];stop_util=[]
        for i,price in enumerate(prices):
            case={}
            for policy in ["confidence_read","never_read"]:
                plan,_=provider.plan(task,full["x"][i],partial["x"][i],partial["dt"][i],partial["observed"][i],float(price),policy,2/3,0.)
                utility=float(np.mean(np.asarray(plan["answer"])==labels[i]))-plan["fee"]
                case[policy]=dict(plan=plan,utility=utility);actual_requests+=len(plan["requests"])
            traces.append(dict(episode=i,price=float(price),cases=case));read_util.append(case["confidence_read"]["utility"]);stop_util.append(case["never_read"]["utility"])
        options=[]
        for cutoff in stage["cutoffs"]:
            score=float(np.mean(np.where(prices<=cutoff,read_util,stop_util)))
            options.append(dict(cutoff=cutoff,utility=score))
        choice=min(options,key=lambda r:(-r["utility"],r["cutoff"]))
        selected[task]=choice["cutoff"];rows.append(dict(task=task,options=options,selected=choice))
        zipped(out/f"DEV_{task}.json.gz",traces)
    candidate=dict(thresholds=selected,q=protocol["q"],protocol_sha256=sha(out/"PROTOCOL.json"),source_hashes=protocol["source_hashes"],
        development_rows=rows,actual_provider_requests=actual_requests,policy_changed_after_dev=False)
    save(out/"CANDIDATE.json",candidate)
    return dict(candidate_sha256=sha(out/"CANDIDATE.json"),thresholds=selected)


def score(prediction,labels,available,fees,groups):
    correct=prediction==labels
    result=dict(accuracy=float(correct.mean()),all4=float(correct.all(-1).mean()),coverage=1.,
        utility=float(np.mean(correct.mean(-1)-fees)),mean_fee=float(np.mean(fees)),known_accuracy=float(correct[available].mean()),
        unavailable_accuracy=float(correct[~available].mean()) if (~available).any() else None,branches={})
    for name,mask in (("final_ambiguous",groups==2),("initial_unknown",groups==1),("unavailable",~available)):
        result["branches"][name]=dict(queries=int(mask.sum()),correct=int(correct[mask].sum()),accuracy=float(correct[mask].mean()),coverage=1.) if mask.any() else None
    return result


def pool_outputs(task,condition,pool,out):
    identities=sorted(pool);positions={key:i for i,key in enumerate(identities)}
    by_length=defaultdict(list)
    for key in identities:by_length[len(pool[key]["dt"])].append(key)
    fits=[r for r in load(R1/"ALL_CHECKPOINTS.json")["fits"] if r["task"]==task]
    result={};receipts=[]
    for fit in fits:
        path=R1/fit["checkpoint"]
        if sha(path)!=fit["checkpoint_sha256"]:raise ValueError("R1 weights changed")
        model=r1.model(fit["core"],fit["seed"]).eval();model.load_state_dict(torch.load(path,map_location="cpu",weights_only=True))
        logits=np.zeros((len(identities),8),np.float32);calls=0;frames=0;cpu=time.process_time();wall=time.perf_counter()
        with torch.no_grad():
            for length,keys in sorted(by_length.items()):
                chunk=min(24,4096//length)
                for start in range(0,len(keys),chunk):
                    selected=keys[start:start+chunk]
                    xx,dd,oo=[torch.from_numpy(np.stack([pool[k][name] for k in selected])) for name in ["x","dt","observed"]]
                    output=model(xx,dd,oo)[:,-1].detach().numpy()
                    if not np.isfinite(output).all():raise ValueError("Nonfinite actual neural replay")
                    logits[[positions[k] for k in selected]]=output;calls+=1;frames+=len(selected)*length
        file=out/f"{task}_{condition}_{fit['core']}_{fit['seed']}.npz";np.savez_compressed(file,logits=logits)
        row=dict(task=task,condition=condition,core=fit["core"],seed=fit["seed"],actual_forward_calls=calls,
            actual_replay_sequences=len(identities),actual_replay_frames=frames,body_cpu_seconds=time.process_time()-cpu,
            body_wall_seconds=time.perf_counter()-wall,checkpoint_sha256=fit["checkpoint_sha256"],raw_file=file.name,raw_sha256=sha(file))
        receipts.append(row);result[fit["core"],fit["seed"]]=logits
    return identities,positions,result,receipts


def confirm(out,publication,candidate_sha):
    protocol=load(out/"PROTOCOL.json");candidate=load(out/"CANDIDATE.json")
    if (sources()!=protocol["source_hashes"] or sha(out/"CANDIDATE.json")!=candidate_sha or len(publication or "")!=40
            or sha(R1/"ALL_CHECKPOINTS.json")!=protocol["r1_candidate_sha256"]):raise ValueError("Source/candidate publication drift")
    stage=protocol["confirmation"];folder=out/"confirmation";folder.mkdir(exist_ok=False)
    save(folder/"STARTED.json",dict(publication_commit=publication,candidate_sha256=candidate_sha,source_hashes=protocol["source_hashes"]))
    rows=[];ledger=[];provider_executions=[]
    for task in TASKS:
        for condition in stage["primary"]+stage["secondary"]:
            full,partial,prices=worlds.batch(task,stage["episodes"],stage["seed"],stage["split"],condition)
            labels=full["y"][:,-4:];available=partial["target_available"][:,-4:];n=len(labels)
            groups=np.full(labels.shape,-1,np.int8)
            if condition in stage["primary"]:
                pre=VisiblePosterior(task,candidate["q"]).forward(partial["x"],partial["dt"],partial["observed"])
                groups=pre["group"][:,-4:]
            traces=[];pool={};mapping=np.empty((n,len(provider.POLICIES),4),object);ordinary={};fees={};reads={}
            for j,policy in enumerate(provider.POLICIES):
                ordinary[policy]=np.zeros(labels.shape,np.int8);fees[policy]=np.zeros(n);reads[policy]=np.zeros(n,np.int8)
                for i,price in enumerate(prices):
                    plan,inputs=provider.plan(task,full["x"][i],partial["x"][i],partial["dt"][i],partial["observed"][i],float(price),policy,candidate["q"],candidate["thresholds"][task])
                    ordinary[policy][i]=plan["answer"];fees[policy][i]=plan["fee"];reads[policy][i]=plan["reads"]
                    traces.append(dict(episode=i,policy=policy,plan=plan))
                    for q,(key,value) in enumerate(inputs):
                        pool.setdefault(key,value);mapping[i,j,q]=key
                provider_executions.append(dict(task=task,condition=condition,policy=policy,actual_policy_world_sessions=n,
                    actual_paid_reads=int(reads[policy].sum()),total_symbolic_fee=float(fees[policy].sum()),
                    actual_read_wait=float(reads[policy].sum()*.1)))
            tracefile=folder/f"{task}_{condition}_TRACE.json.gz";zipped(tracefile,traces)
            identities,positions,neural,calls=pool_outputs(task,condition,pool,folder);ledger.extend(calls)
            index=np.vectorize(positions.__getitem__,otypes=[np.int64])(mapping)
            worldfile=folder/f"{task}_{condition}_WORLD.npz"
            np.savez_compressed(worldfile,full_x=full["x"],partial_x=partial["x"],dt=partial["dt"],observed=partial["observed"],
                labels=labels,available=available,prices=prices,groups=groups,replay_index=index,identities=np.asarray(identities))
            shared=dict(task=task,condition=condition,qualification="primary_known_law" if condition in stage["primary"] else "secondary_conservative_read_only",
                world_file=worldfile.name,world_sha256=sha(worldfile),trace_file=tracefile.name,trace_sha256=sha(tracefile))
            for j,policy in enumerate(provider.POLICIES):
                rows.append(dict(**shared,core="ordinary",seed=None,policy=policy,metrics=score(ordinary[policy],labels,available,fees[policy],groups),mean_reads=float(reads[policy].mean())))
                for (core,seed),logits in neural.items():
                    prediction=logits[index[:,j,:]].argmax(-1)
                    rows.append(dict(**shared,core=core,seed=seed,policy=policy,metrics=score(prediction,labels,available,fees[policy],groups),
                        mean_reads=float(reads[policy].mean()),raw_file=f"{task}_{condition}_{core}_{seed}.npz"))
            zipped(folder/f"{task}_{condition}_POOL.json.gz",dict(identities=identities,
                logical_query_lookups=int(mapping.size),unique_exact_inputs=len(identities),cache_hits=int(mapping.size-len(identities)),
                replay_only="Each hashed tensor contains only ingested source prefix plus past paid READ replies/waits; no labels/future data"))
            print(json.dumps(dict(task=task,condition=condition,records=len(rows),unique_replays=len(identities))),flush=True)
    result=dict(records=rows,model_execution_ledger=ledger,provider_execution_ledger=provider_executions,
        actual_neural_forward_calls=sum(r["actual_forward_calls"] for r in ledger),actual_neural_replay_sequences=sum(r["actual_replay_sequences"] for r in ledger),
        source_unchanged=sources()==protocol["source_hashes"],candidate_sha256=candidate_sha,publication_commit=publication,
        all_blockers_closed=False,production_activation=False,energy_joules=None)
    save(folder/"SUMMARY.json",result)
    return dict(records=len(rows),actual_neural_replay_sequences=result["actual_neural_replay_sequences"],source_unchanged=result["source_unchanged"])


def main():
    p=argparse.ArgumentParser();p.add_argument("mode",choices=["freeze","prepare","confirm"]);p.add_argument("--out",type=Path,required=True)
    p.add_argument("--publication");p.add_argument("--candidate-sha");a=p.parse_args();torch.set_num_threads(1)
    result=freeze(a.out) if a.mode=="freeze" else prepare(a.out) if a.mode=="prepare" else confirm(a.out,a.publication,a.candidate_sha)
    print(json.dumps(result,sort_keys=True),flush=True)


if __name__=="__main__":main()
