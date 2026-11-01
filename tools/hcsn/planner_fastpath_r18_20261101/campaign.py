"""Published exact-tree engineering comparison with complete child-process metering."""

import argparse
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

import numpy as np
import scipy

from ..addressed_decision_r15_20261101.law import Law
from ..addressed_decision_r15_20261101.world import make_episode
from ..support_retention_r16_20261101.compression import BlockLaw
from ..support_retention_r16_20261101.execution import execute as baseline
from .execution import execute
from .planner import KernelCache

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
BASE=HERE.parent/"addressed_decision_r15_20261101"
OUT=HERE/"confirmation_02"
MODES=("baseline","forest","cached")


def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path,value):
    raw=json.dumps(value,sort_keys=True,separators=(",",":"),allow_nan=False).encode()
    if path.suffix==".gz":raw=gzip.compress(raw,mtime=0)
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open("xb") as stream:stream.write(raw)


def verify():
    manifest=json.loads((HERE/"SOURCE_MANIFEST.json").read_text())
    for name,expected in manifest["files"].items():
        if digest(ROOT/name)!=expected:raise RuntimeError(f"Frozen source mismatch {name}")
    publication=json.loads((HERE/"PUBLICATION.json").read_text())
    if not publication["readback_verified"] or publication["manifest_sha256"]!=digest(HERE/"SOURCE_MANIFEST.json"):
        raise RuntimeError("Verified remote source publication required")
    return json.loads((HERE/"PROTOCOL.json").read_text()),publication


def comparable(row):
    return {k:v for k,v in row.items() if k not in ("cpu_seconds","wall_seconds","checkpoint_io_cpu_seconds")}


def memory_metrics(law,cache):
    seen=set();arrays=objects=0
    def visit(value):
        nonlocal arrays,objects
        if id(value) in seen:return
        seen.add(id(value));objects+=sys.getsizeof(value)
        if isinstance(value,np.ndarray):arrays+=value.nbytes
        elif isinstance(value,dict):
            for key,item in value.items():visit(key);visit(item)
        elif isinstance(value,(tuple,list)):
            for item in value:visit(item)
    visit(law.__dict__)
    if cache is not None:visit(cache.__dict__)
    return dict(unique_owned_or_referenced_numpy_bytes=arrays,recursive_getsizeof_bytes=objects,
        transition_entries=len(law._transition_cache),event_entries=len(law._event_cache),
        kernel_cache=None if cache is None else cache.metrics(),
        scope="Law arrays, ordinary transition/event caches and wrapper cache deduplicated together; getsizeof overlaps ndarray data, not added; transient allocations/RSS separate. Law transition cache has no global arbitrary-time bound.")


def worker(fit):
    protocol,publication=verify()
    if fit not in protocol["fits"]:raise ValueError("Unregistered fit")
    save(OUT/f"claim_{fit}.json",dict(fit=fit,publication=publication,source_manifest_sha256=digest(HERE/"SOURCE_MANIFEST.json")))
    training_path=BASE/f"run_01/training/{fit}.json.gz"
    models=json.loads(gzip.decompress(training_path.read_bytes()))["calibration"]["models"]
    train_receipt=json.loads((BASE/f"run_01/supervisor/train_{fit}.json").read_text())
    if train_receipt["exit_code"]:raise RuntimeError("Invalid inherited training receipt")
    arms={};preparation={};caches={}
    for model in protocol["models"]:
        for representation in protocol["representations"]:
            for policy in protocol["policies"]:
                for mode in MODES:
                    key=(model,representation,policy,mode);start=time.process_time()
                    arms[key]=BlockLaw.from_payload(models[model]["payload"])
                    caches[key]=KernelCache(protocol["kernel_cache_capacity"]) if mode=="cached" else None
                    preparation["|".join(key)]=time.process_time()-start
    owner=Law(theta=protocol["world_theta"])
    records=[];failures=[]
    with tempfile.TemporaryDirectory(prefix="hcsn-r18-confirm-") as directory:
        checkpoint=Path(directory)/"state.json"
        for domain_index,domain in enumerate(protocol["domains"]):
            rows=[]
            for index in range(protocol["worlds_per_fit_domain"]):
                seed=protocol["namespace"]*10**12+fit*10**5+domain_index*10000+index
                episode=make_episode(owner,seed,domain)
                for model_index,model in enumerate(protocol["models"]):
                    for rep_index,representation in enumerate(protocol["representations"]):
                        for policy_index,policy in enumerate(protocol["policies"]):
                            outcomes={};snapshots={}
                            offset=(index+domain_index+model_index+rep_index+policy_index)%3
                            order=MODES[offset:]+MODES[:offset]
                            for mode in order:
                                key=(model,representation,policy,mode);start=time.process_time()
                                try:
                                    fun=baseline if mode=="baseline" else execute
                                    kwargs={} if mode=="baseline" else dict(cache=caches[key])
                                    outcome=fun(arms[key],episode,policy,"read_refresh",representation,checkpoint,**kwargs)
                                    snapshots[mode]=json.loads(checkpoint.read_text())
                                except Exception as exc:
                                    outcome=dict(invalid=True,error_type=type(exc).__name__,error=str(exc),
                                        cpu_seconds=time.process_time()-start)
                                    failures.append(dict(fit=fit,model=model,representation=representation,policy=policy,
                                        mode=mode,seed=seed,**outcome))
                                outcomes[mode]=outcome
                            valid=not any(x.get("invalid") for x in outcomes.values())
                            record=dict(fit=fit,model=model,representation=representation,policy=policy,
                                domain=domain,index=index,seed=seed,world=episode.fingerprint,valid=valid,
                                forest_exact=valid and comparable(outcomes["baseline"])==comparable(outcomes["forest"]),
                                cached_exact=valid and comparable(outcomes["baseline"])==comparable(outcomes["cached"]),
                                forest_checkpoint_exact=valid and snapshots["baseline"]==snapshots["forest"],
                                cached_checkpoint_exact=valid and snapshots["baseline"]==snapshots["cached"],
                                costs={mode:outcomes[mode]["cpu_seconds"] for mode in MODES})
                            rows.append(dict(record=record,outcomes=outcomes,query2_snapshots=snapshots))
                            records.append(record)
            save(OUT/f"raw_{fit}_{domain}.json.gz",dict(fit=fit,domain=domain,rows=rows))
    metrics={"|".join(key):memory_metrics(law,caches[key]) for key,law in arms.items()}
    passed=not failures and all(r["forest_exact"] and r["cached_exact"] and r["forest_checkpoint_exact"] and r["cached_checkpoint_exact"] for r in records)
    save(OUT/f"summary_{fit}.json",dict(fit=fit,records=records,preparation_cpu_seconds=preparation,
        memory=metrics,failures=failures,exact_gate=passed,model_training_sha256=digest(training_path),
        inherited_training_cpu_seconds=train_receipt["total_cpu_seconds"],
        inherited_training_scope="Previous hardware and all inherited candidates; retained investment, not a new same-machine measurement"))
    verify()
    if not passed:raise RuntimeError("Exact behavior/state gate failed; all candidate attempts retained")


def summarize(protocol):
    summaries=[json.loads((OUT/f"summary_{fit}.json").read_text()) for fit in protocol["fits"]]
    records=[r for x in summaries for r in x["records"]];groups={}
    common_training=sum(x["inherited_training_cpu_seconds"] for x in summaries)
    for model in protocol["models"]:
        for representation in protocol["representations"]:
            for policy in protocol["policies"]:
                label="|".join((model,representation,policy))
                selected=[r for r in records if (r["model"],r["representation"],r["policy"])==(model,representation,policy)]
                cpu={mode:sum(r["costs"][mode] for r in selected) for mode in MODES}
                prep={mode:sum(x["preparation_cpu_seconds"][label+"|"+mode] for x in summaries) for mode in MODES}
                cold={mode:sum(r["costs"][mode] for r in selected if r["index"]==0) for mode in MODES}
                estimates={}
                for uses in protocol["reuse_counts"]:
                    c={mode:prep[mode]+uses*cpu[mode]/len(selected)*len(summaries) for mode in MODES}
                    estimates[uses]=dict(without_inherited_training={mode:c[mode]/c["baseline"] for mode in MODES},
                        with_inherited_training_illustration={mode:(c[mode]+common_training)/(c["baseline"]+common_training) for mode in MODES})
                groups[label]=dict(cases=len(selected),cpu_seconds=cpu,preparation_cpu_seconds=prep,
                    ratio={mode:cpu[mode]/cpu["baseline"] for mode in MODES},
                    with_preparation_ratio={mode:(cpu[mode]+prep[mode])/(cpu["baseline"]+prep["baseline"]) for mode in MODES},
                    first_episode_each_domain_cpu_seconds=cold,reuse_estimates=estimates,
                    estimate_scope="Linear measured-mix estimates per fit, not executed100/1000-use runs; inherited training illustration uses prior hardware and shared common cost, not same-machine economics")
    exact=all(x["exact_gate"] for x in summaries)
    cost=all(g["with_preparation_ratio"]["cached"]<=protocol["maximum_value_cpu_ratio"] for key,g in groups.items() if key.endswith("|value"))
    save(OUT/"SUMMARY.json",dict(records=len(records),attempts=3*len(records),unique_owner_worlds=len(summaries)*2*protocol["worlds_per_fit_domain"],
        exact_gate=exact,value_policy_cost_gate=exact and cost,groups=groups,
        inherited_common_training_cpu_seconds=common_training,all_project_blockers_closed=False,production_activation=False,
        scope="Exact finite engineering improvement shared by same-matrix ordinary HMM. Does not rejudge old D-B/core/adoption gates, fixed-policy speedup, unknown input laws, production safety, GPU or joules."))


def supervise():
    protocol,_=verify();receipts=[]
    for fit in protocol["fits"]:
        out=OUT/f"worker_{fit}.stdout.log";out.parent.mkdir(parents=True,exist_ok=True);wall=time.perf_counter()
        with out.open("xb") as stdout,(OUT/f"worker_{fit}.stderr.log").open("xb") as stderr:
            child=subprocess.Popen([sys.executable,"-m",__spec__.name,"--fit",str(fit)],stdout=stdout,stderr=stderr,cwd=ROOT)
            _,status,usage=os.wait4(child.pid,0);child.returncode=os.waitstatus_to_exitcode(status)
        receipt=dict(fit=fit,exit_code=child.returncode,total_cpu_seconds=usage.ru_utime+usage.ru_stime,
            wall_seconds=time.perf_counter()-wall,max_rss_linux_kib=usage.ru_maxrss,
            scope="Complete fresh child imports, all model/preparation/candidate attempts, checkpoint/output writes and exit")
        save(OUT/f"worker_{fit}.PROCESS_RECEIPT.json",receipt);receipts.append(receipt)
        if child.returncode:break
    save(OUT/"PROCESS_SUMMARY.json",dict(receipts=receipts,
        nonoverlapping_child_cpu_seconds=sum(x["total_cpu_seconds"] for x in receipts),
        environment=dict(python=platform.python_version(),numpy=np.__version__,scipy=scipy.__version__,platform=platform.platform())))
    if any(x["exit_code"] for x in receipts):raise SystemExit(1)
    summarize(protocol)


if __name__=="__main__":
    parser=argparse.ArgumentParser();parser.add_argument("--fit",type=int);args=parser.parse_args()
    if args.fit is None:supervise()
    else:worker(args.fit)
