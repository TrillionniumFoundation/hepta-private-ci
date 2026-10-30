"""Paired causal stopping policies on one genuinely trained HCSN actor."""

import argparse
import json
from pathlib import Path
import time

import numpy as np
import torch
from torch.nn import functional as F

from .boundary import FiniteHorizonStoppingBoundary, StoppingPolicy
from .models import SequenceClassifier
from .records import (
    checkpoint_load,
    checkpoint_save,
    digest_bytes,
    environment,
    source_seal,
    write_json,
)


FIXED_GRID = (
    0.5001,
    0.55,
    0.60,
    0.65,
    0.70,
    0.75,
    0.80,
    0.85,
    0.90,
    0.925,
    0.95,
    0.975,
    0.99,
    0.999,
)
PROTOCOL = {
    "train_size": 2048,
    "validation_size": 512,
    "test_id_size": 512,
    "test_ood_size": 512,
    "train_snr": [0.25, 0.5, 0.8],
    "train_cost": [0.005, 0.025, 0.08],
    "train_horizon": 16,
    "ood_snr": [0.15, 0.35, 0.7, 1.1],
    "ood_cost": [0.01, 0.04, 0.12],
    "ood_horizon": 24,
    "actor_width": 24,
    "actor_updates": 240,
    "actor_batch_size": 32,
    "actor_lr": 0.003,
    "direct_updates": 100,
    "direct_lr": 0.03,
    "temperature": 0.02,
    "bellman_grid": 257,
    "teacher": "none; actor uses prefix cross-entropy only",
}


def make_episodes(n, horizon, snrs, costs, seed, name):
    """The label controls observation generation and never enters actor inputs."""
    rng = np.random.default_rng(seed)
    contexts = np.array([(s, c) for s in snrs for c in costs], dtype=np.float32)
    selected = np.arange(n) % len(contexts)
    rng.shuffle(selected)
    snr, cost = (torch.from_numpy(contexts[selected, i].copy()) for i in (0, 1))
    labels = np.arange(n) % 2
    rng.shuffle(labels)
    labels = torch.from_numpy(labels.astype(np.int64))
    observations = torch.from_numpy(rng.normal(size=(n, horizon)).astype(np.float32))
    observations = observations + (2 * labels[:, None] - 1) * snr[:, None]
    remaining = torch.arange(horizon - 1, -1, -1).expand(n, -1)
    x = torch.stack(
        (
            observations,
            snr[:, None].expand_as(observations),
            cost[:, None].expand_as(observations),
            remaining / 24.0,
        ),
        dim=-1,
    )
    return {
        "x": x,
        "dt": torch.ones(n, horizon),
        "label": labels,
        "snr": snr,
        "cost": cost,
        "remaining_steps": remaining,
        "observations": observations,
        "bayes_log_odds": (2 * snr[:, None] * observations).cumsum(1),
        "episode_id": np.array([f"{name}:{seed}:{i}" for i in range(n)]),
    }


def prefix_log_odds(model, batch, batch_size=64):
    model.eval()
    values = []
    with torch.no_grad():
        for start in range(0, len(batch["label"]), batch_size):
            logits, _ = model(
                batch["x"][start : start + batch_size],
                batch["dt"][start : start + batch_size],
                return_sequence=True,
            )
            values.append(logits[..., 1] - logits[..., 0])
    return torch.cat(values)


def train_actor(train, validation, seed, output, updates=240, width=24):
    """Small configurable helper is also used by non-formal unit fixtures."""
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    started = time.process_time(), time.perf_counter()
    model = SequenceClassifier(4, 2, width, 1, "hcsn", seed)
    optimizer = torch.optim.AdamW(model.parameters(), lr=0.003, weight_decay=0.0001)
    generator = torch.Generator().manual_seed(seed + 1777)
    batches = torch.randint(len(train["label"]), (updates, 32), generator=generator)
    np.savez_compressed(output / "actor_batch_indices.npz", indices=batches.numpy())
    checkpoints = {max(1, updates // 4), max(1, updates // 2), updates}
    best, selected_step, history, gradients = float("inf"), 0, [], {}
    training_cpu, validation_cpu = 0.0, 0.0
    for step, ids in enumerate(batches, 1):
        cpu = time.process_time()
        model.train()
        optimizer.zero_grad(set_to_none=True)
        logits, _ = model(train["x"][ids], train["dt"][ids], return_sequence=True)
        target = train["label"][ids, None].expand(logits.shape[:2])
        loss = F.cross_entropy(logits.reshape(-1, 2), target.reshape(-1))
        loss.backward()
        if step == 1:
            gradients = {
                name: {
                    "l1": float(p.grad.abs().sum()) if p.grad is not None else None,
                    "finite": bool(torch.isfinite(p.grad).all())
                    if p.grad is not None
                    else False,
                }
                for name, p in model.named_parameters()
                if p.requires_grad
            }
        torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0, error_if_nonfinite=True)
        optimizer.step()
        training_cpu += time.process_time() - cpu
        if step in checkpoints:
            cpu = time.process_time()
            odds = prefix_log_odds(model, validation)
            target = validation["label"][:, None].expand_as(odds).float()
            val_loss = float(F.binary_cross_entropy_with_logits(odds, target))
            validation_cpu += time.process_time() - cpu
            history.append(
                {
                    "step": step,
                    "train_prefix_ce": float(loss.detach()),
                    "validation_prefix_ce": val_loss,
                }
            )
            if val_loss < best:
                best, selected_step = val_loss, step
                checkpoint_save(
                    model, output / "actor_checkpoint", {"selected_step": step}
                )
    checkpoint_load(model, output / "actor_checkpoint")
    model.eval()
    reloaded = SequenceClassifier(**model.config)
    checkpoint_load(reloaded, output / "actor_checkpoint")
    reloaded.eval()
    with torch.no_grad():
        args = (train["x"][:4], train["dt"][:4])
        error = float(
            (
                model(*args, return_sequence=True)[0]
                - reloaded(*args, return_sequence=True)[0]
            )
            .abs()
            .max()
        )
    if error != 0:
        raise ValueError("actor checkpoint reload changed prefix predictions")
    return reloaded, {
        "selected_step": selected_step,
        "history": history,
        "gradient_groups": gradients,
        "parameters": model.counts(),
        "checkpoint_reload_max_error": error,
        "checkpoint_manifest_sha256": digest_bytes(
            (output / "actor_checkpoint/manifest.json").read_bytes()
        ),
        "training_examples_seen": int(batches.numel()),
        "training_cpu_seconds": training_cpu,
        "validation_cpu_seconds": validation_cpu,
        "fit_cpu_seconds": time.process_time() - started[0],
        "fit_wall_seconds": time.perf_counter() - started[1],
    }


def stop_record(log_odds, mask, batch):
    """Execute first stop; index zero still incurs the first observation cost."""
    mask = mask.clone()
    mask[:, -1] = True
    index = mask.to(torch.int64).argmax(1)
    action = (log_odds.gather(1, index[:, None]).squeeze(1) >= 0).long()
    correct = action == batch["label"]
    count = index + 1
    cost = batch["cost"].double() * count
    return {
        "stop_index": index,
        "action": action,
        "correct": correct,
        "observations": count,
        "total_cost": cost,
        "net_utility": correct.double() - cost,
        "stop_mask": mask,
    }


def select_fixed(log_odds, validation):
    scores = []
    for threshold in FIXED_GRID:
        result = stop_record(
            log_odds, log_odds.abs().sigmoid() >= threshold, validation
        )
        scores.append(float(result["net_utility"].mean()))
    selected = max(range(len(scores)), key=lambda i: scores[i])
    return FIXED_GRID[selected], {
        "threshold": FIXED_GRID[selected],
        "grid": list(FIXED_GRID),
        "validation_scores": scores,
        "tie_rule": "first grid entry",
    }


def fit_direct(log_odds, train, updates=100):
    policy = StoppingPolicy("direct", threshold=0.85)
    optimizer = torch.optim.Adam(policy.parameters(), lr=0.03)
    correct = ((log_odds >= 0).long() == train["label"][:, None]).float()
    counts = torch.arange(1, log_odds.shape[1] + 1)
    utility = correct - train["cost"][:, None] * counts
    objectives, gradient_groups = [], {}
    for step in range(updates):
        optimizer.zero_grad(set_to_none=True)
        result = policy(
            log_odds.detach(),
            train["remaining_steps"],
            train["snr"][:, None],
            train["cost"][:, None],
        )
        probability = result["stop_probability"]
        reach = torch.cat(
            (torch.ones_like(probability[:, :1]), (1 - probability).cumprod(1)[:, :-1]),
            dim=1,
        )
        objective = (reach * probability * utility).sum(1).mean()
        (-objective).backward()
        if step == 0:
            gradient_groups = {
                name: float(p.grad.abs().sum()) for name, p in policy.named_parameters()
            }
        optimizer.step()
        objectives.append(float(objective.detach()))
    return policy, {
        "parameters": {
            name: p.detach().tolist() for name, p in policy.named_parameters()
        },
        "updates": updates,
        "temperature": 0.02,
        "initial_soft_utility": objectives[0],
        "last_soft_utility_before_update": objectives[-1],
        "gradient_groups": gradient_groups,
    }


def value_mask(log_odds, batch, solver, cache, timing):
    mask = torch.empty_like(log_odds, dtype=torch.bool)
    contexts = torch.stack((batch["snr"], batch["cost"]), dim=1)
    horizon = log_odds.shape[1]
    for context in torch.unique(contexts, dim=0):
        rows = (contexts == context).all(1)
        key = (float(context[0]), float(context[1]), horizon)
        if key not in cache:
            cpu = time.process_time()
            cache[key] = solver.table(
                context[:1].double(), context[1:].double(), horizon - 1
            )
            timing["bellman_build_cpu_seconds"] += time.process_time() - cpu
        cpu = time.process_time()
        result = solver.evaluate(
            log_odds[rows].double().reshape(-1),
            batch["remaining_steps"][rows].reshape(-1),
            cache[key],
        )
        mask[rows] = result["stop"].reshape(-1, horizon)
        timing["bellman_evaluation_cpu_seconds"] += time.process_time() - cpu
    return mask


def run(seed, output, enforce_seal=True):
    output = Path(output)
    if (output / "RESULT.json").exists():
        raise FileExistsError("completed boundary results must not be overwritten")
    output.mkdir(parents=True, exist_ok=True)
    package = Path(__file__).parent
    seal = source_seal(package) if enforce_seal else "unsealed-development"
    started = time.process_time(), time.perf_counter()
    write_json(
        output / "START.json",
        {
            "kind": "boundary_study",
            "seed": seed,
            "protocol": PROTOCOL,
            "source_seal": seal,
            "environment": environment(),
        },
    )
    batches = {}
    for offset, name, size, ood in (
        (101, "train", 2048, False),
        (202, "validation", 512, False),
        (303, "id", 512, False),
        (404, "ood", 512, True),
    ):
        prefix = "ood" if ood else "train"
        batches[name] = make_episodes(
            size,
            PROTOCOL[f"{prefix}_horizon"],
            PROTOCOL[f"{prefix}_snr"],
            PROTOCOL[f"{prefix}_cost"],
            seed + offset,
            name,
        )
    actor, actor_receipt = train_actor(
        batches["train"], batches["validation"], seed, output
    )
    timing = {"bellman_build_cpu_seconds": 0.0, "bellman_evaluation_cpu_seconds": 0.0}
    cpu = time.process_time()
    odds = {name: prefix_log_odds(actor, batch) for name, batch in batches.items()}
    timing["all_prefix_actor_evaluation_cpu_seconds"] = time.process_time() - cpu
    cpu = time.process_time()
    threshold, fixed_receipt = select_fixed(odds["validation"], batches["validation"])
    timing["fixed_selection_cpu_seconds"] = time.process_time() - cpu
    cpu = time.process_time()
    direct, direct_receipt = fit_direct(odds["train"], batches["train"])
    timing["direct_training_cpu_seconds"] = time.process_time() - cpu
    solver, cache = FiniteHorizonStoppingBoundary(grid_size=257).double(), {}
    metrics, files = {}, []
    for name in ("id", "ood"):
        batch, learned = batches[name], odds[name]
        cpu = time.process_time()
        with torch.no_grad():
            masks = {
                "fixed": learned.abs().sigmoid() >= threshold,
                "direct": direct(
                    learned,
                    batch["remaining_steps"],
                    batch["snr"][:, None],
                    batch["cost"][:, None],
                )["stop"],
                "value": value_mask(learned, batch, solver, cache, timing),
                "oracle": value_mask(
                    batch["bayes_log_odds"], batch, solver, cache, timing
                ),
            }
        records = {
            arm: stop_record(
                batch["bayes_log_odds"] if arm == "oracle" else learned, mask, batch
            )
            for arm, mask in masks.items()
        }
        timing[f"{name}_policy_and_execution_cpu_seconds"] = time.process_time() - cpu
        metrics[name] = {
            arm: {
                "accuracy": float(record["correct"].float().mean()),
                "mean_observations": float(record["observations"].float().mean()),
                "mean_total_cost": float(record["total_cost"].mean()),
                "net_utility": float(record["net_utility"].mean()),
                "cases": len(learned),
            }
            for arm, record in records.items()
        }
        arrays = {
            key: batch[key].numpy()
            for key in (
                "label",
                "snr",
                "cost",
                "observations",
                "bayes_log_odds",
                "remaining_steps",
            )
        }
        arrays.update(
            {
                "episode_id": batch["episode_id"],
                "actor_log_odds": learned.numpy(),
                "horizon": np.full(len(learned), learned.shape[1], dtype=np.int64),
            }
        )
        arrays.update(
            {
                f"{arm}_{key}": value.numpy()
                for arm, record in records.items()
                for key, value in record.items()
            }
        )
        for start in range(0, len(learned), 128):
            path = output / f"episodes_{name}_{start // 128:03d}.npz"
            np.savez_compressed(
                path,
                **{key: value[start : start + 128] for key, value in arrays.items()},
            )
            files.append(
                {
                    "file": path.name,
                    "sha256": digest_bytes(path.read_bytes()),
                    "split": name,
                    "cases": min(128, len(learned) - start),
                }
            )
    if enforce_seal and source_seal(package) != seal:
        raise ValueError("source changed while the boundary study was running")
    result = {
        "kind": "boundary_study",
        "seed": seed,
        "source_seal": seal,
        "protocol": PROTOCOL,
        "actor": actor_receipt,
        "fixed": fixed_receipt,
        "direct": direct_receipt,
        "metrics": metrics,
        "episode_files": files,
        "timing": timing,
        "first_observation_charged": True,
        "bayes_teacher": False,
        "bellman_tables": len(cache),
        "environment": environment(),
        "total_cpu_seconds": time.process_time() - started[0],
        "total_wall_seconds": time.perf_counter() - started[1],
        "cost_scope": "Offline all-prefix actor execution; saved observation costs are task utility, not measured owner cancellation or energy savings.",
    }
    write_json(output / "RESULT.json", result)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--development", action="store_true")
    args = parser.parse_args()
    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
    result = run(args.seed, args.output, not args.development)
    print(json.dumps({"output": args.output, "metrics": result["metrics"]}), flush=True)


if __name__ == "__main__":
    main()
