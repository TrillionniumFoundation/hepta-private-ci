"""Validation-only learning-rate search under measured training CPU budgets.

The data and update stream are deterministic; the number of updates fitting a
CPU budget is machine-dependent. A final indivisible step may overshoot the
budget and that measured overshoot is retained. Validation, serialization and
all search overhead are charged separately and included in total run cost.
"""

import argparse
import json
import math
from pathlib import Path
import time
import traceback

import numpy as np
import torch
from torch.nn import functional as F

from experiments.continuous_spiking_network import records
from experiments.continuous_spiking_network.data import load_data
from experiments.continuous_spiking_network.models import SequenceClassifier
from experiments.continuous_spiking_network.train import evaluate, tensors

from .budget_io import source_arrays, write_arrays


def validate_spec(spec):
    rates = spec["learning_rates"]
    fractions = spec["cpu_milestone_fractions"]
    if len(rates) != 2 or len(set(rates)) != 2:
        raise ValueError("exactly two distinct learning rates are required")
    if not all(math.isfinite(rate) and rate > 0 for rate in rates):
        raise ValueError("learning rates must be finite and positive")
    budget = spec["candidate_cpu_seconds"]
    if not math.isfinite(budget) or budget <= 0:
        raise ValueError("candidate CPU budget must be finite and positive")
    if (
        not fractions
        or sorted(set(fractions)) != fractions
        or fractions[-1] != 1.0
        or not all(math.isfinite(value) and 0 < value <= 1 for value in fractions)
    ):
        raise ValueError("CPU milestone fractions must increase and end at one")
    for name in ("max_updates", "batch_size", "train_size", "width", "length"):
        if not isinstance(spec[name], int) or spec[name] < 1:
            raise ValueError(f"{name} must be a positive integer")
    if "seed" not in spec or "data_seed" not in spec:
        raise ValueError("optimization and data seeds must be explicit")


def current_seals(enforce_seal):
    if not enforce_seal:
        return {"followup": "unsealed-development", "base": "unsealed-development"}
    return {
        "followup": records.source_seal(Path(__file__).parent),
        "base": records.source_seal(Path(records.__file__).parent),
    }


def _optimizer(model, learning_rate):
    decay, no_decay = [], []
    for parameter in model.parameters():
        if parameter.requires_grad:
            target = (
                no_decay
                if (parameter.ndim < 2 or getattr(parameter, "_no_weight_decay", False))
                else decay
            )
            target.append(parameter)
    return torch.optim.AdamW(
        [
            {"params": decay, "weight_decay": 0.0001},
            {"params": no_decay, "weight_decay": 0.0},
        ],
        lr=learning_rate,
    )


def fit_candidate(spec, bundle, directory, index):
    directory = Path(directory)
    cpu_start, wall_start = time.process_time(), time.perf_counter()
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
    optimizer = _optimizer(model, spec["learning_rates"][index])
    x, dt, y = tensors(bundle.train)
    initialization_cpu = time.process_time() - cpu_start
    generator = torch.Generator().manual_seed(spec["seed"] + 777)
    budget = spec["candidate_cpu_seconds"]
    pending = list(spec["cpu_milestone_fractions"])
    costs = {
        key: 0.0
        for key in (
            "training_cpu",
            "training_wall",
            "validation_cpu",
            "validation_wall",
            "serialization_cpu",
            "serialization_wall",
            "reload_cpu",
            "reload_wall",
        )
    }
    history, batches, updates, gradients = [], [], [], {}
    best_ce, best_update, best_anchor = float("inf"), None, None
    anchor_size = min(64, len(bundle.val))
    for update in range(1, spec["max_updates"] + 1):
        cpu, wall = time.process_time(), time.perf_counter()
        ids = torch.randint(len(y), (spec["batch_size"],), generator=generator)
        batches.append(ids.numpy())
        model.train()
        optimizer.zero_grad(set_to_none=True)
        logits, _ = model(x[ids], dt[ids])
        loss = F.cross_entropy(logits, y[ids])
        if not torch.isfinite(loss):
            raise FloatingPointError("nonfinite training loss")
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
        loss_value, grad_value = loss.item(), grad_norm.item()
        step_cpu, step_wall = time.process_time() - cpu, time.perf_counter() - wall
        costs["training_cpu"] += step_cpu
        costs["training_wall"] += step_wall
        updates.append((loss_value, grad_value, step_cpu, step_wall))
        crossed = []
        while pending and costs["training_cpu"] >= budget * pending[0]:
            crossed.append(pending.pop(0))
        final = costs["training_cpu"] >= budget or update == spec["max_updates"]
        if crossed or final:
            cpu, wall = time.process_time(), time.perf_counter()
            validation, validation_logits = evaluate(model, bundle.val)
            costs["validation_cpu"] += time.process_time() - cpu
            costs["validation_wall"] += time.perf_counter() - wall
            row = {
                "update": update,
                "examples_seen": update * spec["batch_size"],
                "training_cpu_seconds": costs["training_cpu"],
                "training_wall_seconds": costs["training_wall"],
                "crossed_milestone_fractions": crossed,
                "validation": validation,
                "last_train_loss": loss_value,
                "last_gradient_norm": grad_value,
                "final": final,
            }
            history.append(row)
            if validation["cross_entropy"] < best_ce:
                best_ce, best_update = validation["cross_entropy"], update
                best_anchor = validation_logits[:anchor_size].copy()
                cpu, wall = time.process_time(), time.perf_counter()
                records.checkpoint_save(
                    model,
                    directory / "checkpoint",
                    {
                        "candidate_index": index,
                        "selected_update": update,
                        "selected_validation_ce": best_ce,
                        "training_cpu_seconds": costs["training_cpu"],
                    },
                )
                costs["serialization_cpu"] += time.process_time() - cpu
                costs["serialization_wall"] += time.perf_counter() - wall
        if final:
            break
    cpu, wall = time.process_time(), time.perf_counter()
    clone = SequenceClassifier(**model.config)
    records.checkpoint_load(clone, directory / "checkpoint")
    clone.eval()
    with torch.no_grad():
        restored = clone(
            torch.from_numpy(bundle.val.x[:anchor_size]),
            torch.from_numpy(bundle.val.dt[:anchor_size]),
        )[0].numpy()
    reload_error = float(np.max(np.abs(restored - best_anchor)))
    if reload_error != 0:
        raise ValueError("candidate checkpoint changed validation anchor logits")
    costs["reload_cpu"] += time.process_time() - cpu
    costs["reload_wall"] += time.perf_counter() - wall
    cpu, wall = time.process_time(), time.perf_counter()
    evidence_hash = write_arrays(
        directory / "arrays",
        {
            "batch_indices": np.stack(batches),
            "update_records": np.asarray(updates, dtype=np.float64),
            "validation_anchor_logits": best_anchor,
            "validation_anchor_sample_ids": bundle.val.sample_ids[:anchor_size],
        },
    )
    costs["serialization_cpu"] += time.process_time() - cpu
    costs["serialization_wall"] += time.perf_counter() - wall
    result = {
        "candidate_index": index,
        "learning_rate": spec["learning_rates"][index],
        "model_config": model.config,
        "parameters": model.counts(),
        "cpu_budget_seconds": budget,
        "updates_completed": len(updates),
        "examples_seen": len(updates) * spec["batch_size"],
        "unique_examples_seen": int(np.unique(np.stack(batches)).size),
        "sequence_positions": len(updates) * spec["batch_size"] * spec["length"],
        "minibatch_rng_seed": spec["seed"] + 777,
        "budget_exhausted": costs["training_cpu"] >= budget,
        "cpu_budget_overshoot_seconds": max(0.0, costs["training_cpu"] - budget),
        "last_update_cpu_seconds": updates[-1][2],
        "termination": "cpu_budget"
        if costs["training_cpu"] >= budget
        else "max_updates",
        "history": history,
        "selected_update": best_update,
        "selected_validation_ce": best_ce,
        "gradient_groups": gradients,
        "checkpoint_reload_max_error": reload_error,
        "checkpoint_manifest_sha256": records.digest_bytes(
            (directory / "checkpoint/manifest.json").read_bytes()
        ),
        "arrays_manifest_sha256": evidence_hash,
        "update_record_columns": [
            "loss",
            "gradient_norm",
            "cpu_seconds",
            "wall_seconds",
        ],
        "costs_seconds": costs,
        "initialization_cpu_seconds": initialization_cpu,
        "total_cpu_seconds": time.process_time() - cpu_start,
        "total_wall_seconds": time.perf_counter() - wall_start,
        "checkpoint_scope": "inference model state; optimizer/RNG continuation not retained",
    }
    records.write_json(directory / "RESULT.json", result)
    return result


def _execute(spec, output, cache_dir, seals):
    cpu_start, wall_start = time.process_time(), time.perf_counter()
    bundle = load_data(
        spec["task"],
        train_size=spec["train_size"],
        val_size=spec.get("val_size", 256),
        test_size=spec.get("test_size", 512),
        context_length=spec["length"],
        seed=spec["data_seed"],
        cache_dir=cache_dir,
    )
    prepare_cpu = time.process_time() - cpu_start
    prepare_wall = time.perf_counter() - wall_start
    cpu, wall = time.process_time(), time.perf_counter()
    records.write_json(output / "DATA.json", bundle.manifest)
    sources_hash = write_arrays(output / "sources", source_arrays(bundle))
    data_record_cpu, data_record_wall = (
        time.process_time() - cpu,
        time.perf_counter() - wall,
    )
    candidates = [
        fit_candidate(spec, bundle, output / "candidates" / f"{index:02d}", index)
        for index in range(len(spec["learning_rates"]))
    ]
    chosen = min(
        range(len(candidates)),
        key=lambda i: (candidates[i]["selected_validation_ce"], i),
    )
    checkpoint = f"candidates/{chosen:02d}/checkpoint"
    selection = {
        "candidate_index": chosen,
        "learning_rate": spec["learning_rates"][chosen],
        "criterion": "minimum validation CE across all recorded candidate checkpoints; tie uses candidate order",
        "selected_validation_ce": candidates[chosen]["selected_validation_ce"],
        "selected_update": candidates[chosen]["selected_update"],
        "selected_checkpoint": checkpoint,
        "test_evaluations_before_selection": 0,
    }
    records.write_json(output / "SELECTION.json", selection)
    cpu, wall = time.process_time(), time.perf_counter()
    model = SequenceClassifier(**candidates[chosen]["model_config"])
    records.checkpoint_load(model, output / checkpoint)
    selected_reload_cpu, selected_reload_wall = (
        time.process_time() - cpu,
        time.perf_counter() - wall,
    )
    cpu, wall = time.process_time(), time.perf_counter()
    test, logits = evaluate(model, bundle.test)
    test_cpu, test_wall = time.process_time() - cpu, time.perf_counter() - wall
    cpu, wall = time.process_time(), time.perf_counter()
    prediction_hash = write_arrays(
        output / "predictions",
        {
            "logits": logits,
            "labels": bundle.test.y,
            "sample_ids": bundle.test.sample_ids,
            "group_ids": bundle.test.group_ids,
        },
    )
    prediction_cpu, prediction_wall = (
        time.process_time() - cpu,
        time.perf_counter() - wall,
    )
    training_cpu = sum(row["costs_seconds"]["training_cpu"] for row in candidates)
    return {
        "spec": spec,
        "source_seals": seals,
        "environment": records.environment(),
        "selection": selection,
        "selected_checkpoint": checkpoint,
        "parameters": candidates[chosen]["parameters"],
        "test": test,
        "candidates": candidates,
        "sources_manifest_sha256": sources_hash,
        "predictions_manifest_sha256": prediction_hash,
        "training_cpu_seconds": training_cpu,
        "costs_seconds": {
            "preparation_cpu": prepare_cpu,
            "preparation_wall": prepare_wall,
            "data_record_cpu": data_record_cpu,
            "data_record_wall": data_record_wall,
            "candidate_totals_cpu": sum(row["total_cpu_seconds"] for row in candidates),
            "candidate_totals_wall": sum(
                row["total_wall_seconds"] for row in candidates
            ),
            "selected_reload_cpu": selected_reload_cpu,
            "selected_reload_wall": selected_reload_wall,
            "test_cpu": test_cpu,
            "test_wall": test_wall,
            "prediction_record_cpu": prediction_cpu,
            "prediction_record_wall": prediction_wall,
        },
        "total_cpu_seconds": time.process_time() - cpu_start,
        "total_wall_seconds": time.perf_counter() - wall_start,
        "cost_scope": "all two-candidate search costs included; nested subtotals must not be added to totals",
        "timing_scope": "data preparation through prediction serialization; excludes interpreter/import, source checks and final RESULT write",
        "training_budget_scope": "minibatch draw, train mode, forward/loss/backward, gradient diagnostics/clipping and optimizer update; validation and checkpointing separately charged",
        "timing_reproducibility": "inputs and minibatch prefixes fixed; CPU-budget update counts depend on machine/runtime load",
    }


def fit_budget(spec, output, cache_dir, enforce_seal=True):
    """Run a fresh two-candidate search; preserve failure evidence on exceptions."""
    validate_spec(spec)
    output = Path(output)
    if (output / "START.json").exists() or (output / "RESULT.json").exists():
        raise FileExistsError(
            "preserve the previous attempt; use a fresh output directory"
        )
    seals = current_seals(enforce_seal)
    torch.set_num_threads(1)
    records.write_json(
        output / "START.json",
        {
            "spec": spec,
            "source_seals": seals,
            "environment": records.environment(),
            "started_unix": time.time(),
        },
    )
    try:
        result = _execute(spec, output, cache_dir, seals)
        if current_seals(enforce_seal) != seals:
            raise ValueError("scientific source changed during CPU-budget training")
        records.write_json(output / "RESULT.json", result)
        return result
    except Exception:
        records.write_json(
            output / "FAILED.json",
            {
                "traceback": traceback.format_exc(),
                "time": time.time(),
                "source_seals_at_start": seals,
            },
        )
        raise


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--spec", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--cache-dir", required=True)
    parser.add_argument("--development", action="store_true")
    args = parser.parse_args()
    torch.set_num_interop_threads(1)
    result = fit_budget(
        json.loads(Path(args.spec).read_text()),
        args.output,
        args.cache_dir,
        enforce_seal=not args.development,
    )
    print(
        json.dumps(
            {
                "output": args.output,
                "test": result["test"],
                "training_cpu_seconds": result["training_cpu_seconds"],
            }
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
