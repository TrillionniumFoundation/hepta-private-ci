"""Train-only, isolated-process equivalence and memory preflight.

Every arm and both actual train splits use the same three B32 draws, all named
parameter gradients, and Adam updates. Heldout arrays are never loaded. The
coordinator uses only the standard library and records complete wait4 costs.
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
import traceback


ROOT = Path(__file__).resolve().parents[2]
PACKAGE = Path(__file__).resolve().parent
UPSTREAM = ROOT / "experiments/hcsn_risk_ablation_v1/EQUAL_UPDATES_4W_PROTOCOL.json"
GIB = 1024 ** 3


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for block in iter(lambda: source.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def write(path, value):
    path = Path(path)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")
    temporary.replace(path)


def utc():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def memory():
    base = Path("/sys/fs/cgroup")
    stat = {key: int(value) for key, value in
            (line.split() for line in (base / "memory.stat").read_text().splitlines())}
    events = {key: int(value) for key, value in
              (line.split() for line in (base / "memory.events").read_text().splitlines())}
    maximum = int((base / "memory.max").read_text())
    nonreclaimable = stat["anon"] + stat.get("shmem", 0) + max(
        0, stat["kernel"] - stat.get("slab_reclaimable", 0))
    return dict(utc=utc(), current_bytes=int((base / "memory.current").read_text()),
                maximum_bytes=maximum, stat=stat, events=events,
                estimated_nonreclaimable_bytes=nonreclaimable,
                estimated_headroom_bytes=maximum - nonreclaimable)


def verify(registration):
    for name, expected in registration["source_files_sha256"].items():
        if sha(ROOT / name) != expected:
            raise RuntimeError("Source mismatch: " + name)
    for task, item in registration["data"].items():
        if sha(ROOT / item["path"]) != item["sha256"]:
            raise RuntimeError("Data mismatch: " + task)


def register(output):
    upstream = json.loads(UPSTREAM.read_bytes())
    if sha(UPSTREAM) != "86bd8bc59c08b96cf76de482cfde007b251ae7fcb2295ff44a4ad0616f1d9a56":
        raise RuntimeError("Frozen fixed128 protocol identity mismatch")
    sources = dict(upstream["source_files_sha256"])
    sources[str(UPSTREAM.relative_to(ROOT))] = sha(UPSTREAM)
    for name in ("vector_kernel.py", "model.py", "COPY_MANIFEST.json",
                 "kernel_validation.py", "train_equivalence.py"):
        path = PACKAGE / name
        sources[str(path.relative_to(ROOT))] = sha(path)
    kernel_result = PACKAGE / "results/kernel_preflight001/RESULTS.json"
    if not json.loads(kernel_result.read_bytes())["passed"]:
        raise RuntimeError("Kernel validation must pass first")
    jobs = [dict(task=task, model=arm, seed=9401, profile=profile)
            for task in ("selective_copy", "mqar")
            for arm in upstream["models"]
            for profile in ("matrix_oracle", "backward_vector")]
    limits = dict(
        logits=dict(atol=2e-6, rtol=2e-6),
        loss=dict(atol=1e-6, rtol=1e-6),
        gradient=dict(atol=5e-8, rtol=2e-5),
        state=dict(atol=2e-7, rtol=2e-6),
        optimizer=dict(atol=5e-9, rtol=2e-5),
        diagnostic=dict(atol=2e-6, rtol=2e-6))
    registration = dict(schema="hcsn-risk-memory-train-equivalence.v1",
        registered_utc=utc(), source_files_sha256=sources, data=upstream["data"],
        kernel_validation=dict(path=str(kernel_result.relative_to(ROOT)), sha256=sha(kernel_result)),
        jobs=jobs, optimization=dict(updates=3, batch_size=32, width=32, depth=1,
            learning_rate=.001, optimizer="Adam defaults", gradient_clip_l2=2.0,
            minibatch_generator="seed+200003, exactly the frozen worker randint prefix"),
        comparison=dict(initial_state="bitwise", input_batches="bitwise", tolerances=limits,
            gradients="all named parameters, before and after clipping, at each update",
            states="entire state_dict after each of three Adam updates",
            optimizer="all tensor states after each Adam update",
            finite="every recorded floating array must be finite", heldout_loaded=False),
        resource=dict(workers=1, per_worker_peak_budget_bytes=int(1.3 * GIB),
            required_shared_reserve_bytes=2 * GIB, poll_seconds=10,
            guard="headroom=max-anon-shmem-max(kernel-slab_reclaimable,0); budget+reserve required",
            failure="stop; preserve every result and full wait4 receipt; no automatic rerun",
            significant_memory_goal="each risk-enabled B32 vector peak RSS <= 0.8 times paired oracle; measured separately from correctness",
            timing="complete wait4 CPU/RSS plus nested core-update CPU; one sequential isolated process per profile/case",
            energy_measured=False),
        outcome_scope="train-only numerical implementation preflight; no predictive-quality comparison or inference")
    verify(registration)
    output.mkdir(parents=True, exist_ok=False)
    write(output / "REGISTRATION.json", registration)
    snapshot = output / "source_snapshot"
    snapshot.mkdir()
    for name in ("vector_kernel.py", "model.py", "COPY_MANIFEST.json",
                 "kernel_validation.py", "train_equivalence.py"):
        (snapshot / name).write_bytes((PACKAGE / name).read_bytes())
    print(json.dumps(dict(registered=str(output), jobs=len(jobs),
                         registration_sha256=sha(output / "REGISTRATION.json"))), flush=True)


def worker(registration_path, output, job):
    import numpy as np
    import torch
    from torch.nn import functional as F
    from experiments.hcsn_free_boundary_v1 import training
    from experiments.hcsn_risk_ablation_v1.model import build_model as original_model
    from .model import build_model as vector_model

    registration = json.loads(registration_path.read_bytes())
    verify(registration)
    if job not in registration["jobs"]:
        raise ValueError("Unregistered preflight job")
    torch.set_num_threads(1)
    output.mkdir(parents=True, exist_ok=False)
    access, rows, arrays = [], [], {}
    start_cpu, start_wall = time.process_time(), time.perf_counter()
    write(output / "REQUEST.json", dict(job=job, registration_sha256=sha(registration_path),
                                       torch_version=torch.__version__))
    try:
        train = training.load_split(ROOT / registration["data"][job["task"]]["path"], "train", access)
        factory = original_model if job["profile"] == "matrix_oracle" else vector_model
        model = factory(job["model"], train["x"].shape[-1], int(train["y"].max()) + 1,
                        width=32, depth=1, seed=job["seed"])
        for name, value in model.state_dict().items():
            arrays["initial::" + name] = value.detach().numpy().copy()
        optimizer = torch.optim.Adam(model.parameters(), lr=.001)
        generator = torch.Generator().manual_seed(job["seed"] + 200003)
        names = [name for name, _ in model.named_parameters()]
        prefix = hashlib.sha256()
        for step in range(1, 4):
            indices = torch.randint(train["x"].shape[0], (32,), generator=generator)
            prefix.update(indices.numpy().tobytes())
            x, dt, y = (train[key][indices] for key in ("x", "dt", "y"))
            for key, value in dict(indices=indices, x=x, dt=dt, y=y).items():
                arrays[f"batch{step}::{key}"] = value.numpy().copy()
            model.train()
            optimizer.zero_grad(set_to_none=True)
            start_update = time.process_time()
            logits, aux = model(x, dt, return_sequence=True)
            loss = F.cross_entropy(logits.flatten(0, 1), y.flatten(), ignore_index=-100)
            loss.backward()
            if not bool(torch.isfinite(loss)):
                raise FloatingPointError("Nonfinite train-only loss")
            for name, value in model.named_parameters():
                if value.grad is None or not bool(torch.isfinite(value.grad).all()):
                    raise FloatingPointError("Missing/nonfinite named gradient: " + name)
                arrays[f"gradient{step}::{name}"] = value.grad.detach().numpy().copy()
            norm = torch.nn.utils.clip_grad_norm_(model.parameters(), 2.0)
            for name, value in model.named_parameters():
                arrays[f"clipped{step}::{name}"] = value.grad.detach().numpy().copy()
            optimizer.step()
            core_cpu = time.process_time() - start_update
            arrays[f"logits{step}"] = logits.detach().numpy().copy()
            arrays[f"loss{step}"] = loss.detach().numpy().copy()
            arrays[f"diagnostic{step}::preclip_l2"] = norm.detach().numpy().copy()
            for key in ("first_event_probability", "probability", "flow_mass", "boundary",
                        "projection_actual_l1_correction"):
                if key in aux:
                    arrays[f"diagnostic{step}::{key}"] = aux[key].detach().numpy().copy()
            for name, value in model.state_dict().items():
                arrays[f"state{step}::{name}"] = value.detach().numpy().copy()
            for name, value in model.named_parameters():
                for key, item in optimizer.state[value].items():
                    if torch.is_tensor(item):
                        arrays[f"optimizer{step}::{name}::{key}"] = item.detach().numpy().copy()
                    else:
                        raise TypeError("Unexpected non-tensor Adam state")
            row = dict(step=step, core_update_cpu_seconds=core_cpu,
                       batch_prefix_sha256=prefix.hexdigest(), named_gradients=len(names),
                       process_peak_rss_bytes=training._peak_rss_bytes())
            rows.append(row)
            write(output / "PROGRESS.json", dict(job=job, rows=rows, access_log=access))
        for name, array in arrays.items():
            if np.issubdtype(array.dtype, np.floating) and not np.isfinite(array).all():
                raise FloatingPointError("Nonfinite recorded array: " + name)
        raw = output / "raw_arrays.npz"
        np.savez_compressed(raw, **arrays)
        verify(registration)
        write(output / "RESULT.json", dict(status="completed", job=job, access_log=access,
            config=model.config, counts=model.counts(), rows=rows, named_parameters=names,
            raw_arrays_sha256=sha(raw), recorded_arrays=len(arrays),
            core_update_cpu_seconds=sum(row["core_update_cpu_seconds"] for row in rows),
            body_cpu_seconds=time.process_time() - start_cpu,
            body_wall_seconds=time.perf_counter() - start_wall,
            process_peak_rss_bytes=training._peak_rss_bytes()))
    except Exception as error:
        write(output / "FAILURE.json", dict(job=job, error_type=type(error).__name__,
            error=str(error), traceback=traceback.format_exc(), access_log=access, rows=rows,
            body_cpu_seconds=time.process_time() - start_cpu))
        raise


def identifier(job):
    return "__".join(str(job[key]) for key in ("task", "model", "seed", "profile"))


def run(output):
    registration_path = output / "REGISTRATION.json"
    registration = json.loads(registration_path.read_bytes())
    verify(registration)
    digest = sha(registration_path)
    runs, logs = output / "runs", output / "process_logs"
    runs.mkdir()
    logs.mkdir()
    records, aborted = [], False
    start_cpu, start_wall = time.process_time(), time.perf_counter()
    environment = os.environ.copy()
    environment.update({key: "1" for key in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS")})
    needed = (registration["resource"]["per_worker_peak_budget_bytes"] +
              registration["resource"]["required_shared_reserve_bytes"])
    with (output / "RESOURCE_JOURNAL.jsonl").open("x") as journal:
        for job in registration["jobs"]:
            while True:
                resources = memory()
                eligible = resources["estimated_headroom_bytes"] >= needed
                journal.write(json.dumps(dict(job=job, eligible=eligible,
                    needed_bytes=needed, resources=resources), sort_keys=True) + "\n")
                journal.flush()
                if eligible:
                    break
                time.sleep(registration["resource"]["poll_seconds"])
            folder, log = runs / identifier(job), logs / (identifier(job) + ".log")
            command = [sys.executable, "-m", "experiments.hcsn_risk_memory_v1.train_equivalence", "worker",
                "--registration", str(registration_path), "--output", str(folder),
                "--task", job["task"], "--model", job["model"], "--seed", str(job["seed"]),
                "--profile", job["profile"]]
            launched = time.perf_counter()
            with log.open("x") as stream:
                process = subprocess.Popen(command, cwd=ROOT, env=environment,
                                           stdout=stream, stderr=subprocess.STDOUT)
                got, status, usage = os.wait4(process.pid, 0)
                if got != process.pid:
                    raise RuntimeError("Unexpected wait4 child")
                code = os.waitstatus_to_exitcode(status)
                process.returncode = code
            after = memory()
            receipt = dict(job=job, command=command, returncode=code,
                registration_sha256=digest, stdout_sha256=sha(log),
                child_user_cpu_seconds=usage.ru_utime, child_system_cpu_seconds=usage.ru_stime,
                child_total_cpu_seconds=usage.ru_utime + usage.ru_stime,
                child_peak_rss_kib_linux=usage.ru_maxrss, wall_seconds=time.perf_counter() - launched,
                resources_before=resources, resources_after=after)
            records.append(receipt)
            write(output / "PROGRESS.json", dict(records=records, expected=len(registration["jobs"])))
            folder.mkdir(exist_ok=True)
            write(folder / "EXECUTION.json", receipt)
            print(json.dumps(dict(completed=len(records), expected=len(registration["jobs"]),
                                  job=job, returncode=code, peak_rss_kib=usage.ru_maxrss)), flush=True)
            if code != 0 or after["events"]["oom_kill"] != resources["events"]["oom_kill"]:
                aborted = True
                break
    verify(registration)
    final = dict(status="aborted" if aborted else "completed", records=records,
        expected=len(registration["jobs"]), completed=len(records),
        unstarted=registration["jobs"][len(records):], failures=sum(row["returncode"] != 0 for row in records),
        registration_sha256=digest,
        complete_child_cpu_seconds=sum(row["child_total_cpu_seconds"] for row in records),
        coordinator_cpu_seconds=time.process_time() - start_cpu,
        wall_seconds=time.perf_counter() - start_wall)
    write(output / ("ABORTED.json" if aborted else "COMPLETE.json"), final)
    if aborted:
        raise RuntimeError("Memory equivalence preflight aborted; preserve outputs")


def analyze(output):
    import numpy as np

    registration_path = output / "REGISTRATION.json"
    registration = json.loads(registration_path.read_bytes())
    verify(registration)
    complete = json.loads((output / "COMPLETE.json").read_bytes())
    if complete["status"] != "completed" or complete["completed"] != len(registration["jobs"]):
        raise RuntimeError("Incomplete numerical comparison")
    if complete["registration_sha256"] != sha(registration_path):
        raise RuntimeError("Execution registration mismatch")
    pairs, failures = [], []
    limits = registration["comparison"]["tolerances"]
    for baseline in registration["jobs"][::2]:
        variant = dict(baseline, profile="backward_vector")
        folders = [output / "runs" / identifier(job) for job in (baseline, variant)]
        results = [json.loads((folder / "RESULT.json").read_bytes()) for folder in folders]
        receipts = [json.loads((folder / "EXECUTION.json").read_bytes()) for folder in folders]
        for result, folder in zip(results, folders):
            if (len(result["access_log"]) != 1 or
                    result["access_log"][0].get("event") != "load_split" or
                    result["access_log"][0].get("split") != "train"):
                raise RuntimeError("Preflight accessed a non-training split")
            if result["raw_arrays_sha256"] != sha(folder / "raw_arrays.npz"):
                raise RuntimeError("Raw-array identity mismatch")
        compared = []
        with np.load(folders[0] / "raw_arrays.npz", allow_pickle=False) as original, \
             np.load(folders[1] / "raw_arrays.npz", allow_pickle=False) as vector:
            if set(original.files) != set(vector.files):
                raise RuntimeError("Recorded tensor names differ")
            for name in sorted(original.files):
                first, second = original[name], vector[name]
                if first.shape != second.shape or first.dtype != second.dtype:
                    raise RuntimeError("Recorded tensor shape/dtype mismatch: " + name)
                if name.startswith(("initial::", "batch")):
                    kind, passed = "bitwise", np.array_equal(first, second)
                    tolerance = dict(atol=0.0, rtol=0.0)
                else:
                    kind = ("gradient" if name.startswith(("gradient", "clipped")) else
                            "state" if name.startswith("state") else
                            "optimizer" if name.startswith("optimizer") else
                            "logits" if name.startswith("logits") else
                            "loss" if name.startswith("loss") else "diagnostic")
                    tolerance = limits[kind]
                    passed = bool(np.allclose(first, second, **tolerance))
                delta = np.abs(first.astype(np.float64) - second.astype(np.float64))
                scale = tolerance["atol"] + tolerance["rtol"] * np.abs(first.astype(np.float64))
                error_ratio = float(np.max(np.divide(delta, scale, out=np.zeros_like(delta), where=scale > 0)))
                record = dict(tensor=name, kind=kind, passed=bool(passed), shape=list(first.shape),
                    maximum_absolute_difference=float(delta.max(initial=0)),
                    maximum_tolerance_fraction=error_ratio, bitwise_equal=bool(np.array_equal(first, second)))
                compared.append(record)
                if not passed:
                    failures.append(dict(job=baseline, comparison=record))
        ratio = receipts[1]["child_peak_rss_kib_linux"] / receipts[0]["child_peak_rss_kib_linux"]
        pair = dict(task=baseline["task"], model=baseline["model"], seed=baseline["seed"],
            passed=all(row["passed"] for row in compared), comparisons=compared,
            original_peak_rss_kib=receipts[0]["child_peak_rss_kib_linux"],
            vector_peak_rss_kib=receipts[1]["child_peak_rss_kib_linux"], peak_rss_ratio=ratio,
            original_total_cpu_seconds=receipts[0]["child_total_cpu_seconds"],
            vector_total_cpu_seconds=receipts[1]["child_total_cpu_seconds"],
            original_core_update_cpu_seconds=results[0]["core_update_cpu_seconds"],
            vector_core_update_cpu_seconds=results[1]["core_update_cpu_seconds"],
            unchanged_parameter_counts=results[0]["counts"] == results[1]["counts"],
            all_initial_tensors_bitwise=all(row["bitwise_equal"] for row in compared if row["tensor"].startswith("initial::")),
            significant_memory_goal_applies=baseline["model"] in
                ("risk_margin_j_risk", "risk_fixed_full", "risk_direct_full", "risk_conditional_full"))
        if not pair["unchanged_parameter_counts"]:
            failures.append(dict(job=baseline, error="Parameter count changed"))
        pairs.append(pair)
    memory_goal = all(row["peak_rss_ratio"] <= .8 for row in pairs if row["significant_memory_goal_applies"])
    result = dict(schema="hcsn-risk-memory-train-equivalence-results.v1", passed=not failures,
        significant_memory_goal_passed=memory_goal, pairs=pairs, failures=failures,
        source_files_sha256=registration["source_files_sha256"],
        registration_sha256=sha(registration_path), complete_sha256=sha(output / "COMPLETE.json"),
        heldout_loaded=False, energy_measured=False,
        limitation="one seed, three updates, B32 train data; does not prove identical long training trajectories")
    write(output / "RESULTS.json", result)
    print(json.dumps(dict(passed=result["passed"], significant_memory_goal_passed=memory_goal,
        pairs=len(pairs), failures=len(failures),
        risk_peak_rss_ratios=[row["peak_rss_ratio"] for row in pairs if row["significant_memory_goal_applies"]])), flush=True)
    if failures:
        raise RuntimeError("Train equivalence failed")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("register", "run", "worker", "analyze"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--registration", type=Path)
    parser.add_argument("--task")
    parser.add_argument("--model")
    parser.add_argument("--seed", type=int)
    parser.add_argument("--profile", choices=("matrix_oracle", "backward_vector"))
    args = parser.parse_args()
    output = args.output.resolve()
    if args.action == "worker":
        worker(args.registration.resolve(), output, dict(task=args.task, model=args.model,
               seed=args.seed, profile=args.profile))
    else:
        dict(register=register, run=run, analyze=analyze)[args.action](output)
