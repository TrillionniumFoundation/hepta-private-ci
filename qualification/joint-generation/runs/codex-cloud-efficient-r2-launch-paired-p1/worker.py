"""One prospective timer-only diagnostic; no qualification or test opening."""
import argparse
import contextlib
import io
import warnings
import hashlib
import json
import os
from pathlib import Path
import resource
import subprocess
import sys
import time
import traceback

BASE = Path(__file__).resolve().parent
RUN = BASE
ROOT = BASE.parents[1]
ORDER = ("A1", "B1", "B2", "A2")
sys.path.insert(0, str(ROOT))
FREEZE = ROOT / "independent/frozen-r2-ledger-cache.json"
THREADS = ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS")


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(name, value):
    with (RUN / name).open("x") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False,
                  default=lambda item: item.tolist())
        stream.write("\n")


def verify():
    protocol = json.loads((BASE / "protocol.json").read_text())
    frozen = json.loads(FREEZE.read_text())
    if (sha(__file__) != protocol["worker_sha256"] or sha(FREEZE) != protocol["freeze_sha256"]
            or sha(BASE / "launcher.py") != protocol["launcher_sha256"]):
        raise ValueError("worker/freeze changed after protocol")
    if sha(ROOT / "independent/plan.json") != frozen["plan_sha256"]:
        raise ValueError("frozen plan changed")
    for name, digest in frozen["sources"].items():
        if sha(ROOT / name) != digest:
            raise ValueError("frozen algorithm changed: " + name)
    if any(os.environ.get(key) != "1" for key in THREADS):
        raise ValueError("required single-thread environment differs")
    return protocol, frozen


def clock():
    child = resource.getrusage(resource.RUSAGE_CHILDREN)
    return {"process_cpu_ns": time.process_time_ns(), "thread_cpu_ns": time.thread_time_ns(),
            "child_cpu_ns": round((child.ru_utime + child.ru_stime) * 1e9),
            "wall_ns": time.perf_counter_ns()}


def delta(before, after):
    out = {key: after[key] - value for key, value in before.items()}
    out["total_cpu_ns"] = out["process_cpu_ns"] + out["child_cpu_ns"]
    return out


def execute():
    diagnostic_start = clock()
    verification_start = clock()
    protocol, frozen = verify()
    verification_clocks = delta(verification_start, clock())
    for previous in ORDER[:ORDER.index(RUN.name)]:
        if not (BASE / previous / "WORKER_COMPLETE.json").exists():
            raise ValueError("fixed prior sample has not finished: " + previous)
    declaration = json.loads((BASE / "START.json").read_text())
    if declaration["protocol_sha256"] != sha(BASE / "protocol.json"):
        raise ValueError("protocol changed after START")
    RUN.mkdir()
    write("RUNNING.json", {"pid": os.getpid(), "started_unix_ns": time.time_ns(), "phase_calls": 1})
    imports_start = clock()
    import independent.run as driver
    import independent.evaluation as evaluation
    import independent.native as native
    from independent.data_v2 import manifest
    import numpy as np
    import threadpoolctl
    imports_clocks = delta(imports_start, clock())

    def boundary():
        return {"task_count": len(list(Path("/proc/self/task").iterdir())),
            "affinity": sorted(os.sched_getaffinity(0)),
            "threadpools": [{k: row[k] for k in ("internal_api", "num_threads", "version", "filepath")}
                            for row in threadpoolctl.threadpool_info()]}

    def runtime():
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            np.show_runtime(); np.show_config()
        keys = (*THREADS, "BLIS_NUM_THREADS", "VECLIB_MAXIMUM_THREADS", "NUMEXPR_NUM_THREADS",
            "PYTHONDONTWRITEBYTECODE", "PYTHONNOUSERSITE", "PYTHONOPTIMIZE", "PYTHONMALLOC",
            "PYTHONWARNINGS", "LD_PRELOAD")
        libraries = [{**row, "sha256": sha(row["filepath"])} for row in threadpoolctl.threadpool_info()]
        return {"executable": sys.executable, "executable_realpath": str(Path(sys.executable).resolve()),
            "python": sys.version, "flags": repr(sys.flags), "numpy_version": np.__version__,
            "numpy_path": np.__file__, "numpy_binary_path": np._core._multiarray_umath.__file__,
            "numpy_binary_sha256": sha(np._core._multiarray_umath.__file__), "numpy_geterr": np.geterr(),
            "numpy_cpu_features": np._core._multiarray_umath.__cpu_features__,
            "runtime_config": buf.getvalue(), "threadpools": libraries, "boundary": boundary(),
            "sys_trace": repr(sys.gettrace()), "sys_profile": repr(sys.getprofile()),
            "safe_environment": {key: os.environ.get(key) for key in keys},
            "warnings_filters": [repr(row) for row in warnings.filters], "pid": os.getpid(),
            "parent_pid": os.getppid(), "parent_executable": os.readlink(f"/proc/{os.getppid()}/exe")}

    runtime_before = runtime()
    spans, probes, telemetry, restorations = [], [], [], []
    state = {"active": None, "seed": None, "decoder_index": 0}

    def begin(phase, **metadata):
        if state["active"] is not None:
            raise RuntimeError("overlapping diagnostic spans")
        metadata["before_boundary"] = boundary()
        state["active"] = (phase, metadata, clock())

    def end(*, incomplete=False):
        after = clock()
        phase, metadata, before = state["active"]
        state["active"] = None
        spans.append({"phase": phase, **metadata, "after_boundary": boundary(),
                      "incomplete": incomplete, **delta(before, after)})

    def call(phase, operation, *args, **kwargs):
        begin(phase, seed=state["seed"])
        try:
            return operation(*args, **kwargs)
        finally:
            end(incomplete=sys.exc_info()[0] is not None)

    def replace(module, name, operation):
        original = getattr(module, name)
        restorations.append((module, name, original))
        setattr(module, name, operation(original))

    def data_wrapper(original):
        def data(split, *args, **kwargs):
            if split not in ("train", "validation"):
                raise ValueError("diagnostic forbids other dataset splits")
            return call("dataset_" + split, original, split, *args, **kwargs)
        return data

    replace(driver, "dataset", data_wrapper)
    replace(driver, "stratified_indices", lambda original: lambda *a, **k:
            (begin("matching_manifest"), original(*a, **k))[1])

    def matching_wrapper(original):
        def matching(*args, **kwargs):
            try:
                return original(*args, **kwargs)
            finally:
                end(incomplete=sys.exc_info()[0] is not None)
        return matching

    replace(driver, "calibration_manifest", matching_wrapper)
    replace(native, "compile_native", lambda original: lambda *a, **k: call("compile", original, *a, **k))

    def model_factory(original):
        def factory(*args, **kwargs):
            counted = original(*args, **kwargs)
            class Timed(counted):
                def fit_decoder(self, *a, **k):
                    state["seed"] = frozen["plan"]["model_seeds"][state["decoder_index"]]
                    state["decoder_index"] += 1
                    return call("decoder", super().fit_decoder, *a, **k)
            return Timed
        return factory

    replace(driver, "counted_model_class", model_factory)

    def objective_wrapper(original):
        def objective(*args, **kwargs):
            out = original(*args, **kwargs)
            begin("pretrain_loop", seed=state["seed"])
            return out
        return objective

    replace(driver, "CachedObjective", objective_wrapper)

    def validation_wrapper(original):
        def validation(*args, **kwargs):
            end()
            return call("validation", original, *args, **kwargs)
        return validation

    replace(driver, "batch_validation", validation_wrapper)
    replace(driver, "save_model", lambda original: lambda *a, **k: call("export", original, *a, **k))

    def measure_wrapper(original):
        def measure(*args, **kwargs):
            begin("calibration_measure", seed=kwargs["seed"], mode=args[2], ordinal=len(probes))
            try:
                result = original(*args, **kwargs)
            finally:
                end(incomplete=sys.exc_info()[0] is not None)
            probes.append({"span_index": len(spans) - 1, "result": result})
            return result
        return measure

    replace(evaluation, "measure", measure_wrapper)
    result = {"schema": "hepta.shared-timing-result.v1", "qualification": False,
              "protocol_sha256": sha(BASE / "protocol.json"), "phase_calls": 1,
              "sample": RUN.name, "launch_kind": "direct" if RUN.name.startswith("A") else "nested",
              "verification_clocks": verification_clocks, "imports_clocks": imports_clocks,
              "runtime_before": runtime_before,
              "source_commit": frozen["source_commit"], "execution_commit": subprocess.check_output(
                  ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()}
    whole_start = clock()
    whole_after = None
    try:
        with driver.traced_phase(telemetry, "timer_only_prepare_shared"):
            shared, bases, train, val, common = driver.prepare_shared(frozen["plan"], RUN, dict(frozen["plan"]))
        whole_after = clock()
        result.update(outcome="diagnostic completed; original T8 failure retained", common=common,
                      ledger=shared.snapshot(), train=manifest(train), validation=manifest(val))
    except BaseException as error:
        result.update(outcome="diagnostic failed; no retry", error=repr(error), traceback=traceback.format_exc())
        raise
    finally:
        if whole_after is None:
            whole_after = clock()
        if state["active"] is not None:
            end(incomplete=True)
        for module, name, original in reversed(restorations):
            setattr(module, name, original)
        whole = delta(whole_start, whole_after)
        summed = {key: sum(row[key] for row in spans) for key in whole}
        result.update(spans=spans, calibration_probes=probes, telemetry=telemetry,
            observed_shared_clocks=whole, sum_disjoint_spans=summed,
            residual={key: whole[key] - summed[key] for key in whole},
            diagnostic_clocks=delta(diagnostic_start, clock()),
            base_comparison={str(seed): {"sha256": sha(RUN / f"base-{seed}.npz"),
                "equals_t8": sha(RUN / f"base-{seed}.npz") == sha(ROOT / f"runs/codex-cloud-efficient-r2-t8/base-{seed}.npz")}
                for seed in frozen["plan"]["model_seeds"] if (RUN / f"base-{seed}.npz").exists()})
        result["runtime_after"] = runtime()
        write("timing.json", result)
        write("manifest.json", {str(p.relative_to(RUN)): {"sha256": sha(p), "bytes": p.stat().st_size}
                                for p in sorted(RUN.rglob("*")) if p.is_file()})
        complete = clock()
        complete["total_cpu_ns"] = complete["process_cpu_ns"] + complete["child_cpu_ns"]
        complete["wall_since_execute_entry_ns"] = complete["wall_ns"] - diagnostic_start["wall_ns"]
        write("WORKER_COMPLETE.json", {"clock": complete, "outcome": result["outcome"],
            "scope": "cumulative process+children CPU through all prior diagnostic persistence; final counter write/print excluded"})
        print(json.dumps({"outcome": result["outcome"], "shared": whole,
                          "residual": result["residual"], "measure_calls": len(probes)}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("declare", "execute"))
    parser.add_argument("sample", nargs="?", choices=ORDER)
    args = parser.parse_args()
    if args.action == "declare":
        verify()
        write("START.json", {"protocol_sha256": sha(BASE / "protocol.json"),
                             "created_unix_ns": time.time_ns(), "order": ORDER, "phase_calls": 4})
        print("declared exactly one paired nonqualification probe: A1 B1 B2 A2")
    else:
        if args.sample is None:
            parser.error("one fixed sample is required")
        RUN = BASE / args.sample
        execute()
