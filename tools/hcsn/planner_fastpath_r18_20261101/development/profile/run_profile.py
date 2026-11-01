"""Declared development profile of the unchanged R16/R15 executor and planners."""

import argparse
import cProfile
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import platform
import pstats
import subprocess
import sys
import tempfile
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[4]


def save(path, value):
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    if path.suffix == ".gz":
        raw = gzip.compress(raw, mtime=0)
    with path.open("xb") as stream:
        stream.write(raw)


def worker():
    sys.path.insert(0, str(ROOT))
    import numpy as np
    import scipy
    from tools.hcsn.addressed_decision_r15_20261101.law import Law
    from tools.hcsn.addressed_decision_r15_20261101.world import make_episode
    from tools.hcsn.support_retention_r16_20261101.compression import BlockLaw
    from tools.hcsn.support_retention_r16_20261101.execution import execute

    protocol = json.loads((HERE / "PROTOCOL.json").read_text())
    profiler = cProfile.Profile()
    rows, failed, action_counts, preparation = [], [], {}, []
    hashes = {}
    baseline = ROOT / "tools/hcsn/addressed_decision_r15_20261101"
    with tempfile.TemporaryDirectory(prefix="hcsn-r18-profile-") as directory:
        for fit in protocol["fits"]:
            model_file = baseline / "run_01/training" / f"{fit}.json.gz"
            hashes[str(model_file.relative_to(ROOT))] = hashlib.sha256(model_file.read_bytes()).hexdigest()
            models = json.loads(gzip.decompress(model_file.read_bytes()))["calibration"]["models"]
            laws = {}
            for model in protocol["models"]:
                for representation in protocol["representations"]:
                    for policy in protocol["policies"]:
                        start = time.process_time()
                        laws[model, representation, policy] = BlockLaw.from_payload(models[model]["payload"])
                        preparation.append(dict(fit=fit, model=model, representation=representation,
                            policy=policy, cpu_seconds=time.process_time()-start))
            owner = Law(theta=protocol["owner_theta"])
            for domain in protocol["domains"]:
                seed = protocol["namespace"]*10**12 + fit*10**5 + (10000 if domain == "ood" else 0)
                episode = make_episode(owner, seed, domain)
                for model in protocol["models"]:
                    for representation in protocol["representations"]:
                        for policy in protocol["policies"]:
                            checkpoint = Path(directory) / "checkpoint.json"
                            start = time.process_time()
                            profiler.enable()
                            try:
                                record = execute(laws[model,representation,policy], episode, policy=policy,
                                    pattern="read_refresh", representation=representation, checkpoint_path=checkpoint)
                            except Exception as error:
                                record = dict(invalid=True, error_type=type(error).__name__, error=str(error),
                                    cpu_seconds=time.process_time()-start)
                                failed.append(dict(fit=fit,domain=domain,model=model,representation=representation,policy=policy,**record))
                            finally:
                                profiler.disable()
                            row = dict(fit=fit,domain=domain,model=model,representation=representation,policy=policy,
                                       seed=seed,world_fingerprint=episode.fingerprint,record=record)
                            rows.append(row)
                            for query in record.get("queries", []):
                                for action in query["actions"]:
                                    name = action["action"]
                                    action_counts[name] = action_counts.get(name,0)+1
    profiler.dump_stats(str(HERE/"executor.prof"))
    stats = pstats.Stats(profiler)
    cumulative = io.StringIO()
    pstats.Stats(profiler,stream=cumulative).strip_dirs().sort_stats("cumulative").print_stats(50)
    (HERE/"CUMULATIVE.txt").write_text(cumulative.getvalue())
    internal = io.StringIO()
    pstats.Stats(profiler,stream=internal).strip_dirs().sort_stats("tottime").print_stats(50)
    (HERE/"INTERNAL.txt").write_text(internal.getvalue())
    functions=[]
    for (filename,line,name),(primitive,total,own,cumulative_time,callers) in stats.stats.items():
        functions.append(dict(file=filename,line=line,function=name,primitive_calls=primitive,total_calls=total,
                              own_seconds=own,cumulative_seconds=cumulative_time))
    functions.sort(key=lambda x:x["cumulative_seconds"],reverse=True)
    for name in ("law.py","world.py","planner.py"):
        path=baseline/name;hashes[str(path.relative_to(ROOT))]=hashlib.sha256(path.read_bytes()).hexdigest()
    for name in ("compression.py","execution.py"):
        path=ROOT/"tools/hcsn/support_retention_r16_20261101"/name
        hashes[str(path.relative_to(ROOT))]=hashlib.sha256(path.read_bytes()).hexdigest()
    save(HERE/"RAW.json.gz",dict(rows=rows,preparation=preparation))
    save(HERE/"SUMMARY.json",dict(scope="Declared development profile, unchanged baseline; cProfile perturbs timing; not confirmation or deployment benchmark",
        executions=len(rows),unique_owner_worlds=len({r["world_fingerprint"] for r in rows}),failures=failed,
        actual_action_counts=action_counts,total_profile_calls=stats.total_calls,total_profile_seconds=stats.total_tt,
        inner_execute_cpu_seconds=sum(r["record"]["cpu_seconds"] for r in rows),
        model_preparation_cpu_seconds=sum(r["cpu_seconds"] for r in preparation),functions=functions,
        source_sha256=hashes,environment=dict(python=platform.python_version(),numpy=np.__version__,scipy=scipy.__version__,
            platform=platform.platform(),threads={key:os.environ.get(key) for key in
            ("OPENBLAS_NUM_THREADS","OMP_NUM_THREADS","MKL_NUM_THREADS")})))
    if failed:
        raise SystemExit(1)


def supervise():
    started=time.perf_counter()
    with (HERE/"worker.stdout.log").open("xb") as stdout, (HERE/"worker.stderr.log").open("xb") as stderr:
        child=subprocess.Popen([sys.executable,str(Path(__file__).resolve()),"--worker"],cwd=ROOT,stdout=stdout,stderr=stderr)
        _,status,usage=os.wait4(child.pid,0)
        child.returncode=os.waitstatus_to_exitcode(status)
    receipt=dict(exit_code=child.returncode,child_cpu_seconds=usage.ru_utime+usage.ru_stime,
        wall_seconds=time.perf_counter()-started,max_rss_linux_kib=usage.ru_maxrss,
        scope="wait4 full child including interpreter/imports, all executed attempts, profiling and artifact writing; parent excluded")
    save(HERE/"PROCESS_RECEIPT.json",receipt)
    print(json.dumps(receipt))
    if child.returncode:
        raise SystemExit(child.returncode)


if __name__ == "__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--worker",action="store_true")
    args=parser.parse_args()
    worker() if args.worker else supervise()
