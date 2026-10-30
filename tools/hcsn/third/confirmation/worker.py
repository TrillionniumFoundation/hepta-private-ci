"""One resumable seed shard: two tasks, three fixed arms, no extra updates."""
import argparse
import gc
import hashlib
import json
import os
from pathlib import Path
import resource
import sys
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
from third.confirmation.contract import atomic_json, require_development, sha


def run_seed(seed):
    prerequisite = require_development()
    started, cpu_started = time.perf_counter(), time.process_time()
    import jax
    jax.config.update("jax_enable_x64", True)
    import numpy as np
    from benchmarks.data import fingerprint
    from next.common import train_model, predict_model, classification_metrics, predictor
    from next.ridge.models import count_parameters
    from third.confirmation.data import unpack
    from third.confirmation.driver import wait_capacity, snapshot
    from third.memory.development import solve_diagnostics
    from third.memory.execution import atomic_checkpoint
    from third.memory.models import init_model, matched_width, apply_model, resources

    protocol = json.loads((HERE / "protocol.json").read_text())
    if seed not in protocol["seeds"]:
        raise ValueError("Unregistered confirmation seed")
    manifest = json.loads((HERE / "data_manifest.json").read_text())
    if not manifest["complete"] or manifest["prerequisite"] != prerequisite:
        raise RuntimeError("Fresh confirmation cohorts have not passed")
    folder = HERE / "shards"
    folder.mkdir(exist_ok=True)
    output = folder / f"seed{seed}.json"
    result = json.loads(output.read_text()) if output.exists() else dict(
        seed=seed, prerequisite=prerequisite, manifest_sha256=sha(HERE / "data_manifest.json"),
        complete=False, runs=[], attempts=[], environment=dict(jax=jax.__version__, numpy=np.__version__,
        affinity=sorted(os.sched_getaffinity(0)), pid=os.getpid()), worker_invocations=[])
    if result["prerequisite"] != prerequisite or result["manifest_sha256"] != sha(HERE / "data_manifest.json"):
        raise RuntimeError("Shard identity changed")
    for row in result["runs"]:
        for field in ("checkpoint", "predictions"):
            if sha(HERE / row[field + "_file"]) != row[field + "_sha256"]:
                raise RuntimeError("Saved run artifact changed")
    if result["complete"]:
        return
    checkpoints = HERE / "checkpoints"
    checkpoints.mkdir(exist_ok=True)
    done = {(r["task"], r["variant"]) for r in result["runs"]}
    for task_index, task in enumerate(protocol["tasks"]):
        cohort = next(r for r in manifest["cohorts"] if r["task"] == task and r["seed"] == seed)
        if sha(HERE / cohort["file"]) != cohort["sha256"]:
            raise RuntimeError("Frozen data file changed")
        data = unpack(HERE / cohort["file"])
        if any(fingerprint(d) != cohort["fingerprints"][name] for name, d in data.items()):
            raise RuntimeError("Frozen semantic data fingerprint changed")
        training = [data["train" + str(n)] for n in protocol["training_lengths"]]
        evaluation = {name: d for name, d in data.items() if not name.startswith("train")}
        rotation = protocol["seeds"].index(seed) % len(protocol["variants"])
        variants = protocol["variants"][rotation:] + protocol["variants"][:rotation]
        for variant in variants:
            if (task, variant) in done:
                continue
            require_development()
            pause = wait_capacity(HERE, f"seed{seed}/{task}/{variant}", 1)
            stem = f"{task}_{variant}_seed{seed}"
            attempt_number = 1 + sum(a["task"] == task and a["variant"] == variant for a in result["attempts"])
            attempt = dict(task=task, variant=variant, number=attempt_number, status="running",
                           started_epoch_seconds=time.time(), resource_pause=pause)
            result["attempts"].append(attempt)
            atomic_json(output, result)
            run_start, run_cpu = time.perf_counter(), time.process_time()
            try:
                width, count = matched_width(variant, 16, 4, protocol["parameter_target"])
                init_seed = protocol["initialization_seed_base"] + task_index * protocol["parameter_task_offset"] + seed
                optimizer_seed = protocol["optimizer_seed_base"] + task_index * protocol["parameter_task_offset"] + seed
                params = init_model(variant, jax.random.PRNGKey(init_seed), 16, width, 4)
                if count_parameters(params) != count:
                    raise RuntimeError("Parameter budget mismatch")
                initial_hash = hashlib.sha256(b"".join(k.encode() + np.asarray(params[k]).tobytes()
                                                       for k in sorted(params))).hexdigest()
                apply = lambda p, x, dt, v=variant: apply_model(p, x, dt, v)
                learned, history, timing = train_model(params, apply, training, data["validation32"],
                    optimizer_seed, steps=protocol["training_updates"], batch_size=protocol["batch_size"],
                    lr=protocol["learning_rate"])
                logits = {name: predict_model(apply, learned, d) for name, d in evaluation.items()}
                metrics = {name: classification_metrics(logits[name], d["y"]) for name, d in evaluation.items()}
                diagnostics = {name: solve_diagnostics(learned, d, variant, protocol["numerical"])
                               for name, d in evaluation.items()}
                checkpoint = checkpoints / f"{stem}_attempt{attempt_number}.npz"
                predictions = checkpoints / f"{stem}_attempt{attempt_number}_predictions.npz"
                atomic_checkpoint(checkpoint, learned)
                atomic_checkpoint(predictions, logits)
                row = dict(task=task, variant=variant, seed=seed, width=width, parameters=count,
                    initialization_seed=init_seed, optimizer_seed_argument=optimizer_seed,
                    actual_minibatch_rng_seed=optimizer_seed + 50000,
                    initial_parameters_sha256=initial_hash, resources=resources(variant, width),
                    data_file=cohort["file"], data_sha256=cohort["sha256"], data_fingerprints=cohort["fingerprints"],
                    metrics=metrics, history=history, timing=timing, solve_diagnostics=diagnostics,
                    checkpoint_file=str(checkpoint.relative_to(HERE)), checkpoint_sha256=sha(checkpoint),
                    predictions_file=str(predictions.relative_to(HERE)), predictions_sha256=sha(predictions),
                    total_run_wall_seconds=time.perf_counter() - run_start,
                    total_run_cpu_seconds=time.process_time() - run_cpu,
                    cumulative_worker_peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
                    resources_after_run=snapshot())
                result["runs"].append(row)
                attempt.update(status="completed", wall_seconds=row["total_run_wall_seconds"],
                               cpu_seconds=row["total_run_cpu_seconds"])
                atomic_json(output, result)
                print(json.dumps(dict(seed=seed, task=task, variant=variant, runs=len(result["runs"]),
                    accuracy={k: v["accuracy"] for k, v in metrics.items()})), flush=True)
            except BaseException as error:
                attempt.update(status="interrupted", reason=type(error).__name__ + ": " + str(error),
                    wall_seconds=time.perf_counter() - run_start, cpu_seconds=time.process_time() - run_cpu)
                atomic_json(output, result)
                raise
            del learned, params
            predictor.cache_clear()
            jax.clear_caches()
            gc.collect()
    result["complete"] = len(result["runs"]) == len(protocol["tasks"]) * len(protocol["variants"])
    result["worker_invocations"].append(dict(wall_seconds=time.perf_counter() - started,
                                               cpu_seconds=time.process_time() - cpu_started))
    atomic_json(output, result)
    print("CONFIRMATION_SHARD_COMPLETE", seed, flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, required=True)
    run_seed(parser.parse_args().seed)
