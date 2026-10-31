"""Sealed development selection, paired formal training, and complete costs."""

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import datetime
import hashlib
import json
import os
from pathlib import Path
import random
import resource
import statistics
import subprocess
import sys
import time
import traceback

import numpy as np

from . import data


ROOT = Path(__file__).resolve().parents[3]
CONTENT = Path(__file__).resolve().parent
MODULE = "experiments.hcsn_blocker_closure_v1.content.study"


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")
    temporary.replace(path)


def read(path):
    return json.loads(Path(path).read_bytes())


def utc():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def source_map():
    dependencies = (
        "experiments/hcsn_conservative_acceleration_v1/kernel.py",
        "experiments/hcsn_conservative_acceleration_v1/model.py",
        "experiments/hcsn_distributional_v2/distribution_kernel.py",
        "experiments/hcsn_distributional_v2/model.py",
        "experiments/hcsn_distributional_v2/stable_probability.py",
        "experiments/hcsn_free_boundary_v1/model.py",
        "experiments/hcsn_free_boundary_v1/oracle_torch.py",
        "experiments/continuous_spiking_network/baseline.py",
    )
    paths = sorted(list(CONTENT.glob("*.py")) + [ROOT / name for name in dependencies])
    paths.append(CONTENT / "DESIGN.json")
    return {str(path.relative_to(ROOT)): data.sha256(path) for path in paths}


def verify(output):
    output = Path(output)
    protocol = read(output / "PROTOCOL.json")
    if protocol["status"] != "registered":
        raise RuntimeError("Registered protocol required")
    for path, sha in protocol["source_sha256"].items():
        if data.sha256(ROOT / path) != sha:
            raise RuntimeError("Source identity changed: " + path)
    if protocol["design"] != read(CONTENT / "DESIGN.json"):
        raise RuntimeError("Protocol settings differ from sealed design")
    if data.sha256(ROOT / protocol["preflight"]["file"]) != protocol["preflight"]["sha256"]:
        raise RuntimeError("Preflight evidence changed")
    seal = protocol.get("public_execution_commit")
    if seal is not None and os.environ.get("GITHUB_SHA") != seal:
        raise RuntimeError("Execution commit differs from registered public seal")
    for splits in protocol["data"].values():
        for row in splits.values():
            if data.sha256(output / "data" / row["file"]) != row["sha256"]:
                raise RuntimeError("Data identity changed: " + row["file"])
    return protocol


def register(output, preflight):
    output = Path(output).resolve()
    output.relative_to(CONTENT.parent)
    proof = read(preflight)
    if proof.get("passed") is not True:
        raise RuntimeError("Passing content preflight required before registration")
    if proof.get("source_sha256") != source_map():
        raise RuntimeError("Preflight is stale: source and design must match exactly")
    output.mkdir(parents=True, exist_ok=False)
    design = read(CONTENT / "DESIGN.json")
    manifest = data.prepare(design, output / "data")
    protocol = dict(schema="hcsn-blocker-content-protocol.v1", status="registered",
        created_utc=utc(), design=design, source_sha256=source_map(), data=manifest,
        public_execution_commit=os.environ.get("GITHUB_SHA"),
        preflight=dict(file=str(Path(preflight).resolve().relative_to(ROOT)),
                       sha256=data.sha256(preflight)))
    write(output / "PROTOCOL.json", protocol)
    jobs = []
    for task in design["tasks"]:
        for arm in design["arms"]:
            for lr in design["learning_rates"]:
                jobs.append(dict(stage="development", task=task, arm=arm,
                    seed=design["development_seed"], learning_rate=lr,
                    updates=design["development_updates"], id=f"{task}__{arm}__lr{lr:g}"))
    write(output / "jobs_development.json", jobs)
    return dict(protocol_sha256=data.sha256(output / "PROTOCOL.json"), jobs=len(jobs))


def metrics(logits, labels):
    logits, labels = np.asarray(logits, np.float64), np.asarray(labels, np.int64)
    if logits.ndim != 2 or labels.shape != (len(logits),) or not len(logits):
        raise ValueError("Supervised logits and labels required")
    if not np.isfinite(logits).all():
        raise FloatingPointError("Nonfinite logits")
    shifted = logits - logits.max(1, keepdims=True)
    probabilities = np.exp(shifted)
    normalizer = probabilities.sum(1)
    probabilities /= normalizer[:, None]
    ce = np.log(normalizer) - shifted[np.arange(len(labels)), labels]
    confidence = probabilities.max(1)
    correct = probabilities.argmax(1) == labels
    ece = 0.0
    for index in range(10):
        selected = (confidence >= index / 10) & (confidence < (index + 1) / 10)
        if index == 9:
            selected |= confidence == 1
        if selected.any():
            ece += selected.mean() * abs(float(correct[selected].mean() - confidence[selected].mean()))
    target = np.eye(logits.shape[1])[labels]
    return dict(cross_entropy=float(ce.mean()), accuracy=float(correct.mean()),
        correct=int(correct.sum()), positions=len(labels),
        brier=float(np.square(probabilities - target).sum(1).mean()), ece=float(ece))


def state_hash(state):
    digest = hashlib.sha256()
    for name, tensor in sorted(state.items()):
        array = tensor.detach().cpu().numpy()
        digest.update(json.dumps([name, str(array.dtype), list(array.shape)]).encode())
        digest.update(array.tobytes())
    return digest.hexdigest()


def save_state(model, path):
    np.savez_compressed(path, **{name: value.detach().cpu().numpy()
                                for name, value in model.state_dict().items()})


def load_split(protocol, output, task, split, job_dir):
    import torch

    if split in ("test", "ood") and not (job_dir / "selection.json").exists():
        raise RuntimeError("Heldout access before durable checkpoint selection")
    row = protocol["data"][task][split]
    path = output / "data" / row["file"]
    if data.sha256(path) != row["sha256"]:
        raise RuntimeError("Dataset changed")
    with (job_dir / "access.jsonl").open("a") as stream:
        stream.write(json.dumps(dict(split=split, path=row["file"], sha256=row["sha256"], utc=utc())) + "\n")
    with np.load(path, allow_pickle=False) as archive:
        return {key: torch.from_numpy(np.array(archive[key], copy=True)) for key in archive.files}


def evaluate(model, arrays, destination, batch_size):
    import torch

    logits, labels = [], []
    model.eval()
    with torch.no_grad():
        for start in range(0, len(arrays["x"]), batch_size):
            stop = start + batch_size
            output = model(arrays["x"][start:stop], arrays["dt"][start:stop],
                           return_sequence=True, return_aux=False)
            selected = arrays["y"][start:stop] >= 0
            logits.append(output[selected].cpu().numpy())
            labels.append(arrays["y"][start:stop][selected].cpu().numpy())
    logits, labels = np.concatenate(logits), np.concatenate(labels)
    np.savez_compressed(destination, logits=logits, labels=labels)
    return dict(**metrics(logits, labels), file=destination.name, sha256=data.sha256(destination))


def group_measurements(model, initial, gradient=False):
    import torch

    result = {}
    for group, entries in model.parameter_groups().items():
        square, changed, maximum = 0.0, 0, 0.0
        for name, parameter in entries:
            delta = parameter.grad if gradient else parameter.detach() - initial[name]
            if delta is None:
                continue
            if not bool(torch.isfinite(delta).all()):
                raise FloatingPointError("Nonfinite " + group)
            square += float(delta.detach().double().square().sum())
            changed += int(torch.count_nonzero(delta.detach()))
            maximum = max(maximum, float(delta.detach().abs().max()))
        result[group] = dict(l2=square ** 0.5, nonzero=changed, maximum_absolute=maximum)
    return result


def physical_audit(aux):
    import torch

    if "probability" not in aux:
        return {}
    p = aux["probability"].detach()
    result = dict(minimum=float(p.min()), maximum_mass_defect=float((p.double().sum(-1) - 1).abs().max()),
                  refractory_mean=float(aux["refractory_mass"].detach().mean()),
                  boundary_mean=float(aux["boundary"].detach().mean()),
                  expected_events=float(aux["activity"].detach().sum()))
    if not bool(torch.isfinite(p).all()) or result["minimum"] < 0 or result["maximum_mass_defect"] > 1e-5:
        raise FloatingPointError("Probability contract failed")
    if "next_first_event_F" in aux:
        f, h = aux["next_first_event_F"].detach(), aux["next_first_event_H"].detach()
        if not bool(torch.isfinite(f).all()) or not bool(torch.isfinite(h).all()):
            raise FloatingPointError("Nonfinite next-first-event forecast")
        result.update(first_event_minimum=float(f.min()), first_event_maximum=float(f.max()),
                      discounted_minus_probability_maximum=float((h - f).max()))
        if float(h.min()) < -1e-6 or float(f.max()) > 1 + 1e-6 or float((h - f).max()) > 1e-6:
            raise FloatingPointError("First-event probability/value contract failed")
    return result


def worker(output, job):
    import torch
    from torch.nn import functional as F
    from .models import build

    started, wall_start = utc(), time.perf_counter()
    output = Path(output).resolve()
    protocol = verify(output)
    design = protocol["design"]
    job_dir = output / job["stage"] / job["id"]
    job_dir.mkdir(parents=True, exist_ok=False)
    write(job_dir / "job.json", job)
    torch.set_num_threads(1)
    torch.manual_seed(job["seed"])
    development = job["stage"] == "development"
    train = load_split(protocol, output, job["task"], "dev_train" if development else "train", job_dir)
    validation = load_split(protocol, output, job["task"], "dev_val" if development else "val", job_dir)
    model = build(job["arm"], width=design["width"], depth=design["depth"], seed=job["seed"])
    initial = {name: parameter.detach().clone() for name, parameter in model.named_parameters()}
    initial_hash = state_hash(model.state_dict())
    common_hash = state_hash({name: value for name, value in model.state_dict().items()
                             if name.startswith(("frontend.", "readout."))})
    frozen = getattr(model, "frozen_group", None)
    if frozen:
        np.savez_compressed(job_dir / "frozen_initial.npz", **{
            name: initial[name].numpy() for name, _ in model.parameter_groups()[frozen]})
    optimizer = torch.optim.Adam([p for p in model.parameters() if p.requires_grad],
                                 lr=job["learning_rate"], weight_decay=0)
    generator = torch.Generator().manual_seed(job["seed"] + 270003)
    batch_digest = hashlib.sha256()
    training_cpu, training_wall, step, best = 0.0, 0.0, 0, None
    trajectory, validations = [], []
    midpoint_seen = False
    try:
        while True:
            model.train()
            cpu_start, tick = time.process_time(), time.perf_counter()
            indices = torch.randint(len(train["x"]), (design["batch_size"],), generator=generator)
            batch_digest.update(indices.numpy().tobytes())
            optimizer.zero_grad(set_to_none=True)
            logits, aux = model(train["x"][indices], train["dt"][indices], return_sequence=True)
            selected = train["y"][indices] >= 0
            loss = F.cross_entropy(logits[selected], train["y"][indices][selected])
            if not bool(torch.isfinite(loss)):
                raise FloatingPointError("Nonfinite training loss")
            loss.backward()
            gradients = group_measurements(model, initial, gradient=True)
            torch.nn.utils.clip_grad_norm_(model.parameters(), design["optimizer"]["gradient_clip_norm"])
            optimizer.step()
            audit = physical_audit(aux)
            step += 1
            training_cpu += time.process_time() - cpu_start
            training_wall += time.perf_counter() - tick
            row = dict(step=step, loss=float(loss.detach()), training_cpu_seconds=training_cpu,
                       gradient_groups=gradients, physical=audit)
            trajectory.append(row)
            cpu_mode = job["stage"] == "equal_cpu"
            finished = training_cpu >= design["equal_cpu_seconds"] if cpu_mode else step >= job["updates"]
            midpoint = (training_cpu >= design["equal_cpu_seconds"] / 2 if cpu_mode
                        else step >= job["updates"] // 2)
            if (midpoint and not midpoint_seen) or finished:
                midpoint_seen = True
                result = evaluate(model, validation, job_dir / f"validation_{step:06d}.npz", design["batch_size"])
                result.update(step=step, training_cpu_seconds=training_cpu)
                validations.append(result)
                if best is None or (result["cross_entropy"], step) < (best["cross_entropy"], best["step"]):
                    save_state(model, job_dir / "selected_state.npz")
                    best = dict(result, state_sha256=data.sha256(job_dir / "selected_state.npz"),
                                tensor_hash=state_hash(model.state_dict()))
            if step % 16 == 0 or finished:
                write(job_dir / "trajectory.json", trajectory)
            if finished:
                break
        updates = group_measurements(model, initial)
        if frozen and updates[frozen]["nonzero"] != 0:
            raise RuntimeError("Frozen group changed")
        final_hash = state_hash(model.state_dict())
        write(job_dir / "selection.json", dict(best, locked_utc=utc(),
              rule="minimum validation FP64 CE; earlier update on exact tie"))
        with np.load(job_dir / "selected_state.npz", allow_pickle=False) as saved:
            model.load_state_dict({key: torch.from_numpy(np.array(saved[key], copy=True)) for key in saved.files})
        if state_hash(model.state_dict()) != best["tensor_hash"]:
            raise RuntimeError("Selected state changed at reload")
        results = {}
        if not development:
            for split in ("test", "ood"):
                arrays = load_split(protocol, output, job["task"], split, job_dir)
                results[split] = evaluate(model, arrays, job_dir / (split + ".npz"), design["batch_size"])
        model.eval()
        sample = {key: value[:16] for key, value in validation.items()}
        inference = []
        with torch.no_grad():
            model(sample["x"], sample["dt"], return_sequence=True, return_aux=False)
            for _ in range(5):
                timer = time.perf_counter()
                model(sample["x"], sample["dt"], return_sequence=True, return_aux=False)
                inference.append(time.perf_counter() - timer)
        report = dict(schema="hcsn-blocker-content-worker.v1", status="complete", job=job,
            public_execution_commit=os.environ.get("GITHUB_SHA"),
            protocol_sha256=data.sha256(output / "PROTOCOL.json"), initial_tensor_hash=initial_hash,
            common_initial_hash=common_hash, final_tensor_hash=final_hash, selected=best,
            selected_update_groups=group_measurements(model, initial), final_update_groups=updates,
            batch_stream_sha256=batch_digest.hexdigest(), validations=validations, evaluation=results,
            config=model.config, counts=model.counts(), updates=step,
            training_cpu_seconds=training_cpu, training_wall_seconds=training_wall,
            training_cpu_budget_overrun_seconds=(training_cpu - design["equal_cpu_seconds"]
                                                  if job["stage"] == "equal_cpu" else None),
            complete_process_cpu_seconds=time.process_time(), worker_wall_seconds=time.perf_counter() - wall_start,
            self_clock_scope="CPU since Python process start, sampled before final RESULT serialization; wall since worker function after torch import. RUN wait4/launch clocks include import, serialization and exit and define complete-worker comparisons.",
            peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * (1 if sys.platform == "darwin" else 1024),
            inference=dict(batch=16, length=design["length"], warmup=1, repetitions=5,
                wall_seconds=inference, median_wall_seconds=statistics.median(inference),
                scope="in-memory selected model; no load, media I/O or service startup"),
            started_utc=started, completed_utc=utc())
        write(job_dir / "RESULT.json", report)
    except Exception as error:
        write(job_dir / "trajectory.json", trajectory)
        write(job_dir / "FAILURE.json", dict(status="failed", job=job, error=repr(error),
            traceback=traceback.format_exc(), updates=step, training_cpu_seconds=training_cpu,
            complete_process_cpu_seconds=time.process_time(), wall_seconds=time.perf_counter() - wall_start))
        raise
    return dict(id=job["id"], status="complete", updates=step)


def lock(output):
    output = Path(output).resolve()
    protocol = verify(output)
    if (output / "SELECTION_LOCK.json").exists():
        raise FileExistsError("Development choices already locked")
    design, candidates = protocol["design"], {}
    for job in read(output / "jobs_development.json"):
        path = output / "development" / job["id"] / "RESULT.json"
        result = read(path)
        if result["status"] != "complete" or result["job"] != job:
            raise RuntimeError("Invalid development worker: " + job["id"])
        candidates.setdefault((job["task"], job["arm"]), []).append((result, path))
    choices, equal_arms = {}, {}
    for task in design["tasks"]:
        choices[task] = {}
        for arm in design["arms"]:
            result, path = min(candidates[task, arm], key=lambda pair: (
                pair[0]["selected"]["cross_entropy"], pair[0]["selected"]["step"], pair[0]["job"]["learning_rate"]))
            choices[task][arm] = dict(learning_rate=result["job"]["learning_rate"],
                development_cross_entropy=result["selected"]["cross_entropy"],
                result_file=str(path.relative_to(output)), result_sha256=data.sha256(path))
        physical = [arm for arm in design["arms"] if arm.startswith(("value_", "fixed_", "learned_"))]
        best = min(physical, key=lambda arm: (choices[task][arm]["development_cross_entropy"], arm))
        equal_arms[task] = [best, "two_gates", "transformer", "lif_snn"]
    write(output / "SELECTION_LOCK.json", dict(locked_utc=utc(), choices=choices,
        equal_cpu_arms=equal_arms, protocol_sha256=data.sha256(output / "PROTOCOL.json")))
    for stage in ("fixed", "equal_cpu"):
        jobs = []
        for task in design["tasks"]:
            for arm in design["arms"] if stage == "fixed" else equal_arms[task]:
                for seed in design["formal_seeds"]:
                    jobs.append(dict(stage=stage, task=task, arm=arm, seed=seed,
                        learning_rate=choices[task][arm]["learning_rate"], updates=design["formal_updates"],
                        id=f"{task}__{arm}__seed{seed}"))
        write(output / ("jobs_" + stage + ".json"), jobs)
    return dict(fixed_jobs=len(read(output / "jobs_fixed.json")),
                equal_cpu_jobs=len(read(output / "jobs_equal_cpu.json")), equal_cpu_arms=equal_arms)


def run(output, stage, workers):
    output = Path(output).resolve()
    verify(output)
    jobs = read(output / ("jobs_" + stage + ".json"))
    ledger = output / ("RUN_" + stage + ".json")
    if ledger.exists():
        raise FileExistsError("Run ledger exists; no silent rerun")
    if stage != "development" and not (output / "SELECTION_LOCK.json").exists():
        raise RuntimeError("Development selection must precede formal runs")
    random.Random(829771 + ("development", "fixed", "equal_cpu").index(stage)).shuffle(jobs)
    logs = output / "logs" / stage
    logs.mkdir(parents=True, exist_ok=False)
    start_cpu, start_wall = time.process_time(), time.perf_counter()
    rows = []

    def execute(job):
        spec = logs / (job["id"] + ".json")
        write(spec, job)
        tick = time.perf_counter()
        with (logs / (job["id"] + ".log")).open("w") as stream:
            process = subprocess.Popen([sys.executable, "-m", MODULE, "worker", "--output", str(output),
                "--job", str(spec)], cwd=ROOT, stdin=subprocess.DEVNULL, stdout=stream, stderr=subprocess.STDOUT)
            _, status, usage = os.wait4(process.pid, 0)
            process.returncode = os.waitstatus_to_exitcode(status)
        return dict(id=job["id"], job=job, exit_code=process.returncode,
            child_cpu_seconds=usage.ru_utime + usage.ru_stime, wall_seconds=time.perf_counter() - tick,
            maxrss_bytes=usage.ru_maxrss * (1 if sys.platform == "darwin" else 1024))

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(execute, job): job for job in jobs}
        for future in as_completed(futures):
            rows.append(future.result())
            write(ledger, dict(stage=stage, complete=False, jobs=rows,
                coordinator_cpu_seconds=time.process_time(),
                coordinator_queue_cpu_seconds=time.process_time() - start_cpu,
                wall_seconds=time.perf_counter() - start_wall))
            print(json.dumps(dict(done=len(rows), total=len(jobs), **rows[-1])), flush=True)
    report = dict(stage=stage, complete=True, jobs=rows,
        failed=sum(row["exit_code"] != 0 for row in rows),
        child_cpu_seconds=sum(row["child_cpu_seconds"] for row in rows),
        coordinator_cpu_seconds=time.process_time(), coordinator_queue_cpu_seconds=time.process_time() - start_cpu,
        wall_seconds=time.perf_counter() - start_wall)
    write(ledger, report)
    return {key: value for key, value in report.items() if key != "jobs"}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("register", "worker", "run", "lock", "analyze"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--preflight", type=Path)
    parser.add_argument("--job", type=Path)
    parser.add_argument("--stage", choices=("development", "fixed", "equal_cpu"))
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    if args.command == "register":
        result = register(args.output, args.preflight)
    elif args.command == "worker":
        result = worker(args.output, read(args.job))
    elif args.command == "lock":
        result = lock(args.output)
    elif args.command == "run":
        result = run(args.output, args.stage, args.workers)
    else:
        from .analysis import analyze
        result = analyze(args.output)
    print(json.dumps(result, sort_keys=True), flush=True)
    if args.command == "analyze" and not result["complete"]:
        raise SystemExit(1)
    if args.command == "run" and result["failed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
