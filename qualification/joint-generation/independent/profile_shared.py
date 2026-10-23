"""One prospective diagnostic of frozen prepare_shared; never qualification."""

import argparse
import cProfile
import hashlib
import json
import os
from pathlib import Path
import pstats
import resource
import subprocess
import sys
import time
import traceback


ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "runs/codex-cloud-efficient-r2-shared-profile-d1"
FREEZE = ROOT / "independent/frozen-r2-preparation-forecast.json"
SCRIPT = Path(__file__).resolve()
THREAD_KEYS = ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS")


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    def convert(item):
        if hasattr(item, "tolist"):
            return item.tolist()
        raise TypeError(type(item).__name__)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False, default=convert)
        stream.write("\n")


def identity():
    frozen = json.loads(FREEZE.read_text())
    for name, digest in frozen["sources"].items():
        if sha(ROOT / name) != digest:
            raise ValueError("frozen algorithm bytes changed: " + name)
    if sha(ROOT / "independent/plan.json") != frozen["plan_sha256"]:
        raise ValueError("frozen plan bytes changed")
    return frozen, {"freeze_sha256": sha(FREEZE), "plan_sha256": frozen["plan_sha256"],
        "frozen_source_commit": frozen["source_commit"], "frozen_sources": frozen["sources"],
        "execution_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT,
                                                     text=True).strip(),
        "debug_script_sha256": sha(SCRIPT)}


def declare():
    frozen, bound = identity()
    if any(os.environ.get(key) != "1" for key in THREAD_KEYS):
        raise ValueError("all declared BLAS/OpenMP thread variables must equal 1")
    RUN.mkdir()
    write(RUN / "START.json", {"schema": "hepta.shared-profile-start.v1", **bound,
        "function": "independent.run.prepare_shared(plan, run, runtime_plan)",
        "shared_phase_calls": 1, "created_unix_ns": time.time_ns(), "cwd": str(ROOT),
        "python": sys.version, "thread_environment": {key: os.environ[key] for key in THREAD_KEYS},
        "frozen_plan": frozen["plan"], "scope": "TRAIN and validation only; no test construction",
        "accounting": "full unchanged operator ledger; actual process, child, thread CPU and wall; "
            "cProfile, raw-measure capture and GC/resource observation overhead retained; "
            "post-phase profile/JSON persistence is diagnostic administration",
        "instrumentation": "measure wrapper calls original exactly once and retains cost receipts; "
            "no output, model, plan, objective or runtime algorithm changes",
        "interpretation": "exactly one debug shared phase; cannot replace T7, count as a pass, "
            "or establish an uninstrumented CPU time"})
    print(json.dumps({"declared": str(RUN / "START.json"), "shared_phase_calls": 1}))


def child_usage():
    usage = resource.getrusage(resource.RUSAGE_CHILDREN)
    return {"user_cpu_ns": round(usage.ru_utime * 1e9),
            "system_cpu_ns": round(usage.ru_stime * 1e9),
            "minor_faults": usage.ru_minflt, "major_faults": usage.ru_majflt,
            "voluntary_context_switches": usage.ru_nvcsw,
            "involuntary_context_switches": usage.ru_nivcsw}


def execute():
    frozen, bound = identity()
    start = json.loads((RUN / "START.json").read_text())
    if any(start[key] != value for key, value in bound.items()):
        raise ValueError("declaration identity changed")
    if any(os.environ.get(key) != "1" for key in THREAD_KEYS):
        raise ValueError("declared thread environment changed")
    write(RUN / "RUNNING.json", {"started_unix_ns": time.time_ns(), "pid": os.getpid(),
                                 "shared_phase_calls_authorized": 1})
    import independent.evaluation as evaluation
    from independent.run import prepare_shared, traced_phase
    from independent.data_v2 import manifest
    raw_samples, telemetry = [], []
    original_measure = evaluation.measure

    def measured(*args, **kwargs):
        result = original_measure(*args, **kwargs)
        raw_samples.append({"mode": args[2], "seed": kwargs.get("seed"),
            "observe": kwargs.get("observe"), "cost": result["cost"],
            "per_row_cost": result["per_row_cost"]})
        return result

    evaluation.measure = measured
    profiler = cProfile.Profile()
    child_before = child_usage()
    clocks_before = (time.process_time_ns(), time.thread_time_ns(), time.perf_counter_ns())
    result = {"schema": "hepta.shared-profile-result.v1", **bound,
              "qualification": False, "phase_calls": 1}
    try:
        with traced_phase(telemetry, "profile_prepare_shared"):
            profiler.enable()
            try:
                shared, bases, train, val, common = prepare_shared(frozen["plan"], RUN, dict(frozen["plan"]))
            finally:
                profiler.disable()
        result.update(outcome="debug phase completed; not qualification", common=common,
            shared_ledger=shared.snapshot(), train=manifest(train), validation=manifest(val),
            base_digests={str(seed): model.digest() for seed, model in bases.items()})
    except BaseException as error:
        result.update(outcome="debug phase failed; no retry", exception=repr(error),
                      traceback=traceback.format_exc())
        raise
    finally:
        clocks_after = (time.process_time_ns(), time.thread_time_ns(), time.perf_counter_ns())
        child_after = child_usage()
        evaluation.measure = original_measure
        profiler.dump_stats(str(RUN / "prepare_shared.pstats"))
        stats = pstats.Stats(profiler)
        rows = [{"file": key[0], "line": key[1], "function": key[2],
                 "primitive_calls": value[0], "total_calls": value[1],
                 "tottime_seconds": value[2], "cumulative_seconds": value[3]}
                for key, value in stats.stats.items()]
        result.update(actual_clocks_ns=dict(zip(("process_cpu", "main_thread_cpu", "wall"),
                           (end - begin for begin, end in zip(clocks_before, clocks_after)))),
            child_before=child_before, child_after=child_after,
            child_difference={key: child_after[key] - child_before[key] for key in child_before},
            telemetry=telemetry, calibration_raw_samples=raw_samples,
            profiler={"total_calls": stats.total_calls, "primitive_calls": stats.prim_calls,
                      "total_tottime_seconds": stats.total_tt,
                      "top80_cumulative": sorted(rows, key=lambda r: r["cumulative_seconds"], reverse=True)[:80],
                      "top80_tottime": sorted(rows, key=lambda r: r["tottime_seconds"], reverse=True)[:80]})
        write(RUN / "profile.json", result)
        files = {str(path.relative_to(RUN)): {"sha256": sha(path), "bytes": path.stat().st_size}
                 for path in sorted(RUN.rglob("*")) if path.is_file()}
        write(RUN / "manifest.json", {"schema": "hepta.shared-profile-artifacts.v1", "files": files})
        print(json.dumps({"outcome": result["outcome"], "actual_clocks_ns": result["actual_clocks_ns"],
                          "child_cpu_ns": sum(result["child_difference"][key]
                                              for key in ("user_cpu_ns", "system_cpu_ns")),
                          "calibration_calls": len(raw_samples), "profile": str(RUN / "profile.json")}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("declare", "execute"))
    action = parser.parse_args().action
    declare() if action == "declare" else execute()
