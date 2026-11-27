"""CPU-budgeted paired training with validation-only selection and numeric checkpoints.

Training budgets cover minibatch sampling, forward/backward, gradient summaries,
clipping and optimizer updates. Validation, checkpoint I/O, setup and reporting
are excluded from that budget and separately included in total process costs.
No test or OOD array is loaded until both learning-rate searches are complete
and their validation-based winner has been durably selected.
"""

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys
import time
import traceback

import numpy as np
import torch
from torch.nn import functional as F

from .benchmark_models import MODEL_NAMES, build_model


def _write_json(path, value):
    path = Path(path)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")
    temporary.replace(path)


def _sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for block in iter(lambda: source.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _peak_rss_bytes():
    try:
        import resource
        value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return int(value if sys.platform == "darwin" else value * 1024)
    except ImportError:
        return None


def load_split(path, split, access_log=None):
    with np.load(path, allow_pickle=False) as archive:
        names = [f"{split}_{key}" for key in ("x", "dt", "y")]
        if not any(name in archive for name in names):
            return None
        arrays = [np.array(archive[name], copy=True) for name in names]
    x, dt, y = arrays
    if (x.ndim != 3 or x.shape[0] < 1 or x.shape[1] < 1
            or dt.shape != x.shape[:2] or y.shape != x.shape[:2]):
        raise ValueError(f"{split}: require x[N,T,I], dt[N,T], y[N,T]")
    if not np.isfinite(x).all() or not np.isfinite(dt).all() or (dt < 0).any():
        raise ValueError(f"{split}: features and nonnegative times must be finite")
    if not np.issubdtype(y.dtype, np.integer) or not ((y >= 0) | (y == -100)).all():
        raise ValueError(f"{split}: labels must be integer classes or -100")
    if not (y != -100).any(axis=1).all():
        raise ValueError(f"{split}: each sample must have at least one supervised position")
    if access_log is not None:
        access_log.append(dict(event="load_split", split=split, samples=int(x.shape[0])))
    return dict(x=torch.as_tensor(x, dtype=torch.float32),
                dt=torch.as_tensor(dt, dtype=torch.float32),
                y=torch.as_tensor(y, dtype=torch.long))


def save_weights(path, model):
    """Portable numeric-only state_dict: loading never enables pickle."""
    path = Path(path)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("wb") as destination:
        np.savez_compressed(destination, **{
            name: tensor.detach().cpu().numpy() for name, tensor in model.state_dict().items()})
    temporary.replace(path)
    return _sha256(path)


def load_weights(path, model):
    with np.load(path, allow_pickle=False) as archive:
        weights = {name: torch.from_numpy(np.array(archive[name], copy=True)) for name in archive.files}
    model.load_state_dict(weights, strict=True)


def evaluate(model, split, batch_size=128, output_path=None):
    model.eval()
    total_loss, correct, count = 0.0, 0, 0
    outputs = []
    with torch.no_grad():
        for start in range(0, split["x"].shape[0], batch_size):
            x, dt, y = (split[key][start:start + batch_size] for key in ("x", "dt", "y"))
            logits = model(x, dt, return_sequence=True, return_aux=False)
            if not torch.isfinite(logits).all():
                raise FloatingPointError("Evaluation produced nonfinite logits")
            mask = y != -100
            total_loss += F.cross_entropy(logits.flatten(0, 1), y.flatten(),
                                          ignore_index=-100, reduction="sum").item()
            correct += ((logits.argmax(-1) == y) & mask).sum().item()
            count += mask.sum().item()
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
    return dict(cross_entropy=total_loss / count, accuracy=correct / count,
                correct=int(correct), supervised_positions=int(count),
                samples=int(split["x"].shape[0]))


def _gradient_summary(model):
    result = {}
    for group, entries in model.parameter_groups().items():
        squared, maximum, missing, finite = 0.0, 0.0, 0, True
        for _, parameter in entries:
            if parameter.grad is None:
                missing += parameter.numel()
                continue
            gradient = parameter.grad.detach()
            finite = finite and bool(torch.isfinite(gradient).all())
            squared += gradient.square().sum().item()
            maximum = max(maximum, gradient.abs().max().item())
        result[group] = dict(l2=squared ** 0.5, max_abs=maximum,
                             missing_elements=missing, finite=finite)
    return result


def _parameter_changes(model, initial):
    return {
        group: dict(l2=sum((parameter.detach() - initial[name]).square().sum().item()
                           for name, parameter in entries) ** 0.5,
                    max_abs=max(((parameter.detach() - initial[name]).abs().max().item()
                                 for name, parameter in entries), default=0.0))
        for group, entries in model.parameter_groups().items()}


def train_candidate(train, validation, model_name, seed, learning_rate, output_dir,
                    cpu_seconds=20.0, width=32, depth=1, batch_size=32, max_updates=8192):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=False)
    process_start, wall_start = time.process_time(), time.perf_counter()
    classes = int(train["y"].max().item()) + 1
    model = build_model(model_name, train["x"].shape[-1], classes,
                        width=width, depth=depth, seed=seed)
    optimizer = torch.optim.Adam(model.parameters(), lr=learning_rate)
    initial = {name: parameter.detach().clone() for name, parameter in model.named_parameters()}
    initial_hash = save_weights(output_dir / "initial.npz", model)
    setup_cpu = time.process_time() - process_start
    generator = torch.Generator().manual_seed(seed + 200003)
    targets = sorted(set([t for t in (5.0, 10.0, 20.0) if t < cpu_seconds] + [cpu_seconds]))
    next_target, training_cpu, step, validation_cpu = 0, 0.0, 0, 0.0
    checkpoints, prefix = [], hashlib.sha256()
    first128_prefix = None
    with (output_dir / "updates.jsonl").open("w") as log:
        while training_cpu < cpu_seconds and step < max_updates:
            update_start = time.process_time()
            model.train()
            indices = torch.randint(train["x"].shape[0], (batch_size,), generator=generator)
            prefix.update(indices.numpy().tobytes())
            x, dt, y = (train[key][indices] for key in ("x", "dt", "y"))
            optimizer.zero_grad(set_to_none=True)
            logits, aux = model(x, dt, return_sequence=True)
            loss = F.cross_entropy(logits.flatten(0, 1), y.flatten(), ignore_index=-100)
            if not bool(torch.isfinite(loss)):
                raise FloatingPointError(f"Nonfinite training loss at step {step + 1}")
            loss.backward()
            gradients = _gradient_summary(model)
            if not all(record["finite"] for record in gradients.values()):
                raise FloatingPointError(f"Nonfinite training gradient at step {step + 1}")
            unclipped_norm = torch.nn.utils.clip_grad_norm_(model.parameters(), 2.0).item()
            optimizer.step()
            step += 1
            training_cpu += time.process_time() - update_start
            if step == 128:
                first128_prefix = prefix.hexdigest()
            record = dict(step=step, loss=loss.item(), training_cpu_seconds=training_cpu,
                           batch_sha256=hashlib.sha256(indices.numpy().tobytes()).hexdigest(),
                           prefix_sha256=prefix.hexdigest(), gradients=gradients,
                           preclip_gradient_l2=unclipped_norm)
            if "total_activity" in aux:
                record["modeled_activity"] = aux["total_activity"].detach().item()
                record["modeled_cost"] = aux["total_cost"].detach().item()
            log.write(json.dumps(record, sort_keys=True, allow_nan=False) + "\n")
            crossed = []
            while next_target < len(targets) and training_cpu >= targets[next_target]:
                crossed.append(targets[next_target])
                next_target += 1
            stopping = training_cpu >= cpu_seconds or step >= max_updates
            if crossed or step == 128 or stopping:
                validation_start = time.process_time()
                metrics = evaluate(model, validation)
                validation_cpu += time.process_time() - validation_start
                filename = f"step_{step:06d}.npz"
                digest = save_weights(output_dir / filename, model)
                checkpoint = dict(step=step, weights=filename, sha256=digest,
                                   training_cpu_seconds=training_cpu,
                                   crossed_cpu_targets=crossed,
                                   fixed_step_128=(step == 128), validation=metrics,
                                   primary_eligible=bool(crossed or stopping),
                                   endpoint_overrun_seconds=max(0.0, training_cpu - cpu_seconds))
                checkpoints.append(checkpoint)
                _write_json(output_dir / "checkpoints.json", checkpoints)
    best = min((item for item in checkpoints if item["primary_eligible"]),
               key=lambda item: (item["validation"]["cross_entropy"],
                                              item["training_cpu_seconds"], item["step"]))
    final_changes = _parameter_changes(model, initial)
    load_weights(output_dir / best["weights"], model)
    result = dict(model=model_name, seed=seed, learning_rate=learning_rate,
                   config=model.config, counts=model.counts(), requested_training_cpu_seconds=cpu_seconds,
                   training_cpu_seconds=training_cpu, overrun_seconds=max(0.0, training_cpu - cpu_seconds),
                   updates=step, stopping_reason="cpu_budget" if training_cpu >= cpu_seconds else "update_cap",
                   setup_cpu_seconds=setup_cpu, validation_cpu_seconds=validation_cpu,
                   total_cpu_seconds=time.process_time() - process_start,
                   total_wall_seconds=time.perf_counter() - wall_start,
                   process_peak_rss_bytes=_peak_rss_bytes(), initial_sha256=initial_hash,
                   batch_prefix_sha256=prefix.hexdigest(), first128_prefix_sha256=first128_prefix,
                   checkpoints=checkpoints, best=best,
                   final_parameter_changes=final_changes,
                   selected_parameter_changes=_parameter_changes(model, initial))
    _write_json(output_dir / "candidate.json", result)
    return result


def run_search(data_path, model_name, seed, output_dir, cpu_seconds=20.0,
               width=32, depth=1, batch_size=32, max_updates=8192,
               learning_rates=(0.001, 0.003)):
    if cpu_seconds <= 0 or min(width, depth, batch_size, max_updates) < 1:
        raise ValueError("Training budget, dimensions, batch size and cap must be positive")
    if not learning_rates or any(rate <= 0 for rate in learning_rates):
        raise ValueError("Learning rates must be positive")
    torch.set_num_threads(1)
    output_dir, data_path = Path(output_dir), Path(data_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    if any(output_dir.iterdir()):
        raise FileExistsError("Use a fresh output directory; previous evidence is preserved")
    process_start, wall_start = time.process_time(), time.perf_counter()
    access_log = []
    request = dict(data=str(data_path), model=model_name, seed=seed, cpu_seconds=cpu_seconds,
                    width=width, depth=depth, batch_size=batch_size, max_updates=max_updates,
                    learning_rates=list(learning_rates), torch_version=torch.__version__,
                    torch_threads=torch.get_num_threads(), loss="task_cross_entropy_only")
    _write_json(output_dir / "request.json", request)
    try:
        data_hash = _sha256(data_path)
        train = load_split(data_path, "train", access_log)
        validation = load_split(data_path, "val", access_log)
        if train is None or validation is None:
            raise ValueError("Both train and val splits are required")
        candidates = []
        for index, learning_rate in enumerate(learning_rates):
            directory = f"lr_{index}_{learning_rate:g}"
            candidate = train_candidate(train, validation, model_name, seed,
                                         learning_rate, output_dir / directory,
                                         cpu_seconds, width, depth, batch_size, max_updates)
            candidate["directory"] = directory
            candidates.append(candidate)
        winner = min(candidates, key=lambda item: (item["best"]["validation"]["cross_entropy"],
                                                   item["learning_rate"]))
        selection = dict(rule="minimum_validation_cross_entropy_only",
                          selected_learning_rate=winner["learning_rate"],
                          selected_step=winner["best"]["step"],
                          selected_validation=winner["best"]["validation"],
                          selected_checkpoint_sha256=winner["best"]["sha256"],
                          completed_lr_candidates=len(candidates),
                          dataset_sha256=data_hash)
        _write_json(output_dir / "selection.json", selection)
        access_log.append(dict(event="selection_locked", learning_rate=winner["learning_rate"],
                               completed_lr_candidates=len(candidates)))
        selected_weights = output_dir / winner["directory"] / winner["best"]["weights"]
        shutil.copyfile(selected_weights, output_dir / "selected.npz")
        if _sha256(output_dir / "selected.npz") != selection["selected_checkpoint_sha256"]:
            raise ValueError("Selected checkpoint identity changed after selection")
        model = build_model(model_name, train["x"].shape[-1], int(train["y"].max().item()) + 1,
                            width=width, depth=depth, seed=seed)
        load_weights(output_dir / "selected.npz", model)
        holdout = {}
        holdout_start = time.process_time()
        if _sha256(data_path) != data_hash:
            raise ValueError("Dataset changed before heldout evaluation")
        for split_name in ("test", "ood"):
            split = load_split(data_path, split_name, access_log)
            holdout[split_name] = (None if split is None else evaluate(
                model, split, output_path=output_dir / f"{split_name}_predictions.npz"))
        summary = dict(request=request, selection=selection, candidates=candidates,
                        holdout=holdout, access_log=access_log, counts=model.counts(),
                        selected_model_config=model.config,
                        holdout_cpu_seconds=time.process_time() - holdout_start,
                        total_cpu_seconds=time.process_time() - process_start,
                        total_wall_seconds=time.perf_counter() - wall_start,
                        process_peak_rss_bytes=_peak_rss_bytes(),
                        memory_measurement="whole_process_high_water_mark_not_model_allocation",
                        energy_measured=False, status="completed")
        _write_json(output_dir / "summary.json", summary)
        return summary
    except Exception as error:
        _write_json(output_dir / "failure.json", dict(error_type=type(error).__name__,
                    error=str(error), traceback=traceback.format_exc(), request=request,
                    access_log=access_log, total_cpu_seconds=time.process_time() - process_start,
                    total_wall_seconds=time.perf_counter() - wall_start))
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", required=True)
    parser.add_argument("--model", choices=MODEL_NAMES, required=True)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--cpu-seconds", type=float, default=20.0)
    parser.add_argument("--width", type=int, default=32)
    parser.add_argument("--depth", type=int, default=1)
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--max-updates", type=int, default=8192)
    args = parser.parse_args()
    summary = run_search(args.data, args.model, args.seed, args.output,
                          args.cpu_seconds, args.width, args.depth,
                          args.batch_size, args.max_updates)
    print(json.dumps(dict(status=summary["status"], model=args.model, seed=args.seed,
                          selection=summary["selection"], holdout=summary["holdout"]), sort_keys=True))


if __name__ == "__main__":
    main()
