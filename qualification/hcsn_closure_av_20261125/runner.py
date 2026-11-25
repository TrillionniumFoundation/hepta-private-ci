"""Linux-only bounded workers: train/dev selection, globally gated AV test."""

import time
ENTRY_WALL = time.perf_counter()
import argparse
from pathlib import Path
import resource
import traceback

import numpy as np
import torch

from qualification.hcsn_smallnet_20261124.cost import CostMeter
from .metrics import compute, duration_reference
from .models import PairedEncoder, objective
from .provenance import check_seal, create, digest, identity, load, load_data, read


def clone(model):
    return {name: value.detach().clone() for name, value in model.state_dict().items()}


def batch(data, indices):
    # This is the complete model-input path. Real elapsed/dt metadata are absent.
    return tuple(torch.from_numpy(data[key][indices]) for key in ("audio", "video", "y"))


def evaluate(model, data):
    model.eval()
    pieces, diagnostics = [], []
    with torch.no_grad():
        for start in range(0, len(data["y"]), 16):
            a, v, _ = batch(data, slice(start, start+16))
            output = model(a, v)
            if not all(bool(torch.isfinite(x).all()) for x in output.values()):
                raise FloatingPointError("nonfinite evaluation")
            pieces.append({k: value.detach().cpu().numpy() for k, value in output.items()})
            diagnostics.append({"audio": dict(model.audio.diagnostics), "video": dict(model.video.diagnostics)})
    output = {k: np.concatenate([part[k] for part in pieces], 0) for k in pieces[0]}
    return compute(output, data["y"], data["actor"]), output, diagnostics


def fit(root, p, slot, smoke=False):
    directory = root/slot["id"]
    directory.mkdir()
    meter = CostMeter("AV fit setup + all attempted updates + dev evaluations + checkpoint IO")
    binding = {"slot": slot, "protocol_sha256": identity(p), "smoke": smoke}
    create(directory/"STARTED.json", binding)
    history, updates, attempted, cpu, best_step = [], 0, 0, 0., 0
    model = optimizer = initial = best = rng = None
    best_metrics = initial_metrics = no_grad = zero_grad = None
    training_numerical = {"maximum_mass_error": 0., "maximum_state_bytes_per_batch": 0}
    error, status = None, "completed"
    cfg = p["training"]
    limit = 3 if smoke else cfg["max_updates"]
    try:
        train = load_data(p, "train")
        # Smoke touches only old training actors; even development is train-only.
        dev = {k: value[:32] for k, value in train.items()} if smoke else load_data(p, "dev")
        model = PairedEncoder(slot["arm"], slot["seed"])
        initial = best = clone(model)
        optimizer = torch.optim.Adam(model.parameters(), lr=cfg["learning_rate"])
        rng = torch.Generator().manual_seed(slot["seed"] ^ 0x73A9)
        initial_metrics, _, _ = evaluate(model, dev)
        best_metrics = initial_metrics
        history.append({"step": 0, "attempted_update_cpu": 0., "development": initial_metrics})
        for step in range(1, limit+1):
            if cpu >= cfg["train_cpu_limit"]:
                status = "censored_cpu"
                break
            start = time.process_time()
            attempted += 1
            try:
                model.train()
                indices = torch.randperm(len(train["y"]), generator=rng)[:cfg["batch_size"]].numpy()
                a, v, y = batch(train, indices)
                optimizer.zero_grad(set_to_none=True)
                output = model(a, v)
                loss = objective(output, y)
                loss.backward()
                if step == 1:
                    no_grad = [k for k, x in model.named_parameters() if x.requires_grad and x.grad is None]
                    zero_grad = [k for k, x in model.named_parameters() if x.requires_grad and x.grad is not None and not bool(torch.count_nonzero(x.grad))]
                norm = torch.nn.utils.clip_grad_norm_(model.parameters(), cfg["gradient_clip"])
                if not bool(torch.isfinite(loss) & torch.isfinite(norm)):
                    raise FloatingPointError("nonfinite loss or gradient")
                optimizer.step()
                updates = step
                for encoder in (model.audio, model.video):
                    training_numerical["maximum_mass_error"] = max(training_numerical["maximum_mass_error"], encoder.diagnostics.get("mass_error", 0.))
                training_numerical["maximum_state_bytes_per_batch"] = max(training_numerical["maximum_state_bytes_per_batch"],
                    sum(encoder.diagnostics["logical_state_bytes"] for encoder in (model.audio, model.video)))
            finally:
                cpu += time.process_time()-start
            if step % cfg["development_every"] == 0 or step == limit or cpu >= cfg["train_cpu_limit"]:
                metrics, _, _ = evaluate(model, dev)
                if metrics["fused"]["cross_entropy"] < best_metrics["fused"]["cross_entropy"]:
                    best, best_metrics, best_step = clone(model), metrics, step
                history.append({"step": step, "attempted_update_cpu": cpu, "loss": float(loss.detach()),
                                "gradient_norm": float(norm.detach()), "development": metrics})
        if updates < limit:
            status = "censored_cpu"
    except Exception:
        status, error = "failed", traceback.format_exc()
    create(directory/"history.json", history)
    checkpoint_sha = None
    if model is not None:
        with (directory/"checkpoint.pt").open("xb") as f:
            torch.save({**binding, "initial_model": initial, "selected_model": best, "last_model": clone(model),
                "updates": updates, "selected_step": best_step, "optimizer": optimizer.state_dict() if optimizer is not None else None,
                "torch_rng": torch.get_rng_state(), "minibatch_rng": rng.get_state() if rng is not None else None}, f)
        checkpoint_sha = digest(directory/"checkpoint.pt")
    result = {**binding, "status": status, "error": error, "updates": updates, "attempted_updates": attempted,
        "attempted_update_cpu_seconds": cpu, "selected_step": best_step, "initial_development": initial_metrics,
        "selected_development": best_metrics, "first_update_none_gradients": no_grad, "first_update_zero_gradients": zero_grad,
        "checkpoint_sha256": checkpoint_sha, "parameter_accounting": None if model is None else model.counts(),
        "training_numerical": training_numerical, "cost": meter.snapshot()}
    create(directory/"result.json", result)
    return result


def test(root, p, slot):
    seal_sha = check_seal(root, p)
    binding = {"protocol_sha256": identity(p), "seal_sha256": seal_sha}
    if read(root/"TEST_CLAIM.json") != binding:
        raise ValueError("missing global test claim")
    directory = root/slot["id"]
    create(directory/"TEST_WORKER_CLAIM.json", {**binding, "slot": slot})
    meter = CostMeter("gated test after complete all-nine validation; data/checkpoint loading + both evaluations + prediction IO")
    trained = read(directory/"result.json")
    if trained["status"] == "failed":
        result = {**binding, "slot": slot, "status": "skipped_failed_fit", "cost": meter.snapshot()}
    else:
        data = load_data(p, "test")
        checkpoint = torch.load(directory/"checkpoint.pt", map_location="cpu", weights_only=True)
        model = PairedEncoder(slot["arm"], slot["seed"])
        predictions = {k: data[k] for k in ("y", "actor", "clip", "elapsed_seconds", "dt_seconds")}
        scores, physical = {}, {}
        for name in ("selected", "initial"):
            model.load_state_dict(checkpoint[name+"_model"], strict=True)
            metrics, output, diagnostics = evaluate(model, data)
            predictions.update({name+"_"+k: value for k, value in output.items()})
            scores[name], physical[name] = metrics, diagnostics
        with (directory/"predictions.npz").open("xb") as f:
            np.savez_compressed(f, **predictions)
        result = {**binding, "slot": slot, "status": "evaluated", "selected_step": trained["selected_step"],
            "training_status": trained["status"], "updates": trained["updates"], "metrics": scores,
            "diagnostics": physical, "duration_only_negative_control": duration_reference(data),
            "predictions_sha256": digest(directory/"predictions.npz"), "test_data_sha256": p["dataset"]["splits"]["test"]["sha256"],
            "cost": meter.snapshot()}
    create(directory/"test_result.json", result)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("fit", "test"))
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--slot", required=True)
    parser.add_argument("--smoke", action="store_true")
    args = parser.parse_args()
    torch.set_num_threads(1)
    p = load(args.root)
    slot = next(s for s in p["slots"] if s["id"] == args.slot)
    status, error = "worker_error", None
    try:
        row = fit(args.root, p, slot, args.smoke) if args.action == "fit" else test(args.root, p, slot)
        status = row["status"]
        return 1 if status == "failed" else 0
    except Exception:
        error = traceback.format_exc()
        raise
    finally:
        directory = args.root/slot["id"]
        directory.mkdir(exist_ok=True)
        usage = resource.getrusage(resource.RUSAGE_SELF)
        create(directory/("worker_cost.json" if args.action == "fit" else "test_worker_cost.json"),
            {"status": status, "error": error, "wall_from_entry_seconds": time.perf_counter()-ENTRY_WALL,
             "cpu_through_receipt_seconds": time.process_time(), "process_max_rss_bytes": usage.ru_maxrss*1024,
             "scope": "Linux process CPU including imports through receipt; excludes shutdown. Nested body costs must not be added.", "energy_joules": None})


if __name__ == "__main__":
    raise SystemExit(main())
