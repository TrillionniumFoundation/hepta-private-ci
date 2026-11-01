"""Reproducible prepare/train/freeze/confirm entry point with retained failures."""

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import numpy as np
from threadpoolctl import threadpool_limits

from .fit import atomic_json

PACKAGE = "tools.hcsn.unified_cell_r12_20261031"
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
PROTOCOL = json.loads((HERE / "PROTOCOL.json").read_text())
KINDS = ("hx_distribution", "gru", "continuous_diagonal_ssm")


def run_job(seed, operation, output, kind=None):
    """Measure the complete child process, including imports and checkpoint IO."""
    path = Path(output) / str(seed)
    path.mkdir(parents=True, exist_ok=True)
    name = operation if kind is None else kind
    command = [sys.executable, "-m", PACKAGE + ".fit", operation, "--seed", str(seed), "--output", str(output)]
    if kind is not None:
        command += ["--kind", kind]
    start = time.perf_counter()
    environment = os.environ.copy()
    environment.update(OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1", MKL_NUM_THREADS="1")
    if not hasattr(os, "wait4"):
        raise RuntimeError("This measurement runner requires POSIX wait4 for complete child CPU accounting")
    with (path / (name + ".log")).open("w") as log:
        process = subprocess.Popen(command, cwd=ROOT, env=environment, stdout=log, stderr=subprocess.STDOUT)
        _, status, usage = os.wait4(process.pid, 0)
        process.returncode = os.waitstatus_to_exitcode(status)
    record = {"seed": seed, "operation": operation, "kind": kind,
              "returncode": process.returncode, "command": command,
              "full_process_cpu_seconds": usage.ru_utime + usage.ru_stime,
              "user_cpu_seconds": usage.ru_utime, "system_cpu_seconds": usage.ru_stime,
              "wall_seconds": time.perf_counter() - start,
              "max_rss_platform_units": usage.ru_maxrss,
              "status": "completed" if process.returncode == 0 else "failed"}
    atomic_json(path / (name + "_job.json"), record)
    print(json.dumps({k: record[k] for k in ("seed", "operation", "kind", "status", "full_process_cpu_seconds")}), flush=True)
    return record


def train_campaign(output, workers=2):
    output = Path(output).resolve()
    if any((output / str(seed) / (kind + ".json")).exists() for seed in PROTOCOL["seeds"] for kind in KINDS):
        raise FileExistsError("Training artifacts already exist; preserve them and choose a new run directory")
    start = time.perf_counter()
    records = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        prepared = list(pool.map(lambda seed: run_job(seed, "prepare", output), PROTOCOL["seeds"]))
        records.extend(prepared)
        valid_seeds = [r["seed"] for r in prepared if r["returncode"] == 0]
        futures = [pool.submit(run_job, seed, "train", output, kind) for seed in valid_seeds for kind in KINDS]
        for future in as_completed(futures):
            records.append(future.result())
    for seed in PROTOCOL["seeds"]:
        cost = {r["kind"] or "prepare": r for r in records if r["seed"] == seed}
        atomic_json(output / str(seed) / "job_costs.json", cost)
    manifest = {"schema": "hcsn-r13-training-campaign-v1", "records": records,
                "workers": workers, "wall_seconds": time.perf_counter() - start,
                "full_child_cpu_seconds": sum(r["full_process_cpu_seconds"] for r in records),
                "failure_count": sum(r["returncode"] != 0 for r in records)}
    atomic_json(output / "training_manifest.json", manifest)
    if manifest["failure_count"]:
        raise RuntimeError("Some jobs failed; all logs and failure records were retained")
    return manifest


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def source_paths():
    files = list(HERE.glob("*.py")) + list(HERE.glob("*.c"))
    files += [HERE / name for name in ("PROTOCOL.json", "IMPLEMENTATION.json", "BASELINE.json", "requirements-numpy.txt")]
    files.append(HERE.parent / "calibrated_operator_r11_20261031" / "numerics" / "kernel.py")
    return sorted(files)


def freeze(output, source_commit):
    output = Path(output).resolve()
    if (output / "FREEZE.json").exists():
        raise FileExistsError("Candidate freeze already exists")
    if list(output.glob("*/confirmation_*.json")) or list(output.glob("CONFIRMATION_*.json")):
        raise FileExistsError("Confirmation has already been opened; a new freeze is forbidden")
    selection, artifacts, training_data = {}, {}, {}
    for seed in PROTOCOL["seeds"]:
        scores = {}
        for kind in KINDS:
            path = output / str(seed) / (kind + ".json")
            fit = json.loads(path.read_text())
            if fit["status"] != "completed" or fit["budget_cpu_seconds"] != 20.:
                raise ValueError("A registered fit is missing or used the wrong CPU budget")
            artifacts[str(path.relative_to(output))] = sha256(path)
            scores[kind] = fit["selected_validation_joint_ce"]
        # Stable tie order is GRU before SSM. No confirmation information is used.
        chosen = min(KINDS[1:], key=lambda key: scores[key])
        selection[str(seed)] = {"kind": chosen, "validation_joint_ce": scores}
        for name in ("data_manifest.json", "job_costs.json"):
            file = output / str(seed) / name
            artifacts[str(file.relative_to(output))] = sha256(file)
        data_file = output / str(seed) / "common_data.npz"
        training_data[str(data_file.relative_to(output))] = sha256(data_file)
    artifacts["training_manifest.json"] = sha256(output / "training_manifest.json")
    payload = {"schema": "hcsn-r13-candidate-freeze-v1", "source_commit": source_commit,
               "source_files": {str(p.relative_to(ROOT)): sha256(p) for p in source_paths()},
               "artifacts": artifacts, "selection": selection,
               "training_data_files": training_data,
               "training_source_provenance": "These hashes are captured before confirmation, not individually at training-job startup. Training source remained unchanged during this campaign; no per-job cryptographic attestation is claimed.",
               "confirmation_generated": False, "independent_unit": "paired fit seed",
               "recorded_unix_time": time.time()}
    atomic_json(output / "FREEZE.json", payload)
    return {"freeze_sha256": sha256(output / "FREEZE.json"), "selection": selection}


def verify_freeze(output):
    output = Path(output).resolve()
    file = output / "FREEZE.json"
    frozen = json.loads(file.read_text())
    for relative, digest in frozen["source_files"].items():
        if sha256(ROOT / relative) != digest:
            raise ValueError("Source changed after freeze: " + relative)
    for relative, digest in frozen["artifacts"].items():
        if sha256(output / relative) != digest:
            raise ValueError("Training artifact changed after freeze: " + relative)
    for relative, digest in frozen["training_data_files"].items():
        if sha256(output / relative) != digest:
            raise ValueError("Common training data changed after freeze: " + relative)
    return frozen, sha256(file)


def restore_data(output):
    """Recreate omitted synthetic NPZ files without rewriting measured ledgers."""
    from .cell import Cell
    from .data import generate_sequences
    from .fit import array_hash
    output = Path(output).resolve()
    frozen = json.loads((output / "FREEZE.json").read_text())
    restored = []
    truth = Cell()
    for seed in PROTOCOL["seeds"]:
        path = output / str(seed) / "common_data.npz"
        expected = frozen["training_data_files"][str(path.relative_to(output))]
        if path.exists():
            if sha256(path) != expected:
                raise ValueError("Existing data differ from freeze; refusing overwrite")
            continue
        manifest = json.loads((path.parent / "data_manifest.json").read_text())
        train = generate_sequences(truth, seed + 1000000, 384)
        validation = generate_sequences(truth, seed + 2000000, 96)
        if array_hash(train) != manifest["train_hash"] or array_hash(validation) != manifest["validation_hash"]:
            raise ValueError("Regenerated arrays do not match the original training data")
        np.savez_compressed(path, **{"train_" + k: v for k, v in train.items()},
                            **{"validation_" + k: v for k, v in validation.items()})
        if sha256(path) != expected:
            raise ValueError("Regenerated NPZ byte hash differs; verify the pinned runtime")
        restored.append(seed)
    return {"restored_seeds": restored, "ledger_files_unchanged": True}


def confirm(output):
    from .evaluate import evaluate_seed
    from .statistics import summarize
    output = Path(output).resolve()
    frozen, identity = verify_freeze(output)
    if list(output.glob("*/confirmation_*.json")) or list(output.glob("CONFIRMATION_*.json")):
        raise FileExistsError("Confirmation outcomes already exist; they cannot be overwritten")
    with (output / "CONFIRMATION_STARTED.json").open("x") as started_file:
        json.dump({"freeze_sha256": identity, "recorded_unix_time": time.time(),
                   "note": "Written before generating any confirmation observation."}, started_file, indent=2)
    start, cpu = time.perf_counter(), time.process_time()
    rows = []
    try:
        for seed in PROTOCOL["seeds"]:
            chosen = frozen["selection"][str(seed)]["kind"]
            rows.extend(evaluate_seed(seed, output, chosen, identity))
            latest = [{"seed": row["seed"], "domain": row["domain"],
                       "D_minus_B": row["arms"]["D"]["mean_utility"] - row["arms"]["B"]["mean_utility"]} for row in rows[-2:]]
            print(json.dumps(latest), flush=True)
    except Exception as error:
        atomic_json(output / "CONFIRMATION_FAILED.json", {"error": repr(error), "completed_rows": len(rows),
                    "freeze_sha256": identity, "rerun_forbidden": True})
        raise
    result = summarize(rows)
    result.update(freeze_sha256=identity, source_commit=frozen["source_commit"],
                  confirmation_cpu_seconds=time.process_time() - cpu,
                  confirmation_wall_seconds=time.perf_counter() - start,
                  production_activation=False, all_scientific_blockers_closed=False)
    verify_freeze(output)
    atomic_json(output / "SUMMARY.json", result)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("operation", choices=("train", "freeze", "confirm", "verify", "restore-data"))
    parser.add_argument("--output", required=True)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--source-commit")
    args = parser.parse_args()
    with threadpool_limits(limits=1):
        if args.operation == "train":
            result = train_campaign(args.output, args.workers)
        elif args.operation == "freeze":
            if not args.source_commit:
                parser.error("freeze requires --source-commit")
            result = freeze(args.output, args.source_commit)
        elif args.operation == "verify":
            _, identity = verify_freeze(args.output)
            result = {"verified_freeze_sha256": identity}
        elif args.operation == "restore-data":
            result = restore_data(args.output)
        else:
            result = confirm(args.output)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
