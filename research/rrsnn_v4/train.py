"""Frozen-protocol training and validation; no evaluation split is loaded."""

import argparse
import copy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import resource
import shutil
import time

import numpy as np
import torch

from .models import make_policy, set_nll_per_decision, training_objective

ROOT = Path(__file__).resolve().parent
PROTOCOL = ROOT / "experiment_protocol.json"
MINIMUM_FREE_BYTES = 200 * 1024 * 1024


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def atomic_json(path, value):
    path = Path(path)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False)+"\n")
    temporary.replace(path)


def memory_snapshot():
    result = {"disk_free_bytes": shutil.disk_usage(ROOT).free}
    for name in ("memory.events", "memory.current", "memory.max", "memory.stat"):
        try:
            text = (Path("/sys/fs/cgroup") / name).read_text().strip()
            if name in ("memory.events", "memory.stat"):
                fields = {line.split()[0]: int(line.split()[1]) for line in text.splitlines()}
                if name == "memory.stat":
                    fields = {k: v for k, v in fields.items() if k in
                              ("anon", "file", "pgfault", "pgmajfault", "pgscan", "pgsteal")}
                result[name] = fields
            else:
                result[name] = text if text == "max" else int(text)
        except (OSError, ValueError) as error:
            result[name] = None
            result[name+"_error"] = str(error)
    return result


def check_disk():
    available = shutil.disk_usage(ROOT).free
    if available < MINIMUM_FREE_BYTES:
        raise RuntimeError(f"disk guard: {available} bytes free, need {MINIMUM_FREE_BYTES}; no files deleted")
    return available


def resource_quality(before, after):
    a, b = before.get("memory.events"), after.get("memory.events")
    if a is None or b is None:
        return {"status": "unknown", "limit_event_deltas": None}
    deltas = {key: b.get(key, 0)-a.get(key, 0) for key in ("max", "oom", "oom_kill")}
    pressure = any(value > 0 for value in deltas.values())
    return {"status": "shared_cgroup_pressure_observed" if pressure else "no_new_cgroup_limit_event_observed",
            "limit_event_deltas": deltas, "attributed_to_this_model": False}


def verify_protocol():
    protocol = json.loads(PROTOCOL.read_text())
    if not (ROOT / "pre_data_freeze.json").exists():
        raise RuntimeError("pre-data source freeze missing")
    if not protocol.get("frozen_files"):
        raise RuntimeError("frozen source/data manifest missing")
    for name, expected in protocol["frozen_files"].items():
        if name.startswith("data/") and name not in (
                "data/train.npz", "data/validation.npz", "data/manifest.json"):
            raise RuntimeError("trainer cannot open a heldout data artifact")
        if sha256(ROOT / name) != expected:
            raise RuntimeError(f"frozen source/data mismatch: {name}")
    for needed in ("train.py", "train_matrix.py", "models.py", "baselines.py", "task.py",
                   "data/train.npz", "data/validation.npz", "data/manifest.json"):
        if needed not in protocol["frozen_files"]:
            raise RuntimeError(f"required frozen identity missing: {needed}")
    return protocol, sha256(PROTOCOL)


def arrays(name):
    if name not in ("train", "validation"):
        raise ValueError("only training and validation are admitted here")
    with np.load(ROOT / "data" / (name+".npz"), allow_pickle=False) as archive:
        result = {k: torch.from_numpy(archive[k].copy()) for k in archive.files}
    required = {"x", "dt", "valid", "optimal", "decision", "lengths", "event_mask"}
    if not required.issubset(result):
        raise RuntimeError("incomplete supervised data")
    return result


@torch.no_grad()
def validation_loss(model, data, settings):
    model.eval()
    rng = np.random.default_rng(settings.get("validation_seed", 777001))
    total, decisions, spikes = 0., 0, 0
    draws = settings.get("validation_draws", 4) if model.is_stochastic else 1
    for _ in range(draws):
        for start in range(0, len(data["x"]), 128):
            ids = slice(start, start+128)
            length = int(data["lengths"][ids].max())
            output = model(data["x"][ids, :length], data["dt"][ids, :length],
                           event_mask=data["event_mask"][ids, :length], rng=rng)
            mask = data["decision"][ids, :length]
            losses = set_nll_per_decision(output["logits"], data["valid"][ids, :length], data["optimal"][ids, :length])
            total += float(losses[mask].sum())
            decisions += int(mask.sum())
            spikes += int(output["actual_counts"].sum())
    if not decisions or not np.isfinite(total):
        raise FloatingPointError("invalid validation loss")
    return {"nll": total/decisions, "actual_internal_spikes": spikes,
            "decision_draws": decisions, "path_draws": draws}


def completed_receipt(variant, seed, protocol_hash):
    destination = ROOT / "results" / variant / f"seed_{seed}"
    result = json.loads((destination / "training.json").read_text())
    if (result.get("status") != "completed" or result["protocol_sha256"] != protocol_hash
            or result.get("variant") != variant or result.get("seed") != seed):
        raise RuntimeError("incompatible completed training receipt")
    if result["checkpoint_sha256"] != sha256(destination / "model.pt"):
        raise RuntimeError("completed model identity mismatch")
    if result["initial_checkpoint_sha256"] != sha256(destination / "initial.pt"):
        raise RuntimeError("initial model identity mismatch")
    return result


def train_one(variant, seed):
    protocol, protocol_hash = verify_protocol()
    settings = protocol["training"]
    cpu_variants = protocol.get("cpu_matched_variants", {})
    if seed not in protocol["seeds"] or variant not in protocol["variants"]+list(cpu_variants):
        raise ValueError("run is outside the frozen matrix")
    torch.set_num_threads(1)
    try:
        torch.set_num_interop_threads(1)
    except RuntimeError:
        pass
    check_disk()
    destination = ROOT / "results" / variant / f"seed_{seed}"
    destination.mkdir(parents=True, exist_ok=True)
    if (destination / "training.json").exists():
        return completed_receipt(variant, seed, protocol_hash)
    cpu_target, reference_identity = None, None
    if variant in cpu_variants:
        reference = completed_receipt("rr_full", seed, protocol_hash)
        cpu_target = reference["train_cpu_seconds"]
        if not np.isfinite(cpu_target) or cpu_target <= 0:
            raise ValueError("invalid paired CPU target")
        reference_path = ROOT / "results" / "rr_full" / f"seed_{seed}" / "training.json"
        reference_identity = {"path": str(reference_path.relative_to(ROOT)),
                              "sha256": sha256(reference_path),
                              "checkpoint_sha256": reference["checkpoint_sha256"]}
    torch.manual_seed(seed)
    training, validation = arrays("train"), arrays("validation")
    if (len(training["x"]) != settings.get("train_episodes", 512)
            or len(validation["x"]) != settings.get("validation_episodes", 128)):
        raise RuntimeError("unexpected frozen dataset sizes")
    model_variant = cpu_variants.get(variant, variant)
    model = make_policy(model_variant)
    optimizer = torch.optim.Adam(model.parameters(), lr=settings["learning_rate"])
    permutation = torch.Generator().manual_seed(seed+100000)
    rng = np.random.default_rng(seed+200000)
    history, gradient_norms, train_spikes = [], [], 0
    named_max = {name: 0. for name, _ in model.named_parameters()}
    gradient_support = {name: torch.zeros_like(p, dtype=torch.bool) for name, p in model.named_parameters()}
    prior_cpu, prior_wall, resumed = 0., 0., False
    checkpoint_path = destination / "trajectory.pt"
    before_resources = memory_snapshot()
    if checkpoint_path.exists():
        checkpoint = torch.load(checkpoint_path, map_location="cpu", weights_only=False)
        if checkpoint["protocol_sha256"] != protocol_hash or checkpoint["variant"] != variant or checkpoint["seed"] != seed:
            raise RuntimeError("resume identity mismatch")
        model.load_state_dict(checkpoint["model"])
        optimizer.load_state_dict(checkpoint["optimizer"])
        permutation.set_state(checkpoint["permutation_rng"])
        rng.bit_generator.state = checkpoint["path_rng"]
        initial, best, best_epoch = checkpoint["initial"], checkpoint["best"], checkpoint["best_epoch"]
        best_state, history, gradient_norms = checkpoint["best_state"], checkpoint["history"], checkpoint["gradient_norms"]
        named_max, gradient_support = checkpoint["named_max"], checkpoint["gradient_support"]
        train_spikes, prior_cpu, prior_wall = checkpoint["train_spikes"], checkpoint["cpu_seconds"], checkpoint["wall_seconds"]
        before_resources, resumed = checkpoint["before_resources"], True
    else:
        initial = validation_loss(model, validation, settings)
        best, best_epoch, best_state = initial["nll"], 0, copy.deepcopy(model.state_dict())
        torch.save({"state_dict": best_state, "variant": model_variant, "run_name": variant,
                    "seed": seed, "protocol_sha256": protocol_hash, "metadata": model.metadata()}, destination / "initial.pt")
    wall_start, cpu_start = time.perf_counter(), time.process_time()
    cpu_used = lambda: prior_cpu+time.process_time()-cpu_start
    wall_used = lambda: prior_wall+time.perf_counter()-wall_start
    cap = settings.get("cpu_epoch_cap", 10000) if cpu_target is not None else settings["epochs"]
    started = datetime.now(timezone.utc).isoformat()

    def save_trajectory():
        temporary = destination / "trajectory.tmp"
        torch.save({"model": model.state_dict(), "optimizer": optimizer.state_dict(),
                    "permutation_rng": permutation.get_state(), "path_rng": rng.bit_generator.state,
                    "initial": initial, "best": best, "best_epoch": best_epoch, "best_state": best_state,
                    "history": history, "gradient_norms": gradient_norms, "named_max": named_max,
                    "gradient_support": gradient_support, "train_spikes": train_spikes,
                    "cpu_seconds": cpu_used(), "wall_seconds": wall_used(), "before_resources": before_resources,
                    "protocol_sha256": protocol_hash, "variant": variant, "seed": seed}, temporary)
        temporary.replace(checkpoint_path)

    epoch_range = [] if cpu_target is not None and prior_cpu >= cpu_target else range(len(history)+1, cap+1)
    for epoch in epoch_range:
        check_disk()
        model.train()
        order = torch.randperm(len(training["x"]), generator=permutation)
        weighted_loss, decisions, epoch_spikes = 0., 0, 0
        for start in range(0, len(order), settings["batch_size"]):
            ids = order[start:start+settings["batch_size"]]
            length = int(training["lengths"][ids].max())
            optimizer.zero_grad(set_to_none=True)
            output = model(training["x"][ids, :length], training["dt"][ids, :length],
                           event_mask=training["event_mask"][ids, :length], rng=rng)
            decision = training["decision"][ids, :length]
            loss = training_objective(output, training["valid"][ids, :length],
                                      training["optimal"][ids, :length], decision)
            if not bool(torch.isfinite(loss)):
                raise FloatingPointError("nonfinite training objective")
            loss.backward()
            for name, parameter in model.named_parameters():
                if parameter.grad is None or not bool(torch.isfinite(parameter.grad).all()):
                    raise FloatingPointError(f"missing or nonfinite gradient: {name}")
                named_max[name] = max(named_max[name], float(parameter.grad.norm()))
                gradient_support[name] |= parameter.grad != 0
            norm = torch.nn.utils.clip_grad_norm_(model.parameters(), settings["clip_norm"], error_if_nonfinite=True)
            gradient_norms.append(float(norm))
            optimizer.step()
            count = int(decision.sum())
            weighted_loss += float(loss.detach())*count
            decisions += count
            epoch_spikes += int(output["actual_counts"].sum())
        train_spikes += epoch_spikes
        row = {"epoch": epoch, "train_nll": weighted_loss/decisions,
               "actual_internal_spikes": epoch_spikes}
        budget_reached = cpu_target is not None and cpu_used() >= cpu_target
        if epoch % settings["validation_every"] == 0 or epoch == cap or budget_reached:
            measured = validation_loss(model, validation, settings)
            row["validation"] = measured
            if measured["nll"] < best:
                best, best_epoch, best_state = measured["nll"], epoch, copy.deepcopy(model.state_dict())
        row.update(cpu_seconds=cpu_used(), active_wall_seconds=wall_used())
        history.append(row)
        with (destination / "trajectory.jsonl").open("a") as stream:
            stream.write(json.dumps(row, allow_nan=False)+"\n")
        atomic_json(destination / "progress.json", {"epoch": epoch, "updates": len(gradient_norms),
                    "best_validation_nll": best, "best_epoch": best_epoch, "last": row,
                    "cpu_target_seconds": cpu_target})
        save_trajectory()
        if "validation" in row:
            print(json.dumps({"variant": variant, "seed": seed, "epoch": epoch,
                              "validation_nll": row["validation"]["nll"],
                              "cpu_seconds": cpu_used()}), flush=True)
        if cpu_target is not None and cpu_used() >= cpu_target:
            if "validation" not in row:
                measured = validation_loss(model, validation, settings)
                row["validation"] = measured
                if measured["nll"] < best:
                    best, best_epoch, best_state = measured["nll"], epoch, copy.deepcopy(model.state_dict())
                save_trajectory()
            break
    if cpu_target is not None and cpu_used() < cpu_target:
        raise RuntimeError("CPU epoch cap reached before paired budget; no completed receipt")
    if history and "validation" not in history[-1] and cpu_target is not None and cpu_used() >= cpu_target:
        measured = validation_loss(model, validation, settings)
        history[-1]["validation"] = measured
        if measured["nll"] < best:
            best, best_epoch, best_state = measured["nll"], len(history), copy.deepcopy(model.state_dict())
        save_trajectory()
    if not history or "validation" not in history[-1]:
        raise RuntimeError("final model was not validated")
    verify_protocol()
    cpu_seconds, wall_seconds = cpu_used(), wall_used()
    metadata = model.metadata()
    saved = {"state_dict": best_state, "variant": model_variant, "run_name": variant,
             "seed": seed, "protocol_sha256": protocol_hash, "metadata": metadata}
    torch.save(saved, destination / "model.pt")
    after_resources = memory_snapshot()
    result = {"schema": "rr-v4-training-1", "status": "completed", "variant": variant,
              "model_variant": model_variant, "seed": seed, "started_at_utc": started,
              "completed_at_utc": datetime.now(timezone.utc).isoformat(), "resumed": resumed,
              "epochs": len(history), "updates": len(gradient_norms), "history": history,
              "initial_validation_nll": initial["nll"], "initial_validation": initial,
              "best_validation_nll": best, "best_epoch": best_epoch,
              "train_cpu_seconds": cpu_seconds, "train_seconds": wall_seconds,
              "cpu_budget_target_seconds": cpu_target,
              "cpu_budget_overshoot_seconds": max(0., cpu_seconds-cpu_target) if cpu_target is not None else None,
              "cpu_budget_reference": reference_identity,
              "cpu_timer_scope": "training, periodic/final validation, selection, progress and resume-checkpoint writes; excludes initialization, initial validation, resume loading, final artifact serialization",
              "resume_timer_qualification": "persisted elapsed counter is sampled before checkpoint serialization; on resume that final serialization cost is not reconstructed",
              "gradients_all_finite": True, "gradient_norm_max_before_clip": max(gradient_norms),
              "per_parameter_gradient_norm_max_before_clip": named_max,
              "nonzero_gradient_elements_seen": {k: int(v.sum()) for k, v in gradient_support.items()},
              "actual_training_internal_spikes": train_spikes, "metadata": metadata,
              "process_peak_rss_mib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024,
              "rss_scope": "Linux process high-water mark including PyTorch/data/temporaries; not per-neuron memory",
              "resources_before": before_resources, "resources_after": after_resources,
              "resource_quality": resource_quality(before_resources, after_resources),
              "cpu_affinity": sorted(os.sched_getaffinity(0)), "torch_version": torch.__version__,
              "protocol_sha256": protocol_hash, "source_and_data_sha256": protocol["frozen_files"],
              "checkpoint_sha256": sha256(destination / "model.pt"),
              "initial_checkpoint_sha256": sha256(destination / "initial.pt"),
              "holdout_opened_by_training": False,
              "checkpoint_selection": "minimum validation optimal-action-set NLL including initialization",
              "task_utility_acceptance": False}
    atomic_json(destination / "training.json", result)
    print(json.dumps({"completed": variant, "seed": seed, "cpu_seconds": cpu_seconds,
                      "best_validation_nll": best, "updates": len(gradient_norms)}), flush=True)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--variant")
    parser.add_argument("--seed", type=int)
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    if args.verify_only:
        verified, digest = verify_protocol()
        print(json.dumps({"verified": True, "protocol_sha256": digest, "frozen_files": len(verified["frozen_files"])}))
    else:
        if args.variant is None or args.seed is None:
            parser.error("--variant and --seed are required")
        train_one(args.variant, args.seed)
