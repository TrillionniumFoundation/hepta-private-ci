"""Paired numerical acceleration, fixed updates and equal training CPU.

All new artifacts live under this package. Existing sealed sources and data are
read-only. Registration follows train-only preflight; test splits are opened
only after a durable validation selection in each isolated worker.
"""

import argparse
import datetime
import hashlib
import json
import math
import os
from pathlib import Path
import random
import resource
import shutil
import statistics
import subprocess
import sys
import time
import traceback

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
PACKAGE = Path(__file__).resolve().parent
MODULE = "experiments.hcsn_conservative_acceleration_v1.study"


def read(path):
    return json.loads(Path(path).read_bytes())


def write(path, value):
    path = Path(path)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")
    temporary.replace(path)


def digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def utc():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def relative(path):
    return str(Path(path).resolve().relative_to(ROOT))


def new_output(path):
    path = Path(path).resolve()
    path.relative_to(PACKAGE)
    path.mkdir(parents=True, exist_ok=False)
    return path


def source_map():
    baseline = read(PACKAGE / "SOURCE_BASELINE.json")
    sources = {}
    for row in baseline["files"]:
        path = ROOT / row["path"]
        if digest(path) != row["sha256"]:
            raise RuntimeError("Parent snapshot changed: " + row["path"])
        if path.suffix == ".py":
            sources[row["path"]] = row["sha256"]
    for path in sorted(PACKAGE.glob("*.py")) + [PACKAGE / "SOURCE_BASELINE.json"]:
        sources[relative(path)] = digest(path)
    return sources


def verify(protocol):
    p = read(protocol)
    if p["status"] != "registered":
        raise RuntimeError("Formal execution requires a registered protocol")
    for path, sha in p["source_files_sha256"].items():
        if digest(ROOT / path) != sha:
            raise RuntimeError("Source changed: " + path)
    for key in ("preflight", "kernel_proof", "kernel_registration"):
        if digest(ROOT / p[key]["path"]) != p[key]["sha256"]:
            raise RuntimeError("Proof identity changed: " + key)
    for data in p["data"].values():
        for split in data["splits"].values():
            if digest(ROOT / split["path"]) != split["sha256"]:
                raise RuntimeError("Dataset identity changed: " + split["path"])
    return p


def factory(name, input_dim, output_dim, width, depth, seed):
    if name in ("hcsn_reference", "hcsn_accelerated"):
        from .model import build_model
        return build_model("distribution_free_dual", input_dim, output_dim,
            width, depth, seed, backend=name.removeprefix("hcsn_"), profile="stable")
    from experiments.hcsn_distributional_v2.model import MatchedClassifier
    return MatchedClassifier(name, input_dim, output_dim, width, depth, seed)


def pair_encoder(name, seed, width, depth):
    import torch
    from torch import nn
    from experiments.hcsn_real_av_v1.study import PairEncoder

    class PairedEncoder(PairEncoder):
        def __init__(self):
            nn.Module.__init__(self)
            self.audio = factory(name, 128, 32, width, depth, seed)
            self.video = factory(name, 128, 32, width, depth, seed + 170003)
            with torch.random.fork_rng():
                torch.manual_seed(seed + 270003)
                self.head = nn.Linear(32, 6)
            self.probability_checks = {}
            self.config = dict(name=name, task="cremad", width=width, depth=depth,
                seed=seed, fusion="shared_linear_head_of_mean_embedding", dt=1.0,
                audio=self.audio.config, video=self.video.config)

        def parameter_groups(self):
            result = {}
            for modality in ("audio", "video"):
                for group, entries in getattr(self, modality).parameter_groups().items():
                    result[modality + "." + group] = [
                        (modality + "." + key, parameter) for key, parameter in entries]
            result["head"] = [("head." + key, p) for key, p in self.head.named_parameters()]
            return result

        def counts(self):
            counts = [self.audio.counts(), self.video.counts()]
            return dict(total=sum(p.numel() for p in self.parameters()),
                backbone=sum(row["backbone"] for row in counts),
                modalities=dict(audio=counts[0], video=counts[1]))

    return PairedEncoder()


def state_digest(model, common_only=False):
    h = hashlib.sha256()
    for name, tensor in sorted(model.state_dict().items()):
        if common_only and not any(part in name.split(".") for part in ("frontend", "readout", "head")):
            continue
        value = tensor.detach().cpu().numpy()
        h.update(json.dumps([name, str(value.dtype), list(value.shape)]).encode())
        h.update(value.tobytes())
    return h.hexdigest()


def metrics(logits, labels):
    logits, labels = np.asarray(logits, np.float64), np.asarray(labels, np.int64)
    if logits.ndim != 2 or labels.shape != (len(logits),) or not len(logits):
        raise ValueError("Expected nonempty supervised logits and labels")
    if not np.isfinite(logits).all():
        raise FloatingPointError("Nonfinite evaluation logits")
    maximum = logits.max(axis=1)
    log_normalizer = maximum + np.log(np.exp(logits - maximum[:, None]).sum(axis=1))
    correct = int((logits.argmax(axis=1) == labels).sum())
    return dict(cross_entropy=float(np.mean(log_normalizer - logits[np.arange(len(labels)), labels])),
                accuracy=correct / len(labels), correct=correct, supervised_positions=len(labels))


def load_data(p, task, split, access_log, output):
    import torch
    item = p["data"][task]["splits"][split]
    if split == "test" and not (output / "selection.json").exists():
        raise RuntimeError("Test access before durable validation selection")
    path = ROOT / item["path"]
    if digest(path) != item["sha256"]:
        raise RuntimeError("Dataset changed before array access")
    with np.load(path, allow_pickle=False) as z:
        data = {key: np.array(z[key], copy=True) for key in z.files}
    if task == "cremad":
        for key in ("audio", "video", "dt", "y"):
            data[key] = torch.from_numpy(data[key])
        data["dt"] = torch.ones_like(data["dt"])
    else:
        data = {key: torch.from_numpy(data[key]) for key in ("x", "dt", "y")}
    access_log.append(dict(event="load_split", split=split, utc=utc(), sha256=item["sha256"]))
    write(output / "access_log.json", access_log)
    return data


def evaluate(model, data, task, path):
    import torch
    model.eval()
    arrays = {}
    with torch.no_grad():
        if task == "cremad":
            rows = [[] for _ in range(5)]
            for start in range(0, len(data["y"]), 16):
                outputs = model(data["audio"][start:start+16], data["video"][start:start+16],
                                data["dt"][start:start+16])
                for values, output in zip(rows, outputs, strict=True):
                    values.append(output.detach().cpu().numpy())
            for key, values in zip(("audio_embedding", "video_embedding", "audio_logits", "video_logits", "logits"), rows, strict=True):
                arrays[key] = np.concatenate(values)
            arrays.update(labels=data["y"].numpy(), actors=data["actor"], clips=data["clip"])
            result = metrics(arrays["logits"], arrays["labels"])
            result["modalities"] = {name: metrics(arrays[name+"_logits"], arrays["labels"])
                                    for name in ("audio", "video")}
        else:
            logits, labels, samples, steps = [], [], [], []
            for start in range(0, len(data["y"]), 32):
                out = model(data["x"][start:start+32], data["dt"][start:start+32],
                            return_sequence=True, return_aux=False)
                target = data["y"][start:start+32]
                mask = target != -100
                row, position = np.nonzero(mask.numpy())
                logits.append(out[mask].detach().cpu().numpy())
                labels.append(target[mask].numpy())
                samples.append(start + row)
                steps.append(position)
            arrays = dict(logits=np.concatenate(logits), labels=np.concatenate(labels),
                          sample_indices=np.concatenate(samples), step_indices=np.concatenate(steps))
            result = metrics(arrays["logits"], arrays["labels"])
    arrays["predictions"] = arrays["logits"].argmax(-1)
    np.savez_compressed(path, **arrays)
    return result, arrays


def probability_audit(aux):
    import torch
    error, minimum = 0.0, 1.0
    records = aux.get("layers", [aux]) if isinstance(aux, dict) else []
    for row in records:
        if "probability" in row:
            value = row["probability"].detach()
            if not bool(torch.isfinite(value).all()):
                raise FloatingPointError("Nonfinite probability")
            error = max(error, float((value.sum(-1) - 1).abs().max()))
            minimum = min(minimum, float(value.min()))
    if error > 1e-4 or minimum < 0:
        raise FloatingPointError("Probability conservation/positivity gate failed")
    return dict(max_mass_error=error, minimum=minimum)


def preflight(protocol, output):
    process_start, wall_start = time.process_time(), time.perf_counter()
    import torch
    from torch.nn import functional as F
    from experiments.hcsn_free_boundary_v1 import datasets, training
    p, output = read(protocol), new_output(output)
    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
    sources = source_map()
    opt, tol = p["optimization"], p["fidelity"]
    rows, paired = [], []
    for task in p["primary_tasks"] + ["irregular"]:
        x, dt, y, _ = datasets.synthetic(task, 16, "train", p["data_design"]["length"],
                                        p["data_design"]["development_seed"])
        x, dt, y = torch.from_numpy(x), torch.from_numpy(dt), torch.from_numpy(y)
        models = [factory(name, 64, 2 if task == "irregular" else 8,
                  opt["width"], opt["depth"], p["primary_seeds"][0])
                  for name in p["models"]]
        reference_count = models[0].counts()["backbone"]
        common = state_digest(models[0], True)
        for name, model in zip(p["models"], models, strict=True):
            gap = abs(model.counts()["backbone"] - reference_count) / reference_count
            if gap > opt["backbone_relative_parameter_tolerance"] or state_digest(model, True) != common:
                raise AssertionError("Parameter matching or shared initialization failed")
            rows.append(dict(task=task, model=name, counts=model.counts(), relative_backbone_gap=gap))
        if state_digest(models[0]) != state_digest(models[1]):
            raise AssertionError("HCSN initial state mismatch")
        optimizers = [torch.optim.Adam(m.parameters(), lr=opt["learning_rate"]) for m in models[:2]]
        initial_parameters = [{name: value.detach().clone() for name, value in model.named_parameters()}
                              for model in models[:2]]
        for step in range(tol["preflight_updates"]):
            start = step * tol["preflight_batch"]
            recordings = []
            for model, optimizer in zip(models[:2], optimizers, strict=True):
                began = time.process_time()
                optimizer.zero_grad(set_to_none=True)
                logits, aux = model(x[start:start+tol["preflight_batch"]],
                                    dt[start:start+tol["preflight_batch"]], return_sequence=True)
                loss = F.cross_entropy(logits.flatten(0, 1),
                    y[start:start+tol["preflight_batch"]].flatten(), ignore_index=-100)
                loss.backward()
                audit = probability_audit(aux)
                gradients = training._gradient_summary(model)
                if any(not row["finite"] or row["missing_elements"] or row["l2"] <= 0 for row in gradients.values()):
                    raise AssertionError("Missing, zero-group or nonfinite preflight gradient")
                gradient_tensors = {n: v.grad.detach().clone() for n, v in model.named_parameters()}
                torch.nn.utils.clip_grad_norm_(model.parameters(), opt["clip_l2"])
                optimizer.step()
                elapsed = time.process_time() - began
                recordings.append(dict(logits=logits.detach().clone(), gradients=gradient_tensors,
                    parameters={n: v.detach().clone() for n, v in model.named_parameters()},
                    loss=float(loss.detach()), cpu_seconds=elapsed, probability=audit,
                    gradient_groups=gradients))
            left, right = recordings
            errors = {}
            for kind in ("logits", "gradients", "parameters"):
                first = {kind: left[kind]} if kind == "logits" else left[kind]
                second = {kind: right[kind]} if kind == "logits" else right[kind]
                for key in first:
                    torch.testing.assert_close(first[key], second[key],
                        atol=tol["preflight_atol"], rtol=tol["preflight_rtol"])
                errors[kind] = max(float((first[k] - second[k]).abs().max()) for k in first)
            paired.append(dict(task=task, step=step+1, max_abs_error=errors,
                reference_cpu_seconds=left["cpu_seconds"], accelerated_cpu_seconds=right["cpu_seconds"],
                reference_gradient_groups=left["gradient_groups"], accelerated_gradient_groups=right["gradient_groups"],
                reference_loss=left["loss"], accelerated_loss=right["loss"]))
        for index, model in enumerate(models[:2]):
            changes = training._parameter_changes(model, initial_parameters[index])
            tensor_changes = {name: float((parameter.detach()-initial_parameters[index][name]).norm())
                              for name, parameter in model.named_parameters()}
            if any(row["l2"] <= 0 for row in changes.values()):
                raise AssertionError("A physical/content group did not update in preflight")
            rows[[row["task"] == task and row["model"] == p["models"][index] for row in rows].index(True)].update(
                group_parameter_changes=changes, tensor_parameter_changes=tensor_changes)
        for name, model in zip(p["models"][2:], models[2:], strict=True):
            logits, aux = model(x[:4], dt[:4], return_sequence=True)
            loss = F.cross_entropy(logits.flatten(0, 1), y[:4].flatten(), ignore_index=-100)
            loss.backward()
            gradients = training._gradient_summary(model)
            if any(not row["finite"] or row["missing_elements"] or row["l2"] <= 0 for row in gradients.values()):
                raise AssertionError("Baseline has missing, zero-group or nonfinite gradients: " + name)
        del models, optimizers, recordings, logits, aux, loss
    if source_map() != sources:
        raise RuntimeError("Source changed during preflight")
    result = dict(schema="hcsn-conservative-preflight.v1", passed=True, train_only=True,
        data_seed=p["data_design"]["development_seed"], source_files_sha256=sources,
        protocol_design_sha256=digest(protocol), counts=rows, trajectory_pairs=paired,
        cpu_seconds=time.process_time()-process_start, wall_seconds=time.perf_counter()-wall_start,
        performance_scope="Three small paired train-only steps per task; descriptive, includes correctness audit; not formal throughput evidence")
    write(output / "PREFLIGHT.json", result)
    print(json.dumps(dict(passed=True, pairs=len(paired), output=relative(output))), flush=True)


def register(protocol, output, preflight_path, kernel_proof_path, av_cache):
    process_start, wall_start = time.process_time(), time.perf_counter()
    from experiments.hcsn_free_boundary_v1.datasets import synthetic
    protocol = Path(protocol)
    p = read(protocol)
    if p["status"] != "draft_not_registered":
        raise FileExistsError("Preserve the existing registration")
    proof = read(preflight_path)
    if (not proof["passed"] or not proof["train_only"]
            or proof["source_files_sha256"] != source_map()
            or proof["protocol_design_sha256"] != digest(protocol)):
        raise RuntimeError("Matching train-only preflight required")
    kernel_proof = read(kernel_proof_path)
    kernel_registration_path = Path(kernel_proof_path).with_name("REGISTRATION.json")
    kernel_registration = read(kernel_registration_path)
    if (not kernel_proof.get("passed") or kernel_proof.get("source_changed_during_run") != []
            or not kernel_registration.get("no_task_labels")
            or kernel_proof["source_sha256"] != kernel_registration["source_sha256"]):
        raise RuntimeError("Independent passed kernel proof required")
    for filename, expected in kernel_proof["source_sha256"].items():
        source = Path(filename)
        if source.is_absolute():
            # Older proof receipts preserve their creation path. Resolve the
            # repository-relative experiments suffix against this checkout.
            parts = source.parts
            source = ROOT / Path(*parts[parts.index("experiments"):])
        else:
            source = ROOT / source
        source.resolve().relative_to(ROOT)
        if digest(source) != expected:
            raise RuntimeError("Kernel proof does not cover current source: " + filename)
    output = new_output(output)
    data_root = output / "data"
    data_root.mkdir()
    p["data"] = {}
    for task in p["primary_tasks"] + ["irregular"]:
        folder = data_root / task
        folder.mkdir()
        splits = {}
        for split, size in p["data_design"]["sizes"].items():
            x, dt, y, metadata = synthetic(task, size, split, p["data_design"]["length"], p["data_design"]["seed"])
            path = folder / (split + ".npz")
            np.savez_compressed(path, x=x, dt=dt, y=y)
            write(path.with_suffix(".json"), metadata)
            splits[split] = dict(path=relative(path), sha256=digest(path), examples=size)
        p["data"][task] = dict(input_dim=64, output_dim=2 if task == "irregular" else 8,
            data_seed=p["data_design"]["seed"], splits=splits, previously_observed_examples=False)
    av_cache = Path(av_cache)
    manifest = read(av_cache / "DATASET.json")
    folder = data_root / "cremad"
    folder.mkdir()
    splits = {}
    for split, original in (("train", "train"), ("val", "validation"), ("test", "test")):
        row = manifest["splits"][original]
        source = av_cache / row["path"]
        if digest(source) != row["sha256"]:
            raise RuntimeError("Cached CREMA-D checksum mismatch")
        target = folder / (split + ".npz")
        shutil.copyfile(source, target)
        splits[split] = dict(path=relative(target), sha256=digest(target),
                            examples=row["examples"], actors=row["actors"])
    write(folder / "SOURCE_DATASET.json", manifest)
    p["data"]["cremad"] = dict(input_dim=128, output_dim=6, splits=splits,
        previously_observed_examples=True, dt_override=1.0,
        source_manifest_sha256=digest(av_cache / "DATASET.json"))
    jobs = [dict(family=family, task=task, model=model, seed=seed, supplementary=False)
        for family in ("fixed", "cpu") for task in p["primary_tasks"]
        for seed in p["primary_seeds"] for model in p["models"]]
    jobs += [dict(family="fixed", task=task, model=model,
                 seed=p["supplementary_seed"], supplementary=True)
             for task in p["supplementary_tasks"] for model in p["models"]]
    random.Random(p["execution"]["order_seed"]).shuffle(jobs)
    if len(jobs) != p["execution"]["expected_jobs"]:
        raise AssertionError("Registered job count changed")
    p.update(status="registered", registered_utc=utc(), jobs=jobs,
        source_files_sha256=source_map(), output=relative(output),
        preflight=dict(path=relative(preflight_path), sha256=digest(preflight_path)),
        kernel_proof=dict(path=relative(kernel_proof_path), sha256=digest(kernel_proof_path)),
        kernel_registration=dict(path=relative(kernel_registration_path), sha256=digest(kernel_registration_path)),
        proof_scope="Kernel proof covers only its listed source_sha256; model/runner/analyzer are independently bound by the later train-only preflight.")
    write(output / "DESIGN.json", read(protocol))
    write(protocol, p)
    shutil.copyfile(protocol, output / "PROTOCOL.json")
    write(output / "REGISTRATION.json", dict(protocol_sha256=digest(protocol), registered_utc=p["registered_utc"], jobs=len(jobs),
        cpu_seconds=time.process_time()-process_start, wall_seconds=time.perf_counter()-wall_start,
        scope="Data preparation, byte verification and registration; excluded from isolated training workers"))
    print(json.dumps(dict(status="registered", jobs=len(jobs), output=relative(output))), flush=True)


def inference_timing(model, data, task, settings):
    import torch
    batch = settings["inference_batch"]
    model.eval()
    values = []
    with torch.inference_mode():
        for index in range(settings["warmups"] + settings["repetitions"]):
            cpu, wall = time.process_time(), time.perf_counter()
            if task == "cremad":
                model(data["audio"][:batch], data["video"][:batch], data["dt"][:batch])
            else:
                model(data["x"][:batch], data["dt"][:batch], return_sequence=True, return_aux=False)
            row = dict(cpu_seconds=time.process_time()-cpu, wall_seconds=time.perf_counter()-wall)
            if index >= settings["warmups"]:
                values.append(row)
    return dict(batch=batch, repetitions=values,
        median_cpu_seconds=statistics.median(row["cpu_seconds"] for row in values),
        median_wall_seconds=statistics.median(row["wall_seconds"] for row in values))


def worker(protocol, output, job_index):
    import torch
    from torch.nn import functional as F
    from experiments.hcsn_free_boundary_v1 import training
    from experiments.hcsn_real_av_v1.study import objective, retrieval
    p = verify(protocol)
    output = new_output(output)
    job, opt = p["jobs"][job_index], p["optimization"]
    start_cpu, start_wall = time.process_time(), time.perf_counter()
    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
    torch.manual_seed(job["seed"])
    write(output / "request.json", dict(job=job, protocol_sha256=digest(protocol), utc=utc()))
    accesses = []
    train, validation = (load_data(p, job["task"], split, accesses, output) for split in ("train", "val"))
    model = (pair_encoder(job["model"], job["seed"], opt["width"], opt["depth"])
        if job["task"] == "cremad" else factory(job["model"], p["data"][job["task"]]["input_dim"],
            p["data"][job["task"]]["output_dim"], opt["width"], opt["depth"], job["seed"]))
    optimizer = torch.optim.Adam(model.parameters(), lr=opt["learning_rate"])
    initial = {name: value.detach().clone() for name, value in model.named_parameters()}
    initial_hash, common_hash = state_digest(model), state_digest(model, True)
    training.save_weights(output / "initial.npz", model)
    generator = torch.Generator().manual_seed(job["seed"] + 200003)
    batch = opt["av_batch_size"] if job["task"] == "cremad" else opt["batch_size"]
    permutation = torch.randperm(len(train["y"]), generator=generator) if job["task"] == "cremad" else None
    position = 0
    fixed_steps = opt["supplementary_updates"] if job["supplementary"] else opt["fixed_updates"]
    step_targets = opt["supplementary_validation_updates"] if job["supplementary"] else opt["fixed_validation_updates"]
    cpu_targets = opt["cpu_validation_seconds"]
    checkpoints, training_cpu, validation_cpu, step, next_target = [], 0.0, 0.0, 0, 0
    prefix = hashlib.sha256()
    with (output / "updates.jsonl").open("x") as stream:
        while step < (fixed_steps if job["family"] == "fixed" else opt["max_updates"]):
            if job["family"] == "cpu" and training_cpu >= opt["cpu_seconds"]:
                break
            began = time.process_time()
            model.train()
            if job["task"] == "cremad":
                if position + batch > len(permutation):
                    permutation, position = torch.randperm(len(train["y"]), generator=generator), 0
                indices = permutation[position:position+batch]
                position += batch
            else:
                indices = torch.randint(len(train["y"]), (batch,), generator=generator)
            prefix.update(indices.numpy().tobytes())
            optimizer.zero_grad(set_to_none=True)
            if job["task"] == "cremad":
                outputs = model(train["audio"][indices], train["video"][indices], train["dt"][indices])
                loss = objective(outputs, train["y"][indices], opt["av_temperature"])
                aux = {}
            else:
                logits, aux = model(train["x"][indices], train["dt"][indices], return_sequence=True)
                loss = F.cross_entropy(logits.flatten(0, 1), train["y"][indices].flatten(), ignore_index=-100)
            if not bool(torch.isfinite(loss)):
                raise FloatingPointError("Nonfinite training objective")
            audit = probability_audit(aux)
            loss.backward()
            gradients = training._gradient_summary(model)
            if any(not row["finite"] or row["missing_elements"] for row in gradients.values()):
                raise FloatingPointError("Nonfinite or disconnected training gradient")
            norm = float(torch.nn.utils.clip_grad_norm_(model.parameters(), opt["clip_l2"]))
            optimizer.step()
            step += 1
            training_cpu += time.process_time() - began
            record = dict(step=step, loss=float(loss.detach()), training_cpu_seconds=training_cpu,
                batch_sha256=hashlib.sha256(indices.numpy().tobytes()).hexdigest(), prefix_sha256=prefix.hexdigest(),
                gradients=gradients, probability=audit, preclip_gradient_l2=norm)
            if "total_activity" in aux:
                record.update(modeled_activity=float(aux["total_activity"].detach()),
                              modeled_cost=float(aux["total_cost"].detach()))
            stream.write(json.dumps(record, sort_keys=True, allow_nan=False) + "\n")
            stream.flush()
            crossed = []
            if job["family"] == "cpu":
                while next_target < len(cpu_targets) and training_cpu >= cpu_targets[next_target]:
                    crossed.append(cpu_targets[next_target])
                    next_target += 1
            should_validate = bool(crossed) if job["family"] == "cpu" else step in step_targets
            if should_validate:
                began = time.process_time()
                filename = f"step_{step:06d}.npz"
                prediction = f"validation_{step:06d}.npz"
                validation_metrics, _ = evaluate(model, validation, job["task"], output / prediction)
                checkpoint_sha = training.save_weights(output / filename, model)
                validation_cpu += time.process_time() - began
                checkpoints.append(dict(step=step, weights=filename, sha256=checkpoint_sha,
                    training_cpu_seconds=training_cpu, crossed_cpu_targets=crossed,
                    validation=validation_metrics, predictions=prediction, predictions_sha256=digest(output / prediction)))
                write(output / "checkpoints.json", checkpoints)
            if job["family"] == "fixed" and training_cpu > opt["fixed_training_cpu_cap_seconds"]:
                raise RuntimeError("Fixed-update engineering CPU cap exceeded; preserve failed job")
    if job["family"] == "cpu" and training_cpu < opt["cpu_seconds"]:
        raise RuntimeError("CPU family hit update cap before budget")
    if not checkpoints or checkpoints[-1]["step"] != step:
        raise AssertionError("Final registered milestone was not evaluated")
    selected = min(checkpoints, key=lambda row: (row["validation"]["cross_entropy"], row["step"]))
    final_hash = training.save_weights(output / "final.npz", model)
    selection = dict(checkpoint=selected, rule=opt["selection"], completed_candidates=1,
        initial_state_sha256=initial_hash, common_initial_state_sha256=common_hash,
        final_checkpoint_sha256=final_hash, protocol_sha256=digest(protocol))
    write(output / "selection.json", selection)
    shutil.copyfile(output / selected["weights"], output / "selected.npz")
    if digest(output / "selected.npz") != selected["sha256"]:
        raise RuntimeError("Selected checkpoint identity mismatch")
    accesses.append(dict(event="validation_selection_locked", utc=utc(), sha256=digest(output / "selection.json")))
    write(output / "access_log.json", accesses)
    training.load_weights(output / "selected.npz", model)
    changes = {name: float((parameter.detach()-initial[name]).norm()) for name, parameter in model.named_parameters()}
    test = load_data(p, job["task"], "test", accesses, output)
    test_metrics, predictions = evaluate(model, test, job["task"], output / "test_predictions.npz")
    retrieval_metrics = None
    if job["task"] == "cremad":
        retrieval_metrics, _ = retrieval(predictions, test["actor"])
    timing = inference_timing(model, test, job["task"], p["timing"])
    verify(protocol)
    result = dict(status="completed", job=job, protocol_sha256=digest(protocol),
        config=model.config, counts=model.counts(), updates=step,
        training_cpu_seconds=training_cpu, validation_cpu_seconds=validation_cpu,
        endpoint_overrun_seconds=max(0.0, training_cpu-opt["cpu_seconds"]) if job["family"] == "cpu" else 0.0,
        worker_body_cpu_seconds=time.process_time()-start_cpu,
        worker_body_wall_seconds=time.perf_counter()-start_wall,
        peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,
        initial_state_sha256=initial_hash, common_initial_state_sha256=common_hash,
        minibatch_prefix_sha256=prefix.hexdigest(), selection=selection,
        selected_parameter_changes=changes, test=test_metrics, retrieval=retrieval_metrics,
        audiovisual_probability_checks=getattr(model, "probability_checks", None),
        predictions_sha256=digest(output / "test_predictions.npz"), inference=timing,
        access_log=accesses, measured_energy_joules=None, gpu_memory_bytes=None)
    write(output / "summary.json", result)


def memory_state():
    folder = Path("/sys/fs/cgroup")
    maximum, current = (folder / "memory.max").read_text().strip(), int((folder / "memory.current").read_text())
    statistics_map = {key: int(value) for key, value in (row.split() for row in (folder / "memory.stat").read_text().splitlines())}
    events = {key: int(value) for key, value in (row.split() for row in (folder / "memory.events").read_text().splitlines())}
    # File cache and reclaimable slab can fill a cgroup even when anonymous
    # model memory is small. Keep tmpfs/shared memory and dirty/writeback pages
    # charged, and retain the independent 1GiB shared safety reserve.
    clean_file = max(0, statistics_map.get("file", 0)-statistics_map.get("shmem", 0)
                     -statistics_map.get("file_dirty", 0)-statistics_map.get("file_writeback", 0))
    reclaimable = clean_file+statistics_map.get("slab_reclaimable", 0)
    return dict(maximum_bytes=int(maximum) if maximum != "max" else 8 * 1024**3,
        estimated_nonreclaimable_bytes=max(0, current-reclaimable),
        estimated_reclaimable_bytes=reclaimable, current_bytes=current, memory_stat=statistics_map,
        reclaim_assumption="Clean non-shmem file pages and slab_reclaimable may be reclaimed; dirty/writeback/shmem remain charged. Reservation is a forecast, not a hard memory guarantee.",
        oom={key: events.get(key, 0) for key in ("oom", "oom_kill")})


def run(protocol, output, public_commit):
    if len(public_commit or "") != 40 or any(c not in "0123456789abcdef" for c in public_commit):
        raise ValueError("Root-supplied 40-character publication commit required")
    p, output = verify(protocol), Path(output).resolve()
    if relative(output) != p["output"] or read(output / "REGISTRATION.json")["protocol_sha256"] != digest(protocol):
        raise RuntimeError("Registration/output mismatch")
    (output / "runs").mkdir()
    (output / "logs").mkdir()
    settings = p["execution"]
    if settings["workers"] > 2 or settings["threads_per_worker"] != 1:
        raise ValueError("Shared resource ceiling changed")
    initial_memory = memory_state()
    write(output / "LAUNCH.json", dict(protocol_sha256=digest(protocol), public_commit=public_commit,
        utc=utc(), python=sys.executable, memory=initial_memory, command=sys.argv))
    env = dict(os.environ, OMP_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1", MKL_NUM_THREADS="1",
               NUMEXPR_NUM_THREADS="1", PYTHONDONTWRITEBYTECODE="1")
    live, records, next_job, stopped, reason = {}, [], 0, False, None
    began, coordinator_cpu = time.perf_counter(), time.process_time()
    last_heartbeat, blocked_since = -math.inf, None
    while live or (next_job < len(p["jobs"]) and not stopped):
        state = memory_state()
        if (output / "STOP_REQUESTED.json").exists():
            stopped, reason = True, "explicit stop request"
        if state["oom"] != initial_memory["oom"]:
            stopped, reason = True, "new shared cgroup OOM event"
        remaining_reservations = 0
        for pid in live:
            try:
                status = dict(row.split(":", 1) for row in Path(f"/proc/{pid}/status").read_text().splitlines() if ":" in row)
                current_anon = int(status.get("RssAnon", "0 kB").split()[0]) * 1024
            except (OSError, ValueError):
                current_anon = 0
            remaining_reservations += max(0, settings["worker_memory_reservation_bytes"]-current_anon)
        available = state["maximum_bytes"]-state["estimated_nonreclaimable_bytes"]-remaining_reservations
        can_dispatch = available >= settings["worker_memory_reservation_bytes"] + settings["shared_reserve_bytes"]
        if not stopped and next_job < len(p["jobs"]) and len(live) < settings["workers"] and can_dispatch:
            job = p["jobs"][next_job]
            name = f"{job['family']}__{job['task']}__{job['model']}__{job['seed']}"
            command = [sys.executable, "-m", MODULE, "worker", "--protocol", str(Path(protocol).resolve()),
                       "--output", str(output / "runs" / name), "--job-index", str(next_job)]
            log = (output / "logs" / (name + ".log")).open("xb")
            child = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT, env=env, cwd=ROOT)
            live[child.pid] = dict(child=child, job=job, directory="runs/"+name,
                                  command=command, log=log, started=time.perf_counter(), index=next_job)
            next_job += 1
            blocked_since = None
        elif not live and not stopped and next_job < len(p["jobs"]):
            blocked_since = time.perf_counter() if blocked_since is None else blocked_since
            if time.perf_counter()-blocked_since > settings["memory_wait_limit_seconds"]:
                stopped, reason = True, "memory reservation unavailable before dispatch"
        for pid in list(live):
            finished, status, usage = os.wait4(pid, os.WNOHANG)
            if not finished:
                continue
            item = live.pop(pid)
            item["log"].close()
            code = os.waitstatus_to_exitcode(status)
            item["child"].returncode = code
            row = dict(job=item["job"], index=item["index"], directory=item["directory"], returncode=code,
                command=item["command"], wall_seconds=time.perf_counter()-item["started"],
                whole_worker_cpu_seconds=usage.ru_utime+usage.ru_stime, peak_rss_bytes=usage.ru_maxrss*1024)
            records.append(row)
            folder = output / row["directory"]
            folder.mkdir(exist_ok=True)
            write(folder / "EXECUTION.json", row)
            if code or row["peak_rss_bytes"] > settings["worker_memory_reservation_bytes"]:
                stopped, reason = True, "worker failure or measured peak exceeds reservation"
            print(json.dumps({k: row[k] for k in ("job", "returncode", "whole_worker_cpu_seconds", "peak_rss_bytes")}), flush=True)
        if time.perf_counter()-last_heartbeat >= settings["heartbeat_seconds"] or not live:
            write(output / "PROGRESS.json", dict(completed=len(records), expected=len(p["jobs"]),
                dispatched=next_job, running=[row["job"] for row in live.values()], records=records,
                memory=state, stopped=stopped, reason=reason))
            last_heartbeat = time.perf_counter()
        if live or (next_job < len(p["jobs"]) and not stopped):
            time.sleep(.1)
    complete = not stopped and len(records) == len(p["jobs"]) and all(row["returncode"] == 0 for row in records)
    write(output / ("COMPLETE.json" if complete else "ABORTED.json"), dict(completed=complete,
        protocol_sha256=digest(protocol), records=sorted(records, key=lambda row: row["index"]),
        unstarted=p["jobs"][next_job:], reason=reason,
        whole_child_cpu_seconds=sum(row["whole_worker_cpu_seconds"] for row in records),
        coordinator_cpu_seconds=time.process_time()-coordinator_cpu, wall_seconds=time.perf_counter()-began,
        cost_scope="Isolated cohort workers and coordinator only; preflight, kernel audit, data registration and analysis are separate costs, not included here."))
    if not complete:
        raise SystemExit(1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("preflight", "register", "run", "worker"))
    parser.add_argument("--protocol", type=Path, default=PACKAGE / "PROTOCOL.json")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--preflight", type=Path)
    parser.add_argument("--kernel-proof", type=Path)
    parser.add_argument("--av-cache", type=Path)
    parser.add_argument("--public-commit")
    parser.add_argument("--job-index", type=int)
    args = parser.parse_args()
    if args.action == "preflight":
        preflight(args.protocol, args.output)
    elif args.action == "register":
        register(args.protocol, args.output, args.preflight, args.kernel_proof, args.av_cache)
    elif args.action == "run":
        run(args.protocol, args.output, args.public_commit)
    else:
        try:
            worker(args.protocol, args.output, args.job_index)
        except Exception:
            args.output.mkdir(parents=True, exist_ok=True)
            write(args.output / "WORKER_FAILURE.json", dict(traceback=traceback.format_exc(), utc=utc()))
            raise


if __name__ == "__main__":
    main()
