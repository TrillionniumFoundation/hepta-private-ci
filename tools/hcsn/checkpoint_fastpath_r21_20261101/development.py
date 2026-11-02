"""Declared fixed-fixture proof and matched old/new executor measurements."""

import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import time
import tracemalloc

import numpy as np

from ..addressed_decision_r15_20261101.law import Law
from ..addressed_decision_r15_20261101.world import make_episode
from ..planner_fastpath_r18_20261101.planner import KernelCache
from ..planner_r20_20261101 import execution as old
from ..planner_r20_20261101.campaign import save, semantic
from ..support_retention_r16_20261101.compression import BlockLaw
from . import execution as new

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]


def instrumented(module, law, episode, variant, representation, path):
    cls = module.AnchoredPackedMemory if representation == "anchored" else module.BeliefMemory
    checkpoint, persist, fsync = cls.checkpoint, module.persist, os.fsync
    counts, wires, descriptors = [], [], []
    def observed_checkpoint(self):
        counts.append(self.clock)
        return checkpoint(self)
    def observed_persist(target, body):
        result = persist(target, body)
        wires.append(hashlib.sha256(target.read_bytes()).hexdigest())
        return result
    def observed_fsync(fd):
        descriptors.append("directory" if stat.S_ISDIR(os.fstat(fd).st_mode) else "file")
        return fsync(fd)
    cls.checkpoint, module.persist, os.fsync = observed_checkpoint, observed_persist, observed_fsync
    try:
        row = module.execute(law, episode, variant, representation, path, KernelCache())
    finally:
        cls.checkpoint, module.persist, os.fsync = checkpoint, persist, fsync
    return dict(result=row, checkpoint_count=len(counts), checkpoint_clocks=counts,
                wire_sha256=wires, fsync_descriptors=descriptors)


def worker(output):
    protocol = json.loads((HERE / "DEVELOPMENT_PROTOCOL.json").read_text())
    manifest = json.loads((HERE / "DEVELOPMENT_SOURCE_MANIFEST.json").read_text())
    for name, digest in manifest["files"].items():
        if hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != digest:
            raise RuntimeError(f"Changed engineering input: {name}")
    training = ROOT / protocol["training_archive"]
    models = json.loads(gzip.decompress(training.read_bytes()))["calibration"]["models"]
    owner = Law()
    worlds = [make_episode(owner, protocol["namespace"] * 10**9 + index,
                           ("iid", "ood")[index % 2]) for index in range(protocol["timing_worlds"])]
    proofs, guards, groups = [], [], []
    for model in protocol["models"]:
        for representation in protocol["representations"]:
            for variant in protocol["variants"]:
                with tempfile.TemporaryDirectory(prefix="checkpoint-r21-proof-") as directory:
                    for episode in worlds[:2]:
                        results = {}
                        for name, module in (("old", old), ("new", new)):
                            law = BlockLaw.from_payload(models[model]["payload"])
                            results[name] = instrumented(module, law, episode, variant, representation,
                                                        Path(directory) / (name + ".json"))
                        assert semantic(results["old"]["result"]) == semantic(results["new"]["result"])
                        assert results["old"]["wire_sha256"] == results["new"]["wire_sha256"]
                        assert results["old"]["checkpoint_count"] == 18
                        assert results["new"]["checkpoint_count"] == 12
                        assert results["old"]["fsync_descriptors"] == results["new"]["fsync_descriptors"] == ["file", "directory"] * 6
                        proofs.append(dict(model=model, representation=representation, variant=variant,
                                           seed=episode.seed, old=results["old"], new=results["new"]))
                laws, caches, preparation = {}, {}, {}
                for name in ("old", "new"):
                    start = time.process_time()
                    laws[name] = BlockLaw.from_payload(models[model]["payload"])
                    caches[name] = KernelCache()
                    preparation[name] = time.process_time() - start
                records = []
                with tempfile.TemporaryDirectory(prefix="checkpoint-r21-timing-") as directory:
                    for index, episode in enumerate(worlds):
                        results = {}
                        order = ("old", "new") if index % 2 == 0 else ("new", "old")
                        for name in order:
                            module = old if name == "old" else new
                            results[name] = module.execute(laws[name], episode, variant, representation,
                                                           Path(directory) / (name + ".json"), caches[name])
                        assert semantic(results["old"]) == semantic(results["new"])
                        records.append(dict(index=index, order=order, results=results))
                    memory = {}
                    for name, module in (("old", old), ("new", new)):
                        peaks = []
                        for episode in worlds[:protocol["memory_worlds"]]:
                            tracemalloc.start()
                            module.execute(laws[name], episode, variant, representation,
                                           Path(directory) / (name + ".json"), caches[name])
                            _, peak = tracemalloc.get_traced_memory()
                            tracemalloc.stop()
                            peaks.append(peak)
                        memory[name] = peaks
                cpu = {name: preparation[name] + sum(r["results"][name]["cpu_seconds"] for r in records)
                       for name in ("old", "new")}
                group = dict(model=model, representation=representation, variant=variant, preparation=preparation,
                             cpu_with_preparation=cpu, memory_peaks=memory,
                             new_old_cpu_ratio=cpu["new"] / cpu["old"],
                             new_old_peak_ratio=max(memory["new"]) / max(memory["old"]))
                save(output / f"{model}_{representation}_{variant}.json.gz", dict(group=group, records=records))
                groups.append(group)
    # Verify that the final, newly generated post-restore comparison remains an
    # effective rejection guard; corrupt the restored clock in this process only.
    for representation in protocol["representations"]:
        cls = new.AnchoredPackedMemory if representation == "anchored" else new.BeliefMemory
        descriptor = cls.__dict__["restore"]
        original = cls.restore
        def corrupted_restore(cls_arg, law, payload):
            memory = original(law, payload)
            memory.clock += .001
            return memory
        cls.restore = classmethod(corrupted_restore)
        try:
            with tempfile.TemporaryDirectory(prefix="checkpoint-r21-guard-") as directory:
                for name, module in (("old", old), ("new", new)):
                    try:
                        module.execute(BlockLaw.from_payload(models["hx"]["payload"]), worlds[0], "r20",
                                       representation, Path(directory) / (name + ".json"), KernelCache())
                    except RuntimeError as exc:
                        assert "Owned state changed" in str(exc)
                        guards.append(dict(representation=representation, version=name, rejected=str(exc)))
                    else:
                        raise AssertionError("Corrupted restored memory was accepted")
        finally:
            cls.restore = descriptor
    save(output / "PROOFS.json.gz", dict(cases=proofs, corrupt_restore_guards=guards))
    save(output / "SUMMARY.json", dict(groups=groups, proof_pairs=len(proofs), guards=len(guards),
         timed_executions=len(groups) * len(worlds) * 2,
         memory_executions=len(groups) * protocol["memory_worlds"] * 2,
         instrumented_executions=len(proofs) * 2, rejected_guard_executions=len(guards),
         scope="Locallyfrozenfixedfixturesonly, notformalresourcequalification; all24model/representation/variantgroups retained; no quality/1000-use claim"))


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
             complete_child_cpu_seconds=usage.ru_utime + usage.ru_stime,
             wall_seconds=time.perf_counter() - started, linux_max_rss_kib=usage.ru_maxrss,
             scope="Fullengineeringchildimports,proofspyIO,alltiming/memoryattempts,guardrejectionsandoutputs; nestedtimersnotadded"))
        raise SystemExit(code)
