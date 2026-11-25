"""Immutable train workers and a separately gated once-only holdout stage."""

import time
ENTRY_WALL = time.perf_counter()
import argparse
import gzip
import json
from pathlib import Path
import random
import sys
import traceback

try:
    import resource
except ImportError:
    resource = None

import torch

from qualification.hcsn_smallnet_20261124.cost import CostMeter
from qualification.hcsn_smallnet_20261124.train import evaluate, forward_batch
from .data import make_data
from .models import make_model, parameter_accounting
from .provenance import check_seal, create, digest, identity, load, read


def clone_state(model):
    return {k: v.detach().clone() for k, v in model.state_dict().items()}


def fit(root, p, slot, smoke=False):
    directory = root / slot["id"]
    directory.mkdir(parents=True, exist_ok=False)
    meter = CostMeter("fit_setup_all_updates_all_development_checkpoint")
    random.seed(slot["seed"])
    torch.manual_seed(slot["seed"])
    cfg = p["training"]
    binding = {"slot": slot, "protocol_sha256": identity(p), "smoke": smoke}
    create(directory / "STARTED.json", binding)
    initial = best = prefix = model = optimizer = rng = None
    train = dev = best_metrics = initial_metrics = None
    history, updates, attempts, cpu, best_step, prefix_step = [], 0, 0, 0., 0, 0
    prefix_cpu, no_gradient, zero_gradient = 0., None, None
    error, status = None, "completed"
    update_limit = min(cfg["max_updates"], 3) if smoke else cfg["max_updates"]
    try:
        train = make_data("smoke_train" if smoke else "train", per_source=8 if smoke else p["data"]["train_per_source"], length=p["data"]["length"])
        dev = make_data("smoke_dev" if smoke else "dev", per_source=8 if smoke else p["data"]["dev_per_source"], length=p["data"]["length"])
        model = make_model(slot)
        initial = best = prefix = clone_state(model)
        optimizer = torch.optim.Adam(model.parameters(), lr=cfg["learning_rate"])
        rng = torch.Generator().manual_seed(slot["seed"] ^ 0x76AC)
        initial_metrics, _, _ = evaluate(model, dev)
        best_metrics = initial_metrics
        history.append({"step": 0, "train_cpu": 0., "development": initial_metrics})
        for step in range(1, update_limit + 1):
            if cpu >= cfg["train_cpu_limit"]:
                status = "censored_cpu"
                break
            start = time.process_time()
            attempts += 1
            try:
                indices = torch.randperm(len(train.y), generator=rng)[:cfg["batch_size"]]
                batch = train.select(indices)
                optimizer.zero_grad(set_to_none=True)
                logits, _, _ = forward_batch(model, batch)
                target = batch.y.expand(len(logits), -1).flatten()
                loss = (.8 * torch.nn.functional.cross_entropy(logits[-1], batch.y)
                        + .2 * torch.nn.functional.cross_entropy(logits.flatten(0, 1), target))
                loss.backward()
                if step == 1:
                    no_gradient = [name for name, value in model.named_parameters()
                                   if value.requires_grad and value.grad is None]
                    zero_gradient = [name for name, value in model.named_parameters()
                                     if value.requires_grad and value.grad is not None
                                     and not bool(torch.count_nonzero(value.grad))]
                norm = torch.nn.utils.clip_grad_norm_(model.parameters(), cfg["gradient_clip"])
                if not bool(torch.isfinite(loss) & torch.isfinite(norm)):
                    raise FloatingPointError("nonfinite loss or gradient")
                optimizer.step()
                updates = step
            finally:
                cpu += time.process_time() - start
            if cpu <= cfg["cpu_prefix"]:
                prefix, prefix_step, prefix_cpu = clone_state(model), step, cpu
            if step % cfg["development_every"] == 0 or step == update_limit or cpu >= cfg["train_cpu_limit"]:
                metrics, _, _ = evaluate(model, dev)
                if metrics["cross_entropy"] < best_metrics["cross_entropy"]:
                    best, best_metrics, best_step = clone_state(model), metrics, step
                history.append({"step": step, "train_cpu": cpu, "loss": float(loss.detach()),
                                "gradient_norm": float(norm.detach()), "development": metrics})
        if updates < update_limit and status == "completed":
            status = "censored_cpu"
    except Exception:
        status, error = "failed", traceback.format_exc()
    create(directory / "history.json", history)
    checkpoint_sha = None
    if model is not None:
        path = directory / "checkpoint.pt"
        with path.open("xb") as handle:
            torch.save({**binding, "initial_model": initial, "selected_model": best,
                        "last_model": clone_state(model), "cpu_prefix_model": prefix,
                        "cpu_prefix_step": prefix_step, "selected_step": best_step, "updates": updates,
                        "optimizer": None if optimizer is None else optimizer.state_dict(),
                        "torch_rng": torch.get_rng_state(), "minibatch_rng": None if rng is None else rng.get_state()}, handle)
        checkpoint_sha = digest(path)
    result = {**binding, "status": status, "error": error, "updates": updates,
              "attempted_updates": attempts, "training_cpu_seconds": cpu,
              "selected_step": best_step, "cpu_prefix_step": prefix_step,
              "cpu_prefix_training_cpu_seconds": prefix_cpu,
              "first_update_none_gradient_parameters": no_gradient,
              "first_update_all_zero_gradient_parameters": zero_gradient,
              "gradient_scope": "First minibatch observation, not a global functional rank proof.",
              "cpu_prefix_checkpoint_rule": "last post-update state whose attempted-update CPU total <=180; excludes setup, dev and snapshot copies, all of which are in complete cost; no holdout or development selection",
              "initial_development": initial_metrics, "selected_development": best_metrics,
              "parameter_accounting": None if model is None else parameter_accounting(model),
              "train_data_sha256": None if train is None else train.digest(),
              "dev_data_sha256": None if dev is None else dev.digest(),
              "checkpoint_sha256": checkpoint_sha, "cost": meter.snapshot()}
    create(directory / "result.json", result)
    return result


def subgroup_metrics(logits, data):
    correct = logits[-1].argmax(-1) == data.y
    groups = {}
    for parity in (0, 1):
        chosen = data.late_step % 2 == parity
        groups["late_parity_" + str(parity)] = {"examples": int(chosen.sum()),
            "accuracy": float(correct[chosen].double().mean())}
    boundaries = torch.quantile(data.initial_margin.double(), torch.tensor([0., .25, .5, .75, 1.], dtype=torch.float64))
    for index in range(4):
        chosen = (data.initial_margin >= boundaries[index]) & (data.initial_margin <= boundaries[index+1] if index == 3 else data.initial_margin < boundaries[index+1])
        groups["initial_margin_quartile_" + str(index)] = {"examples": int(chosen.sum()),
            "accuracy": float(correct[chosen].double().mean())}
    return groups


def test(root, p, slot):
    check_seal(root, p)
    claim = read(root / "TEST_CLAIM.json")
    if claim != {"seal_sha256": digest(root / "SEAL.json"), "protocol_sha256": identity(p)}:
        raise ValueError("holdout claim does not match complete training seal")
    directory = root / slot["id"]
    if (directory / "test_result.json").exists():
        raise FileExistsError("holdout worker cannot overwrite a terminal result")
    create(directory / "TEST_WORKER_CLAIM.json", {"seal_sha256": digest(root / "SEAL.json"),
                                                "protocol_sha256": identity(p), "slot": slot})
    record = read(directory / "result.json")
    if record["status"] not in ("completed", "censored_cpu"):
        result = {"slot": slot, "status": "unavailable", "reason": record["error"]}
        create(directory / "test_result.json", result)
        return result
    meter = CostMeter("data_construction_model_load_three_holdout_evaluations_prediction_write")
    data = make_data("test", per_source=p["data"]["test_per_source"], length=p["data"]["length"])
    saved = torch.load(directory / "checkpoint.pt", map_location="cpu", weights_only=True)
    model = make_model(slot)
    metrics, predictions = {}, {}
    for label, key in (("selected", "selected_model"), ("initial", "initial_model"), ("cpu_prefix", "cpu_prefix_model")):
        model.load_state_dict(saved[key])
        score, logits, _ = evaluate(model, data)
        score["subgroups"] = subgroup_metrics(logits, data)
        metrics[label], predictions[label] = score, logits.tolist()
    payload = {"slot": slot, "data_sha256": data.digest(), "protocol_sha256": identity(p),
               "ids": data.ids, "labels": data.y.tolist(), "source": data.source.tolist(),
               "late_step": data.late_step.tolist(), "initial_margin": data.initial_margin.tolist(),
               "prefix_logits": predictions}
    path = directory / "test_predictions.json.gz"
    with path.open("xb") as output:
        with gzip.GzipFile(fileobj=output, mode="wb", mtime=0) as zipped:
            zipped.write(json.dumps(payload, separators=(",", ":"), allow_nan=False).encode())
    gate = p["validation"]
    selected, initial = metrics["selected"], metrics["initial"]
    passed = (selected["accuracy"] >= gate["min_final_accuracy"]
              and selected["accuracy"] - initial["accuracy"] >= gate["min_gain_over_initial"]
              and selected["accuracy"] - selected["pre_late_accuracy"] >= gate["min_gain_over_prelate"])
    result = {"slot": slot, "status": "evaluated", "training_status": record["status"],
              "updates": record["updates"], "selected_step": record["selected_step"],
              "cpu_prefix_step": record["cpu_prefix_step"], "metrics": metrics,
              "learning_gate": passed, "data_sha256": data.digest(),
              "predictions_sha256": digest(path), "cost": meter.snapshot()}
    create(directory / "test_result.json", result)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("fit", "test", "smoke"))
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--slot", required=True)
    args = parser.parse_args()
    torch.set_num_threads(1)
    p = load(args.root)
    slot = next(s for s in p["slots"] if s["id"] == args.slot)
    name = "worker_cost.json" if args.action != "test" else "test_worker_cost.json"
    status, error = "failed", None
    try:
        result = test(args.root, p, slot) if args.action == "test" else fit(args.root, p, slot, args.action == "smoke")
        status = result["status"]
        print(json.dumps({k: result.get(k) for k in ("slot", "status", "updates", "selected_step", "learning_gate", "error")}), flush=True)
    except Exception:
        error = traceback.format_exc()
        raise
    finally:
        directory = args.root / slot["id"]
        directory.mkdir(exist_ok=True)
        peak = None if resource is None else resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        create(directory / name, {"status": status, "error": error,
            "wall_from_first_module_statement": time.perf_counter() - ENTRY_WALL,
            "process_cpu_through_receipt": time.process_time(),
            "process_peak_rss_bytes": None if peak is None else peak * (1 if sys.platform == "darwin" else 1024),
            "energy_joules_process": None, "scope": "fresh child; imports included, interpreter shutdown excluded"})
    return 0 if status in ("completed", "censored_cpu", "evaluated", "unavailable") else 1


if __name__ == "__main__":
    raise SystemExit(main())
