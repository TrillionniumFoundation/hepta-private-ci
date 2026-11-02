"""Actual thousand-use deployment accounting; two single-thread workers maximum."""

import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import resource
import subprocess
import sys
import time

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
BASE=HERE.parent/"addressed_decision_r15_20261101"
OUT=HERE/"confirmation_01"
ARMS=("B","D","anchored","B_ref","D_ref","anchored_ref")
PAIRS=(("B","B_ref"),("D","D_ref"),("anchored","anchored_ref"))


def canonical(value):return json.dumps(value,sort_keys=True,separators=(",",":"),allow_nan=False).encode()


def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path,value):
    raw=canonical(value)
    if path.suffix==".gz":raw=gzip.compress(raw,mtime=0)
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open("xb") as stream:stream.write(raw)
    return dict(path=str(path.relative_to(HERE)),sha256=hashlib.sha256(raw).hexdigest(),bytes=len(raw))


def verify():
    manifest=json.loads((HERE/"SOURCE_MANIFEST.json").read_text())
    for name,expected in manifest["files"].items():
        if digest(ROOT/name)!=expected:raise RuntimeError(f"Frozen source changed: {name}")
    publication=json.loads((HERE/"PUBLICATION.json").read_text())
    if not publication["readback_verified"] or publication["manifest_sha256"]!=digest(HERE/"SOURCE_MANIFEST.json"):
        raise RuntimeError("Remote source publication and readback required")
    return json.loads((HERE/"PROTOCOL.json").read_text()),publication


def comparable(row):
    return {k:v for k,v in row.items() if k not in ("cpu_seconds","wall_seconds","checkpoint_io_cpu_seconds")}


def worker(fit,domain):
    import tempfile
    import numpy as np
    from ..addressed_decision_r15_20261101.law import Law
    from ..addressed_decision_r15_20261101.world import make_episode
    from ..support_retention_r16_20261101.compression import BlockLaw
    from ..planner_fastpath_r18_20261101.execution import execute as reference
    from ..planner_fastpath_r18_20261101.planner import KernelCache
    from .bounded import BoundedLaw,BoundedKernels,Workspace,resource_metrics
    from .execution import execute
    protocol,publication=verify()
    if fit not in protocol["fits"] or domain not in protocol["domains"]:raise ValueError("Unregistered worker")
    prefix=f"{fit}_{domain}"
    save(OUT/f"claim_{prefix}.json",dict(fit=fit,domain=domain,publication=publication))
    compilation=time.process_time()
    for relative in protocol["compile_check_paths"]:
        path=ROOT/relative;compile(path.read_text(),str(path),"exec")
    compile_cpu=time.process_time()-compilation
    training=json.loads(gzip.decompress((BASE/f"run_01/training/{fit}.json.gz").read_bytes()))
    models=training["calibration"]["models"];ordinary=training["ordinary_selected"]
    specs={"B":(ordinary,"full"),"D":("hx","full"),"anchored":("hx","anchored"),
           "B_ref":(ordinary,"full"),"D_ref":("hx","full"),"anchored_ref":("hx","anchored")}
    laws={};caches={};workspaces={};preparation={};identities={}
    for arm,(model,representation) in specs.items():
        started=time.process_time();is_ref=arm.endswith("_ref")
        laws[arm]=(BlockLaw if is_ref else BoundedLaw).from_payload(models[model]["payload"])
        caches[arm]=KernelCache() if is_ref else BoundedKernels();workspaces[arm]=None if is_ref else Workspace()
        preparation[arm]=time.process_time()-started
        identities[arm]=dict(model=model,identity=laws[arm].identity,operator_identity=laws[arm].operator_identity)
    for one,two in PAIRS:
        if laws[one].export()!=laws[two].export():raise RuntimeError("Pair changed model identity")
    owner=Law(theta=protocol["world_theta"])
    sums={arm:dict(attempts=0,invalid=0,actor_cpu=0.,complete_arm_cpu=0.,checkpoint_io_cpu=0.,
        utility_sum=0.,reward_sum=0.,fee_sum=0.,failure_cpu=0.) for arm in ARMS}
    resource_history=[];failures=[];archives=[];objects={};rows=[];world_cpu=0.;exact=True
    def intern(value):
        key=hashlib.sha256(canonical(value)).hexdigest()
        if key in objects and canonical(objects[key])!=canonical(value):raise RuntimeError("Object identity collision")
        objects.setdefault(key,value);return key
    with tempfile.TemporaryDirectory(prefix="hcsn-r19-owned-checkpoint-") as directory:
        checkpoint=Path(directory)/"state.json"
        for index in range(protocol["uses_per_fit_domain"]):
            started=time.process_time();seed=protocol["namespace"]*10**12+fit*10**5+(10000 if domain=="ood" else 0)+index
            episode=make_episode(owner,seed,domain);world_cpu+=time.process_time()-started
            offset=(index+protocol["fits"].index(fit)+(domain=="ood"))%len(ARMS)
            order=ARMS[offset:]+ARMS[:offset];runs={}
            for arm in order:
                started=time.process_time();stats=sums[arm];stats["attempts"]+=1
                model,representation=specs[arm]
                try:
                    is_ref=arm.endswith("_ref");fun=reference if is_ref else execute
                    kwargs={} if is_ref else dict(workspace=workspaces[arm])
                    result=fun(laws[arm],episode,"value","stop",representation,checkpoint,cache=caches[arm],**kwargs)
                    snapshot=json.loads(checkpoint.read_text())
                    row_id=intern(comparable(result));snapshot_id=intern(snapshot)
                    timing={name:result[name] for name in ("cpu_seconds","wall_seconds","checkpoint_io_cpu_seconds")}
                    runs[arm]=dict(valid=True,result=row_id,snapshot=snapshot_id,timing=timing)
                    stats["actor_cpu"]+=result["cpu_seconds"];stats["checkpoint_io_cpu"]+=result["checkpoint_io_cpu_seconds"]
                    for metric in ("utility","reward","fee"):stats[metric+"_sum"]+=result[metric]
                except Exception as exc:
                    cpu=time.process_time()-started;stats["invalid"]+=1;stats["failure_cpu"]+=cpu
                    error=dict(arm=arm,index=index,seed=seed,error_type=type(exc).__name__,error=str(exc),cpu_seconds=cpu)
                    failures.append(error);runs[arm]=dict(valid=False,error=error);exact=False
                elapsed=time.process_time()-started;stats["complete_arm_cpu"]+=elapsed;runs[arm]["complete_arm_cpu"]=elapsed
            matches={one:runs[one]["valid"] and runs[two]["valid"] and runs[one]["result"]==runs[two]["result"] and runs[one]["snapshot"]==runs[two]["snapshot"] for one,two in PAIRS}
            exact=exact and all(matches.values())
            rows.append(dict(index=index,seed=seed,world=episode.fingerprint,order=order,runs=runs,exact_matches=matches))
            if (index+1)%protocol["resource_sample_every"]==0 or index+1==protocol["uses_per_fit_domain"]:
                resources={arm:resource_metrics(laws[arm],caches[arm],workspaces[arm]) for arm in ("B","D","anchored")}
                if any(state[name]["counters_saturated"] for state in resources.values() for name in ("transition","event","kernel","workspace")):
                    raise RuntimeError("Countersaturatedoutsidequalifiedprofile")
                from .bounded import array_bytes
                resource_history.append(dict(completed=index+1,arms=resources,
                    reference_transition_entries={arm:len(laws[arm]._transition_cache) for arm in ("B_ref","D_ref","anchored_ref")},
                    reference_array_bytes={arm:array_bytes((laws[arm].__dict__,caches[arm].__dict__)) for arm in ("B_ref","D_ref","anchored_ref")}))
            if (index+1)%protocol["raw_chunk_uses"]==0 or index+1==protocol["uses_per_fit_domain"]:
                archives.append(save(OUT/f"raw_{prefix}_{index//protocol['raw_chunk_uses']:04d}.json.gz",
                    dict(schema="r19-lossless-object-references-v1",fit=fit,domain=domain,objects=objects,rows=rows)))
                objects={};rows=[]
            if (index+1)%125==0:print(json.dumps(dict(fit=fit,domain=domain,completed=index+1,exact=exact)),flush=True)
    metrics={arm:dict(**stats,quality_valid=not stats["invalid"],
        utility=None if stats["invalid"] else stats["utility_sum"]/stats["attempts"],
        reward=None if stats["invalid"] else stats["reward_sum"]/stats["attempts"],
        fee=None if stats["invalid"] else stats["fee_sum"]/stats["attempts"]) for arm,stats in sums.items()}
    summary=dict(fit=fit,domain=domain,uses=protocol["uses_per_fit_domain"],ordinary_selected=ordinary,identities=identities,
        preparation_cpu=preparation,source_compile_check_cpu=compile_cpu,world_generation_cpu=world_cpu,
        arms=metrics,exact_gate=exact,failures=failures,resource_history=resource_history,archives=archives,
        source_manifest_sha256=digest(HERE/"SOURCE_MANIFEST.json"),
        evidence_encoding="Lossless canonicalJSON content-addressed objects, including every semantic execution result and query2 snapshot. Equal actual bytes share an object; no state precision reduction.")
    save(OUT/f"summary_{prefix}.json",summary);verify()
    if not exact:raise RuntimeError("Actual use parity failed; all attempted cases retained")


def supervise():
    protocol,_=verify();jobs=[(fit,domain) for fit in protocol["fits"] for domain in protocol["domains"]]
    running={};receipts=[]
    while jobs or running:
        while jobs and len(running)<protocol["workers"]:
            fit,domain=jobs.pop(0);prefix=f"{fit}_{domain}";OUT.mkdir(parents=True,exist_ok=True)
            out=(OUT/f"worker_{prefix}.stdout.log").open("xb");err=(OUT/f"worker_{prefix}.stderr.log").open("xb")
            child=subprocess.Popen([sys.executable,"-m",__spec__.name,"--worker",str(fit),domain],stdout=out,stderr=err,cwd=ROOT)
            running[child.pid]=(child,fit,domain,time.perf_counter(),out,err)
        for pid,item in list(running.items()):
            waited,status,usage=os.wait4(pid,os.WNOHANG)
            if not waited:continue
            child,fit,domain,wall,out,err=item;child.returncode=os.waitstatus_to_exitcode(status);out.close();err.close()
            receipt=dict(fit=fit,domain=domain,exit_code=child.returncode,total_cpu_seconds=usage.ru_utime+usage.ru_stime,
                wall_seconds=time.perf_counter()-wall,max_rss_linux_kib=usage.ru_maxrss,
                scope="Full worker including interpreter/import/compile/input/every successful or failed arm/checkpoints/serialization/output/exit")
            save(OUT/f"worker_{fit}_{domain}.PROCESS_RECEIPT.json",receipt);receipts.append(receipt);del running[pid]
        if running:time.sleep(.1)
    save(OUT/"WORKERS.json",dict(receipts=receipts,nonoverlapping_worker_cpu_seconds=sum(x["total_cpu_seconds"] for x in receipts),
        workers=protocol["workers"],all_exited_zero=all(not r["exit_code"] for r in receipts)))
    if any(r["exit_code"] for r in receipts):raise SystemExit(1)


def finish(pipeline_receipt):
    from scipy.stats import t
    protocol,publication=verify();history=json.loads((HERE/"HISTORY.json").read_text())
    receipts=json.loads((OUT/"WORKERS.json").read_text())["receipts"]
    summaries=[json.loads((OUT/f"summary_{fit}_{domain}.json").read_text()) for fit in protocol["fits"] for domain in protocol["domains"]]
    worker_cost={(r["fit"],r["domain"]):r["total_cpu_seconds"] for r in receipts};groups={};allocation=[]
    for row in summaries:
        accounted=sum(row["preparation_cpu"].values())+sum(a["complete_arm_cpu"] for a in row["arms"].values())
        common=worker_cost[row["fit"],row["domain"]]-accounted
        if common < -1e-8:raise RuntimeError("Overlapping worker accounting")
        allocation.append(dict(fit=row["fit"],domain=row["domain"],common_worker_cpu=common,
            complete_use_cpu={arm:row["preparation_cpu"][arm]+row["arms"][arm]["complete_arm_cpu"]+common/6 for arm in ARMS}))
    own=resource.getrusage(resource.RUSAGE_SELF)
    launcher_cpu=own.ru_utime+own.ru_stime
    complete_current_lower_bound=pipeline_receipt["inclusive_pipeline_cpu_seconds"]+launcher_cpu
    overhead=complete_current_lower_bound-sum(worker_cost.values())
    if overhead < -1e-8:raise RuntimeError("wait4 descendant-inclusion contract failed")
    total_known=history["all_known_preuse_cpu_lower_bound"]+complete_current_lower_bound
    quality_valid={arm:all(s["arms"][arm]["quality_valid"] for s in summaries) for arm in ARMS}
    for domain in protocol["domains"]:
        selected=[s for s in summaries if s["domain"]==domain]
        actual={arm:sum(s["arms"][arm]["actor_cpu"] for s in selected) for arm in ARMS}
        allocated={arm:sum(a["complete_use_cpu"][arm] for a in allocation if a["domain"]==domain)+overhead/12 for arm in ARMS}
        mean_differences={}
        for metric in ("utility","reward"):
            if not quality_valid["anchored"] or not quality_valid["D"]:mean_differences[metric]=None;continue
            differences=[s["arms"]["anchored"][metric]-s["arms"]["D"][metric] for s in selected]
            mean=sum(differences)/8;sd=(sum((x-mean)**2 for x in differences)/7)**.5
            mean_differences[metric]=dict(fits=differences,mean=mean,lower=mean-float(t.ppf(.9875,7))*sd/(8**.5),margin=-.01)
        I=history["all_known_preuse_cpu_lower_bound"]
        groups[domain]=dict(actual_actor_cpu_for_8000_uses=actual,actual_complete_allocated_cpu_for_8000_uses=allocated,
            original_online_anchored_over_D=None if not all(quality_valid[a] for a in ("anchored","D")) else actual["anchored"]/actual["D"],
            common_history_before_current_use_ratio=(I+allocated["anchored"])/(I+allocated["D"]),
            strict_original_search_then_1000_reuse_ratio=(total_known+allocated["anchored"])/(total_known+allocated["D"]),
            zero_online_candidate_floor_with_preuse_common_history=I/(I+allocated["D"]),
            zero_online_candidate_floor_strict_original=total_known/(total_known+allocated["D"]),
            paired_fit_quality=mean_differences,
            R19_over_strong_shared_optimizer={one:allocated[one]/allocated[two] for one,two in PAIRS},
            conservative_optimizer_investment_sensitivity={one:(I+complete_current_lower_bound+allocated[one])/allocated[two] for one,two in PAIRS})
    exact=all(s["exact_gate"] for s in summaries);ni=all(v is not None and v["lower"]>-.01 for g in groups.values() for v in g["paired_fit_quality"].values())
    cost=all(g["original_online_anchored_over_D"] is not None and g["original_online_anchored_over_D"]<=.9 and g["strict_original_search_then_1000_reuse_ratio"]<=.9 for g in groups.values())
    save(OUT/"ECONOMICS.json",dict(protocol=protocol,publication=publication,actual_uses_per_fit_domain=1000,
        actual_total_worlds=16000,actual_candidate_attempts=96000,quality_valid_global=quality_valid,groups=groups,
        exact_pair_gate=exact,original_quality_noninferiority_gate=ni,original_cost_gate_numeric_on_known_costs=exact and ni and cost,
        original_cost_gate=exact and ni and cost and history["complete_history_reconciled"],
        historical_costs_complete=history["complete_history_reconciled"],
        known_history_before_use_cpu_lower_bound=I,strict_original_investment_with_current_qualification_cpu=total_known,
        pipeline_overhead_above_workers_cpu=overhead,worker_allocations=allocation,
        launcher_own_cpu_through_economic_construction=launcher_cpu,
        complete_current_pipeline_cpu_lower_bound=complete_current_lower_bound,
        accounting="Current actual run costs are charged once in deployment-use view. Strict original I+N view charges current qualification as search then adds the measured1000-use reference; this is separate qualification-plus-reuse accounting, not a claim these cycles happened twice. Shared overhead allocation is predeclared equal by six arms. Unknown historical costs prevent positive full-history closure.",
        all_project_blockers_closed=False,production_activation=False))


def launch():
    protocol,_=verify();wall=time.perf_counter();OUT.mkdir(parents=True,exist_ok=True)
    out=(OUT/"supervisor.stdout.log").open("xb");err=(OUT/"supervisor.stderr.log").open("xb")
    child=subprocess.Popen([sys.executable,"-m",__spec__.name,"--supervise"],stdout=out,stderr=err,cwd=ROOT)
    _,status,usage=os.wait4(child.pid,0);child.returncode=os.waitstatus_to_exitcode(status);out.close();err.close()
    receipt=dict(exit_code=child.returncode,inclusive_pipeline_cpu_seconds=usage.ru_utime+usage.ru_stime,
        wall_seconds=time.perf_counter()-wall,max_rss_linux_kib=usage.ru_maxrss,
        scope="Linuxwait4pipelineprocessincludingwaitedworkerdescendants; workerreceiptssubsetsnotaddedagain; outerlauncher/analyzerCPUreportedseparately")
    save(OUT/"PIPELINE_RECEIPT.json",receipt)
    if child.returncode:raise SystemExit(child.returncode)
    finish(receipt)
    own=resource.getrusage(resource.RUSAGE_SELF)
    save(OUT/"LAUNCHER_RECEIPT.json",dict(own_cpu_through_finalization_seconds=own.ru_utime+own.ru_stime,
        inclusive_pipeline_cpu_seconds=receipt["inclusive_pipeline_cpu_seconds"],scope="DisjointlauncherownCPUthroughfinalization, includingstatistics/imports. Finalreceiptwrite/exitnotincluded; knownlowerbound."))


if __name__=="__main__":
    parser=argparse.ArgumentParser();parser.add_argument("--worker",nargs=2);parser.add_argument("--supervise",action="store_true");args=parser.parse_args()
    if args.worker:worker(int(args.worker[0]),args.worker[1])
    elif args.supervise:supervise()
    else:launch()
