"""Separate fixed-128-update diagnostic after the incomplete original secondary.

Only free_dual is retrained, from its original initialization. The seven
baseline references reuse the already evaluated strict-128 secondary. No main
study source, protocol, checkpoint or missing-secondary record is changed.
The coordinator is stdlib-only; Torch is imported only inside each worker.
"""

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import traceback


PACKAGE = Path(__file__).resolve().parent
REPOSITORY = PACKAGE.parents[1]
PROTOCOL = PACKAGE / "EQUAL_UPDATES_CORE002_PROTOCOL.json"
DEFAULT_OUTPUT = PACKAGE / "results/equal_updates_core002"


def read(path):
    return json.loads(Path(path).read_text())


def sha(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            result.update(block)
    return result.hexdigest()


def write(path, value):
    path = Path(path)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")
    temporary.replace(path)


def update_prefix(path, count):
    records = []
    with Path(path).open() as stream:
        for line in stream:
            record = json.loads(line)
            records.append({key: record[key] for key in ("step", "batch_sha256", "prefix_sha256")})
            if len(records) == count:
                break
    if len(records) != count or any(row["step"] != i + 1 for i, row in enumerate(records)):
        raise ValueError("Reference does not contain the full required ordered update prefix")
    return records


def register(output=DEFAULT_OUTPUT, protocol_path=PROTOCOL):
    output, protocol_path = Path(output), Path(protocol_path)
    if output.exists() or protocol_path.exists():
        raise FileExistsError("Refuse to replace a registered fixed-update diagnostic")
    main = PACKAGE / "results/study001"
    freeze = read(PACKAGE / "FREEZE.json")
    main_protocol = read(PACKAGE / "PROTOCOL.json")
    completed = read(main / "COMPLETE.json")
    if completed["finished_searches"] != 244 or completed["statuses"] != {"completed": 244}:
        raise ValueError("Require the original completed main matrix")
    files = dict(freeze["files"])
    for name, expected in files.items():
        if sha(REPOSITORY / name) != expected:
            raise ValueError(f"Original frozen file changed: {name}")
    for path in (Path(__file__), PACKAGE / "equal_updates_core002_tests.py",
                 PACKAGE / "results/equal_updates_core002_preflight001.json",
                 main / "COMPLETE.json", main / "secondary128/SECONDARY128.json"):
        files[str(path.relative_to(REPOSITORY))] = sha(path)
    jobs = []
    for task in main_protocol["core"]["tasks"]:
        for seed in main_protocol["core"]["seeds"]:
            original = main / "runs" / task / "free_dual" / str(seed)
            summary = read(original / "summary.json")
            initial, old128 = {}, {}
            for candidate in summary["candidates"]:
                key = str(candidate["learning_rate"])
                path = original / candidate["directory"] / "initial.npz"
                if sha(path) != candidate["initial_sha256"]:
                    raise ValueError("Original initial checkpoint failed its hash")
                relative = str(path.relative_to(REPOSITORY))
                initial[key] = dict(path=relative, sha256=sha(path))
                files[relative] = sha(path)
                checkpoints = [c for c in candidate["checkpoints"] if c["step"] == 128]
                if checkpoints:
                    checkpoint = original / candidate["directory"] / checkpoints[0]["weights"]
                    relative_checkpoint = str(checkpoint.relative_to(REPOSITORY))
                    if sha(checkpoint) != checkpoints[0]["sha256"]:
                        raise ValueError("Existing original128 checkpoint failed its hash")
                    old128[key] = dict(path=relative_checkpoint, sha256=sha(checkpoint))
                    files[relative_checkpoint] = sha(checkpoint)
            reference = main / "runs" / task / "two_gates" / str(seed)
            candidate = read(reference / "summary.json")["candidates"][0]
            log = reference / candidate["directory"] / "updates.jsonl"
            prefix = update_prefix(log, 128)
            relative_log = str(log.relative_to(REPOSITORY))
            files[relative_log] = sha(log)
            jobs.append(dict(task=task, model="free_dual", seed=seed,
                             original_initial=initial, existing_original128=old128,
                             expected_prefix_source=relative_log,
                             expected_first128_prefix_sha256=prefix[-1]["prefix_sha256"]))
    secondary = read(main / "secondary128/SECONDARY128.json")
    references = []
    baseline_names = [m for m in main_protocol["core"]["models"] if m != "free_dual"]
    for row in secondary["records"]:
        if row["model"] not in baseline_names or row["seed"] not in main_protocol["core"]["seeds"]:
            continue
        if row["status"] != "evaluated":
            raise ValueError("Every reused baseline must have both exact128 LR snapshots")
        directory = main / "secondary128/runs" / row["task"] / row["model"] / str(row["seed"])
        for path in directory.iterdir():
            if path.is_file():
                files[str(path.relative_to(REPOSITORY))] = sha(path)
        original = main / "runs" / row["task"] / row["model"] / str(row["seed"])
        for name in ("summary.json", "EXECUTION.json"):
            files[str((original / name).relative_to(REPOSITORY))] = sha(original / name)
        selected = row["eligibility"]["selected"]
        checkpoint = original / selected["directory"] / selected["checkpoint"]["weights"]
        files[str(checkpoint.relative_to(REPOSITORY))] = sha(checkpoint)
        references.append(dict(task=row["task"], model=row["model"], seed=row["seed"],
                               directory=str(directory.relative_to(REPOSITORY)),
                               selected_sha256=row["selection"]["selected_sha256"],
                               original_search_directory=str(original.relative_to(REPOSITORY)),
                               inference_reused=True, new_training=False))
    if len(jobs) != 18 or len(references) != 126:
        raise ValueError("Unexpected fixed-update/core-reference matrix")
    protocol = dict(schema="hcsn-equal-updates-core002-protocol.v1", study_id="equal_updates_core002",
        created_utc=datetime.now(timezone.utc).isoformat(),
        status="registered_before_new_training_or_inference; primary outcomes already known",
        reason="The original strict128 secondary has 42 missing searches and no complete free-cell task panel; execute a separate fixed-update diagnostic, preserving that original result",
        interpretation="post-primary diagnostic; not a new untouched test confirmation, not a replacement equal-CPU study, not part of the original Holm family",
        primary_study_unchanged=True, original_secondary_unchanged="202 evaluated /42 incomplete /0 added training",
        main_freeze_identity=freeze["identity_sha256"], files_sha256=files,
        tasks=main_protocol["core"]["tasks"], seeds=main_protocol["core"]["seeds"],
        baseline_names=baseline_names, jobs=jobs, reused_baseline_references=references,
        optimization=dict(model="free_dual", target_updates=128, learning_rates=[.001, .003],
                          width=32, depth=1, batch_size=32, optimizer="frozen training.py Adam defaults",
                          gradient_clip_l2=2.0, task_loss="cross_entropy_only; ignore_index=-100",
                          initialization="fresh original same-seed initialization; exact initial NPZ SHA required; no optimizer continuation",
                          minibatches="frozen seed+200003 generator; all first128 batch/prefix hashes must match pinned original two_gates stream",
                          execution_cpu_ceiling_per_lr=120.0,
                          cpu_ceiling_meaning="failure guard only, not target budget; stop at exactly128 updates; do not increase ceiling after failure",
                          checkpoint_rule="only exactly128 checkpoint participates in new selection; helper CPU checkpoints never participate",
                          selection="minimum validation CE at128 across both complete LRs; exact tie smaller LR; durable lock before heldout",
                          existing128_replay="require exact checkpoint SHA agreement whenever original candidate already reached128",
                          numeric_retention="keep initial, exactly128 and selected NPZ; prune only this diagnostic's intermediate CPU-checkpoint NPZ after hashing metadata",
                          max_parallel_workers=3, threads_per_worker=1),
        analysis=dict(core="six tasks x eight models x three paired seeds; accuracy/CE means/sample SD and ID/OOD, preserve failures",
                      inference="descriptive diagnostic; no new superiority acceptance test or retroactive Holm membership",
                      compute="report all new wait4 worker CPU and update-prefix CPU separately; baseline training/inference is explicit reuse, not fabricated new work",
                      limitations="equal updates are not equal CPU; same already-inspected test arrays; reuse and fresh retraining occur in distinct executions"),
        failure_rule="Preserve every failed candidate/search and full execution cost; continue declared jobs, no silent retry, LR change, retuning or extra updates")
    output.mkdir(parents=True, exist_ok=False)
    write(protocol_path, protocol)
    write(output / "REGISTRATION.json", dict(study_id=protocol["study_id"],
        protocol_sha256=sha(protocol_path), created_utc=protocol["created_utc"],
        new_training_started=False, new_heldout_inference_started=False,
        primary_outcomes_previously_known=True, jobs=18, new_lr_candidates=36,
        reused_baseline_searches=126, protocol_path=str(protocol_path.relative_to(REPOSITORY))))
    return protocol


def verify(protocol_path, output):
    protocol = read(protocol_path)
    registration = read(Path(output) / "REGISTRATION.json")
    if sha(protocol_path) != registration["protocol_sha256"]:
        raise ValueError("Fixed-update protocol differs from its pre-run registration")
    if protocol["study_id"] != "equal_updates_core002" or protocol["optimization"]["target_updates"] != 128:
        raise ValueError("Unexpected fixed-update protocol")
    for name, expected in protocol["files_sha256"].items():
        if sha(REPOSITORY / name) != expected:
            raise ValueError(f"Registered input changed: {name}")
    return protocol


def run_fixed_search(data_path, seed, destination, initial_references, expected_prefix,
                     existing128=None, target_updates=128, cpu_ceiling=120.0,
                     width=32, depth=1, batch_size=32, learning_rates=(.001, .003)):
    import numpy as np
    import torch
    from . import training

    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    if any(destination.iterdir()):
        raise FileExistsError("Fixed-update search requires a fresh directory")
    started, started_wall = time.process_time(), time.perf_counter()
    access = []
    train = training.load_split(data_path, "train", access)
    validation = training.load_split(data_path, "val", access)
    request = dict(model="free_dual", seed=seed, target_updates=target_updates,
                   learning_rates=list(learning_rates), cpu_ceiling_per_lr=cpu_ceiling,
                   width=width, depth=depth, batch_size=batch_size,
                   source_dataset_sha256=sha(data_path), original_initial=initial_references)
    write(destination / "REQUEST.json", request)
    candidates = []
    try:
        for index, learning_rate in enumerate(learning_rates):
            directory = destination / f"lr_{index}_{learning_rate:g}"
            result = training.train_candidate(train, validation, "free_dual", seed, learning_rate,
                        directory, cpu_seconds=cpu_ceiling, width=width, depth=depth,
                        batch_size=batch_size, max_updates=target_updates)
            if result["updates"] != target_updates or result["stopping_reason"] != "update_cap":
                raise RuntimeError("Candidate failed to reach exactly the registered update count under its guard")
            checkpoints = [c for c in result["checkpoints"] if c["step"] == target_updates]
            if len(checkpoints) != 1:
                raise ValueError("Need exactly one terminal fixed-update checkpoint")
            checkpoint = checkpoints[0]
            reference = initial_references[str(learning_rate)]
            original_path = Path(reference["path"])
            original_path = original_path if original_path.is_absolute() else REPOSITORY / original_path
            if sha(directory / "initial.npz") != reference["sha256"] or sha(original_path) != reference["sha256"]:
                raise ValueError("Fresh initialization is not byte-identical to the pinned original")
            actual_prefix = update_prefix(directory / "updates.jsonl", target_updates)
            if actual_prefix != expected_prefix:
                raise ValueError("Fixed-update minibatch stream differs from original paired prefix")
            old = (existing128 or {}).get(str(learning_rate))
            replay = None
            if old is not None:
                old_path = Path(old["path"])
                old_path = old_path if old_path.is_absolute() else REPOSITORY / old_path
                replay = sha(directory / checkpoint["weights"]) == old["sha256"] == sha(old_path)
                if not replay:
                    raise ValueError("Fixed-update training does not exactly replay an existing original128 snapshot")
            pruned = []
            for earlier in result["checkpoints"]:
                if earlier["step"] != target_updates:
                    path = directory / earlier["weights"]
                    if sha(path) != earlier["sha256"]:
                        raise ValueError("Own temporary checkpoint changed before pruning")
                    pruned.append(dict(weights=earlier["weights"], sha256=earlier["sha256"]))
                    path.unlink()
            record = dict(learning_rate=learning_rate, directory=directory.name,
                          terminal_checkpoint=checkpoint, initial_sha256=result["initial_sha256"],
                          original_initial_byte_identical=True, all_update_prefixes_identical=True,
                          existing_original128_byte_identical=replay,
                          updates=result["updates"], training_cpu_seconds=result["training_cpu_seconds"],
                          setup_cpu_seconds=result["setup_cpu_seconds"], validation_cpu_seconds=result["validation_cpu_seconds"],
                          complete_helper_cpu_seconds=result["total_cpu_seconds"],
                          parameter_changes_at_target=result["final_parameter_changes"],
                          ignored_helper_cpu_gate_best=result["best"],
                          ignored_helper_primary_selection=True,
                          retained_numeric=["initial.npz", checkpoint["weights"]], pruned_intermediate_numeric=pruned,
                          prefix_sha256=actual_prefix[-1]["prefix_sha256"],
                          counts=result["counts"], config=result["config"])
            write(directory / "FIXED_UPDATE_RECEIPT.json", record)
            candidates.append(record)
        winner = min(candidates, key=lambda row: (row["terminal_checkpoint"]["validation"]["cross_entropy"], row["learning_rate"]))
        checkpoint = winner["terminal_checkpoint"]
        selection = dict(rule="minimum validation CE at the fixed update across both complete LRs; exact tie smaller LR",
                         selected_learning_rate=winner["learning_rate"], selected_step=target_updates,
                         selected_validation=checkpoint["validation"], selected_checkpoint_sha256=checkpoint["sha256"],
                         completed_lr_candidates=len(candidates), dataset_sha256=request["source_dataset_sha256"])
        write(destination / "SELECTION.json", selection)
        access.append(dict(event="selection_locked", selected_step=target_updates, completed_lr_candidates=len(candidates)))
        shutil.copyfile(destination / winner["directory"] / checkpoint["weights"], destination / "selected.npz")
        if sha(destination / "selected.npz") != checkpoint["sha256"]:
            raise ValueError("Selected exact-update checkpoint copy changed")
        model = training.build_model("free_dual", train["x"].shape[-1], int(train["y"].max().item()) + 1,
                                     width=width, depth=depth, seed=seed)
        training.load_weights(destination / "selected.npz", model)
        metrics = {}
        heldout_start = time.process_time()
        for split in ("test", "ood"):
            dataset = training.load_split(data_path, split, access)
            metrics[split] = None if dataset is None else training.evaluate(model, dataset,
                                               output_path=destination / f"{split}_predictions.npz")
        result = dict(status="completed", request=request, selection=selection, candidates=candidates,
                      metrics=metrics, counts=model.counts(), access_log=access,
                      holdout_cpu_seconds=time.process_time()-heldout_start,
                      search_function_cpu_seconds=time.process_time()-started,
                      search_function_wall_seconds=time.perf_counter()-started_wall,
                      no_primary_or_original_secondary_changes=True)
        write(destination / "SUMMARY.json", result)
        return result
    except Exception as error:
        write(destination / "FAILURE.json", dict(status="failed", request=request,
              completed_candidates=candidates, access_log=access,
              error_type=type(error).__name__, error=str(error), traceback=traceback.format_exc(),
              search_function_cpu_seconds=time.process_time()-started))
        raise


def worker(protocol_path, output, task, seed):
    import torch
    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
    protocol = verify(protocol_path, output)
    jobs = [j for j in protocol["jobs"] if j["task"] == task and j["seed"] == seed]
    if len(jobs) != 1:
        raise ValueError("Unregistered fixed-update job")
    job, options = jobs[0], protocol["optimization"]
    expected = update_prefix(REPOSITORY / job["expected_prefix_source"], 128)
    result = run_fixed_search(PACKAGE / "data/study001" / f"{task}.npz", seed,
        Path(output) / "runs" / task / str(seed), job["original_initial"], expected,
        existing128=job["existing_original128"], target_updates=128,
        cpu_ceiling=options["execution_cpu_ceiling_per_lr"], width=options["width"], depth=options["depth"],
        batch_size=options["batch_size"], learning_rates=options["learning_rates"])
    verify(protocol_path, output)
    print(json.dumps(dict(task=task, seed=seed, status=result["status"])), flush=True)


def _run_one(protocol_path, output, job):
    env = os.environ.copy()
    env.update({key: "1" for key in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS", "NUMEXPR_NUM_THREADS")})
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    identifier = f"{job['task']}--{job['seed']}"
    log_path = Path(output) / "process_logs" / f"{identifier}.log"
    command = [sys.executable, "-m", "experiments.hcsn_free_boundary_v1.equal_updates_core002",
               "worker", "--protocol", str(protocol_path), "--output", str(output),
               "--task", job["task"], "--seed", str(job["seed"])]
    start = time.perf_counter()
    with log_path.open("x") as log:
        child = subprocess.Popen(command, cwd=REPOSITORY, env=env, stdout=log, stderr=subprocess.STDOUT)
        _, status, usage = os.wait4(child.pid, 0)
        child.returncode = os.waitstatus_to_exitcode(status)
    result = dict(task=job["task"], model="free_dual", seed=job["seed"],
                  status="completed" if child.returncode == 0 else "failed", returncode=child.returncode,
                  child_cpu_seconds=usage.ru_utime+usage.ru_stime,
                  child_user_cpu_seconds=usage.ru_utime, child_system_cpu_seconds=usage.ru_stime,
                  wall_seconds=time.perf_counter()-start, whole_child_peak_rss_kib_linux=usage.ru_maxrss,
                  command=command, log_sha256=sha(log_path),
                  cost_scope="complete new worker: interpreter/import/hash/init/two LR128 fits/validation/checkpoints/holdout/writes")
    destination = Path(output) / "runs" / job["task"] / str(job["seed"])
    destination.mkdir(parents=True, exist_ok=True)
    write(destination / "EXECUTION.json", result)
    return result


def batch(protocol_path=PROTOCOL, output=DEFAULT_OUTPUT, workers=3):
    import resource
    protocol_path, output = Path(protocol_path).resolve(), Path(output).resolve()
    protocol = verify(protocol_path, output)
    if workers < 1 or workers > protocol["optimization"]["max_parallel_workers"]:
        raise ValueError("Worker count differs from registered maximum")
    if (output / "PROGRESS.json").exists() or (output / "COMPLETE.json").exists():
        raise FileExistsError("No silent retries or replacement of fixed-update evidence")
    (output / "process_logs").mkdir(exist_ok=False)
    started_cpu, started_wall = time.process_time(), time.perf_counter()
    children_before = resource.getrusage(resource.RUSAGE_CHILDREN)
    results = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_run_one, protocol_path, output, job): job for job in protocol["jobs"]}
        for future in as_completed(futures):
            job = futures[future]
            try:
                result = future.result()
            except Exception as error:
                result = dict(task=job["task"], model="free_dual", seed=job["seed"], status="coordinator_failure",
                              error_type=type(error).__name__, error=str(error))
            results.append(result)
            write(output / "PROGRESS.json", dict(completed_jobs=len(results), expected_jobs=len(protocol["jobs"]), results=results))
            print(json.dumps(dict(completed_jobs=len(results), expected_jobs=len(protocol["jobs"]),
                                  task=job["task"], seed=job["seed"], status=result["status"])), flush=True)
    verify(protocol_path, output)
    children_after = resource.getrusage(resource.RUSAGE_CHILDREN)
    result = dict(study_id=protocol["study_id"], status="completed" if all(r["status"]=="completed" for r in results) else "completed_with_failures",
                  completed_jobs=len(results), expected_jobs=len(protocol["jobs"]), results=results,
                  sum_complete_child_cpu_seconds=sum(r.get("child_cpu_seconds",0) for r in results),
                  aggregate_rusage_children_cpu_seconds=(children_after.ru_utime+children_after.ru_stime-children_before.ru_utime-children_before.ru_stime),
                  coordinator_cpu_seconds=time.process_time()-started_cpu,
                  wall_seconds=time.perf_counter()-started_wall,
                  protocol_sha256=sha(protocol_path), new_searches=18, reused_baseline_searches=126,
                  original_secondary_unchanged=True, primary_study_unchanged=True)
    write(output / "COMPLETE.json", result)
    print(json.dumps({key: result[key] for key in ("status","completed_jobs","sum_complete_child_cpu_seconds","wall_seconds")}))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("register", "run", "worker"))
    parser.add_argument("--protocol", type=Path, default=PROTOCOL)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--task")
    parser.add_argument("--seed", type=int)
    args = parser.parse_args()
    if args.command == "register":
        protocol = register(args.output, args.protocol)
        print(json.dumps(dict(status="registered", jobs=len(protocol["jobs"]), baseline_references=len(protocol["reused_baseline_references"]))))
    elif args.command == "run":
        batch(args.protocol, args.output, args.workers)
    else:
        worker(args.protocol, args.output, args.task, args.seed)


if __name__ == "__main__":
    main()
