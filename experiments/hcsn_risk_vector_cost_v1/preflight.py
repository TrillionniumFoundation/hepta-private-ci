"""Six train-only matrix/vector pairs across the registered cost scales."""

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from .study import (ROOT, PACKAGE, MATRIX_PROTOCOL, MODEL, factory, source_map, base,
                    guarded_resources, measurement, oom_counters)


def worker(task, width, depth, profile, output):
    import numpy as np
    import torch
    from torch.nn import functional as F
    from experiments.hcsn_free_boundary_v1 import training
    from experiments.hcsn_risk_ablation_v1.model import build_model as matrix_factory

    torch.set_num_threads(1)
    output.mkdir(parents=True, exist_ok=False)
    protocol, sources = base.verify(MATRIX_PROTOCOL), source_map()
    access = []
    train = training.load_split(ROOT / protocol["data"][task]["path"], "train", access)
    make = matrix_factory if profile == "matrix" else factory
    model = make(MODEL, train["x"].shape[-1], protocol["data"][task]["output_dim"], width, depth, 9301)
    values = {"initial__" + name: value.detach().numpy().copy() for name, value in model.state_dict().items()}
    optimizer = torch.optim.Adam(model.parameters(), lr=.001)
    generator = torch.Generator().manual_seed(9301 + 200003)
    elapsed, losses, diagnostics = [], [], []
    for step in range(1, 3):
        indices = torch.randint(len(train["x"]), (4,), generator=generator)
        values[f"step{step}__indices"] = indices.numpy().copy()
        optimizer.zero_grad(set_to_none=True)
        begin = time.process_time()
        logits, aux = model(train["x"][indices], train["dt"][indices], return_sequence=True)
        loss = F.cross_entropy(logits.flatten(0, 1), train["y"][indices].flatten(), ignore_index=-100)
        assert bool(torch.isfinite(loss))
        loss.backward()
        for name, parameter in model.named_parameters():
            assert parameter.grad is not None and bool(torch.isfinite(parameter.grad).all())
            values[f"step{step}__grad_before__{name}"] = parameter.grad.detach().numpy().copy()
        torch.nn.utils.clip_grad_norm_(model.parameters(), 2.)
        for name, parameter in model.named_parameters():
            values[f"step{step}__grad_after__{name}"] = parameter.grad.detach().numpy().copy()
        optimizer.step()
        elapsed.append(time.process_time() - begin)
        values[f"step{step}__logits"] = logits.detach().numpy().copy()
        values[f"step{step}__loss"] = loss.detach().numpy().copy()
        for name, parameter in model.named_parameters():
            for key, value in optimizer.state[parameter].items():
                if torch.is_tensor(value):
                    values[f"step{step}__adam__{name}__{key}"] = value.detach().numpy().copy()
        for name, value in model.state_dict().items():
            values[f"step{step}__state__{name}"] = value.detach().numpy().copy()
        mass = float((aux["flow_mass"].detach() - 1).abs().max())
        projection = float(aux["projection_actual_l1_correction"].detach().max())
        assert mass <= 1e-6 and projection <= 260 * np.finfo(np.float32).eps
        diagnostics.append(dict(max_mass_error=mass, max_projection_l1=projection))
        losses.append(float(loss.detach()))
    assert all(np.isfinite(value).all() for value in values.values())
    assert all(row.get("split") == "train" for row in access)
    physical_changes = {name: bool(np.any(value.detach().numpy() != values["initial__" + name]))
        for name, value in model.named_parameters() if any(part in name for part in
            ("mu_bias", "raw_sigma", "raw_rho", "raw_K", "raw_reset", "raw_refractory"))}
    assert all(physical_changes.values())
    assert sources == source_map()
    np.savez_compressed(output / "arrays.npz", **values)
    result = dict(task=task, width=width, depth=depth, profile=profile, seed=9301,
        batch=4, updates=2, train_only=True, access_log=access, counts=model.counts(),
        config=model.config, update_cpu_seconds=elapsed, train_losses=losses,
        diagnostics=diagnostics, arrays=len(values), arrays_sha256=base.digest(output / "arrays.npz"),
        source_files_sha256=sources, physical_tensor_changes=physical_changes)
    base.write(output / "RESULTS.json", result)


def register(output):
    sources = source_map()
    output.mkdir(parents=True, exist_ok=False)
    limits = dict(logits=(2e-6, 2e-6), loss=(1e-6, 1e-6), gradient=(5e-8, 2e-5),
                  state=(2e-7, 2e-6), optimizer=(5e-9, 2e-5))
    jobs = [dict(task=task, width=width, depth=depth, profile=profile)
            for task in base.TASKS for width, depth in base.SCALES for profile in ("matrix", "vector")]
    resources = dict(workers=1, per_worker_peak_budget_bytes=int(1.3 * 1024**3),
        required_shared_reserve_bytes=2 * 1024**3,
        prerequisite="risk001 terminal after both workers drain; memory002 desired<=2 and active<=2 under root-controlled temporary window; preserve its future capacity",
        shape="one isolated B4 model, two updates, no simultaneous original/vector graphs",
        monitored_oom_event_counters=["oom", "oom_kill"],
        failure="stop and retain receipts on worker failure, new OOM or peak-budget exceedance; no automatic rerun")
    base.write(output / "REGISTRATION.json", dict(jobs=jobs, seed=9301, batch=4, updates=2,
        train_only=True, limits=limits, source_files_sha256=sources, resources=resources,
        purpose="Numerical scale-equivalence preflight, not a large-batch memory certification or predictive experiment"))
    print(json.dumps(dict(registered=True, jobs=12, sources=len(sources),
        registration_sha256=base.digest(output / "REGISTRATION.json"))), flush=True)


def run(output):
    import numpy as np

    registration = base.read(output / "REGISTRATION.json")
    sources = source_map()
    if registration["source_files_sha256"] != sources:
        raise RuntimeError("Preflight registered source closure changed")
    if any(path.name != "REGISTRATION.json" for path in output.iterdir()):
        raise FileExistsError("Only a fresh, registered but unexecuted preflight may run")
    limits, jobs, resources = (registration[key] for key in ("limits", "jobs", "resources"))
    records, pairs, started_cpu = [], [], time.process_time()
    initial_oom, stopped, reason, heartbeat = oom_counters(measurement()), False, None, -1e30
    risk = ROOT / "experiments/hcsn_risk_ablation_v1/results/risk001"
    for job in jobs:
        while True:
            guard = guarded_resources(resources)
            dependency = (risk / "COMPLETE.json").exists() or (risk / "ABORTED.json").exists()
            if oom_counters(guard["resources"]) != initial_oom:
                stopped, reason = True, "new shared cgroup OOM during preflight"
                break
            if time.perf_counter() - heartbeat >= 30:
                with (output / "RESOURCE_JOURNAL.jsonl").open("a") as log:
                    log.write(json.dumps(dict(utc=base.utc(), risk001_drained=dependency, guard=guard)) + "\n")
                heartbeat = time.perf_counter()
            priority = guard["priority_queue"]
            temporary_window = priority.get("desired_workers", 0) <= 2 and len(priority.get("active_jobs", [])) <= 2
            if dependency and temporary_window and guard["allowed"]:
                break
            time.sleep(2)
        if stopped:
            break
        name = f"{job['task']}__w{job['width']}d{job['depth']}__{job['profile']}"
        command = [sys.executable, "-m", "experiments.hcsn_risk_vector_cost_v1.preflight", "worker",
            "--task", job["task"], "--width", str(job["width"]), "--depth", str(job["depth"]),
            "--profile", job["profile"], "--output", str((output / name).resolve())]
        begin = time.perf_counter()
        with (output / (name + ".log")).open("xb") as log:
            process = subprocess.Popen(command, cwd=ROOT, env=dict(os.environ, OMP_NUM_THREADS="1",
                MKL_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1"), stdout=log, stderr=subprocess.STDOUT)
            _, status, usage = os.wait4(process.pid, 0)
            process.returncode = os.waitstatus_to_exitcode(status)
        records.append(dict(job=job, returncode=process.returncode, command=command,
            whole_worker_cpu_seconds=usage.ru_utime + usage.ru_stime, peak_rss_bytes=usage.ru_maxrss * 1024,
            wall_seconds=time.perf_counter()-begin, directory=name, stdout_sha256=base.digest(output / (name + ".log"))))
        base.write(output / "PROGRESS.json", dict(records=records, expected=12))
        if (process.returncode or usage.ru_maxrss * 1024 > resources["per_worker_peak_budget_bytes"]
                or oom_counters(measurement()) != initial_oom):
            stopped, reason = True, "worker failure, preflight peak-budget exceedance or new shared OOM"
            break
    passed = not stopped and len(records) == 12 and all(row["returncode"] == 0 for row in records)
    if passed:
        for task in base.TASKS:
            for width, depth in base.SCALES:
                prefix = f"{task}__w{width}d{depth}__"
                old, new = output / (prefix + "matrix"), output / (prefix + "vector")
                a, b = base.read(old / "RESULTS.json"), base.read(new / "RESULTS.json")
                assert a["counts"] == b["counts"]
                assert {k:v for k,v in b["config"].items() if k != "risk_operator_profile"} == a["config"]
                with np.load(old / "arrays.npz", allow_pickle=False) as x, np.load(new / "arrays.npz", allow_pickle=False) as y:
                    assert set(x.files) == set(y.files)
                    comparisons = []
                    for name in x.files:
                        exact = np.array_equal(x[name], y[name])
                        if "initial__" in name or "indices" in name:
                            close, category = exact, "exact_initialization_or_batch"
                        else:
                            category = ("gradient" if "grad_" in name else "optimizer" if "__adam__" in name
                                else "logits" if "__logits" in name else "loss" if "__loss" in name else "state")
                            atol, rtol = limits[category]
                            close = bool(np.allclose(x[name], y[name], atol=atol, rtol=rtol))
                        comparisons.append(dict(name=name, category=category, bitwise_equal=bool(exact),
                            accepted=close, maximum_absolute_difference=float(np.max(np.abs(x[name].astype(float)-y[name].astype(float))))))
                    passed = passed and all(row["accepted"] for row in comparisons)
                pairs.append(dict(task=task, width=width, depth=depth, counts=a["counts"],
                    all_arrays_bitwise_equal=all(row["bitwise_equal"] for row in comparisons), comparisons=comparisons,
                    matrix_result_sha256=base.digest(old / "RESULTS.json"), vector_result_sha256=base.digest(new / "RESULTS.json")))
    assert sources == source_map()
    result = dict(passed=passed, train_only=True, source_files_sha256=sources, limits=limits,
        records=records, pairs=pairs, complete_child_cpu_seconds=sum(r["whole_worker_cpu_seconds"] for r in records),
        coordinator_cpu_seconds=time.process_time()-started_cpu,
        large_batch_memory_certified=False, formal_worker_budget_bytes=int(2.5 * 1024**3),
        resources=resources, stop_reason=reason)
    base.write(output / "RESULTS.json", result)
    print(json.dumps(dict(passed=passed, completed=len(records), pairs=len(pairs),
        all_bitwise=all(row["all_arrays_bitwise_equal"] for row in pairs), complete_child_cpu_seconds=result["complete_child_cpu_seconds"])))
    if not passed:
        raise SystemExit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("register", "run", "worker"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--task")
    parser.add_argument("--width", type=int)
    parser.add_argument("--depth", type=int)
    parser.add_argument("--profile", choices=("matrix", "vector"))
    args = parser.parse_args()
    if args.action == "register":
        register(args.output.resolve())
    elif args.action == "run":
        run(args.output.resolve())
    else:
        worker(args.task, args.width, args.depth, args.profile, args.output.resolve())
