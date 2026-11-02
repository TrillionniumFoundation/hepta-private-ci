"""Bounded old/new validation equivalence and actual shared durable-actor trials."""

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


def validator_checks(oldlaw, newlaw, samples, seed):
    rng, records = np.random.default_rng(seed), []
    for width, tolerance in ((8, 2e-11), (40, 2e-11)):
        arrays = []
        for sign in (-1., 1.):
            center = 1. + sign * tolerance
            for value in (np.nextafter(center, -np.inf), center, np.nextafter(center, np.inf)):
                p = np.zeros(width)
                p[0] = value
                arrays.append(("actual_boundary", p))
        for kind in ("normal", "nan", "inf", "negative", "tiny_negative", "wrong_width", "overflow"):
            p = np.zeros(width)
            p[0] = 1.
            if kind == "nan": p[1] = np.nan
            if kind == "inf": p[1] = np.inf
            if kind == "negative": p[1] = -.01; p[0] += .01
            if kind == "tiny_negative": p[1] = -1e-14; p[0] += 1e-14
            if kind == "wrong_width": p = p[:-1]
            if kind == "overflow": p[:] = 1e308
            arrays.append((kind, p))
        for index in range(samples):
            p = rng.dirichlet(np.ones(width))
            if index % 3 == 0:
                p *= 1. + rng.uniform(-5e-11, 5e-11)
            arrays.append(("declared_random", p))
        for kind, p in arrays:
            shapes = [p, np.tile(p, (3, 1)), np.tile(p, (2, 3, 1))]
            for value in shapes:
                value.setflags(write=False)
                before = value.tobytes()
                functions = ((old_memory._probability, new_memory._probability) if width == 8 else
                             (lambda x, n: oldlaw._belief(x), lambda x, n: newlaw._belief(x)))
                outcomes, outputs = [], []
                with np.errstate(over="ignore", invalid="ignore"):
                    for function in functions:
                        try:
                            result = function(value, width)
                            outcomes.append("accepted")
                            outputs.append(result.tobytes())
                        except ValueError:
                            outcomes.append("ValueError")
                assert outcomes[0] == outcomes[1] and value.tobytes() == before
                assert not outputs or outputs[0] == outputs[1]
                mass = value.sum(-1)
                records.append(dict(width=width, kind=kind, shape=list(value.shape), outcome=outcomes[0],
                    input_sha256=hashlib.sha256(before).hexdigest(),
                    actual_max_mass_error=float(np.max(np.abs(mass - 1.))) if np.isfinite(mass).all() else None))
    return records


def worker(output):
    protocol = json.loads((HERE / "DEVELOPMENT_PROTOCOL.json").read_text())
    for name, digest in json.loads((HERE / "DEVELOPMENT_SOURCE_MANIFEST.json").read_text())["files"].items():
        if hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != digest:
            raise RuntimeError(f"Changed development input: {name}")
    archive = ROOT / protocol["training_archive"]
    models = json.loads(gzip.decompress(archive.read_bytes()))["calibration"]["models"]
    rows = validator_checks(old_memory.BlockLaw.from_payload(models["hx"]["payload"]),
                            new_memory.BlockLaw.from_payload(models["hx"]["payload"]),
                            protocol["validator_random_samples"], protocol["validator_seed"])
    save(output / "VALIDATOR_EQUIVALENCE.json.gz", dict(passed=True, cases=rows))
    owner = Law()
    worlds = [make_episode(owner, protocol["namespace"] * 10**9 + i, ("iid", "ood")[i % 2])
              for i in range(protocol["worlds"])]
    groups = []
    for model in protocol["models"]:
        for representation in protocol["representations"]:
            for variant in protocol["variants"]:
                laws, caches, preparation = {}, {}, {}
                for name, memory in (("old", old_memory), ("new", new_memory)):
                    start = time.process_time()
                    laws[name] = memory.BlockLaw.from_payload(models[model]["payload"])
                    caches[name] = KernelCache()
                    preparation[name] = time.process_time() - start
                    assert laws[name].identity == models[model]["payload"]["identity"]
                records = []
                with tempfile.TemporaryDirectory(prefix="r22-actual-durable-") as directory:
                    for index, episode in enumerate(worlds):
                        results = {}
                        order = ("old", "new") if index % 2 == 0 else ("new", "old")
                        for name in order:
                            module = old if name == "old" else new
                            path = Path(directory) / (name + ".json")
                            row = module.execute(laws[name], episode, variant, representation, path, caches[name])
                            results[name] = dict(result=row, final_wire_sha256=hashlib.sha256(path.read_bytes()).hexdigest())
                        assert semantic(results["old"]["result"]) == semantic(results["new"]["result"])
                        assert results["old"]["final_wire_sha256"] == results["new"]["final_wire_sha256"]
                        records.append(dict(index=index, order=order, outcomes=results))
                    memory_peaks = {}
                    for name, module in (("old", old), ("new", new)):
                        peaks = []
                        for episode in worlds[:protocol["memory_worlds"]]:
                            tracemalloc.start()
                            module.execute(laws[name], episode, variant, representation,
                                           Path(directory) / (name + ".json"), caches[name])
                            _, peak = tracemalloc.get_traced_memory()
                            tracemalloc.stop()
                            peaks.append(peak)
                        memory_peaks[name] = peaks
                cpu = {name: preparation[name] + sum(r["outcomes"][name]["result"]["cpu_seconds"] for r in records)
                       for name in ("old", "new")}
                group = dict(model=model, representation=representation, variant=variant,
                             uses=len(worlds), preparation=preparation, cpu_with_preparation=cpu,
                             new_old_cpu_ratio=cpu["new"] / cpu["old"], memory_peaks=memory_peaks,
                             new_old_peak_ratio=max(memory_peaks["new"]) / max(memory_peaks["old"]))
                save(output / f"{model}_{representation}_{variant}.json.gz", dict(group=group, records=records))
                groups.append(group)
    save(output / "SUMMARY.json", dict(groups=groups, validator_cases=len(rows),
         timed_executions=len(groups) * len(worlds) * 2,
         memory_executions=len(groups) * protocol["memory_worlds"] * 2,
         scope="Locallyfrozendevelopmentonly; sameinformationandcomplete6durablecommitworkforeachplanner. Notformalresourceconfirmationorqualityadmission."))


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
        start = time.perf_counter()
        child = subprocess.Popen([sys.executable, "-m", __spec__.name, "--worker", "--output", str(args.output)])
        _, status, usage = os.wait4(child.pid, 0)
        code = os.waitstatus_to_exitcode(status)
        save(args.output / "PROCESS_RECEIPT.json", dict(exit_code=code,
             complete_child_cpu_seconds=usage.ru_utime + usage.ru_stime,
             wall_seconds=time.perf_counter() - start, linux_max_rss_kib=usage.ru_maxrss,
             scope="Completeengineeringchildincludingallchecks/candidates/durableIOandmemoryprobes; nestedtimersnotadded."))
        raise SystemExit(code)
