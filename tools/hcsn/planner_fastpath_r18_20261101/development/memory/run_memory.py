"""Posthoc scoped allocation diagnostic using already-opened confirmation worlds."""

import argparse
import gc
import gzip
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
import time
import tracemalloc

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[4]
STUDY=HERE.parents[1]


def save(path,value):
    raw=json.dumps(value,sort_keys=True,separators=(",",":"),allow_nan=False).encode()
    if path.suffix==".gz":raw=gzip.compress(raw,mtime=0)
    with path.open("xb") as stream:stream.write(raw)


def compare(row):
    return {key:value for key,value in row.items() if key not in
            ("cpu_seconds","wall_seconds","checkpoint_io_cpu_seconds")}


def worker():
    sys.path.insert(0,str(ROOT))
    from tools.hcsn.addressed_decision_r15_20261101.law import Law
    from tools.hcsn.addressed_decision_r15_20261101.world import make_episode
    from tools.hcsn.support_retention_r16_20261101.compression import BlockLaw
    from tools.hcsn.support_retention_r16_20261101.execution import execute as baseline
    from tools.hcsn.planner_fastpath_r18_20261101.execution import execute
    from tools.hcsn.planner_fastpath_r18_20261101.planner import KernelCache
    from tools.hcsn.planner_fastpath_r18_20261101.campaign import memory_metrics

    protocol=json.loads((HERE/"PROTOCOL.json").read_text())
    frozen=json.loads((STUDY/"SOURCE_MANIFEST.json").read_text())
    for name,expected in frozen["files"].items():
        if hashlib.sha256((ROOT/name).read_bytes()).hexdigest()!=expected:
            raise RuntimeError(f"Frozen source changed: {name}")
    base=ROOT/"tools/hcsn/addressed_decision_r15_20261101"
    rows,groups,failures=[],[],[]
    with tempfile.TemporaryDirectory(prefix="hcsn-r18-memory-") as directory:
        for fit_index,fit in enumerate(protocol["fits"]):
            models=json.loads(gzip.decompress((base/f"run_01/training/{fit}.json.gz").read_bytes()))["calibration"]["models"]
            owner=Law(theta=protocol["world_theta"])
            episodes={}
            for domain_index,domain in enumerate(protocol["domains"]):
                seed=protocol["namespace"]*10**12+fit*10**5+domain_index*10000
                episode=make_episode(owner,seed,domain)
                prior=json.loads(gzip.decompress((STUDY/f"confirmation_02/raw_{fit}_{domain}.json.gz").read_bytes()))
                if not any(row["record"]["seed"]==seed and row["record"]["world"]==episode.fingerprint for row in prior["rows"]):
                    raise RuntimeError("Diagnostic world was not present in completed confirmation_02")
                episodes[domain]=episode
            for model_index,model in enumerate(protocol["models"]):
                for rep_index,representation in enumerate(protocol["representations"]):
                    for policy_index,policy in enumerate(protocol["policies"]):
                        outcomes,allocations,snapshots={},{},{}
                        order=["baseline","cached"] if (fit_index+model_index+rep_index+policy_index)%2==0 else ["cached","baseline"]
                        for mode in order:
                            gc.collect()
                            tracemalloc.start(1)
                            started,wall=time.process_time(),time.perf_counter()
                            law=BlockLaw.from_payload(models[model]["payload"])
                            cache=KernelCache(protocol["kernel_cache_capacity"]) if mode=="cached" else None
                            retained,snaps=[],[]
                            for domain in protocol["domains"]:
                                one_start=time.process_time()
                                try:
                                    fun=baseline if mode=="baseline" else execute
                                    kwargs={} if mode=="baseline" else dict(cache=cache)
                                    result=fun(law,episodes[domain],policy,"read_refresh",representation,
                                               Path(directory)/"checkpoint.json",**kwargs)
                                    snap=json.loads((Path(directory)/"checkpoint.json").read_text())
                                except Exception as error:
                                    result=dict(invalid=True,error_type=type(error).__name__,error=str(error),
                                                cpu_seconds=time.process_time()-one_start)
                                    snap=None
                                    failures.append(dict(fit=fit,domain=domain,model=model,representation=representation,
                                                         policy=policy,mode=mode,**result))
                                retained.append(result)
                                snaps.append(snap)
                            current,peak=tracemalloc.get_traced_memory()
                            traced_cpu,traced_wall=time.process_time()-started,time.perf_counter()-wall
                            tracemalloc.stop()
                            allocations[mode]=dict(current_traced_bytes=current,peak_traced_bytes=peak,
                                cpu_seconds=traced_cpu,wall_seconds=traced_wall,
                                end_memory_metrics=memory_metrics(law,cache),
                                scope="Imports and owner worlds excluded; starts before law/cache construction, retains two complete outputs/query2 snapshots; includes execution temporary allocation and JSON readback. Tracemalloc reports supported Python/NumPy allocations, not complete process RSS or all native allocators. End metrics computed after tracing stopped.")
                            outcomes[mode]=retained
                            snapshots[mode]=snaps
                            del law,cache,retained,snaps,result,snap,kwargs
                        exact=True
                        for index,domain in enumerate(protocol["domains"]):
                            valid=not any(outcomes[mode][index].get("invalid") for mode in order)
                            semantic=valid and compare(outcomes["baseline"][index])==compare(outcomes["cached"][index])
                            state=valid and snapshots["baseline"][index]==snapshots["cached"][index]
                            rows.append(dict(fit=fit,model=model,representation=representation,policy=policy,domain=domain,
                                seed=episodes[domain].seed,world=episodes[domain].fingerprint,valid=valid,
                                exact_semantics=semantic,query2_snapshot_exact=state,
                                outcomes={mode:outcomes[mode][index] for mode in order},
                                query2_snapshots={mode:snapshots[mode][index] for mode in order}))
                            exact &= semantic and state
                        groups.append(dict(fit=fit,model=model,representation=representation,policy=policy,
                            allocation_order=order,allocations=allocations,exact=exact))
    save(HERE/"RAW.json.gz",dict(rows=rows,groups=groups,failures=failures))
    summaries={}
    for model in protocol["models"]:
        for representation in protocol["representations"]:
            for policy in protocol["policies"]:
                selected=[g for g in groups if (g["model"],g["representation"],g["policy"])==(model,representation,policy)]
                modes={}
                for mode in ("baseline","cached"):
                    allocation=[g["allocations"][mode] for g in selected]
                    modes[mode]=dict(groups=len(allocation),current_traced_range_bytes=[min(a["current_traced_bytes"] for a in allocation),max(a["current_traced_bytes"] for a in allocation)],
                        peak_traced_range_bytes=[min(a["peak_traced_bytes"] for a in allocation),max(a["peak_traced_bytes"] for a in allocation)],
                        current_traced_mean_bytes=sum(a["current_traced_bytes"] for a in allocation)/len(allocation),
                        peak_traced_mean_bytes=sum(a["peak_traced_bytes"] for a in allocation)/len(allocation),
                        allocation_scoped_cpu_seconds=sum(a["cpu_seconds"] for a in allocation),
                        law_transition_entries_range=[min(a["end_memory_metrics"]["transition_entries"] for a in allocation),max(a["end_memory_metrics"]["transition_entries"] for a in allocation)])
                summaries["|".join((model,representation,policy))]=dict(modes=modes,
                    peak_ratio=modes["cached"]["peak_traced_mean_bytes"]/modes["baseline"]["peak_traced_mean_bytes"],
                    current_ratio=modes["cached"]["current_traced_mean_bytes"]/modes["baseline"]["current_traced_mean_bytes"])
    passed=not failures and all(g["exact"] for g in groups)
    save(HERE/"SUMMARY.json",dict(scope="Posthoc memory diagnostic on already-opened confirmation_02 index0 worlds; no new quality evidence or frozen acceptance changes",
        paired_executions=len(rows),candidate_attempts=2*len(rows),allocation_groups=len(groups),
        unique_owner_worlds=len(protocol["fits"])*len(protocol["domains"]),exact_gate=passed,failures=failures,groups=summaries,
        final_source_commit=protocol["final_source_commit"],
        limits=["Tracemalloc adds overhead; diagnostic CPU must not replace uninstrumented confirmation CPU",
                "Per-arm scoped peaks include law/cache, two outputs/query2 snapshots and transient planner allocations; owner worlds/imports are excluded",
                "NumPy allocations are traced when its allocator exposes them; not all native/BLAS allocations are traced",
                "One child process hosts both methods sequentially; max RSS is shared overall, not a per-method memory result"] ))
    for name,expected in frozen["files"].items():
        if hashlib.sha256((ROOT/name).read_bytes()).hexdigest()!=expected:
            raise RuntimeError(f"Frozen source changed after diagnostic: {name}")
    if not passed:raise SystemExit(1)


def supervise():
    started=time.perf_counter()
    with (HERE/"worker.stdout.log").open("xb") as stdout,(HERE/"worker.stderr.log").open("xb") as stderr:
        child=subprocess.Popen([sys.executable,str(Path(__file__).resolve()),"--worker"],cwd=ROOT,stdout=stdout,stderr=stderr)
        _,status,usage=os.wait4(child.pid,0)
        child.returncode=os.waitstatus_to_exitcode(status)
    receipt=dict(exit_code=child.returncode,child_cpu_seconds=usage.ru_utime+usage.ru_stime,
        wall_seconds=time.perf_counter()-started,max_rss_linux_kib=usage.ru_maxrss,
        scope="Complete shared diagnostic child imports, all law/cache/preparation/candidate attempts, tracemalloc, output writes and exit; max RSS is aggregate across methods, never attributed to one method")
    save(HERE/"PROCESS_RECEIPT.json",receipt)
    print(json.dumps(receipt))
    if child.returncode:raise SystemExit(child.returncode)


if __name__=="__main__":
    parser=argparse.ArgumentParser();parser.add_argument("--worker",action="store_true");args=parser.parse_args()
    worker() if args.worker else supervise()
