"""Fresh-process serial paired evaluation of the actor-aware rollout repair."""

import argparse
import gzip
import hashlib
from itertools import product
import json
import os
from pathlib import Path
import resource
import subprocess
import sys
import time

import numpy as np
from scipy.stats import t

from ..audit import choose_actor
from ..run import verify as verify_inherited
from ..upstream.cell import Cell
from ..upstream.data import EpisodeOwner,generate_episode_tapes
from ..upstream.estimators import restore_model
from ..upstream.task_value import ExactBeliefDP,choose_values
from .controller import choose_rollout


HERE=Path(__file__).resolve().parent
VALUE=HERE.parent
ROOT=HERE.parents[3]
PACKAGE="experiments.hcsn_validation_r14_20261101.value.rollout_repair"


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path,value):
    Path(path).write_text(json.dumps(value,sort_keys=True,indent=2,allow_nan=False)+"\n")


def source_map():
    return {p.name:sha(p) for p in sorted(list(HERE.glob("*.py"))+[HERE/"PROTOCOL.json"])}


def verify():
    verify_inherited()
    frozen=json.loads((HERE/"SOURCE_FREEZE.json").read_text())
    if frozen["source_files"]!=source_map() or frozen["inherited_freeze_sha256"]!=sha(VALUE/"SOURCE_FREEZE.json"):
        raise ValueError("Repair sources or inherited identity changed after freeze")
    return json.loads((HERE/"PROTOCOL.json").read_text())


def worker(seed,domain,arm,folder):
    protocol=verify()
    selections=json.loads((VALUE/"upstream/CANDIDATE_FREEZE.json").read_text())["selection"]
    kind,control=protocol["arms"][arm]
    kind=selections[str(seed)]["kind"] if kind=="ordinary" else kind
    setup_start=time.process_time()
    fits={k:json.loads((VALUE/"upstream/checkpoints"/str(seed)/(k+".json")).read_text()) for k in {kind,"hx_distribution"}}
    fitted_cell=restore_model(fits["hx_distribution"]["selected_model"]).build_cell()
    model=restore_model(fits[kind]["selected_model"])
    planner=ExactBeliefDP(fitted_cell)
    true_world=Cell()
    tape_seed=protocol["tape_seed_offsets"][domain]+seed
    tapes=generate_episode_tapes(tape_seed,protocol["episodes_per_seed_domain"],3,protocol["domains"][domain])
    setup_cpu=time.process_time()-setup_start
    components=dict(controller=0.,estimator=0.,owner=0.,diagnostic=0.,recording=0.)
    rows=[]
    local_gaps=[]
    equivalence=dict(max_hx_score_error=0.,hx_action_disagreements=0,hx_nontie_disagreements=0,
                     hx_near_tie_prefixes=0,ordinary_changed_first_actions=0)
    start=time.process_time()
    for index,tape in enumerate(tapes):
        ep_wall=time.perf_counter();ep_cpu=time.process_time()
        op=time.process_time();owner=EpisodeOwner(true_world,tape,2);components["owner"]+=time.process_time()-op
        op=time.process_time();model.start(fitted_cell.prior);components["estimator"]+=time.process_time()-op
        trace=[]
        while True:
            schedule,budget=owner.remaining_schedule,owner.remaining_reads
            op=time.process_time()
            if control=="actor_rollout_base_tail":
                action,scores=choose_rollout(model,planner,schedule,budget)
            else:
                action=choose_actor(model,planner,schedule,budget,control)
                scores=None
            components["controller"]+=time.process_time()-op
            step=dict(action=action,clock=list(schedule),read_budget=budget)
            if scores is not None:
                step["base_tail_scores_under_actor_belief"]=scores
            trace.append(step)
            op=time.process_time()
            if action.startswith("STOP"):
                result=owner.finish(int(action[-1]));components["owner"]+=time.process_time()-op
                break
            observation=owner.advance(action);components["owner"]+=time.process_time()-op
            step["observed_input"]=observation["input"].tolist()
            op=time.process_time();model.step(observation["input"]);components["estimator"]+=time.process_time()-op
        result.update(episode=index,arm=arm,trace=trace,
                      episode_wall_seconds=time.perf_counter()-ep_wall,
                      episode_cpu_seconds=time.process_time()-ep_cpu)
        rows.append(result)
    execution_cpu=time.process_time()-start
    actor_cache=planner.cache_info()
    diagnostic_cache=None
    if control=="actor_rollout_base_tail":
        op=time.process_time()
        diagnostic_planner=ExactBeliefDP(fitted_cell)
        diagnostic_model=restore_model(fits[kind]["selected_model"])
        for row in rows:
            diagnostic_model.start(fitted_cell.prior)
            for step in row["trace"]:
                scores=step["base_tail_scores_under_actor_belief"]
                reference=diagnostic_planner.action_values(diagnostic_model.current,step["clock"],step["read_budget"])
                original=choose_values(reference);action=step["action"]
                gap=scores[action]-scores[original];local_gaps.append(gap)
                step.update(original_value_action=original,fitted_local_advantage=gap)
                if kind=="hx_distribution":
                    error=max(abs(scores[a]-reference[a]) for a in scores)
                    equivalence["max_hx_score_error"]=max(equivalence["max_hx_score_error"],error)
                    best=max(reference.values());tied=[a for a in reference if best-reference[a]<=2e-12]
                    equivalence["hx_near_tie_prefixes"]+=len(tied)>1
                    if action!=original:
                        equivalence["hx_action_disagreements"]+=1
                        equivalence["hx_nontie_disagreements"]+=abs(reference[action]-reference[original])>2e-12
                        step["hx_tie_diagnostic"]=dict(reference=reference,tied=tied,error=error)
                else:
                    equivalence["ordinary_changed_first_actions"]+=action!=original
                if "observed_input" in step:
                    diagnostic_model.step(step["observed_input"])
        diagnostic_cache=diagnostic_planner.cache_info()
        components["diagnostic"]=time.process_time()-op
        if planner.cache_info()!=actor_cache:
            raise AssertionError("Diagnostic replay changed the actual planner cache")
    op=time.process_time()
    with gzip.open(folder/"episodes.jsonl.gz","wt") as log:
        for row in rows:
            log.write(json.dumps(row,sort_keys=True,allow_nan=False)+"\n")
    components["recording"]=time.process_time()-op
    def mean(key):
        return float(np.mean([r[key] for r in rows]))
    result=dict(seed=seed,domain=domain,arm=arm,kind=kind,control=control,
        tape_seed=tape_seed,episodes=len(rows),mean_utility=mean("utility"),accuracy=mean("correct"),
        mean_task_cost=mean("cost"),mean_reward=mean("reward"),
        mean_episode_cpu_seconds=mean("episode_cpu_seconds"),
        mean_actor_cpu_seconds=(components["controller"]+components["estimator"])/len(rows),
        actor_cpu_seconds=components["controller"]+components["estimator"],
        episode_latency_ms={name:float(np.quantile([r["episode_wall_seconds"] for r in rows],q)*1000) for name,q in (("p50",.5),("p95",.95))},
        counts={a:sum(r["counts"][a] for r in rows) for a in ("READ","WAIT","RESET")},
        initial_stop_count=sum(len(r["trace"])==1 for r in rows),setup_cpu_seconds=setup_cpu,
        execution_cpu_seconds=execution_cpu,component_cpu_seconds=components,
        unattributed_execution_cpu_seconds=execution_cpu-sum(components[k] for k in ("controller","estimator","owner")),
        caches=dict(actual=actor_cache,diagnostic=diagnostic_cache,
                    scope="actual planner reused across128episodes; diagnostics use separate planner/model after all timed episodes"),
        min_fitted_local_advantage=None if not local_gaps else min(local_gaps),equivalence=equivalence,
        max_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,energy_joules=None,
        source_freeze_sha256=sha(HERE/"SOURCE_FREEZE.json"),
        checkpoint_sha256=sha(VALUE/"upstream/checkpoints"/str(seed)/(kind+".json")),
        evidence=dict(path="episodes.jsonl.gz",sha256=sha(folder/"episodes.jsonl.gz")),
        value_claim="Rollout scores follow the ORIGINAL base policy, not Qpi of the receding repaired policy. This worker measures the actual repaired policy's sampled return.")
    write(folder/"RESULT.json",result)


def effect(values):
    x=np.asarray(values)
    half=t.ppf(.975,len(x)-1)*x.std(ddof=1)/np.sqrt(len(x))
    return dict(mean=float(x.mean()),ci95_descriptive=[float(x.mean()-half),float(x.mean()+half)],fit_values=x.tolist())


def summarize(output,protocol):
    verify()
    if (output/"FAILURE.json").exists():
        raise ValueError("Do not summarize a failed campaign")
    identity=sha(HERE/"SOURCE_FREEZE.json")
    summary=dict(scope="New tapes, eight inherited paired fits, original four arms plus B_prime/D_prime; descriptive comparisons only",domains={})
    for domain in protocol["domains"]:
        rows={seed:{arm:json.loads((output/str(seed)/domain/arm/"RESULT.json").read_text()) for arm in protocol["arms"]} for seed in protocol["seeds"]}
        for seed,arms in rows.items():
            for arm,row in arms.items():
                folder=output/str(seed)/domain/arm
                receipt=json.loads((folder/"PROCESS.json").read_text())
                if (row["source_freeze_sha256"]!=identity or row["seed"]!=seed or row["domain"]!=domain
                        or row["arm"]!=arm or row["episodes"]!=protocol["episodes_per_seed_domain"]
                        or receipt["exit_code"]!=0 or receipt["seed"]!=seed or receipt["domain"]!=domain or receipt["arm"]!=arm
                        or sha(folder/row["evidence"]["path"])!=row["evidence"]["sha256"]):
                    raise ValueError("Incomplete or mismatched actual worker identity")
        results=dict(arms={},contrasts={})
        for arm in protocol["arms"]:
            parts=[rows[s][arm] for s in protocol["seeds"]]
            result={key:float(np.mean([r[key] for r in parts])) for key in ("mean_utility","accuracy","mean_task_cost","mean_episode_cpu_seconds","mean_actor_cpu_seconds")}
            receipts=[json.loads((output/str(seed)/domain/arm/"PROCESS.json").read_text()) for seed in protocol["seeds"]]
            result.update(full_process_cpu_seconds=sum(r["child_cpu_seconds"] for r in receipts),
                          full_process_wall_seconds=sum(r["wall_seconds"] for r in receipts),
                          max_rss_kib=max(r["max_rss_kib"] for r in receipts),
                          counts={a:sum(r["counts"][a] for r in parts) for a in ("READ","WAIT","RESET")},
                          component_cpu_seconds={k:sum(r["component_cpu_seconds"][k] for r in parts) for k in parts[0]["component_cpu_seconds"]},
                          equivalence={"max_hx_score_error":max(r["equivalence"]["max_hx_score_error"] for r in parts),
                            **{key:sum(r["equivalence"][key] for r in parts) for key in parts[0]["equivalence"] if key!="max_hx_score_error"}})
            results["arms"][arm]=result
        for label,left,right in (("B-A","B","A"),("D-C","D","C"),("C-A","C","A"),("D-B","D","B"),
                                ("B_prime-A","B_prime","A"),("D_prime-C","D_prime","C"),
                                ("D_prime-B_prime","D_prime","B_prime"),("B_prime-B","B_prime","B"),("D_prime-D","D_prime","D")):
            results["contrasts"][label]=effect([rows[s][left]["mean_utility"]-rows[s][right]["mean_utility"] for s in protocol["seeds"]])
        for label,b,d in (("interaction","B","D"),("interaction_prime","B_prime","D_prime")):
            results["contrasts"][label]=effect([(rows[s][d]["mean_utility"]-rows[s]["C"]["mean_utility"])-(rows[s][b]["mean_utility"]-rows[s]["A"]["mean_utility"]) for s in protocol["seeds"]])
        for label,left,right in (("B_prime/B","B_prime","B"),("D_prime/D","D_prime","D")):
            results[label+"_ratios"]={key:results["arms"][left][key]/results["arms"][right][key] for key in ("mean_episode_cpu_seconds","mean_actor_cpu_seconds","full_process_cpu_seconds")}
        clocks={seed:json.loads((output/"full_clock"/str(seed)/domain/"RESULT.json").read_text()) for seed in protocol["seeds"]}
        expected={(arm,clock) for arm in protocol["arms"] for clock in product(protocol["domains"][domain],repeat=3)}
        for seed,row in clocks.items():
            folder=output/"full_clock"/str(seed)/domain
            receipt=json.loads((folder/"PROCESS.json").read_text())
            observed={(r["arm"],tuple(r["clock"])) for r in row["records"]}
            if (row["source_freeze_sha256"]!=identity or row["seed"]!=seed or row["domain"]!=domain
                    or receipt["exit_code"]!=0 or receipt["seed"]!=seed or receipt["domain"]!=domain
                    or observed!=expected or len(row["records"])!=len(expected)
                    or max(abs(r["leaf_mass"]-1) for r in row["records"])>2e-10):
                raise ValueError("Incomplete or mismatched27-clock worker")
            for arm in protocol["arms"]:
                average=float(np.mean([r["utility"] for r in row["records"] if r["arm"]==arm]))
                if abs(average-row["mean_utility"][arm])>2e-12:
                    raise ValueError("Finite clock mean is inconsistent")
        finite={"clock_count_per_fit":27,"fit_count":len(clocks),"contrasts":{},
                "per_fit_mean_utility":{str(seed):row["mean_utility"] for seed,row in clocks.items()},
                "mean_utility":{arm:float(np.mean([r["mean_utility"][arm] for r in clocks.values()])) for arm in protocol["arms"]},
                "max_mass_error":max(r["max_mass_error"] for r in clocks.values()),
                "scope":"All27public clocks, uniform; exact finite true-world expectation of the actual policy at all future prefixes, including repair; not primary sampled evidence or a continuum certificate."}
        for label,left,right in (("B-A","B","A"),("D-C","D","C"),("C-A","C","A"),("D-B","D","B"),
                                ("B_prime-A","B_prime","A"),("D_prime-C","D_prime","C"),
                                ("D_prime-B_prime","D_prime","B_prime"),("B_prime-B","B_prime","B"),("D_prime-D","D_prime","D")):
            finite["contrasts"][label]=effect([clocks[s]["mean_utility"][left]-clocks[s]["mean_utility"][right] for s in protocol["seeds"]])
        for label,b,d in (("interaction","B","D"),("interaction_prime","B_prime","D_prime")):
            finite["contrasts"][label]=effect([(clocks[s]["mean_utility"][d]-clocks[s]["mean_utility"]["C"])-(clocks[s]["mean_utility"][b]-clocks[s]["mean_utility"]["A"]) for s in protocol["seeds"]])
        results["full_clock_secondary"]=finite
        summary["domains"][domain]=results
    verify()
    write(output/"SUMMARY.json",summary)


def campaign(output):
    protocol=verify()
    output.mkdir(parents=True,exist_ok=False)
    write(output/"STARTED.json",dict(source_freeze_sha256=sha(HERE/"SOURCE_FREEZE.json"),unix_time=time.time()))
    start=time.perf_counter();parent_cpu=time.process_time();receipts=[]
    for seed in protocol["seeds"]:
        for domain in protocol["domains"]:
            order=list(protocol["arms"])
            np.random.default_rng(seed+14000+(domain=="ood")).shuffle(order)
            for arm in order:
                folder=output/str(seed)/domain/arm
                folder.mkdir(parents=True)
                command=[sys.executable,"-B","-m",PACKAGE+".run","worker","--seed",str(seed),"--domain",domain,"--arm",arm,"--out",str(folder)]
                environment=os.environ.copy()
                environment.update(OPENBLAS_NUM_THREADS="1",OMP_NUM_THREADS="1",MKL_NUM_THREADS="1")
                wall=time.perf_counter()
                with (folder/"STDOUT.log").open("x") as stdout,(folder/"STDERR.log").open("x") as stderr:
                    child=subprocess.Popen(command,cwd=ROOT,env=environment,stdout=stdout,stderr=stderr)
                    _,status,usage=os.wait4(child.pid,0)
                receipt=dict(seed=seed,domain=domain,arm=arm,command=command,exit_code=os.waitstatus_to_exitcode(status),
                    child_cpu_seconds=usage.ru_utime+usage.ru_stime,wall_seconds=time.perf_counter()-wall,
                    max_rss_kib=usage.ru_maxrss,energy_joules=None,
                    scope="fresh serial worker: imports, source/checkpoint verification, setup, actual rollout, diagnostics, evidence writes and exit; nested execution components are not added again")
                write(folder/"PROCESS.json",receipt);receipts.append(receipt)
                if receipt["exit_code"]:
                    write(output/"FAILURE.json",receipt)
                    raise RuntimeError("Repair worker failed; preserve its complete evidence")
            print(json.dumps(dict(completed=f"{seed}/{domain}",workers=len(receipts))),flush=True)
    secondary_receipts=[]
    for seed in protocol["seeds"]:
        for domain in protocol["domains"]:
            folder=output/"full_clock"/str(seed)/domain
            folder.mkdir(parents=True)
            command=[sys.executable,"-B","-m",PACKAGE+".run","clock","--seed",str(seed),"--domain",domain,"--out",str(folder)]
            wall=time.perf_counter()
            with (folder/"STDOUT.log").open("x") as stdout,(folder/"STDERR.log").open("x") as stderr:
                child=subprocess.Popen(command,cwd=ROOT,env=environment,stdout=stdout,stderr=stderr)
                _,status,usage=os.wait4(child.pid,0)
            receipt=dict(seed=seed,domain=domain,command=command,exit_code=os.waitstatus_to_exitcode(status),
                child_cpu_seconds=usage.ru_utime+usage.ru_stime,wall_seconds=time.perf_counter()-wall,max_rss_kib=usage.ru_maxrss,
                scope="Separate fresh process for complete27-clock true-world expectations of all six actual policies")
            write(folder/"PROCESS.json",receipt);secondary_receipts.append(receipt)
            if receipt["exit_code"]:
                write(output/"FAILURE.json",receipt)
                raise RuntimeError("Finite expectation worker failed; evidence preserved")
            print(json.dumps(dict(completed_clock=f"{seed}/{domain}")),flush=True)
    summarize(output,protocol)
    verify()
    write(output/"PROCESS.json",dict(workers=len(receipts),secondary_workers=len(secondary_receipts),serial_workers=True,
        summed_full_worker_cpu_seconds=sum(r["child_cpu_seconds"] for r in receipts),
        summed_secondary_worker_cpu_seconds=sum(r["child_cpu_seconds"] for r in secondary_receipts),
        campaign_wall_seconds=time.perf_counter()-start,parent_body_cpu_seconds=time.process_time()-parent_cpu,
        inherited_training_and_preparation_cpu_seconds=494.924698,new_training_cpu_seconds=0,energy_joules=None,
        scope="worker sum includes fresh imports/start/exit; parent body time is separate; inherited cost shared with earlier study, not incurred again"))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage",choices=("freeze","run","worker","clock"))
    parser.add_argument("--out",type=Path)
    parser.add_argument("--seed",type=int)
    parser.add_argument("--domain")
    parser.add_argument("--arm")
    args=parser.parse_args()
    if args.stage=="freeze":
        verify_inherited()
        target=HERE/"SOURCE_FREEZE.json"
        if target.exists():
            raise FileExistsError("Repair source freeze already exists")
        write(target,dict(schema="hcsn.r14.rollout.source.v1",source_files=source_map(),
              inherited_freeze_sha256=sha(VALUE/"SOURCE_FREEZE.json"),unix_time=time.time(),evaluation_started=False))
    elif args.stage=="worker":
        worker(args.seed,args.domain,args.arm,args.out)
    elif args.stage=="clock":
        from .full_clock import worker as clock_worker
        clock_worker(args.seed,args.domain,args.out,verify(),VALUE)
    else:
        output=args.out.resolve()
        if output.exists():
            raise FileExistsError("Choose a fresh output path; preserve previous results")
        try:
            campaign(output)
        except Exception as error:
            if output.exists() and not (output/"FAILURE.json").exists():
                write(output/"FAILURE.json",dict(type=type(error).__name__,error=str(error)))
            raise


if __name__=="__main__":
    main()
