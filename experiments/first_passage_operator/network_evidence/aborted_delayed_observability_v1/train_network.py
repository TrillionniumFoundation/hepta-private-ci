"""Train, freeze and evaluate the registered sampled-network comparison.

Development never constructs the confirmation split. Confirmation requires a
source/checkpoint freeze receipt and refuses mismatches. Predictions are retained
per independent example and stochastic rollout; no result is discarded.
"""

import argparse
import hashlib
import json
from pathlib import Path
import time

import numpy as np
import torch
from torch.nn import functional as functional

from .network import RecurrentNetwork, RenewalNetwork
from .tasks import TASKS, task_data

HERE = Path(__file__).resolve().parent
KINDS = ("first_passage", "lif", "rnn")
SOURCES = ("network.py", "tasks.py", "train_network.py", "NETWORK_PROTOCOL.json")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise FileExistsError(path)
    path.write_text(json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n")


def model(kind, seed):
    return RecurrentNetwork(seed=seed) if kind == "rnn" else RenewalNetwork(kind=kind, seed=seed)


def encoded(net):
    return {k: v.detach().numpy().tolist() for k, v in net.state_dict().items()}


def restore(kind, seed, checkpoint):
    net = model(kind, seed)
    net.load_state_dict({k: torch.tensor(v, dtype=torch.float64)
                         for k, v in checkpoint.items()})
    return net


def predict(net, inputs, labels, *, noise_seed, repeats):
    x = torch.as_tensor(inputs, dtype=torch.float64)
    y = torch.as_tensor(labels, dtype=torch.float64)
    losses, correct, probabilities = [], [], []
    with torch.no_grad():
        for j in range(repeats):
            logits = net(x, noise_seed=noise_seed + j)
            losses.append(functional.binary_cross_entropy_with_logits(logits, y, reduction="none").numpy())
            correct.append(((logits >= 0) == (y > 0)).numpy().astype(float))
            probabilities.append(torch.sigmoid(logits).numpy())
    return np.asarray(losses), np.asarray(correct), np.asarray(probabilities)


def develop_one(kind, task, seed, protocol, directory):
    path = directory / f"fit_{task}_{kind}_{seed}.json"
    if path.exists():
        raise FileExistsError(path)
    net = model(kind, seed)
    inputs, labels = task_data(task, "train", seed, protocol["train_examples"])
    dev_x, dev_y = task_data(task, "development", seed, protocol["development_examples"])
    x, y = torch.tensor(inputs), torch.tensor(labels)
    optimizer = torch.optim.Adam(net.parameters(), lr=protocol["learning_rate"])
    initial = encoded(net)
    gradients = {name: 0.0 for name, _ in net.named_parameters()}
    history, best, best_epoch, best_loss = [], None, -1, float("inf")
    rng = np.random.default_rng(seed + 913009)
    begin = time.perf_counter()
    initial_loss = float(predict(net, inputs, labels, noise_seed=seed + 173, repeats=4)[0].mean())
    for epoch in range(protocol["epochs"]):
        order = rng.permutation(len(x))
        epoch_losses = []
        for batch_index, start in enumerate(range(0, len(x), protocol["batch_size"])):
            idx = order[start:start + protocol["batch_size"]]
            logits = net(x[idx], noise_seed=seed * 1000000 + epoch * 100 + batch_index)
            loss = functional.binary_cross_entropy_with_logits(logits, y[idx])
            if not torch.isfinite(loss):
                raise ArithmeticError("Non-finite training loss")
            optimizer.zero_grad()
            loss.backward()
            for name, parameter in net.named_parameters():
                if parameter.grad is None or not torch.isfinite(parameter.grad).all():
                    raise ArithmeticError("Missing or non-finite gradient: " + name)
                gradients[name] += float(parameter.grad.square().sum())
            torch.nn.utils.clip_grad_norm_(net.parameters(), protocol["gradient_norm_clip"])
            optimizer.step()
            epoch_losses.append(float(loss.detach()))
        if (epoch + 1) % protocol["development_every"] == 0:
            dev = predict(net, dev_x, dev_y, noise_seed=seed + 300000000,
                          repeats=protocol["development_repeats"])
            mean = float(dev[0].mean())
            history.append({"epoch": epoch + 1, "train_batch_loss": float(np.mean(epoch_losses)),
                            "development_loss": mean, "development_accuracy": float(dev[1].mean())})
            if mean < best_loss:
                best, best_epoch, best_loss = encoded(net), epoch + 1, mean
    selected = restore(kind, seed, best)
    fitted_loss = float(predict(selected, inputs, labels, noise_seed=seed + 173, repeats=4)[0].mean())
    deltas = {}
    for name, values in best.items():
        difference = np.asarray(values) - np.asarray(initial[name])
        deltas[name] = {"l2": float(np.linalg.norm(difference)),
                        "min_abs": float(np.abs(difference).min()),
                        "max_abs": float(np.abs(difference).max()),
                        "changed": int(np.count_nonzero(difference)), "total": int(difference.size)}
    elapsed = time.perf_counter() - begin
    result = {"schema": "hepta.renewal-network.fit.v1", "kind": kind, "task": task,
              "seed": seed, "parameters": sum(p.numel() for p in net.parameters()),
              "initial_train_loss": initial_loss, "selected_train_loss": fitted_loss,
              "best_epoch": best_epoch, "development_loss": best_loss,
              "gradient_squared_sum": gradients, "selected_parameter_deltas": deltas,
              "initial": initial, "checkpoint": best, "history": history,
              "wall_seconds": elapsed, "optimizer_updates": protocol["epochs"] *
              math_ceil_div(len(x), protocol["batch_size"]),
              "source_sha256": {p: digest(HERE / p) for p in SOURCES},
              "gradient_scope": ("biased conditional-renewal-moment straight-through" if kind == "first_passage"
                                 else "hard LIF sigmoid surrogate" if kind == "lif" else "ordinary BPTT")}
    write_json(path, result)
    print(json.dumps({"fit": path.name, "seconds": elapsed, "train": fitted_loss,
                      "dev": best_loss, "epoch": best_epoch}), flush=True)


def math_ceil_div(a, b):
    return (a + b - 1) // b


def freeze(directory, protocol):
    required = [directory / f"fit_{task}_{kind}_{seed}.json"
                for task in TASKS for kind in KINDS for seed in protocol["seeds"]]
    for path in required:
        row = json.loads(path.read_text())
        if row["source_sha256"] != {p: digest(HERE / p) for p in SOURCES}:
            raise ValueError("Training source changed before freeze: " + path.name)
    value = {"schema": "hepta.renewal-network.freeze.v1", "utc_unix_time": time.time(),
             "sources": {p: digest(HERE / p) for p in SOURCES},
             "fits": {p.name: digest(p) for p in required},
             "confirmation_opened": False}
    write_json(directory / "FREEZE.json", value)
    print(json.dumps({"freeze_sha256": digest(directory / "FREEZE.json"), "fits": len(required)}))


def confirmation(directory, protocol):
    frozen = json.loads((directory / "FREEZE.json").read_text())
    if frozen["sources"] != {p: digest(HERE / p) for p in SOURCES}:
        raise ValueError("Source does not match pre-confirmation freeze")
    for path, expected in frozen["fits"].items():
        if digest(directory / path) != expected:
            raise ValueError("Fit differs from the frozen checkpoint")
    rows, arrays = [], {}
    for task in TASKS:
        for seed in protocol["seeds"]:
            x, y = task_data(task, "confirmation", seed, protocol["confirmation_examples"])
            arrays[f"{task}_{seed}_labels"] = y
            for kind in KINDS:
                path = directory / f"confirmation_{task}_{kind}_{seed}.json"
                if path.exists():
                    raise FileExistsError(path)
                fit = json.loads((directory / f"fit_{task}_{kind}_{seed}.json").read_text())
                net = restore(kind, seed, fit["checkpoint"])
                begin = time.perf_counter()
                losses, correct, probability = predict(net, x, y, noise_seed=seed + 700000000,
                                                       repeats=protocol["confirmation_repeats"])
                result = {"schema": "hepta.renewal-network.confirmation.v1", "task": task,
                          "kind": kind, "seed": seed, "mean_loss": float(losses.mean()),
                          "mean_single_rollout_accuracy": float(correct.mean()),
                          "ensemble_accuracy": float(((probability.mean(0) >= 0.5) == y).mean()),
                          "wall_seconds": time.perf_counter() - begin,
                          "loss_by_example": losses.mean(0).tolist(),
                          "accuracy_by_example": correct.mean(0).tolist(),
                          "probability_by_example": probability.mean(0).tolist(),
                          "checkpoint_sha256": digest(directory / f"fit_{task}_{kind}_{seed}.json"),
                          "freeze_sha256": digest(directory / "FREEZE.json")}
                write_json(path, result)
                rows.append(result)
                key = f"{task}_{kind}_{seed}"
                arrays[key + "_loss"] = losses
                arrays[key + "_correct"] = correct
                arrays[key + "_probability"] = probability
    # Each task's array archive stays below the repository blob gate.
    for task in TASKS:
        target = directory / f"confirmation_arrays_{task}.npz"
        if target.exists():
            raise FileExistsError(target)
        np.savez_compressed(target, **{k: v for k, v in arrays.items() if k.startswith(task + "_")})
    summary = {"schema": "hepta.renewal-network.comparison.v1", "comparisons": [],
               "interpretation": "Three training seeds; empirical simultaneous intervals, not universal superiority or population coverage guarantees."}
    rng = np.random.default_rng(protocol["bootstrap_seed"])
    for task in TASKS:
        for baseline in ("lif", "rnn"):
            improvements = []
            for seed in protocol["seeds"]:
                fp = next(r for r in rows if r["task"] == task and r["kind"] == "first_passage" and r["seed"] == seed)
                base = next(r for r in rows if r["task"] == task and r["kind"] == baseline and r["seed"] == seed)
                improvements.append(np.array(base["loss_by_example"]) - fp["loss_by_example"])
            improvements = np.array(improvements)
            replicates = []
            for _ in range(protocol["bootstrap_replicates"]):
                chosen = rng.integers(len(improvements), size=len(improvements))
                means = [improvements[i, rng.integers(improvements.shape[1], size=improvements.shape[1])].mean()
                         for i in chosen]
                replicates.append(float(np.mean(means)))
            tail = 0.05 / (2 * 6)
            interval = np.quantile(replicates, [tail, 1 - tail]).tolist()
            summary["comparisons"].append({"task": task, "baseline": baseline,
                                           "loss_improvement": float(improvements.mean()),
                                           "seed_means": improvements.mean(1).tolist(),
                                           "simultaneous_empirical_interval": interval,
                                           "passes_advantage_gate": bool(interval[0] > protocol["advantage_margin"]
                                                                         and np.all(improvements.mean(1) > 0))})
    summary["cross_task_advantage_established"] = all(r["passes_advantage_gate"] for r in summary["comparisons"])
    write_json(directory / "CONFIRMATION_SUMMARY.json", summary)
    print(json.dumps(summary, indent=2))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=("develop", "freeze", "confirm"))
    parser.add_argument("--kind", choices=KINDS)
    parser.add_argument("--task", choices=TASKS)
    parser.add_argument("--seed", type=int)
    args = parser.parse_args()
    torch.set_num_threads(1)
    protocol = json.loads((HERE / "NETWORK_PROTOCOL.json").read_text())
    directory = HERE / "network_evidence"
    directory.mkdir(exist_ok=True)
    if args.stage == "develop":
        for task in ([args.task] if args.task else TASKS):
            for kind in ([args.kind] if args.kind else KINDS):
                for seed in ([args.seed] if args.seed else protocol["seeds"]):
                    if seed not in protocol["seeds"]:
                        raise ValueError("Unregistered training seed")
                    develop_one(kind, task, seed, protocol, directory)
    elif args.stage == "freeze":
        freeze(directory, protocol)
    else:
        confirmation(directory, protocol)


if __name__ == "__main__":
    main()
