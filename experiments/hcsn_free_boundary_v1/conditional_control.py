"""Additional conditional-threshold control, outside the frozen main family.

Only the direct policy's threshold generator changes. The original content,
drift, own-policy J/G, first-passage mean closure and training code are reused.
Each isolated worker temporarily binds training.build_model to this factory.
"""

import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import numpy as np
import torch
from torch import nn
from torch.nn import functional as F

from .benchmark_models import build_model as original_build_model
from .model import HCSNClassifier, RegenerativeContentCell


class ConditionalCell(RegenerativeContentCell):
    def __init__(self, width):
        super().__init__(width, boundary_mode="direct", channels="dual")
        self.raw_boundary_gap_slope = nn.Parameter(torch.zeros(width))

    def prepare(self, sequence):
        signal, local = super().prepare(sequence)
        local["boundary"] = local["K"] + F.softplus(
            self.raw_boundary_gap + self.raw_boundary_gap_slope * local["mu"])
        return signal, local


class ConditionalClassifier(HCSNClassifier):
    def __init__(self, input_dim, output_dim, width=32, depth=1, seed=0):
        super().__init__(input_dim, output_dim, width, depth, "direct", "dual", seed)
        # Replaying the identical backbone RNG preserves every inherited weight.
        # The extra slope is initialized with zeros and consumes no random draw.
        with torch.random.fork_rng():
            torch.manual_seed(seed + 100003)
            self.layers = nn.ModuleList([ConditionalCell(width) for _ in range(depth)])
        self.config.update(name="conditional_dual", boundary_mode="conditional_direct",
                           threshold_formula="K+softplus(raw_boundary_gap+raw_boundary_gap_slope*mu)")

    def parameter_groups(self):
        groups = super().parameter_groups()
        slopes = [(name, value) for name, value in groups["boundary"]
                  if name.endswith("raw_boundary_gap_slope")]
        groups["boundary"] = [(name, value) for name, value in groups["boundary"]
                              if not name.endswith("raw_boundary_gap_slope")]
        groups["boundary_conditioning"] = slopes
        return groups


def build_model(name, input_dim, output_dim, width=32, depth=1, seed=0):
    if name == "conditional_dual":
        return ConditionalClassifier(input_dim, output_dim, width, depth, seed)
    return original_build_model(name, input_dim, output_dim, width, depth, seed)


def run_conditional_search(data_path, seed, output_dir, **kwargs):
    from . import training
    previous = training.build_model
    try:
        training.build_model = build_model
        return training.run_search(data_path, "conditional_dual", seed, output_dir, **kwargs)
    finally:
        training.build_model = previous


def _hash(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for block in iter(lambda: source.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _write(path, value):
    path = Path(path)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")
    temporary.replace(path)


def verify_protocol(protocol_path):
    protocol_path = Path(protocol_path).resolve()
    protocol = json.loads(protocol_path.read_text())
    root = Path(__file__).resolve().parents[2]
    for relative, expected in protocol["files_sha256"].items():
        if _hash(root / relative) != expected:
            raise RuntimeError(f"Registered source/data identity changed: {relative}")
    if protocol["study_id"] != "conditional001":
        raise ValueError("Unexpected additional-study identity")
    return root, protocol


def run_worker(protocol_path, output, task, seed):
    protocol_hash = _hash(protocol_path)
    root, protocol = verify_protocol(protocol_path)
    job = dict(task=task, seed=seed, model="conditional_dual")
    if job not in protocol["jobs"]:
        raise ValueError("Job was not registered")
    optimization = protocol["optimization"]
    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
    summary = run_conditional_search(
        root / protocol["data"][task]["path"], seed, output,
        cpu_seconds=optimization["training_cpu_seconds_per_lr"],
        width=optimization["width"], depth=optimization["depth"],
        batch_size=optimization["batch_size"], max_updates=optimization["max_updates"],
        learning_rates=optimization["learning_rates"])
    verify_protocol(protocol_path)
    if _hash(protocol_path) != protocol_hash:
        raise RuntimeError("Supplementary protocol changed within the worker")
    selected_slopes = {}
    with np.load(Path(output) / "selected.npz", allow_pickle=False) as archive:
        for name in archive.files:
            if name.endswith("raw_boundary_gap_slope"):
                values = archive[name]
                selected_slopes[name] = dict(elements=values.size,
                                             l2_from_zero=float(np.linalg.norm(values)),
                                             max_abs_from_zero=float(np.max(np.abs(values))),
                                             nonzero_elements=int(np.count_nonzero(values)))
    _write(Path(output) / "CONDITIONAL_RECEIPT.json", dict(
        schema="hcsn-conditional-control-worker.v1", job=job,
        protocol_sha256=protocol_hash, files_sha256=protocol["files_sha256"],
        selected_checkpoint_sha256=summary["selection"]["selected_checkpoint_sha256"],
        selected_slope_changes=selected_slopes,
        counts=summary["counts"], status=summary["status"],
        family="additional/exploratory; outside original six-contrast Holm family"))
    print(json.dumps(dict(status=summary["status"], task=task, seed=seed)), flush=True)


def run_batch(protocol_path, output):
    root, protocol = verify_protocol(protocol_path)
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    registration_path = output / "REGISTRATION.json"
    registration = json.loads(registration_path.read_text())
    if registration["protocol_sha256"] != _hash(protocol_path):
        raise RuntimeError("Protocol differs from pre-run registration")
    if (output / "BATCH.json").exists():
        raise FileExistsError("Refuse to replace existing supplementary batch evidence")
    (output / "worker_logs").mkdir(exist_ok=True)
    (output / "jobs").mkdir(exist_ok=True)
    started_cpu, started_wall = time.process_time(), time.perf_counter()
    receipts = []
    environment = os.environ.copy()
    for key in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS",
                "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
        environment[key] = "1"
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    for index, job in enumerate(protocol["jobs"]):
        verify_protocol(protocol_path)
        if registration["protocol_sha256"] != _hash(protocol_path):
            raise RuntimeError("Protocol changed during supplementary execution")
        identifier = f"{job['task']}__conditional_dual__{job['seed']}"
        destination = output / "jobs" / identifier
        log_path = output / "worker_logs" / f"{identifier}.log"
        command = [sys.executable, "-m", "experiments.hcsn_free_boundary_v1.conditional_control",
                   "--worker", "--protocol", str(Path(protocol_path).resolve()),
                   "--output", str(destination), "--task", job["task"], "--seed", str(job["seed"])]
        wall = time.perf_counter()
        with log_path.open("w") as log:
            process = subprocess.Popen(command, cwd=root, env=environment,
                                       stdout=log, stderr=subprocess.STDOUT)
            _, status, usage = os.wait4(process.pid, 0)
            process.returncode = os.waitstatus_to_exitcode(status)
        destination.mkdir(parents=True, exist_ok=True)
        receipt = dict(job=job, command=command, returncode=process.returncode,
                       child_user_cpu_seconds=usage.ru_utime,
                       child_system_cpu_seconds=usage.ru_stime,
                       child_total_cpu_seconds=usage.ru_utime + usage.ru_stime,
                       wall_seconds=time.perf_counter()-wall,
                       child_peak_rss_kib_linux=usage.ru_maxrss,
                       measurement="os.wait4 complete worker: interpreter/import/hash/setup/two LR/train/validation/checkpoint/holdout/receipts",
                       protocol_sha256=registration["protocol_sha256"],
                       stdout_sha256=_hash(log_path), output=str(destination))
        _write(destination / "EXECUTION.json", receipt)
        receipts.append(receipt)
        _write(output / "BATCH.json", dict(study_id=protocol["study_id"],
                protocol_sha256=registration["protocol_sha256"], completed_jobs=len(receipts),
                expected_jobs=len(protocol["jobs"]), receipts=receipts,
                status="running", main_outcomes_read=False))
        print(json.dumps(dict(completed_jobs=index+1, expected_jobs=len(protocol["jobs"]),
                              task=job["task"], seed=job["seed"], returncode=process.returncode,
                              complete_child_cpu_seconds=receipt["child_total_cpu_seconds"])), flush=True)
    verify_protocol(protocol_path)
    if _hash(protocol_path) != registration["protocol_sha256"]:
        raise RuntimeError("Protocol changed before supplementary completion")
    success = all(row["returncode"] == 0 for row in receipts)
    final = dict(study_id=protocol["study_id"], protocol_sha256=registration["protocol_sha256"],
                 files_sha256=protocol["files_sha256"], completed_jobs=len(receipts),
                 expected_jobs=len(protocol["jobs"]), receipts=receipts,
                 complete_child_cpu_seconds=sum(row["child_total_cpu_seconds"] for row in receipts),
                 coordinator_cpu_seconds=time.process_time()-started_cpu,
                 wall_seconds=time.perf_counter()-started_wall,
                 completed_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                 status="completed" if success else "incomplete_failures_preserved",
                 main_outcomes_read=False, new_comparison_family="additional/exploratory")
    _write(output / "BATCH.json", final)
    _write(output / ("COMPLETE.json" if success else "INCOMPLETE.json"), final)
    print(json.dumps({key: final[key] for key in ("status", "completed_jobs", "complete_child_cpu_seconds", "wall_seconds")}), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, default=Path(__file__).with_name("CONDITIONAL_PROTOCOL.json"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--worker", action="store_true")
    parser.add_argument("--task")
    parser.add_argument("--seed", type=int)
    args = parser.parse_args()
    if args.worker:
        run_worker(args.protocol, args.output, args.task, args.seed)
    else:
        run_batch(args.protocol, args.output)


if __name__ == "__main__":
    main()
