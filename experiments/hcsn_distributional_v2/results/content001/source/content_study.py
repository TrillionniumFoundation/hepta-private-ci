"""Registered CPU-budgeted study of the retained-distribution content model.

Reuses the frozen v1 optimizer/search implementation with an isolated model
factory and probability-auditing evaluator. No heldout arrays are loaded until
both learning-rate searches finish and validation selection is durably locked.
"""

import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import random
import subprocess
import sys
import time
import traceback

import numpy as np
import torch
from torch.nn import functional as F

from experiments.hcsn_free_boundary_v1 import training
from .model import DISTRIBUTION_ARMS, MODEL_NAMES, build_model
from .content_training import train_candidate


TASKS = ("selective_copy", "mqar", "irregular", "mnist", "fsdd", "multimodal_select")
MECHANISM_MODELS = DISTRIBUTION_ARMS + ("two_gates",)
MECHANISM_TASKS = ("selective_copy", "multimodal_select")
ROOT = Path(__file__).resolve().parents[2]
PACKAGE = Path(__file__).resolve().parent


def file_hash(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for block in iter(lambda: source.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path, data):
    path = Path(path)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, indent=2, sort_keys=True, allow_nan=False) + "\n")
    temporary.replace(path)


def evaluate(model, split, batch_size=128, output_path=None):
    model.eval()
    total_loss, correct, count = 0.0, 0, 0
    maximum_mass_error, minimum_probability, maximum_events = 0.0, 1.0, 0.0
    distribution_audited = False
    outputs = []
    with torch.no_grad():
        for start in range(0, split["x"].shape[0], batch_size):
            x, dt, y = (split[key][start:start + batch_size] for key in ("x", "dt", "y"))
            logits, aux = model(x, dt, return_sequence=True)
            if not bool(torch.isfinite(logits).all()):
                raise FloatingPointError("Nonfinite evaluation logits")
            if "flow_mass" in aux:
                distribution_audited = True
                for layer in aux["layers"]:
                    probability = layer["probability"]
                    if not bool(torch.isfinite(probability).all()) or bool((probability < 0).any()):
                        raise FloatingPointError("Invalid probability state")
                    maximum_mass_error = max(maximum_mass_error,
                        float((layer["flow_mass"] - 1).abs().max()))
                    minimum_probability = min(minimum_probability, float(probability.min()))
                    maximum_events = max(maximum_events, float(layer["activity"].max()))
                if maximum_mass_error > 1e-4:
                    raise FloatingPointError("Probability mass error exceeds recorded float32 gate")
            mask = y != -100
            total_loss += F.cross_entropy(logits.flatten(0, 1), y.flatten(),
                                          ignore_index=-100, reduction="sum").item()
            correct += int(((logits.argmax(-1) == y) & mask).sum())
            count += int(mask.sum())
            if output_path is not None:
                outputs.append(logits.cpu().numpy())
    if output_path is not None:
        all_logits = np.concatenate(outputs)
        supervised = (split["y"] != -100).numpy()
        samples, steps = np.nonzero(supervised)
        logits = all_logits[supervised]
        np.savez_compressed(output_path, logits=logits, predictions=logits.argmax(-1),
                            labels=split["y"].numpy()[supervised], supervised=supervised,
                            sample_indices=samples, step_indices=steps)
    return dict(cross_entropy=total_loss/count, accuracy=correct/count, correct=correct,
                supervised_positions=count, samples=int(split["x"].shape[0]),
                distribution_audited=distribution_audited,
                max_mass_error=maximum_mass_error if distribution_audited else None,
                min_probability=minimum_probability if distribution_audited else None,
                max_expected_events_per_interval=maximum_events if distribution_audited else None)


def register(protocol_path, output, cpu_seconds=60.0, mechanism_seeds=8, workers=6):
    protocol_path, output = Path(protocol_path), Path(output)
    if protocol_path.exists() or output.exists():
        raise FileExistsError("Registration and output must be new")
    if cpu_seconds <= 0 or not 3 <= mechanism_seeds <= 8:
        raise ValueError("Positive CPU budget and 3..8 mechanism seeds required")
    frozen = json.loads((ROOT / "experiments/hcsn_free_boundary_v1/FREEZE.json").read_bytes())
    source_files = dict(frozen["files"])
    for name in ("model.py", "model_tests.py", "distribution_kernel.py", "kernel_tests.py",
                 "content_study.py", "content_training.py", "content_analysis.py", "content_tests.py"):
        path = PACKAGE / name
        source_files[str(path.relative_to(ROOT))] = file_hash(path)
    for relative, expected in source_files.items():
        if file_hash(ROOT / relative) != expected:
            raise RuntimeError(f"Frozen dependency changed: {relative}")
    index = json.loads((ROOT / "experiments/hcsn_free_boundary_v1/data/study001/INDEX.json").read_bytes())
    data = {task: dict(path=f"experiments/hcsn_free_boundary_v1/data/study001/{index[task]['path']}",
                       sha256=index[task]["sha256"], output_dim=index[task]["output_dim"])
            for task in TASKS}
    core = [dict(task=task, model=model, seed=seed) for task in TASKS
            for model in MODEL_NAMES for seed in (9201, 9202, 9203)]
    mechanism = [dict(task=task, model=model, seed=seed) for task in MECHANISM_TASKS
                 for model in MECHANISM_MODELS for seed in range(9201, 9201 + mechanism_seeds)]
    jobs = list({(j["task"], j["model"], j["seed"]): j for j in core + mechanism}.values())
    random.Random(20261030).shuffle(jobs)
    priority = dict(task="mnist", model="distribution_free_dual", seed=9201)
    jobs.remove(priority)
    jobs.insert(0, priority)
    protocol = dict(schema="hcsn-distribution-content-study.v2", study_id="content001",
        parent_commit="caa94dc53f8b8b721ee00076ce060d44a98d7a4f",
        registered_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        status_at_registration="no_content001_training_started",
        outcome_scope="new source and seeds; post-v1 diagnostic using previously observed task datasets",
        source_files_sha256=source_files, data=data, jobs=jobs,
        core=dict(tasks=list(TASKS), models=list(MODEL_NAMES), seeds=[9201, 9202, 9203]),
        mechanism=dict(tasks=list(MECHANISM_TASKS), models=list(MECHANISM_MODELS),
                       seeds=list(range(9201, 9201 + mechanism_seeds)),
                       reference="distribution_free_dual", contrasts=list(MECHANISM_MODELS[1:]),
                       unit="Within seed, equal average of two task accuracy differences",
                       test="exact two-sided sign flip; Holm across four contrasts",
                       interval="nominal paired t 95%; not simultaneous",
                       gate="mean>=.01 AND Holm p<=.05 AND nominal CI lower>0",
                       assumptions="sign exchangeability; fixed two tasks are not a random task population"),
        optimization=dict(learning_rates=[.001, .003], training_cpu_seconds_per_lr=cpu_seconds,
            primary_cpu_checkpoints=sorted(set([x for x in (15.0, 30.0, 60.0) if x < cpu_seconds] + [cpu_seconds])),
            width=32, depth=1, batch_size=32, max_updates=65536, threads=1,
            preregistration_budget_history="20->40->60 proposed using train-only engineering throughput; all before content001 heldout evaluation; final60 is common to every arm",
            optimizer="Adam defaults, clip gradient L2 at2", loss="task cross entropy only",
            selection="validation CE at common CPU gates only; both LR finish before selection lock and heldout",
            fixed128="saved if reached, ineligible for primary selection; no coverage-completion retraining"),
        physical_contract=dict(channels=8, cells=8, refractory_stages=2, lower=-2.0,
            time_scale=.1, state="full active-cell and refractory-phase masses",
            numerical_profile=dict(fixed_rate=8.1, fixed_terms=21, max_physical_duration=.36,
                fallback="none; reject out-of-domain rate/duration", parameter_domain="bounded transforms in model.py",
                causality="fixed numerical choices independent of batch neighbors and future inputs"),
            boundary="Brownian infinite-domain optimum with Erlang Laplace factor; not finite-grid or task optimum",
            conditional_boundary="K+.01+3.99*sigmoid(a+s*mu); gap initially.65, slope initially0; bounded to keep reset/initial inside grid-center range",
            values="finite-generator own-policy J/G; G equals forced continuation on refractory states",
            collapse="only active mass collapsed to two-center conditional mean; phase masses retained",
            ordinary_information="same full probability, mu/sigma/rho/K/reset/tau/b and content/time input",
            ordinary_compute="ordinary features omit unused policy-value solve; all actual work is charged",
            ordinary_variance="active mass weighted conditional cell-center variance; not full physical variance",
            same_parameter_arms="free dual, free ordinary, active mean collapse; conditional adds16 effective parameters",
            event="expected event count including repeated events and boundary-jump atoms, not event probability",
            float32_mass_gate=1e-4,
            limitations="finite lower wall, eight spatial cells, two Erlang phases; task value alignment separately tested"),
        parameter_matching=dict(target="actual distribution_free_dual backbone count",
            tolerance=.03, same_frontend_readout=True, padding=False,
            legacy="old mean-state cell with active learned inner projections to match count; new training required"),
        content_gate="descriptive3seed mean within .02 of best external legacy_free/two_gates/Transformer on each task",
        cost=dict(training_clock="sampling+forward+backward+gradient audit+clip+optimizer; full update overrun charged",
                  full_worker="os.wait4 includes interpreter/import/hash/setup/bothLR/validation/checkpoint/heldout",
                  no_energy_measurement=True, failures="preserved and charged; affected comparison incomplete"),
        execution=dict(workers=workers, expected_searches=len(jobs), expected_lr_candidates=2*len(jobs),
                       nominal_training_cpu_seconds=2*len(jobs)*cpu_seconds,
                       priority_reason="unlock actual v2 owner integration; remaining job order fixed before outcomes"))
    protocol_path.parent.mkdir(parents=True, exist_ok=True)
    write_json(protocol_path, protocol)
    output.mkdir(parents=True, exist_ok=False)
    write_json(output / "REGISTRATION.json", dict(protocol_sha256=file_hash(protocol_path),
                registered_utc=protocol["registered_utc"], status="before_main_training", jobs=len(jobs)))
    return protocol


def verify(protocol_path):
    protocol = json.loads(Path(protocol_path).read_bytes())
    for relative, expected in protocol["source_files_sha256"].items():
        if file_hash(ROOT / relative) != expected:
            raise RuntimeError(f"Registered dependency changed: {relative}")
    for record in protocol["data"].values():
        if file_hash(ROOT / record["path"]) != record["sha256"]:
            raise RuntimeError("Registered data changed")
    return protocol


def worker(protocol_path, output, task, model, seed):
    protocol = verify(protocol_path)
    original_protocol_hash = file_hash(protocol_path)
    job = dict(task=task, model=model, seed=seed)
    if job not in protocol["jobs"]:
        raise ValueError("Unregistered job")
    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
    old_factory, old_evaluate, old_candidate = training.build_model, training.evaluate, training.train_candidate
    try:
        training.build_model, training.evaluate = build_model, evaluate
        training.train_candidate = train_candidate
        o = protocol["optimization"]
        summary = training.run_search(ROOT / protocol["data"][task]["path"], model, seed, output,
            cpu_seconds=o["training_cpu_seconds_per_lr"], width=o["width"], depth=o["depth"],
            batch_size=o["batch_size"], max_updates=o["max_updates"], learning_rates=o["learning_rates"])
    finally:
        training.build_model, training.evaluate = old_factory, old_evaluate
        training.train_candidate = old_candidate
    verify(protocol_path)
    if file_hash(protocol_path) != original_protocol_hash:
        raise RuntimeError("Protocol changed during worker")
    write_json(Path(output) / "IDENTITY.json", dict(job=job, protocol_sha256=original_protocol_hash,
        source_files_sha256=protocol["source_files_sha256"], dataset_sha256=protocol["data"][task]["sha256"],
        status=summary["status"]))
    print(json.dumps(dict(job=job, status=summary["status"], selected_step=summary["selection"]["selected_step"])), flush=True)


def batch(protocol_path, output):
    protocol, output = verify(protocol_path), Path(output).resolve()
    protocol_path = Path(protocol_path).resolve()
    registration = json.loads((output / "REGISTRATION.json").read_bytes())
    if registration["protocol_sha256"] != file_hash(protocol_path):
        raise RuntimeError("Registration mismatch")
    if (output / "PROGRESS.json").exists():
        raise FileExistsError("Batch output already contains execution evidence")
    (output / "runs").mkdir()
    (output / "process_logs").mkdir()
    started_cpu, started_wall = time.process_time(), time.perf_counter()
    environment = os.environ.copy()
    for key in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
        environment[key] = "1"
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    pending, active, records = list(protocol["jobs"]), {}, []
    while pending or active:
        while pending and len(active) < protocol["execution"]["workers"]:
            job = pending.pop(0)
            identifier = f"{job['task']}__{job['model']}__{job['seed']}"
            destination, log_path = output / "runs" / identifier, output / "process_logs" / f"{identifier}.log"
            command = [sys.executable, "-m", "experiments.hcsn_distributional_v2.content_study", "worker",
                       "--protocol", str(protocol_path), "--output", str(destination),
                       "--task", job["task"], "--model", job["model"], "--seed", str(job["seed"])]
            stream = log_path.open("w")
            process = subprocess.Popen(command, cwd=ROOT, env=environment, stdout=stream, stderr=subprocess.STDOUT)
            active[process.pid] = dict(process=process, stream=stream, job=job, output=destination,
                                       log_path=log_path, command=command, wall=time.perf_counter())
        finished = []
        for pid, item in list(active.items()):
            got, status, usage = os.wait4(pid, os.WNOHANG)
            if not got:
                continue
            code = os.waitstatus_to_exitcode(status)
            item["process"].returncode = code
            item["stream"].close()
            item["output"].mkdir(parents=True, exist_ok=True)
            receipt = dict(job=item["job"], command=item["command"], returncode=code,
                child_user_cpu_seconds=usage.ru_utime, child_system_cpu_seconds=usage.ru_stime,
                child_total_cpu_seconds=usage.ru_utime+usage.ru_stime,
                wall_seconds=time.perf_counter()-item["wall"], child_peak_rss_kib_linux=usage.ru_maxrss,
                protocol_sha256=registration["protocol_sha256"], stdout_sha256=file_hash(item["log_path"]),
                output=str(item["output"].relative_to(output)),
                measurement="os.wait4 complete isolated worker; training CPU is a nested component")
            write_json(item["output"] / "EXECUTION.json", receipt)
            records.append(receipt)
            finished.append(pid)
            print(json.dumps(dict(completed=len(records), expected=len(protocol["jobs"]),
                                  job=item["job"], returncode=code)), flush=True)
        for pid in finished:
            del active[pid]
        if finished:
            write_json(output / "PROGRESS.json", dict(expected=len(protocol["jobs"]), completed=len(records),
                protocol_sha256=registration["protocol_sha256"], records=records))
        if active:
            time.sleep(.05)
    verify(protocol_path)
    if file_hash(protocol_path) != registration["protocol_sha256"]:
        raise RuntimeError("Protocol changed during batch")
    success = all(row["returncode"] == 0 for row in records)
    final = dict(schema="hcsn-distribution-content-completion.v2", status="completed" if success else "incomplete",
        expected=len(protocol["jobs"]), completed=len(records), failures=sum(row["returncode"] != 0 for row in records),
        protocol_sha256=registration["protocol_sha256"], records=records,
        complete_child_cpu_seconds=sum(row["child_total_cpu_seconds"] for row in records),
        coordinator_cpu_seconds=time.process_time()-started_cpu, wall_seconds=time.perf_counter()-started_wall,
        completed_utc=datetime.datetime.now(datetime.timezone.utc).isoformat())
    write_json(output / "COMPLETE.json", final)
    return final


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("register", "run", "worker"))
    parser.add_argument("--protocol", type=Path, default=PACKAGE / "CONTENT_PROTOCOL.json")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cpu-seconds", type=float, default=60)
    parser.add_argument("--mechanism-seeds", type=int, default=8)
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--task", choices=TASKS)
    parser.add_argument("--model", choices=MODEL_NAMES)
    parser.add_argument("--seed", type=int)
    args = parser.parse_args()
    if args.action == "register":
        result = register(args.protocol, args.output, args.cpu_seconds, args.mechanism_seeds, args.workers)
        print(json.dumps(result["execution"]))
    elif args.action == "worker":
        worker(args.protocol, args.output, args.task, args.model, args.seed)
    else:
        result = batch(args.protocol, args.output)
        print(json.dumps({key: result[key] for key in ("status", "expected", "completed", "failures",
                                                     "complete_child_cpu_seconds", "wall_seconds")}))


if __name__ == "__main__":
    main()
