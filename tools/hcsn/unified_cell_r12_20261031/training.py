"""Independent per-core CPU-budgeted fit; no confirmation outcomes are read."""

import argparse
import hashlib
import json
import platform
import time
from pathlib import Path

import numpy as np
import torch

from contract import PROTOCOL
from contract import true_model
from data import sequences
from data import tensors
from models import make_model
from models import objective


def validation(model, batch):
    with torch.no_grad():
        p = model(batch["dt"], batch["tokens"], batch["observed"])
        loss, ce, label_loss = objective(p, batch)
        marginal = p.reshape(*p.shape[:-1], 2, -1).sum(-1)
        accuracy = (marginal.argmax(-1) == batch["labels"]).double().mean()
    return {"loss": float(loss), "posterior_ce": float(ce),
            "content_ce": float(label_loss), "accuracy": float(accuracy)}


def digest_data(data):
    sha = hashlib.sha256()
    for key, value in sorted(data.items()):
        sha.update(key.encode())
        sha.update(np.ascontiguousarray(value).tobytes())
    return sha.hexdigest()


def fit(name, seed, seconds, destination):
    torch.set_num_threads(1)
    torch.manual_seed(seed)
    prepare_start = time.process_time()
    world = true_model()
    train_raw = sequences(seed + 100000, PROTOCOL["train_sequences"], world,
                          PROTOCOL["train_dt"], PROTOCOL["sequence_length"])
    valid_raw = sequences(seed + 200000, PROTOCOL["validation_sequences"], world,
                          PROTOCOL["train_dt"], PROTOCOL["sequence_length"])
    train, valid = tensors(train_raw), tensors(valid_raw)
    preparation_cpu = time.process_time() - prepare_start
    rng = np.random.default_rng(seed + 300000)
    start, wall = time.process_time(), time.perf_counter()
    model = make_model(name)
    parameter_count = sum(p.numel() for p in model.parameters())
    optimizer = torch.optim.Adam(model.parameters(), lr=0.04 if
                                 name == "hx_distribution" else 0.004)
    initial = validation(model, valid)
    best, best_step = initial, 0
    best_state = {key: value.detach().clone() for key, value in model.state_dict().items()}
    trace, updates, max_gradient, max_update_cpu = [], 0, 0.0, 0.0
    while time.process_time() - start < seconds:
        update_start = time.process_time()
        indices = rng.integers(0, len(train["dt"]), PROTOCOL["batch_size"])
        batch = {key: value[indices] for key, value in train.items()}
        optimizer.zero_grad(set_to_none=True)
        p = model(batch["dt"], batch["tokens"], batch["observed"])
        loss, _, _ = objective(p, batch)
        if not torch.isfinite(loss):
            raise FloatingPointError("Non-finite training loss")
        loss.backward()
        norm = torch.nn.utils.clip_grad_norm_(model.parameters(), 5.0,
                                              error_if_nonfinite=True)
        max_gradient = max(max_gradient, float(norm))
        optimizer.step()
        updates += 1
        if updates % 20 == 0:
            current = validation(model, valid)
            trace.append({"update": updates, "cpu": time.process_time() - start,
                          "training_loss": float(loss.detach()), **current})
            if current["posterior_ce"] < best["posterior_ce"]:
                best, best_step = current, updates
                best_state = {k: v.detach().clone() for k, v in model.state_dict().items()}
        max_update_cpu = max(max_update_cpu, time.process_time() - update_start)
    final_candidate = validation(model, valid)
    if final_candidate["posterior_ce"] < best["posterior_ce"]:
        best, best_step = final_candidate, updates
        best_state = {k: v.detach().clone() for k, v in model.state_dict().items()}
    model.load_state_dict(best_state)
    exported = model.export_model() if name == "hx_distribution" else None
    payload = {
        "schema": "hcsn-r12-fitted-core-v1", "core": name, "seed": seed,
        "parameter_count": parameter_count, "budget_cpu_seconds": seconds,
        "preparation_cpu_seconds": preparation_cpu,
        "train_data_sha256": digest_data(train_raw),
        "validation_data_sha256": digest_data(valid_raw),
        "initial_validation": initial, "selected_validation": best,
        "selected_update": best_step, "updates": updates,
        "maximum_gradient_norm_before_clipping": max_gradient,
        "maximum_update_cpu_seconds": max_update_cpu,
        "trace": trace,
        "weights": {k: v.tolist() for k, v in best_state.items()},
        "shared_model": None if exported is None else
        {k: v.tolist() for k, v in exported.items()},
        "versions": {"python": platform.python_version(), "numpy": np.__version__,
                     "torch": torch.__version__},
    }
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(payload, separators=(",", ":")) + "\n")
    # Include serialization, validation and construction in the reported budget.
    payload["fit_cpu_seconds"] = time.process_time() - start
    payload["fit_wall_seconds"] = time.perf_counter() - wall
    payload["budget_overshoot_seconds"] = max(0.0, payload["fit_cpu_seconds"] - seconds)
    destination.write_text(json.dumps(payload, separators=(",", ":")) + "\n")
    print(json.dumps({k: payload[k] for k in ["core", "seed", "parameter_count",
                     "updates", "selected_update", "selected_validation",
                     "fit_cpu_seconds", "preparation_cpu_seconds"]}), flush=True)


def load_fit(path):
    payload = json.loads(Path(path).read_text())
    model = make_model(payload["core"])
    state = model.state_dict()
    model.load_state_dict({k: torch.tensor(v, dtype=state[k].dtype)
                           for k, v in payload["weights"].items()})
    model.eval()
    return model, payload


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--core", choices=PROTOCOL["cores"], required=True)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--seconds", type=float, default=20.0)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    fit(args.core, args.seed, args.seconds, args.output)
