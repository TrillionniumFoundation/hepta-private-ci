"""Deterministic differential development; never labelled fresh confirmation."""

import argparse
import gzip
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

import numpy as np

from ..addressed_decision_r15_20261101.law import Law
from ..addressed_decision_r15_20261101.world import make_episode
from ..addressed_decision_r15_20261101.planner import Planner
from ..support_retention_r16_20261101.compression import BlockLaw
from ..support_retention_r16_20261101.execution import AnchoredPlanner, execute as baseline
from .execution import execute
from .planner import BatchedPlanner, KernelCache

HERE=Path(__file__).resolve().parent
BASE=HERE.parent/"addressed_decision_r15_20261101"


def save(path,value):
    raw=json.dumps(value,sort_keys=True,separators=(",",":"),allow_nan=False).encode()
    if path.suffix==".gz":raw=gzip.compress(raw,mtime=0)
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open("xb") as f:f.write(raw)


def comparable(row):
    return {k:v for k,v in row.items() if k not in ("cpu_seconds","wall_seconds","checkpoint_io_cpu_seconds")}


def worker():
    protocol=json.loads((HERE/"DEVELOPMENT_PROTOCOL.json").read_text())
    allcases,allrows=[],[]
    for fit in protocol["fits"]:
        models=json.loads(gzip.decompress((BASE/f"run_01/training/{fit}.json.gz").read_bytes()))["calibration"]["models"]
        owner=Law()
        cases,rows=[],[]
        for model in protocol["models"]:
            laws={mode:BlockLaw.from_payload(models[model]["payload"]) for mode in ("baseline","batched","cached")}
            for representation in protocol["representations"]:
                cache=KernelCache()
                for dt in protocol["intervals"]:
                    for price in protocol["prices"]:
                        rng=np.random.default_rng([fit,protocol["seed"],int(100*dt)])
                        beliefs=[laws["baseline"].prior,np.eye(40)[0],rng.dirichlet(np.ones(40))]
                        for belief_index,p in enumerate(beliefs):
                            old=(AnchoredPlanner if representation=="anchored" else Planner)(
                                laws["baseline"],dt,price,2*price,projection="block" if representation=="anchored" else "full")
                            new=BatchedPlanner(laws["batched"],dt,price,2*price,
                                projection="block" if representation=="anchored" else "full",anchored=representation=="anchored")
                            for remaining in range(4):
                                before,after=old.values(p,remaining),new.values(p,remaining)
                                error=max(abs(before[k]-after[k]) for k in before)
                                cases.append(dict(fit=fit,model=model,representation=representation,dt=dt,
                                    price=price,belief_index=belief_index,remaining=remaining,baseline=before,batched=after,
                                    maximum_error=error,choice_equal=max(before,key=before.get)==max(after,key=after.get),
                                    answer_equal=old.answer(p,remaining)==new.answer(p,remaining)))
                with tempfile.TemporaryDirectory(prefix="hcsn-r18-dev-") as directory:
                    checkpoint=Path(directory)/"state.json"
                    for domain_index,domain in enumerate(protocol["domains"]):
                        episode=make_episode(owner,protocol["namespace"]*10**12+fit*10**5+domain_index*10000,domain)
                        for policy,pattern in (("value","stop"),("fixed","read_refresh")):
                            outcomes={}
                            for mode in ("baseline","batched","cached"):
                                start=time.process_time()
                                try:
                                    fun=baseline if mode=="baseline" else execute
                                    kwargs={} if mode=="baseline" else {"cache":cache if mode=="cached" else None}
                                    row=fun(laws[mode],episode,policy,pattern,representation,checkpoint,**kwargs)
                                except Exception as exc:
                                    row=dict(invalid=True,error=repr(exc),cpu_seconds=time.process_time()-start)
                                outcomes[mode]=row
                            good=not any(x.get("invalid") for x in outcomes.values())
                            rows.append(dict(fit=fit,model=model,representation=representation,domain=domain,policy=policy,
                                seed=episode.seed,outcomes=outcomes,cache=cache.metrics(),
                                batched_equal=good and comparable(outcomes["baseline"])==comparable(outcomes["batched"]),
                                cached_equal=good and comparable(outcomes["baseline"])==comparable(outcomes["cached"])))
        save(HERE/f"development/differential_v4/raw_{fit}.json.gz",dict(cases=cases,rows=rows))
        allcases+=cases;allrows+=rows
    groups={}
    for model in protocol["models"]:
        for representation in protocol["representations"]:
            for policy in ("value","fixed"):
                selected=[r for r in allrows if r["model"]==model and r["representation"]==representation and r["policy"]==policy]
                costs={mode:sum(r["outcomes"][mode]["cpu_seconds"] for r in selected) for mode in ("baseline","batched","cached")}
                groups[f"{model}_{representation}_{policy}"]=dict(costs=costs,batched_ratio=costs["batched"]/costs["baseline"],cached_ratio=costs["cached"]/costs["baseline"])
    save(HERE/"development/differential_v4/SUMMARY.json",dict(value_cases=len(allcases),execution_cases=len(allrows),
        choice_mismatches=sum(not c["choice_equal"] for c in allcases),answer_mismatches=sum(not c["answer_equal"] for c in allcases),
        max_value_error=max(c["maximum_error"] for c in allcases),batched_execution_mismatches=sum(not r["batched_equal"] for r in allrows),
        cached_execution_mismatches=sum(not r["cached_equal"] for r in allrows),groups=groups,
        role="development, same deterministic fixtures, not formal timing confirmation"))


if __name__=="__main__":
    parser=argparse.ArgumentParser();parser.add_argument("--worker",action="store_true");args=parser.parse_args()
    if args.worker:worker()
    else:
        wall=time.perf_counter();child=subprocess.Popen([sys.executable,"-m",__spec__.name,"--worker"])
        _,status,usage=os.wait4(child.pid,0);child.returncode=os.waitstatus_to_exitcode(status)
        save(HERE/"development/differential_v4/PROCESS_RECEIPT.json",dict(exit_code=child.returncode,
            child_cpu_seconds=usage.ru_utime+usage.ru_stime,wall_seconds=time.perf_counter()-wall,
            max_rss_linux_kib=usage.ru_maxrss,scope="Full development child imports/allattempts/output; not scientific confirmation"))
        raise SystemExit(child.returncode)
