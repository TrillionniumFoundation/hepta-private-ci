"""Predeclared deterministic parity, allocation and LRU-eviction development."""

import argparse
import gzip
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import tracemalloc

import numpy as np

from ..addressed_decision_r15_20261101.law import Law
from ..addressed_decision_r15_20261101.planner import Planner
from ..addressed_decision_r15_20261101.world import make_episode
from ..support_retention_r16_20261101.compression import BlockLaw
from ..support_retention_r16_20261101.execution import AnchoredPlanner
from ..planner_fastpath_r18_20261101.execution import execute as previous
from ..planner_fastpath_r18_20261101.planner import KernelCache
from .bounded import BoundedLaw,BoundedKernels,Workspace,resource_metrics
from .execution import execute
from .planner import WorkspacePlanner

HERE=Path(__file__).resolve().parent
BASE=HERE.parent/"addressed_decision_r15_20261101"


def save(path,value):
    raw=json.dumps(value,sort_keys=True,separators=(",",":"),allow_nan=False).encode()
    if path.suffix==".gz":raw=gzip.compress(raw,mtime=0)
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open("xb") as stream:stream.write(raw)


def comparable(row):
    return {k:v for k,v in row.items() if k not in ("cpu_seconds","wall_seconds","checkpoint_io_cpu_seconds")}


def worker():
    protocol=json.loads((HERE/"DEVELOPMENT_PROTOCOL.json").read_text());values=[];records=[]
    for fit in protocol["fits"]:
        models=json.loads(gzip.decompress((BASE/f"run_01/training/{fit}.json.gz").read_bytes()))["calibration"]["models"]
        fit_values=[];fit_rows=[];owner=Law()
        for name in protocol["models"]:
            for representation in protocol["representations"]:
                ref=BlockLaw.from_payload(models[name]["payload"]);law=BoundedLaw.from_payload(models[name]["payload"])
                for dt in protocol["intervals"]:
                    rng=np.random.default_rng([fit,int(1000*dt),protocol["seed"]])
                    for price in protocol["prices"]:
                        for kind,p in enumerate((law.prior,np.eye(40)[0],np.eye(40)[39],rng.dirichlet(np.ones(40)))):
                            initial=p.copy();projection="block" if representation=="anchored" else "full"
                            old=(AnchoredPlanner if representation=="anchored" else Planner)(ref,dt,price,2*price,projection=projection)
                            new=WorkspacePlanner(law,dt,price,2*price,projection=projection,anchored=representation=="anchored",cache=BoundedKernels(),workspace=Workspace())
                            for remaining in range(4):
                                a,b=old.values(p,remaining),new.values(p,remaining)
                                fit_values.append(dict(fit=fit,model=name,representation=representation,dt=dt,price=price,
                                    belief=kind,remaining=remaining,old=a,new=b,exact=a==b,
                                    choice_equal=max(a,key=a.get)==max(b,key=b.get),input_unchanged=np.array_equal(p,initial)))
                with tempfile.TemporaryDirectory(prefix="hcsn-r19-development-") as directory:
                    checkpoint=Path(directory)/"state.json"
                    for policy in ("value","fixed"):
                        outcomes={};snapshots={};allocations={}
                        for mode in ("previous","workspace"):
                            tracemalloc.start();start=time.process_time()
                            model=(BlockLaw if mode=="previous" else BoundedLaw).from_payload(models[name]["payload"])
                            cache=KernelCache() if mode=="previous" else BoundedKernels();workspace=Workspace()
                            rows=[];states=[]
                            for index,domain in enumerate(protocol["domains"]):
                                episode=make_episode(owner,protocol["namespace"]*10**12+fit*10**5+index*10000,domain)
                                fun=previous if mode=="previous" else execute
                                kwargs={} if mode=="previous" else dict(workspace=workspace)
                                row=fun(model,episode,policy,"read_refresh",representation,checkpoint,cache=cache,**kwargs)
                                rows.append(row);states.append(json.loads(checkpoint.read_text()))
                            current,peak=tracemalloc.get_traced_memory();tracemalloc.stop()
                            allocations[mode]=dict(current=current,peak=peak,cpu_seconds=time.process_time()-start)
                            outcomes[mode]=rows;snapshots[mode]=states
                            if mode=="workspace":allocations[mode]["resources"]=resource_metrics(model,cache,workspace)
                        equal=all(comparable(a)==comparable(b) for a,b in zip(outcomes["previous"],outcomes["workspace"],strict=True)) and snapshots["previous"]==snapshots["workspace"]
                        fit_rows.append(dict(fit=fit,model=name,representation=representation,policy=policy,
                            outcomes=outcomes,snapshots=snapshots,allocations=allocations,exact=equal))
        save(HERE/f"development_03/raw_{fit}.json.gz",dict(values=fit_values,records=fit_rows))
        values+=fit_values;records+=fit_rows
    law=BoundedLaw();ref=BlockLaw.from_payload(law.export());kernels=BoundedKernels();workspace=Workspace();stress=[]
    for index in range(protocol["stress_intervals"]):
        dt=.01+index*.0031
        actual=law.transition(dt);expected=ref.transition(dt)
        matrix_exact=np.array_equal(actual,expected)
        kernels.get(law,dt)
        event_exact=(np.array_equal(law.first_hit(law.prior,dt),ref.first_hit(ref.prior,dt)) and
            np.array_equal(law.event_count(law.prior,dt),ref.event_count(ref.prior,dt)))
        # Forget reference caches deliberately to keep this development control bounded too.
        ref._transition_cache.clear();ref._event_cache.clear()
        n=1+index%125;p=np.tile(law.prior,(n,1))
        terminal_exact=np.array_equal(workspace.terminal(p,law.reward),np.max(p@law.reward,axis=1)[:,None])
        stress.append(dict(index=index,dt=dt,matrix_exact=matrix_exact,event_exact=event_exact,
            terminal_exact=terminal_exact,resources=resource_metrics(law,kernels,workspace)))
    save(HERE/"development_03/STRESS.json.gz",stress)
    exact=all(v["exact"] and v["choice_equal"] and v["input_unchanged"] for v in values) and all(r["exact"] for r in records)
    stress_pass=all(r["matrix_exact"] and r["event_exact"] and r["terminal_exact"] for r in stress)
    summary=dict(value_cases=len(values),value_mismatches=sum(not v["exact"] for v in values),
        action_mismatches=sum(not v["choice_equal"] for v in values),mutation_mismatches=sum(not v["input_unchanged"] for v in values),
        execution_pairs=2*len(records),execution_mismatches=sum(not r["exact"] for r in records),exact_gate=exact,
        stress_gate=stress_pass,stress_steps=len(stress),final_stress_resources=stress[-1]["resources"],
        peak_ratios={f'{model}|{rep}|{policy}':sum(r['allocations']['workspace']['peak'] for r in records if (r['model'],r['representation'],r['policy'])==(model,rep,policy))/sum(r['allocations']['previous']['peak'] for r in records if (r['model'],r['representation'],r['policy'])==(model,rep,policy)) for model in protocol['models'] for rep in protocol['representations'] for policy in ('value','fixed')},
        scope="Development, not formal1000-use confirmation. tracemalloc includes imports-excluded model construction, two world generations/outputs/state snapshots and transient buffers; no per-method RSS claim.")
    save(HERE/"development_03/SUMMARY.json",summary)
    if not exact or not stress_pass:raise RuntimeError("Development parity or resource gate failed")


if __name__=="__main__":
    parser=argparse.ArgumentParser();parser.add_argument("--worker",action="store_true");args=parser.parse_args()
    if args.worker:worker()
    else:
        wall=time.perf_counter();child=subprocess.Popen([sys.executable,"-m",__spec__.name,"--worker"])
        _,status,usage=os.wait4(child.pid,0);child.returncode=os.waitstatus_to_exitcode(status)
        save(HERE/"development_03/PROCESS_RECEIPT.json",dict(exit_code=child.returncode,child_cpu_seconds=usage.ru_utime+usage.ru_stime,
            wall_seconds=time.perf_counter()-wall,max_rss_linux_kib=usage.ru_maxrss,scope="Full development child imports, every candidate/failed attempt, tracing, stress and output; not fresh formal confirmation"))
        raise SystemExit(child.returncode)
