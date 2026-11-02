"""Create-only paired engineering replay and actual 1,000-use deployment groups."""

import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import resource
import subprocess
import sys
import tempfile
import time
import tracemalloc

import numpy as np

from ..addressed_decision_r15_20261101.law import Law
from ..addressed_decision_r15_20261101.world import make_episode
from ..planner_fastpath_r18_20261101 import execution as fast_execution
from ..planner_fastpath_r18_20261101.planner import BatchedPlanner, KernelCache
from ..support_retention_r16_20261101.compression import BlockLaw
from ..support_retention_r16_20261101.execution import execute as baseline
from .planner import OwnedPlanner

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
MODES = ("baseline", "r18", "r19")


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


def run(mode, law, episode, representation, checkpoint, cache):
    if mode == "baseline":
        return baseline(law, episode, representation=representation, checkpoint_path=checkpoint)
    fast_execution.BatchedPlanner = BatchedPlanner if mode == "r18" else OwnedPlanner
    return fast_execution.execute(law, episode, representation=representation,
                                  checkpoint_path=checkpoint, cache=cache)


def worker(output, diagnostic):
    protocol = json.loads((HERE / "PROTOCOL.json").read_text())
    manifest = json.loads((HERE / "SOURCE_MANIFEST.json").read_text())
    for name, digest in manifest["files"].items():
        if hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != digest:
            raise RuntimeError(f"Source changed: {name}")
    if not diagnostic:
        publication = json.loads((HERE / "PUBLICATION.json").read_text())
        if publication["manifest_sha256"] != hashlib.sha256((HERE / "SOURCE_MANIFEST.json").read_bytes()).hexdigest():
            raise RuntimeError("Unbound publication receipt")
    model_path = ROOT / protocol["training_archive"]
    models = json.loads(gzip.decompress(model_path.read_bytes()))["calibration"]["models"]
    owner = Law()
    n = protocol["diagnostic_uses"] if diagnostic else protocol["uses_per_group"]
    all_groups, mismatches = [], 0
    # World generation and all three variants are inside the outer wait4 scope.
    # Its costs are shared evaluation overhead, not charged as execution savings.
    namespace = protocol["diagnostic_namespace"] if diagnostic else protocol["namespace"]
    worlds = [make_episode(owner, namespace * 10**9 + index,
                           protocol["domains"][index % 2]) for index in range(n)]
    for model in protocol["models"]:
        for representation in protocol["representations"]:
            laws, caches, preparation = {}, {}, {}
            for mode in MODES:
                started = time.process_time()
                laws[mode] = BlockLaw.from_payload(models[model]["payload"])
                caches[mode] = KernelCache()
                preparation[mode] = time.process_time() - started
            records = []
            with tempfile.TemporaryDirectory(prefix="hcsn-r19-cost-") as directory:
                for index, episode in enumerate(worlds):
                    results = {}
                    # Fixed Latin rotation prevents one mode always running first.
                    order = MODES[index % 3:] + MODES[:index % 3]
                    for mode in order:
                        row = run(mode, laws[mode], episode, representation,
                                  Path(directory) / (mode + ".json"), caches[mode])
                        body = semantic(row)
                        results[mode] = dict(semantic_sha256=hashlib.sha256(
                            json.dumps(body, sort_keys=True, separators=(",", ":"),
                                       allow_nan=False).encode()).hexdigest(),
                            cpu_seconds=row["cpu_seconds"], wall_seconds=row["wall_seconds"],
                            checkpoint_io_cpu_seconds=row["checkpoint_io_cpu_seconds"],
                            utility=row["utility"], reward=row["reward"], fee=row["fee"], semantic=body)
                    equal = len({row["semantic_sha256"] for row in results.values()}) == 1
                    mismatches += not equal
                    records.append(dict(index=index, seed=episode.seed, world=episode.fingerprint,
                                        order=list(order), equal=equal, modes=results))
            memory = {}
            for mode in MODES:
                peaks = []
                for episode in worlds[:protocol["memory_uses"]]:
                    tracemalloc.start()
                    run(mode, laws[mode], episode, representation, None, caches[mode])
                    _, peak = tracemalloc.get_traced_memory()
                    tracemalloc.stop()
                    peaks.append(peak)
                memory[mode] = dict(peaks=peaks, maximum=max(peaks), mean=float(np.mean(peaks)))
            costs = {mode: preparation[mode] + sum(r["modes"][mode]["cpu_seconds"] for r in records)
                     for mode in MODES}
            walls = {mode: sum(r["modes"][mode]["wall_seconds"] for r in records) for mode in MODES}
            group = dict(model=model, representation=representation, uses=n, preparation=preparation,
                         cpu_with_preparation=costs, actor_wall_seconds=walls,
                         measured_actor_episodes_per_second={mode: n / walls[mode] for mode in MODES},
                         r19_baseline_cpu_ratio=costs["r19"] / costs["baseline"],
                         r19_r18_cpu_ratio=costs["r19"] / costs["r18"], memory=memory,
                         r19_r18_peak_ratio=memory["r19"]["maximum"] / memory["r18"]["maximum"],
                         r19_baseline_peak_ratio=memory["r19"]["maximum"] / memory["baseline"]["maximum"])
            for offset in range(0, len(records), 100):
                save(output / f"{model}_{representation}_{offset // 100:02}.json.gz",
                     dict(group=group, records=records[offset:offset + 100]))
            all_groups.append(group)
    save(output / "SUMMARY.json", dict(groups=all_groups, mismatches=mismatches,
         timed_execution_count=n * len(all_groups) * 3,
         memory_execution_count=min(n, protocol["memory_uses"]) * len(all_groups) * 3,
         total_execution_count=(n + min(n, protocol["memory_uses"])) * len(all_groups) * 3,
         paired_world_uses=n * len(all_groups),
         role="engineering replay of one frozen fit; not independent scientific efficacy samples",
         original_online_cpu_gate=all(g["r19_baseline_cpu_ratio"] <= .90 for g in all_groups),
         allocation_reduction_gate=all(g["r19_r18_peak_ratio"] <= .90 for g in all_groups)))
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
        started = time.perf_counter()
        before = resource.getrusage(resource.RUSAGE_SELF)
        child = subprocess.Popen([sys.executable, "-m", __spec__.name, "--worker", "--output",
                                  str(args.output)] + (["--diagnostic"] if args.diagnostic else []))
        _, status, usage = os.wait4(child.pid, 0)
        code = os.waitstatus_to_exitcode(status)
        after = resource.getrusage(resource.RUSAGE_SELF)
        save(args.output / "PROCESS_RECEIPT.json", dict(exit_code=code,
             child_cpu_seconds=usage.ru_utime + usage.ru_stime,
             supervisor_cpu_seconds=(after.ru_utime + after.ru_stime - before.ru_utime - before.ru_stime),
             wall_seconds=time.perf_counter() - started, linux_max_rss_kib=usage.ru_maxrss,
             scope="Complete child imports, source checks, world generation, every execution, memory diagnostics, archive writes; nested actor costs not added"))
        raise SystemExit(code)
