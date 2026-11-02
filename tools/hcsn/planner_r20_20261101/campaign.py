"""Frozen eight-fit, four-implementation all-query durability resource campaign."""

import argparse
import gzip
import hashlib
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
from ..addressed_decision_r15_20261101.world import make_episode
from ..planner_fastpath_r18_20261101.planner import KernelCache
from ..support_retention_r16_20261101.compression import BlockLaw
from .execution import execute

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
MODES = ("baseline", "r18", "r19", "r20")


def save(path, value):
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    if path.suffix == ".gz":
        raw = gzip.compress(raw, mtime=0)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(raw)


def semantic(row):
    return {k: v for k, v in row.items() if k not in
            ("cpu_seconds", "wall_seconds", "checkpoint_io_cpu_seconds")}


def worker(output, diagnostic):
    protocol = json.loads((HERE / "PROTOCOL.json").read_text())
    manifest = json.loads((HERE / "SOURCE_MANIFEST.json").read_text())
    for name, digest in manifest["files"].items():
        if hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != digest:
            raise RuntimeError(f"Changed frozen input: {name}")
    if not diagnostic:
        receipt = json.loads((HERE / "PUBLICATION.json").read_text())
        if receipt["manifest_sha256"] != hashlib.sha256((HERE / "SOURCE_MANIFEST.json").read_bytes()).hexdigest():
            raise RuntimeError("Unbound source publication")
    fits = protocol["diagnostic_fits"] if diagnostic else protocol["fits"]
    n = protocol["diagnostic_uses"] if diagnostic else protocol["uses_per_fit_group"]
    namespace = protocol["diagnostic_namespace"] if diagnostic else protocol["namespace"]
    owner, groups, mismatches = Law(), [], 0
    for fit in fits:
        model_path = ROOT / f"tools/hcsn/addressed_decision_r15_20261101/run_01/training/{fit}.json.gz"
        models = json.loads(gzip.decompress(model_path.read_bytes()))["calibration"]["models"]
        worlds = [make_episode(owner, namespace * 10**10 + fit * 10**4 + index,
                               protocol["domains"][index % 2]) for index in range(n)]
        for model in protocol["models"]:
            for representation in protocol["representations"]:
                laws, caches, preparation = {}, {}, {}
                for mode in MODES:
                    start = time.process_time()
                    laws[mode] = BlockLaw.from_payload(models[model]["payload"])
                    caches[mode] = KernelCache()
                    preparation[mode] = time.process_time() - start
                records = []
                with tempfile.TemporaryDirectory(prefix="hcsn-r20-all-query-") as directory:
                    for index, episode in enumerate(worlds):
                        results = {}
                        order = MODES[index % 4:] + MODES[:index % 4]
                        for mode in order:
                            try:
                                row = execute(laws[mode], episode, mode, representation,
                                              Path(directory) / (mode + ".json"), caches[mode])
                            except Exception as exc:
                                save(output / f"FAILED_{fit}_{model}_{representation}_{index}_{mode}.json",
                                     dict(fit=fit, model=model, representation=representation, index=index,
                                          mode=mode, error=repr(exc), completed=records, current=results))
                                raise
                            body = semantic(row)
                            results[mode] = dict(semantic=body, semantic_sha256=hashlib.sha256(
                                json.dumps(body, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest(),
                                cpu_seconds=row["cpu_seconds"], wall_seconds=row["wall_seconds"],
                                checkpoint_io_cpu_seconds=row["checkpoint_io_cpu_seconds"])
                        equal = len({r["semantic_sha256"] for r in results.values()}) == 1
                        mismatches += not equal
                        records.append(dict(index=index, seed=episode.seed, world=episode.fingerprint,
                                            order=list(order), equal=equal, modes=results))
                    memory = {}
                    for mode in MODES:
                        peaks = []
                        for episode in worlds[:protocol["memory_uses"]]:
                            tracemalloc.start()
                            execute(laws[mode], episode, mode, representation,
                                    Path(directory) / (mode + ".json"), caches[mode])
                            _, peak = tracemalloc.get_traced_memory()
                            tracemalloc.stop()
                            peaks.append(peak)
                        memory[mode] = dict(peaks=peaks, maximum=max(peaks), mean=float(np.mean(peaks)))
                cpu = {mode: preparation[mode] + sum(r["modes"][mode]["cpu_seconds"] for r in records)
                       for mode in MODES}
                wall = {mode: sum(r["modes"][mode]["wall_seconds"] for r in records) for mode in MODES}
                group = dict(fit=fit, model=model, representation=representation, uses=n,
                             preparation=preparation, cpu_with_preparation=cpu,
                             actor_wall_seconds=wall, memory=memory,
                             actor_episodes_per_second={mode: n / wall[mode] for mode in MODES},
                             r20_baseline_cpu_ratio=cpu["r20"] / cpu["baseline"],
                             r20_r18_cpu_ratio=cpu["r20"] / cpu["r18"],
                             r20_r19_cpu_ratio=cpu["r20"] / cpu["r19"],
                             r20_r18_peak_ratio=memory["r20"]["maximum"] / memory["r18"]["maximum"])
                save(output / f"{fit}_{model}_{representation}.json.gz", dict(group=group, records=records))
                groups.append(group)
    pooled = {}
    for model in protocol["models"]:
        for representation in protocol["representations"]:
            selected = [g for g in groups if g["model"] == model and g["representation"] == representation]
            cpu = {mode: sum(g["cpu_with_preparation"][mode] for g in selected) for mode in MODES}
            pooled[model + "|" + representation] = dict(cpu_with_preparation=cpu,
                r20_baseline_cpu_ratio=cpu["r20"] / cpu["baseline"],
                r20_r18_cpu_ratio=cpu["r20"] / cpu["r18"])
    actual_savings = sum(g["cpu_with_preparation"]["baseline"] - g["cpu_with_preparation"]["r20"] for g in groups)
    prior_floor = protocol["historical_r18_investment_cpu_seconds"] + protocol["historical_r19_investment_cpu_seconds"]
    save(output / "SUMMARY.json", dict(groups=groups, pooled=pooled, mismatches=mismatches,
         frozen_fit_count=len(fits), unique_worlds=len(fits) * n, actual_uses_per_fit_group=n,
         timed_executions=len(groups) * n * 4,
         memory_executions=len(groups) * min(n, protocol["memory_uses"]) * 4,
         original_cpu_gate=all(g["r20_baseline_cpu_ratio"] <= .90 for g in groups),
         joint_cpu_memory_gate=all(g["r20_r18_cpu_ratio"] <= 1. and g["r20_r18_peak_ratio"] <= .90 for g in groups),
         actual_actor_cpu_savings=actual_savings, historical_investment_cpu_floor=prior_floor,
         savings_minus_historical_floor=actual_savings - prior_floor,
         full_investment_gate=False if actual_savings <= prior_floor else None,
         production_activation=False,
         role="Registered finite Linux all-six-query durability engineering profile; not historicalquery2profile or1000-use qualification"))
    if mismatches:
        raise RuntimeError(f"Semantic mismatches: {mismatches}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--worker", action="store_true")
    parser.add_argument("--diagnostic", action="store_true")
    args = parser.parse_args()
    if args.worker:
        worker(args.output, args.diagnostic)
    else:
        if args.output.exists():
            raise FileExistsError(args.output)
        wall = time.perf_counter()
        child = subprocess.Popen([sys.executable, "-m", __spec__.name, "--worker", "--output", str(args.output)]
                                 + (["--diagnostic"] if args.diagnostic else []))
        _, status, usage = os.wait4(child.pid, 0)
        code = os.waitstatus_to_exitcode(status)
        save(args.output / "PROCESS_RECEIPT.json", dict(exit_code=code,
             complete_child_cpu_seconds=usage.ru_utime + usage.ru_stime,
             wall_seconds=time.perf_counter() - wall, linux_max_rss_kib=usage.ru_maxrss,
             scope="Complete child imports, allpreparation/worlds/executions/all-query commits/memory/archives; nested costs not added, supervisorstartup excluded"))
        raise SystemExit(code)
