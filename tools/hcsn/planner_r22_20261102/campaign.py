"""Prospectively frozen matched shared-validator and original resource gates."""

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
from ..checkpoint_fastpath_r21_20261101 import execution as old
from ..planner_fastpath_r18_20261101.planner import KernelCache
from ..planner_r20_20261101.campaign import ROOT, save, semantic
from ..support_retention_r16_20261101 import compression as old_memory
from . import execution as new, memory as new_memory

HERE = Path(__file__).resolve().parent
VERSIONS = ("old", "new")


def verify_sources():
    path = HERE / "SOURCE_MANIFEST.json"
    for name, digest in json.loads(path.read_text())["files"].items():
        if hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != digest:
            raise RuntimeError(f"Changed frozen input: {name}")
    receipt = json.loads((HERE / "PUBLICATION.json").read_text())
    if receipt["manifest_sha256"] != hashlib.sha256(path.read_bytes()).hexdigest():
        raise RuntimeError("Unbound R22 publication")


def worker(output):
    verify_sources()
    protocol = json.loads((HERE / "PROTOCOL.json").read_text())
    rng = np.random.default_rng(protocol["order_seed"])
    owner, groups, comparisons, mismatches = Law(), [], [], 0
    for fit in protocol["fits"]:
        archive = ROOT / f"tools/hcsn/addressed_decision_r15_20261101/run_01/training/{fit}.json.gz"
        models = json.loads(gzip.decompress(archive.read_bytes()))["calibration"]["models"]
        worlds = [make_episode(owner, protocol["namespace"] * 10**10 + fit * 10**4 + i,
                               protocol["domains"][i % 2]) for i in range(protocol["uses_per_fit_group"])]
        for model in protocol["models"]:
            for representation in protocol["representations"]:
                laws, caches, preparation, preparation_wall = {}, {}, {}, {}
                arms = [(variant, version) for variant in protocol["variants"] for version in VERSIONS]
                for position in rng.permutation(len(arms)):
                    arm = arms[int(position)]
                    started, wall = time.process_time(), time.perf_counter()
                    memory = old_memory if arm[1] == "old" else new_memory
                    laws[arm] = memory.BlockLaw.from_payload(models[model]["payload"])
                    caches[arm] = KernelCache()
                    preparation[arm] = time.process_time() - started
                    preparation_wall[arm] = time.perf_counter() - wall
                    assert laws[arm].identity == models[model]["payload"]["identity"]
                records, memory_peaks = [], {}
                with tempfile.TemporaryDirectory(prefix="r22-all-six-durable-") as directory:
                    for index, episode in enumerate(worlds):
                        variants = list(rng.permutation(protocol["variants"]))
                        order = [(variant, version) for variant in variants
                                 for version in (VERSIONS if rng.integers(2) == 0 else VERSIONS[::-1])]
                        results = {}
                        for variant, version in order:
                            module = old if version == "old" else new
                            arm = (variant, version)
                            path = Path(directory) / (variant + "_" + version + ".json")
                            try:
                                row = module.execute(laws[arm], episode, variant, representation, path, caches[arm])
                            except Exception as error:
                                save(output / f"FAILED_{fit}_{model}_{representation}_{index}.json",
                                     dict(error=repr(error), arm=arm, completed=records, current=results))
                                raise
                            results[variant + "|" + version] = dict(result=row,
                                final_wire_sha256=hashlib.sha256(path.read_bytes()).hexdigest())
                        equal = all(semantic(result["result"]) == semantic(next(iter(results.values()))["result"])
                                    for result in results.values())
                        wire_equal = len({result["final_wire_sha256"] for result in results.values()}) == 1
                        mismatches += not (equal and wire_equal)
                        records.append(dict(index=index, seed=episode.seed, world=episode.fingerprint,
                                            order=order, exact_semantics=equal, exact_wire=wire_equal, outcomes=results))
                    for variant, version in arms:
                        module = old if version == "old" else new
                        arm, peaks = (variant, version), []
                        for episode in worlds[:protocol["memory_uses"]]:
                            tracemalloc.start()
                            module.execute(laws[arm], episode, variant, representation,
                                           Path(directory) / (variant + "_" + version + ".json"), caches[arm])
                            _, peak = tracemalloc.get_traced_memory()
                            tracemalloc.stop()
                            peaks.append(peak)
                        memory_peaks[variant + "|" + version] = peaks
                summaries = {}
                for variant, version in arms:
                    key, arm = variant + "|" + version, (variant, version)
                    actor_rows = [record["outcomes"][key]["result"] for record in records]
                    walls = [row["wall_seconds"] for row in actor_rows]
                    cpu = preparation[arm] + sum(row["cpu_seconds"] for row in actor_rows)
                    wall = preparation_wall[arm] + sum(walls)
                    summaries[key] = dict(preparation_cpu=preparation[arm], preparation_wall=preparation_wall[arm],
                        cpu_with_preparation=cpu, wall_with_preparation=wall, actor_wall_seconds=sum(walls),
                        actor_latency_p50=float(np.quantile(walls, .5)), actor_latency_p95=float(np.quantile(walls, .95)),
                        episodes_per_second=len(worlds) / wall, memory_peaks=memory_peaks[key],
                        maximum_peak_bytes=max(memory_peaks[key]))
                software = []
                for variant in protocol["variants"]:
                    a, b = summaries[variant + "|old"], summaries[variant + "|new"]
                    software.append(dict(fit=fit, model=model, representation=representation, variant=variant,
                        new_old_cpu_ratio=b["cpu_with_preparation"] / a["cpu_with_preparation"],
                        new_old_peak_ratio=b["maximum_peak_bytes"] / a["maximum_peak_bytes"]))
                comparisons.extend(software)
                selected, baseline, r18 = [summaries[name + "|new"] for name in ("r20", "baseline", "r18")]
                group = dict(fit=fit, model=model, representation=representation, uses=len(worlds), arms=summaries,
                    shared_software_comparisons=software,
                    original_cpu_ratio=selected["cpu_with_preparation"] / baseline["cpu_with_preparation"],
                    joint_cpu_ratio=selected["cpu_with_preparation"] / r18["cpu_with_preparation"],
                    joint_peak_ratio=selected["maximum_peak_bytes"] / r18["maximum_peak_bytes"])
                save(output / f"{fit}_{model}_{representation}.json.gz", dict(group=group, records=records))
                groups.append(group)
        print(json.dumps(dict(completed_fit=fit, fit_groups=len(groups), mismatches=mismatches)), flush=True)
    cpu = {variant + "|" + version: sum(g["arms"][variant + "|" + version]["cpu_with_preparation"] for g in groups)
           for variant in protocol["variants"] for version in VERSIONS}
    actual_savings = cpu["baseline|new"] - cpu["r20|new"]
    shared_savings = sum(cpu[variant + "|old"] - cpu[variant + "|new"] for variant in protocol["variants"])
    save(output / "SUMMARY.json", dict(groups=groups, software_comparisons=comparisons,
        mismatches=mismatches, frozen_fit_count=len(protocol["fits"]), unique_worlds=len(protocol["fits"]) * len(worlds),
        actual_uses_per_fit_group=len(worlds), timed_executions=len(groups) * len(worlds) * len(arms),
        memory_executions=len(groups) * protocol["memory_uses"] * len(arms), actual_arm_cpu=cpu,
        original_cpu_gate=all(g["original_cpu_ratio"] <= protocol["original_cpu_ratio_maximum"] for g in groups),
        joint_cpu_memory_gate=all(g["joint_cpu_ratio"] <= 1. and g["joint_peak_ratio"] <= .90 for g in groups),
        shared_software_cpu_memory_gate=all(g["new_old_cpu_ratio"] <= .90 and g["new_old_peak_ratio"] <= 1.
                                            for g in comparisons),
        actual_actor_cpu_savings_vs_shared_baseline=actual_savings, actual_shared_fix_cpu_savings=shared_savings,
        historical_recorded_cpu_floor=protocol["historical_recorded_cpu_floor"],
        full_investment_gate=False if max(actual_savings, shared_savings) <= protocol["historical_recorded_cpu_floor"] else None,
        production_activation=False, scope=protocol["scope"]))
    if mismatches:
        raise RuntimeError(f"Exact behavior failures: {mismatches}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--worker", action="store_true")
    args = parser.parse_args()
    if args.worker:
        worker(args.output)
    else:
        if args.output.exists():
            raise FileExistsError(args.output)
        started = time.perf_counter()
        child = subprocess.Popen([sys.executable, "-m", __spec__.name, "--worker", "--output", str(args.output)])
        _, status, usage = os.wait4(child.pid, 0)
        code = os.waitstatus_to_exitcode(status)
        save(args.output / "PROCESS_RECEIPT.json", dict(exit_code=code,
            complete_child_cpu_seconds=usage.ru_utime + usage.ru_stime, wall_seconds=time.perf_counter() - started,
            linux_max_rss_kib=usage.ru_maxrss, affinity=sorted(os.sched_getaffinity(0)),
            python=sys.version, numpy_version=np.__version__, scipy_version=sys.modules["scipy"].__version__,
            system=list(os.uname()),
            blas_environment={name: os.environ.get(name) for name in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS")},
            scope="Complete serial child including imports, all arms, worlds, storage, probes and archives; peak RSS combined, nested timers not added again."))
        raise SystemExit(code)
