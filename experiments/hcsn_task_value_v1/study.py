"""Register and execute the six-deliverable research matrix, preserving failures."""

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import random
import subprocess
import sys
import time


PACKAGE = Path(__file__).resolve().parent
ROOT = PACKAGE.parents[1]
SEEDS = (31031, 31067, 31103)
SOURCES = (
    "operators.py", "model.py", "experiment.py", "training.py", "study.py", "async_av.py", "cost_meter.py",
    "../continuous_spiking_network/baseline.py", "../continuous_spiking_network/data.py",
    "../hcsn_free_boundary_v1/datasets.py", "../hcsn_free_boundary_v1/oracle_torch.py",
    "../hcsn_distributional_v2/distribution_kernel.py", "../hcsn_distributional_v2/stable_probability.py",
    "../hcsn_conservative_acceleration_v1/kernel.py", "data/async_manifest.json",
    "results/async_frontend001/data/NORMALIZATION.json",
    "results/async_frontend001/data/train.npz", "results/async_frontend001/data/validation.npz",
    "results/async_frontend001/data/test.npz",
)


def write(path, value):
    path = Path(path)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")
    temporary.replace(path)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def register(destination):
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=False)
    (destination / "jobs").mkdir()
    hashes = {name: sha(PACKAGE / name) for name in SOURCES}
    jobs, identifiers = [], set()

    def add(family, task, arm, width=16, cpu_budget=None):
        for seed in SEEDS:
            prefix = "cpu" if cpu_budget else "fixed"
            identifier = f"{prefix}_{task}_{arm}_w{width}_s{seed}"
            if identifier in identifiers:
                raise ValueError("Duplicate job: " + identifier)
            identifiers.add(identifier)
            av = task == "async_av"
            job = dict(id=identifier, family=family, task=task, arm=arm, seed=seed, width=width,
                       learning_rate=.003, updates=8192 if cpu_budget else 64 if av else 256,
                       batch_size=2 if av else 8, validate_every=32,
                       training_cpu_budget=cpu_budget, source_hashes=hashes)
            write(destination / "jobs" / f"{identifier}.json", job)
            jobs.append({**{key: value for key, value in job.items() if key != "source_hashes"},
                         "job_file_sha256": sha(destination / "jobs" / f"{identifier}.json")})

    for boundary in ("value", "fixed", "direct"):
        for channel in ("dual", "single", "ordinary"):
            add("factorial", "selective_copy", boundary + "_" + channel)
    for arm in ("two_gates", "transformer", "lif_snn"):
        add("factorial", "selective_copy", arm)
    for group in ("content", "dynamics", "boundary", "reset", "refractory"):
        add("freeze", "selective_copy", "freeze_" + group)
    add("freeze", "selective_copy", "stop_gradient_dual")
    for task in ("mqar", "delayed_recall"):
        for arm in ("value_dual", "value_single", "value_ordinary", "two_gates", "transformer", "lif_snn"):
            add("transfer", task, arm)
        for width in (8, 32):
            for arm in ("value_dual", "two_gates", "transformer"):
                add("width", task, arm, width)
    for arm in ("value_dual", "value_ordinary", "two_gates", "transformer", "lif_snn"):
        add("async_av", "async_av", arm)
    for task in ("selective_copy", "mqar", "delayed_recall"):
        for arm in ("value_dual", "two_gates", "transformer"):
            add("equal_cpu", task, arm, cpu_budget=15.0)
    random.Random(2026103191).shuffle(jobs)
    protocol = dict(schema="hcsn-task-value-study.v1", status="registered", jobs=jobs,
        registered_at=datetime.now(timezone.utc).isoformat(), seeds=list(SEEDS),
        data_seed=2026103107, source_hashes=hashes,
        parent_commit="1d959d8d82091e6014b13c2191f62bf74e778561",
        objective="Identical masked cross-entropy + AdamW weight decay for every arm; learned local reward is supervised inductive bias, not actual future task return",
        budget_contract="Fixed family matches updates and batch stream; equal_cpu family caps training-loop CPU with at most one completed minibatch overshoot; all whole-process costs also reported",
        information_contract="Shared raw feature/time/presence inputs and train-only transforms; external recurrent controls take one step per observed event including dt=0, physical seconds remain explicit inputs",
        missing_contract="Missing payload: observed=false while acquisition time/valid terminal position remain; padding has valid=false; no hidden payload exposed",
        capacity_contract="Same frontend width and output classes; nearest active backbone parameter count without padding; five freeze arms intentionally reduce trainable parameter count",
        selection="Minimum validation cross-entropy at every 32 updates and last/budget step; checkpoint+optimizer+RNG saved before any test load",
        testing="Fresh deterministic synthetic test generated after selection; lengths32/64/128. AV is previously observed actor-disjoint development subset; missing modality interventions are synthetic, not measured transport outages",
        evaluation=dict(accuracy_noninferiority_margin=.02, maximum_ce_ratio=1.05,
                        parameter_relative_gap_max=.05, cpu_relative_gap_max=.10,
                        paired_seed_t_critical=4.302652729911275, confidence=.95,
                        minimum_accuracy_gain_lower_bound=0.0,
                        multiple_comparisons="Nominal preregistered pairwise intervals; no multiplicity-adjusted discovery or global superiority claim"),
        economics="Whole worker wait4 includes startup/imports/initialization/training/validation/checkpoints/test/inference; train clock is a subtotal. AV front-end preparation separately reported. Shared CPU host; no measured joules/GPU/distributed communication claim",
        state_memory="No-grad returned state: report logical tensor bytes AND deduplicated storage bytes. Training/BPTT/aux traces are not constant-memory",
        expected_jobs=len(jobs), max_parallel_workers=3,
        preflight="results/preflight001: train-only code/shape/resource check; controls subsequently repaired before formal registration")
    write(destination / "protocol.json", protocol)
    write(destination / "registration_receipt.json", dict(protocol_sha256=sha(destination / "protocol.json"),
          source_hashes=hashes, timestamp=datetime.now(timezone.utc).isoformat()))
    return protocol


def execute(destination, workers=3):
    destination = Path(destination).resolve()
    protocol = json.loads((destination / "protocol.json").read_text())
    registration = json.loads((destination / "registration_receipt.json").read_text())
    if sha(destination / "protocol.json") != registration["protocol_sha256"]:
        raise RuntimeError("Registered protocol changed")
    for name, expected in protocol["source_hashes"].items():
        if sha(PACKAGE / name) != expected:
            raise RuntimeError("Source or data drift: " + name)
    if workers not in range(1, protocol["max_parallel_workers"] + 1):
        raise ValueError("Worker count exceeds registration")
    for name in ("runs", "meter"):
        (destination / name).mkdir(exist_ok=True)
    environment = dict(os.environ, OMP_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1", MKL_NUM_THREADS="1")
    started, rows = time.perf_counter(), []

    def worker(job):
        identifier = job["id"]
        receipt = destination / "meter" / f"{identifier}.json"
        output = destination / "runs" / identifier
        if receipt.exists() or output.exists():
            raise FileExistsError("Refuse to rerun or overwrite job: " + identifier)
        if sha(destination / "jobs" / f"{identifier}.json") != job["job_file_sha256"]:
            raise RuntimeError("Registered job file changed: " + identifier)
        command = [sys.executable, "-B", "-m", "experiments.hcsn_task_value_v1.cost_meter",
                   "--output", str(receipt), "--timeout-seconds", "1200", "--", sys.executable,
                   "-B", "-m", "experiments.hcsn_task_value_v1.training", "--job",
                   str(destination / "jobs" / f"{identifier}.json"), "--output", str(output)]
        launch = subprocess.run(command, cwd=ROOT, env=environment, text=True, capture_output=True)
        (destination / "meter" / f"{identifier}.launcher.log").write_text(launch.stdout + launch.stderr)
        return dict(id=identifier, returncode=launch.returncode, receipt_exists=receipt.exists(),
                    summary_exists=(output / "summary.json").exists())

    with ThreadPoolExecutor(max_workers=workers) as pool:
        pending = {pool.submit(worker, job): job for job in protocol["jobs"]}
        for future in as_completed(pending):
            job = pending[future]
            try:
                row = future.result()
            except Exception as error:
                row = dict(id=job["id"], returncode=None, launcher_error=f"{type(error).__name__}: {error}")
            rows.append(row)
            write(destination / "progress.json", dict(completed=len(rows), expected=len(pending), rows=rows,
                elapsed_wall_seconds=time.perf_counter() - started, workers=workers))
            print(json.dumps(dict(completed=len(rows), expected=len(pending), **row)), flush=True)
    status = dict(complete=len(rows) == len(protocol["jobs"]), rows=rows,
                  elapsed_wall_seconds=time.perf_counter() - started, workers=workers,
                  protocol_sha256=registration["protocol_sha256"],
                  successful=sum(row["returncode"] == 0 and row.get("summary_exists", False) for row in rows))
    write(destination / "execution.json", status)
    return status


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("register", "run"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=3)
    args = parser.parse_args()
    if args.action == "register":
        value = register(args.output)
        print(json.dumps(dict(expected_jobs=value["expected_jobs"], source_files=len(value["source_hashes"]))))
    else:
        value = execute(args.output, args.workers)
        print(json.dumps({k: value[k] for k in ("complete", "successful", "elapsed_wall_seconds")}))
        raise SystemExit(0 if value["successful"] == len(value["rows"]) else 1)


if __name__ == "__main__":
    main()
