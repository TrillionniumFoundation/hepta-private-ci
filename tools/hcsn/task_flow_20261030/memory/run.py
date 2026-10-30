"""Run exactly one sealed, paired 30-run mechanism matrix."""
import gc
import hashlib
import json
import os
from pathlib import Path
import resource
import sys
import time

import jax
import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
from next.common import predict_model, classification_metrics, measure_latency, predictor
from next.ridge.models import count_parameters
from third.memory.execution import atomic_json, atomic_checkpoint
from task_flow_20261030.memory import models
from task_flow_20261030.memory.data import make_suite, audit_freshness
from task_flow_20261030.memory.freeze import verify, sha
from task_flow_20261030.memory.training import train


def working_set():
    folder = Path("/sys/fs/cgroup")
    if not (folder / "memory.current").exists():
        return None
    stats = dict(line.split() for line in (folder / "memory.stat").read_text().splitlines())
    clean = max(0, int(stats.get("inactive_file", 0)) - int(stats.get("file_dirty", 0))
                - int(stats.get("file_writeback", 0)))
    return int((folder / "memory.current").read_text()) - clean


def admission():
    began = time.perf_counter()
    while True:
        used = working_set()
        if used is None or used < 6800000000:
            return dict(wait_seconds=time.perf_counter() - began, working_set_bytes=used)
        atomic_json(HERE / "resource_pause.json", dict(used=used, wait_seconds=time.perf_counter() - began))
        print("RESOURCE_PAUSE", used, flush=True)
        time.sleep(10)


def main():
    jax.config.update("jax_enable_x64", True)
    frozen = verify()
    freeze_hash = sha(HERE / "freeze.json")
    protocol = json.loads((HERE / "protocol.json").read_text())
    validation = json.loads((HERE / "validation.json").read_text())
    if not validation["passed"] or validation["freeze_sha256"] != freeze_hash:
        raise RuntimeError("This source freeze has not passed numerical validation")
    output = HERE / "results.json"
    if output.exists():
        result = json.loads(output.read_text())
        if result["complete"] or result["freeze_sha256"] != freeze_hash:
            raise RuntimeError("Refuse completed or mismatching-source rerun")
    else:
        freshness = audit_freshness(protocol)
        atomic_json(HERE / "freshness.json", freshness)
        if not freshness["passed"]:
            raise RuntimeError("Retain failed freshness, do not train")
        result = dict(complete=False, runs=[], freeze_sha256=freeze_hash,
                      source_sha256=frozen["source_sha256"], protocol=protocol,
                      jax=jax.__version__, numpy=np.__version__, cpu_affinity=sorted(os.sched_getaffinity(0)))
        atomic_json(output, result)
    expected = len(protocol["variants"]) * len(protocol["tasks"]) * len(protocol["seeds"])
    done = {(r["task"], r["seed"], r["variant"]) for r in result["runs"]}
    for row in result["runs"]:
        if sha(HERE / row["checkpoint"]) != row["checkpoint_sha256"]:
            raise RuntimeError("Selected checkpoint changed")
    for task in protocol["tasks"]:
        for seed in protocol["seeds"]:
            training, suite, fingerprints = make_suite(task, seed, protocol)
            offset = seed % len(protocol["variants"])
            variants = protocol["variants"][offset:] + protocol["variants"][:offset]
            for variant in variants:
                if (task, seed, variant) in done:
                    continue
                verify()
                pauses = admission()
                run_id = f"{task}_{variant}_seed{seed}"
                directory = HERE / "runs" / run_id
                if directory.exists():
                    raise RuntimeError("An incomplete run directory exists; retain and diagnose before resuming")
                before, cpu_before = time.perf_counter(), time.process_time()
                atomic_json(HERE / "active.json", dict(run_id=run_id, status="running", epoch=time.time()))
                width, count = models.matched_width(variant, 16, 4, protocol["parameter_target"])
                p = models.init_model(variant, jax.random.PRNGKey(protocol["initialization_seed_base"] + seed), 16, width, 4)
                if count_parameters(p) != count:
                    raise RuntimeError("Parameter budget mismatch")
                initial_hash = hashlib.sha256(b"".join(k.encode() + np.asarray(p[k]).tobytes() for k in sorted(p))).hexdigest()
                apply = lambda par, x, dt, v=variant: models.apply_model(par, x, dt, v)
                learned, history, costs = train(p, apply, training, suite["validation32"],
                    protocol["optimizer_seed_base"] + seed, directory, protocol)
                chosen = directory / "selected.npz"
                atomic_checkpoint(chosen, learned)
                metrics, predictions = {}, {}
                for name, dataset in suite.items():
                    logits = predict_model(apply, learned, dataset, batch_size=32)
                    if not np.isfinite(logits).all():
                        raise FloatingPointError("Nonfinite evaluation logits")
                    metrics[name] = classification_metrics(logits, dataset["y"])
                    path = directory / (name + "_predictions.npz")
                    atomic_checkpoint(path, dict(logits=logits, labels=dataset["y"]))
                    predictions[name] = dict(path=str(path.relative_to(HERE)), sha256=sha(path))
                _, aux = models.apply_model(learned, suite["test512"]["x"][:16], suite["test512"]["dt"][:16], variant, True)
                diagnostics = dict(all_aux_finite=all(np.isfinite(np.asarray(a)).all() for a in aux.values()))
                if variant.endswith("delta"):
                    norms = np.linalg.norm(np.asarray(aux["memory"]), axis=1)
                    diagnostics.update(maximum_column_norm=float(norms.max()),
                                       radius_satisfied=bool(np.all(norms <= 8.00002)))
                updates = {k: float(np.linalg.norm(np.asarray(learned[k]) - np.asarray(p[k]))) for k in p}
                row = dict(run_id=run_id, task=task, seed=seed, variant=variant, width=width, parameters=count,
                    resources=models.resources(variant, width), initial_parameters_sha256=initial_hash,
                    data_sha256=fingerprints, metrics=metrics, predictions=predictions,
                    history=history, training=costs, parameter_update_norms=updates, diagnostics=diagnostics,
                    checkpoint=str(chosen.relative_to(HERE)), checkpoint_sha256=sha(chosen), resource_admission=pauses,
                    latency=measure_latency(apply, learned, suite["validation32"], repeats=20),
                    run_wall_seconds=time.perf_counter() - before, run_cpu_seconds=time.process_time() - cpu_before,
                    process_peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024)
                atomic_json(directory / "run.json", row)
                result["runs"].append(row)
                result["complete"] = len(result["runs"]) == expected
                atomic_json(output, result)
                atomic_json(HERE / "active.json", dict(run_id=run_id, status="complete", epoch=time.time()))
                print(json.dumps(dict(completed=len(result["runs"]), run_id=run_id,
                      accuracy={k: v["accuracy"] for k, v in metrics.items()}, seconds=row["run_wall_seconds"])), flush=True)
                del learned, p, aux, apply
                predictor.cache_clear()
                jax.clear_caches()
                gc.collect()


if __name__ == "__main__":
    try:
        main()
    except BaseException as error:
        atomic_json(HERE / "failure.json", dict(type=type(error).__name__, error=str(error), epoch=time.time()))
        raise
