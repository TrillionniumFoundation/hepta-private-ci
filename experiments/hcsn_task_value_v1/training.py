"""Isolated, reproducible training and validation-selected evaluation workers."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import resource
import time

import numpy as np
import torch
from torch.nn import functional as F

from .experiment import build, data, tensor_batch


PACKAGE = Path(__file__).resolve().parent


def write(path, value):
    path = Path(path)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")
    temp.replace(path)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def cpu():
    r = resource.getrusage(resource.RUSAGE_SELF)
    return r.ru_utime + r.ru_stime


def parameter_snapshot(model):
    return {name: p.detach().clone() for name, p in model.named_parameters()}


def group_delta(model, initial):
    return {group: dict(l2=float(sum((p.detach() - initial[name]).square().sum()
                                      for name, p in entries).sqrt()),
                        changed=sum(not torch.equal(p.detach(), initial[name]) for name, p in entries),
                        tensors=len(entries), trainable=sum(p.numel() for _, p in entries if p.requires_grad))
            for group, entries in model.parameter_groups().items()}


def evaluate(model, values, batch_size=16):
    model.eval()
    logits, labels, episodes, positions = [], [], [], []
    with torch.no_grad():
        for start in range(0, len(values["x"]), batch_size):
            item = tensor_batch(values, slice(start, start + batch_size))
            out = model(item["x"], item["dt"], item["observed"])
            mask = item["y"] != -100
            sample, position = torch.where(mask)
            logits.append(out[mask].numpy())
            labels.append(item["y"][mask].numpy())
            episodes.append(sample.numpy() + start)
            positions.append(position.numpy())
    logits, labels, episodes, positions = map(np.concatenate, (logits, labels, episodes, positions))
    loss = float(F.cross_entropy(torch.from_numpy(logits), torch.from_numpy(labels)))
    correct = logits.argmax(-1) == labels
    prediction = dict(logits=logits, labels=labels, episodes=episodes, token_index=positions, correct=correct)
    if "clip_ids" in values:
        prediction["clip_ids"] = values["clip_ids"][episodes]
        prediction["actors"] = np.array([str(v).split("_")[0] for v in prediction["clip_ids"]])
    return dict(accuracy=float(correct.mean()), cross_entropy=loss,
                supervised_tokens=len(labels), episodes=len(values["x"])), prediction


def _tensor_bytes(value):
    if torch.is_tensor(value):
        return value.numel() * value.element_size()
    if isinstance(value, dict):
        return sum(_tensor_bytes(v) for v in value.values())
    if isinstance(value, (tuple, list)):
        return sum(_tensor_bytes(v) for v in value)
    return 0


def _storage_bytes(value, seen=None):
    seen = set() if seen is None else seen
    if torch.is_tensor(value):
        storage = value.untyped_storage()
        identity = (str(value.device), storage.data_ptr(), storage.nbytes())
        if identity in seen:
            return 0
        seen.add(identity)
        return storage.nbytes()
    if isinstance(value, dict):
        return sum(_storage_bytes(v, seen) for v in value.values())
    if isinstance(value, (list, tuple)):
        return sum(_storage_bytes(v, seen) for v in value)
    return 0


def inference_cost(model, values):
    """Full-sequence batch=1 CPU timing; no claim of optimized KV-cache service."""
    item = tensor_batch(values, slice(0, 1))
    lengths = (32, 64, 128) if item["x"].shape[1] == 32 else (item["x"].shape[1],)
    rows = []
    model.eval()
    for length in lengths:
        repeat = (length + item["x"].shape[1] - 1) // item["x"].shape[1]
        x = item["x"].repeat(1, repeat, 1)[:, :length]
        dt = item["dt"].repeat(1, repeat)[:, :length]
        observed = item["observed"].repeat(1, repeat)[:, :length]
        with torch.no_grad():
            model(x, dt, observed)
            times, cpus = [], []
            for _ in range(5):
                start, start_cpu = time.perf_counter(), cpu()
                _, aux = model(x, dt, observed, return_aux=True)
                times.append(time.perf_counter() - start)
                cpus.append(cpu() - start_cpu)
        rows.append(dict(length=length, batch=1, wall_seconds=times, cpu_seconds=cpus,
                         median_wall_seconds=float(np.median(times)),
                         median_cpu_seconds=float(np.median(cpus)),
                         persistent_numeric_state_bytes=_tensor_bytes(aux.get("state", {})) or None,
                         persistent_storage_bytes=_storage_bytes(aux.get("state", {})) or None,
                         input_tensor_bytes=_tensor_bytes((x, dt, observed)),
                         output_logits_bytes=length * model.config["output_dim"] * 4))
    return dict(scope="Full sequence on CPU; five measured repetitions after one warm-up; shared host",
                samples=rows, energy_joules=None, energy_reason="No exposed GPU or RAPL energy counter",
                network_bytes=0, network_scope="Single-process model execution; no distributed transport",
                excludes="environment installation, hardware power, optimized serving/KV-cache implementation")


def run(job, output, *, preflight=False):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    write(output / "job.json", job)
    started, started_cpu = time.perf_counter(), cpu()
    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
    torch.manual_seed(job["seed"])
    av = job["task"] == "async_av"
    access = []

    def load(split, length=32, missing=None):
        if split == "test" and not (output / "selection.json").exists():
            raise RuntimeError("Test access requires a durable validation selection")
        value = data(job["task"], split, length, 512 if split == "train" else 128,
                     PACKAGE / "results/async_frontend001/data", missing)
        identity = hashlib.sha256()
        for key in sorted(value):
            identity.update(key.encode()); identity.update(value[key].tobytes())
        access.append(dict(split=split, length=length, missing_modality=missing,
                           sha256=identity.hexdigest(), unix_seconds=time.time()))
        write(output / "access.json", access)
        return value

    train = load("train")
    val = None if preflight else load("val")
    output_dim = 6 if av else 8
    model = build(job["arm"], train["x"].shape[-1], output_dim, job["width"], job["seed"])
    initial = parameter_snapshot(model)
    parameters = [p for p in model.parameters() if p.requires_grad]
    optimizer = torch.optim.AdamW(parameters, lr=job["learning_rate"], weight_decay=.001)
    rng = np.random.default_rng(job["seed"] + 100003)
    trace, best, training_cpu, training_wall, last_selection = [], float("inf"), 0.0, 0.0, None
    gradients = {key: 0.0 for key in model.parameter_groups()}
    peak_gradient = {key: 0.0 for key in gradients}
    first_loss = None

    def select(step):
        nonlocal best, last_selection
        metrics, prediction = evaluate(model, val, 2 if av else 16)
        if metrics["cross_entropy"] < best:
            best = metrics["cross_entropy"]
            checkpoint = dict(model=model.state_dict(), optimizer=optimizer.state_dict(), step=step,
                              torch_rng=torch.get_rng_state(), numpy_rng=rng.bit_generator.state,
                              job=job, config=model.config, training_cpu=training_cpu)
            torch.save(checkpoint, output / "selected.pt")
            np.savez_compressed(output / "validation_prediction.npz", **prediction)
            last_selection = dict(step=step, validation=metrics, checkpoint_sha256=digest(output / "selected.pt"))
            write(output / "selection.json", last_selection)
        return metrics

    for step in range(1, job["updates"] + 1):
        model.train()
        tick, tick_cpu = time.perf_counter(), cpu()
        chosen = rng.integers(0, len(train["x"]), job["batch_size"])
        item = tensor_batch(train, chosen)
        optimizer.zero_grad(set_to_none=True)
        logits, aux = model(item["x"], item["dt"], item["observed"], return_aux=True)
        mask = item["y"] != -100
        loss = F.cross_entropy(logits[mask], item["y"][mask])
        if not bool(torch.isfinite(loss)):
            raise FloatingPointError("Nonfinite training loss")
        loss.backward()
        for group, entries in model.parameter_groups().items():
            norm = sum(float(p.grad.detach().square().sum()) for _, p in entries if p.grad is not None) ** .5
            gradients[group] += norm
            peak_gradient[group] = max(peak_gradient[group], norm)
        norm = torch.nn.utils.clip_grad_norm_(parameters, 1.0, error_if_nonfinite=True)
        optimizer.step()
        training_cpu += cpu() - tick_cpu
        training_wall += time.perf_counter() - tick
        first_loss = float(loss.detach()) if first_loss is None else first_loss
        row = dict(step=step, loss=float(loss.detach()), gradient_norm=float(norm),
                   training_cpu_seconds=training_cpu, training_wall_seconds=training_wall)
        if "activity" in aux:
            row.update(expected_events=float(aux["activity"].detach().sum() / len(chosen)),
                       modeled_reward=float(aux["reward"].detach().sum() / len(chosen)),
                       boundary_mean=float(aux["boundary"].detach().mean()))
        budget_exhausted = job.get("training_cpu_budget") is not None and training_cpu >= job["training_cpu_budget"]
        if not preflight and (step % job["validate_every"] == 0 or step == job["updates"] or budget_exhausted):
            row["validation"] = select(step)
        trace.append(row)
        if budget_exhausted:
            break
    del aux, logits, loss
    write(output / "trace.json", trace)
    deltas = group_delta(model, initial)
    if job["arm"].startswith("freeze_"):
        frozen = job["arm"].removeprefix("freeze_")
        if deltas[frozen]["changed"] != 0:
            raise RuntimeError("Frozen parameters changed")
    summary = dict(job=job, config=model.config, actual_updates=step, first_loss=first_loss,
                   final_train_loss=trace[-1]["loss"], group_delta=deltas,
                   mean_gradient={key: value / step for key, value in gradients.items()},
                   peak_gradient=peak_gradient,
                   allocated_parameters=sum(p.numel() for p in model.parameters()),
                   trainable_parameters=sum(p.numel() for p in parameters),
                   training_cpu_seconds=training_cpu, training_wall_seconds=training_wall,
                   validation_selection=last_selection,
                   runtime=dict(python=platform.python_version(), torch=torch.__version__, numpy=np.__version__,
                                device="cpu", threads=torch.get_num_threads(), preflight=preflight))
    if not preflight:
        checkpoint = torch.load(output / "selected.pt", map_location="cpu", weights_only=False)
        model.load_state_dict(checkpoint["model"])
        summary["selected_group_delta"] = group_delta(model, initial)
        summary["evaluation"] = {}
        cases = [(32, None)] if av else [(length, None) for length in (32, 64, 128)]
        if av:
            cases += [(32, 0), (32, 1)]
        for length, missing in cases:
            test = load("test", length, missing)
            key = f"length{length}" if missing is None else f"missing_modality{missing}"
            metrics, prediction = evaluate(model, test, 2 if av else 16)
            summary["evaluation"][key] = metrics
            np.savez_compressed(output / f"prediction_{key}.npz", **prediction)
        summary["inference"] = inference_cost(model, load("test"))
    summary["worker_body_wall_seconds"] = time.perf_counter() - started
    summary["worker_body_cpu_seconds"] = cpu() - started_cpu
    summary["process_max_rss_kib"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    summary["process_cpu_seconds_before_final_write"] = cpu()
    summary["artifact_bytes_before_summary"] = sum(p.stat().st_size for p in output.rglob("*") if p.is_file())
    write(output / "summary.json", summary)
    return summary


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--job", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--preflight", action="store_true")
    args = parser.parse_args()
    job = json.loads(args.job.read_text())
    if "source_hashes" in job:
        for name, expected in job["source_hashes"].items():
            if digest(PACKAGE / name) != expected:
                raise RuntimeError("Registered source changed: " + name)
    result = run(job, args.output, preflight=args.preflight)
    print(json.dumps({key: result[key] for key in ("actual_updates", "training_cpu_seconds", "group_delta")}))


if __name__ == "__main__":
    main()
