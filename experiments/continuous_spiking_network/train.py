"""Actual matched-data optimization, checkpoint reload and blind test scoring."""

import argparse
import json
from pathlib import Path
import time
import traceback

import numpy as np
import torch
from torch.nn import functional as F

from .data import load_data
from .models import SequenceClassifier
from .records import (
    checkpoint_load,
    checkpoint_save,
    digest_bytes,
    environment,
    source_seal,
    write_json,
)


def tensors(split):
    return (
        torch.from_numpy(split.x),
        torch.from_numpy(split.dt),
        torch.from_numpy(split.y),
    )


def evaluate(model, split, batch_size=64):
    x, dt, labels = tensors(split)
    outputs = []
    model.eval()
    with torch.no_grad():
        for start in range(0, len(labels), batch_size):
            logits, _ = model(
                x[start : start + batch_size], dt[start : start + batch_size]
            )
            outputs.append(logits)
    logits = torch.cat(outputs)
    probabilities = logits.softmax(-1)
    correct = logits.argmax(-1).eq(labels)
    result = {
        "accuracy": correct.float().mean().item(),
        "cross_entropy": F.cross_entropy(logits, labels).item(),
        "brier": ((probabilities - F.one_hot(labels, logits.shape[-1])) ** 2)
        .sum(-1)
        .mean()
        .item(),
        "cases": len(labels),
    }
    if "query_modalities" in split.metadata:
        for modality in ("image", "spoken"):
            mask = np.array(split.metadata["query_modalities"]) == modality
            if mask.any():
                result[f"{modality}_accuracy"] = (
                    correct[torch.from_numpy(mask)].float().mean().item()
                )
        images = np.array(split.metadata["image_labels"])
        audio = np.array(split.metadata["audio_labels"])
        conflict = (images >= 0) & (audio >= 0) & (images != audio)
        if conflict.any():
            result["conflict_accuracy"] = (
                correct[torch.from_numpy(conflict)].float().mean().item()
            )
    return result, logits.numpy()


def fit(spec, output, cache_dir, enforce_seal=True):
    package = Path(__file__).parent
    seal = source_seal(package) if enforce_seal else "unsealed-development"
    output = Path(output)
    if (output / "RESULT.json").exists():
        raise FileExistsError("completed results must not be overwritten")
    output.mkdir(parents=True, exist_ok=True)
    write_json(
        output / "START.json",
        {
            "spec": spec,
            "source_seal": seal,
            "environment": environment(),
            "started_unix": time.time(),
        },
    )
    start_cpu, start_wall = time.process_time(), time.perf_counter()
    bundle = load_data(
        spec["task"],
        train_size=spec["train_size"],
        val_size=spec.get("val_size", 512),
        test_size=spec.get("test_size", 1024),
        context_length=spec["length"],
        seed=spec.get("data_seed", 7123),
        cache_dir=cache_dir,
    )
    prepare_cpu = time.process_time() - start_cpu
    write_json(output / "DATA.json", bundle.manifest)
    sources = {}
    for split_name in ("train", "val", "test"):
        split = getattr(bundle, split_name)
        sources[f"{split_name}_sample_ids"] = split.sample_ids
        sources[f"{split_name}_group_ids"] = split.group_ids
        for key in (
            "image_source_ids",
            "audio_source_ids",
            "query_modalities",
            "image_labels",
            "audio_labels",
        ):
            if key in split.metadata:
                sources[f"{split_name}_{key}"] = np.asarray(split.metadata[key])
    np.savez_compressed(output / "split_sources.npz", **sources)
    torch.manual_seed(spec["seed"])
    model = SequenceClassifier(
        bundle.input_dim,
        bundle.num_classes,
        spec["width"],
        spec.get("depth", 1),
        spec["architecture"],
        spec["seed"],
        spec.get("match_cell_budget", False),
    )
    counts = model.counts()
    decay, no_decay = [], []
    for parameter in model.parameters():
        if parameter.requires_grad:
            group = (
                no_decay
                if parameter.ndim < 2 or getattr(parameter, "_no_weight_decay", False)
                else decay
            )
            group.append(parameter)
    optimizer = torch.optim.AdamW(
        [
            {"params": decay, "weight_decay": 0.0001},
            {"params": no_decay, "weight_decay": 0.0},
        ],
        lr=spec.get("lr", 0.003),
    )
    x, dt, y = tensors(bundle.train)
    generator = torch.Generator().manual_seed(spec["seed"] + 777)
    batch_size = spec.get("batch_size", 32)
    batches = torch.randint(len(y), (spec["updates"], batch_size), generator=generator)
    np.savez_compressed(output / "batch_indices.npz", indices=batches.numpy())
    history, gradients = [], {}
    best, best_step = float("inf"), 0
    train_cpu, train_wall, validation_cpu = 0.0, 0.0, 0.0
    checkpoints = sorted(
        set(
            [
                max(1, spec["updates"] // 4),
                max(1, spec["updates"] // 2),
                spec["updates"],
            ]
        )
    )
    losses = []
    for update, ids in enumerate(batches, start=1):
        model.train()
        cpu, wall = time.process_time(), time.perf_counter()
        optimizer.zero_grad(set_to_none=True)
        logits, _ = model(x[ids], dt[ids])
        loss = F.cross_entropy(logits, y[ids])
        if not torch.isfinite(loss):
            raise FloatingPointError(f"nonfinite loss at update {update}")
        loss.backward()
        if update == 1:
            gradients = {
                name: {
                    "l1": p.grad.abs().sum().item() if p.grad is not None else None,
                    "finite": bool(torch.isfinite(p.grad).all())
                    if p.grad is not None
                    else False,
                }
                for name, p in model.named_parameters()
                if p.requires_grad
            }
        grad_norm = torch.nn.utils.clip_grad_norm_(
            model.parameters(), 1.0, error_if_nonfinite=True
        )
        optimizer.step()
        train_cpu += time.process_time() - cpu
        train_wall += time.perf_counter() - wall
        losses.append(loss.item())
        if update in checkpoints:
            cpu = time.process_time()
            validation, _ = evaluate(model, bundle.val)
            validation_cpu += time.process_time() - cpu
            history.append(
                {
                    "update": update,
                    "train_loss": float(np.mean(losses)),
                    "last_grad_norm": grad_norm.item(),
                    "validation": validation,
                    "training_cpu_seconds": train_cpu,
                    "training_wall_seconds": train_wall,
                }
            )
            losses.clear()
            if validation["cross_entropy"] < best:
                best, best_step = validation["cross_entropy"], update
                checkpoint_save(model, output / "checkpoint", {"selected_step": update})
    checkpoint_load(model, output / "checkpoint")
    model.eval()
    with torch.no_grad():
        anchor = model(x[:4], dt[:4])[0]
    reloaded = SequenceClassifier(**model.config)
    checkpoint_load(reloaded, output / "checkpoint")
    reloaded.eval()
    with torch.no_grad():
        reload_error = (reloaded(x[:4], dt[:4])[0] - anchor).abs().max().item()
    if reload_error != 0:
        raise ValueError(f"checkpoint reload changed predictions: {reload_error}")
    # Test labels are scored only after all fitting and validation selection ends.
    cpu, wall = time.process_time(), time.perf_counter()
    test, logits = evaluate(reloaded, bundle.test)
    test_cpu, test_wall = time.process_time() - cpu, time.perf_counter() - wall
    np.savez_compressed(
        output / "predictions.npz",
        logits=logits,
        labels=bundle.test.y,
        sample_ids=bundle.test.sample_ids,
        group_ids=bundle.test.group_ids,
    )
    if enforce_seal and source_seal(package) != seal:
        raise ValueError("source changed while the experiment was running")
    result = {
        "spec": spec,
        "source_seal": seal,
        "parameters": counts,
        "test": test,
        "history": history,
        "selected_step": best_step,
        "checkpoint_reload_max_error": reload_error,
        "gradient_groups": gradients,
        "checkpoint_manifest_sha256": digest_bytes(
            (output / "checkpoint/manifest.json").read_bytes()
        ),
        "split_sources_sha256": digest_bytes(
            (output / "split_sources.npz").read_bytes()
        ),
        "checkpoint_scope": "exact model state for inference; optimizer is not retained",
        "training_examples_seen": int(batches.numel()),
        "unique_training_examples_seen": int(batches.unique().numel()),
        "training_sequence_positions": int(batches.numel() * spec["length"]),
        "prepare_cpu_seconds": prepare_cpu,
        "training_cpu_seconds": train_cpu,
        "training_wall_seconds": train_wall,
        "validation_cpu_seconds": validation_cpu,
        "test_cpu_seconds": test_cpu,
        "test_wall_seconds": test_wall,
        "total_cpu_seconds": time.process_time() - start_cpu,
        "total_wall_seconds": time.perf_counter() - start_wall,
        "timing_scope": "includes preparation, fitting, validation, serialization, reload and test; installation excluded",
        "environment": environment(),
    }
    write_json(output / "RESULT.json", result)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--spec", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--cache-dir", required=True)
    parser.add_argument("--development", action="store_true")
    args = parser.parse_args()
    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
    try:
        result = fit(
            json.loads(Path(args.spec).read_text()),
            args.output,
            args.cache_dir,
            not args.development,
        )
        print(
            json.dumps(
                {
                    "output": args.output,
                    "accuracy": result["test"]["accuracy"],
                    "cpu": result["total_cpu_seconds"],
                }
            ),
            flush=True,
        )
    except Exception:
        write_json(
            Path(args.output) / "FAILED.json",
            {"traceback": traceback.format_exc(), "time": time.time()},
        )
        raise


if __name__ == "__main__":
    main()
