"""Autonomous native execution first; independent replay/scoring afterwards."""
import argparse
from datetime import datetime, timezone
import gzip
import json
from pathlib import Path
import resource
import time

import numpy as np

from ..task_native_loop_20261031.experiment import archive_chunks, augment_public, native_process, verify_build
from ..task_native_loop_20261031.train import packed
from ..task_value_factorial_20261030.dataset import state_record
from ..task_value_factorial_20261030.task import ACTIONS, Bellman, ContentAdapter, Owner, build_cohort, save, score_terminal, sha
from .model import infer
from .train import HERE, sources
from .value import GridValue, select_action


def evaluate_native(raw, folder, policy, adapter):
    native = raw["payload"]
    if raw["returncode"] != 0 or native is None or not native.get("end",{}).get("task",{}).get("terminal"):
        raise ValueError("Native failure/nonterminal; labels must remain unopened")
    owner = Owner(folder,adapter,policy["confusion"],policy["multiplier"],policy["latency_price"])
    grid = GridValue(owner.meta,policy["confusion"],policy["multiplier"],policy["latency_price"],policy["grid_nodes"])
    teacher = Bellman(owner.meta,policy["confusion"],policy["multiplier"],policy["latency_price"])
    history, detail, regret, q_error, feature_error, target_error, decisions = [], [], 0., 0., 0., 0., 0
    for receipt in native["receipts"]:
        record = state_record(owner,history)
        prediction = infer(policy,record,grid)
        if prediction["action"] != receipt["action"]:
            raise ValueError(("native/reference action mismatch",receipt["sequence"],prediction,receipt["q"]))
        q_error = max(q_error,float(np.max(abs(np.asarray(prediction["q"])-receipt["q"]))))
        if prediction["cell_features"] is not None:
            feature_error = max(feature_error,float(np.max(abs(np.asarray(prediction["cell_features"])-receipt["cell_features"]))))
        elif receipt["cell_features"] is not None:
            raise ValueError("grid unexpectedly queried learned cell")
        if not np.allclose(record["features"],receipt["public_features"],atol=5e-10,rtol=0):
            raise ValueError("native/reference causal feature mismatch")
        exact = np.asarray(teacher.q(owner.job,owner.tick,owner.budget,owner.posterior))
        legal = np.asarray(record["feasible"])
        step_regret = float(np.max(exact)-exact[prediction["action_index"]])
        target_error = max(target_error,float(np.max(abs(np.asarray(prediction["q"])[legal]-exact[legal]))))
        regret += step_regret
        decisions += 1
        event = owner.act(receipt["action"])
        if event.get("observation") != receipt["event"]["observation"]:
            raise ValueError("native/reference content mismatch")
        for key in ("job","tick","budget","posterior","terminal","reads_in_job","charged_cost","query_cost","latency_cost","task_elapsed"):
            a,b = getattr(owner,key),receipt["after"][key]
            if (abs(a-b)>5e-10) if isinstance(a,float) else (a!=b):
                raise ValueError(("native/reference successor mismatch",key,a,b))
        history.append(dict(driver=record["driver"],duration=event["duration"],reset=receipt["action"]=="FIRE"))
        detail.append(dict(sequence=receipt["sequence"],fitted_q=np.where(legal,exact,0.).tolist(),
                           fitted_regret=step_regret))
    if not owner.terminal or max(q_error,feature_error)>1e-7:
        raise ValueError(("native parity/terminal gate",q_error,feature_error))
    # The first access to evaluator labels occurs only now, after native and replay termination.
    score = score_terminal(owner)
    return dict(score=score,counts=owner.counts,regret=regret,decisions=decisions,
                native_q_error=q_error,native_feature_error=feature_error,max_target_q_error=target_error,
                stop_max_absolute=max(abs(r["q"][0]) for r in native["receipts"]),
                detail=detail,task_elapsed=owner.task_elapsed,action_sequence=[h["action"] for h in native["receipts"]],
                decision_states=[(r["before"]["job"],r["before"]["tick"],r["action"]) for r in native["receipts"]])


def exact_episode(folder,policy,adapter):
    start,cpu = time.perf_counter(),time.process_time()
    owner=Owner(folder,adapter,policy["confusion"],policy["multiplier"],policy["latency_price"])
    dp=Bellman(owner.meta,policy["confusion"],policy["multiplier"],policy["latency_price"])
    while not owner.terminal:
        q=dp.q(owner.job,owner.tick,owner.budget,owner.posterior)
        owner.act(ACTIONS[select_action(q, np.isfinite(q))])
    return dict(score=score_terminal(owner),counts=owner.counts,events=owner.events,
                cpu_seconds=time.process_time()-cpu,wall_seconds=time.perf_counter()-start)


def run(training,binary,build_report,out):
    protocol=json.loads((training/"PROTOCOL.json").read_text())
    freeze=json.loads((training/"FREEZE.json").read_text())
    if freeze["source"]!=sources() or freeze["heldout_generated"]:
        raise ValueError("Changed training source/chronology")
    for path,record in freeze["models"].items():
        if sha(training/path)!=record["sha256"]:
            raise ValueError("Changed model")
    if protocol!=json.loads((HERE/"PROTOCOL.json").read_text()):
        raise ValueError("Protocol differs from freeze")
    build=verify_build(binary,build_report)
    out.mkdir(parents=True,exist_ok=False)
    save(out/"EXECUTION_FREEZE.json",dict(at=datetime.now(timezone.utc).isoformat(),
        training_freeze_sha256=sha(training/"FREEZE.json"),binary_sha256=sha(binary),build_report_sha256=sha(build_report),
        source={str(p.relative_to(HERE)):sha(p) for p in [HERE/"experiment.py",HERE/"statistics.py"]},
        heldout_generated=False))
    adapter=ContentAdapter()
    content=HERE.parent/"round9_20261031/native/fixtures/fullhx.json"
    if not content.exists():
        matches=list((HERE.parent/"native_task_bridge_20261031").rglob("*content*.json"))
        raise FileNotFoundError((str(content),list(map(str,matches))))
    results,archives,members=[],{},{}
    wall,cpu=time.perf_counter(),time.process_time()
    children=resource.getrusage(resource.RUSAGE_CHILDREN)
    execution_sources={str(p.relative_to(HERE)):sha(p) for p in [HERE/"experiment.py",HERE/"statistics.py"]}
    for seed in protocol["seeds"]:
        policies={arm:json.loads((training/"models"/f"seed{seed}_{arm}.json").read_text()) for arm in protocol["arms"]}
        for split in ("test","ood"):
            print(json.dumps(dict(stage="native_confirmation",seed=seed,split=split)),flush=True)
            task_protocol=dict(protocol)
            if split=="ood":task_protocol.update(protocol["ood"])
            work=out/"_work"/f"seed{seed}_{split}"
            order_rng=np.random.default_rng(seed+1190000+(split=="ood"))
            cohort=build_cohort(work/"data",split,seed,protocol[f"{split}_sessions"],task_protocol)
            for session in cohort["records"]:
                folder=Path(session["folder"])
                public=augment_public(folder,task_protocol)
                for arm in order_rng.permutation(protocol["arms"]):
                    policy=policies[arm]
                    path=training/"models"/f"seed{seed}_{arm}.json"
                    snap=work/"runs"/f"{session['id']}_{arm}"/"checkpoint.json"
                    raw=native_process(binary,public,content,path,policy,snap)
                    try:
                        evaluation=evaluate_native(raw,folder,policy,adapter)
                    except Exception as exc:
                        packed(out/f"FAILURE_{seed}_{split}_{session['id']}_{arm}.json.gz",dict(raw=raw,error=repr(exc)))
                        raise
                    row=dict(seed=seed,split=split,session=session["id"],arm=arm,
                        runtime_cpu_seconds=raw["runtime_cpu_seconds"],runtime_wall_seconds=raw["runtime_wall_seconds"],
                        **evaluation)
                    packed(snap.parent/"receipt.json.gz",dict(raw=raw,evaluation=evaluation))
                    results.append(row)
                dp=exact_episode(folder,policies["grid"],adapter)
                results.append(dict(seed=seed,split=split,session=session["id"],arm="fitted_dp",**dp))
                with (out/"partial_results.jsonl").open("a") as stream:
                    for row in results[-5:]:stream.write(json.dumps(row,allow_nan=False)+"\n")
            a,m=archive_chunks(out,work,f"archives/seed{seed}_{split}")
            archives.update(a)
            members.update({f"seed{seed}_{split}/{k}":v for k,v in m.items()})
    packed(out/"RESULTS.json.gz",results)
    save(out/"ARCHIVES.json",dict(archives=archives,members=members))
    from .statistics import analyze
    analysis=analyze(results,freeze,protocol)
    save(out/"STATISTICS.json",analysis)
    if freeze["source"]!=sources() or execution_sources!={str(p.relative_to(HERE)):sha(p) for p in [HERE/"experiment.py",HERE/"statistics.py"]}:
        raise ValueError("Source changed during confirmation")
    after=resource.getrusage(resource.RUSAGE_CHILDREN)
    save(out/"COMPLETE.json",dict(at=datetime.now(timezone.utc).isoformat(),runs=len(results),
        native_runs=sum(r["arm"]!="fitted_dp" for r in results),failures=0,
        source_digest=build["source_digest"],training_freeze_sha256=sha(training/"FREEZE.json"),
        parent_cpu_seconds=time.process_time()-cpu,wall_seconds=time.perf_counter()-wall,
        child_cpu_seconds=after.ru_utime+after.ru_stime-children.ru_utime-children.ru_stime,
        statistics_sha256=sha(out/"STATISTICS.json"),results_sha256=sha(out/"RESULTS.json.gz")))
    print(json.dumps(dict(stage="complete",native_runs=4*5*2*64)),flush=True)


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    for name in ("training","binary","build-report","out"):
        parser.add_argument("--"+name,required=True,type=Path)
    args=parser.parse_args()
    run(args.training.resolve(),args.binary.resolve(),args.build_report.resolve(),args.out.resolve())
