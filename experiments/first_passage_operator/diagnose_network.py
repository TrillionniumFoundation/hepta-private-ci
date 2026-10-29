"""Fixed development-only probes and actual-objective gradient diagnostics."""

import json
from pathlib import Path
import time

import numpy as np
from scipy.optimize import minimize
from scipy.special import expit
import torch
from torch.nn import functional

from .tasks import task_data
from .train_network import digest, restore, write_json

HERE = Path(__file__).resolve().parent


def _trace_features(net, inputs, seed, repeats):
    traces, counts, probabilities = [], [], []
    decay = np.exp(-0.25 / net.physical()["decay"].detach().numpy())
    with torch.no_grad():
        for j in range(repeats):
            logits, logs = net(torch.tensor(inputs), noise_seed=seed + j, capture=True)
            state = np.zeros((2, len(inputs), 3))
            count = np.zeros_like(state)
            for row in logs:
                layer = row["layer"]
                state[layer] = decay[layer] * state[layer] + (1 - decay[layer]) * row["count"] / 0.25
                count[layer] += row["count"]
            expected = torch.tensor(state[1]) @ net.readout + net.output_bias
            if not torch.allclose(expected, logits, atol=1e-12, rtol=1e-12):
                raise ArithmeticError("Captured spike traces do not reproduce the native readout")
            traces.append(state)
            counts.append(count)
            probabilities.append(torch.sigmoid(logits).numpy())
    return np.array(traces), np.array(counts), np.array(probabilities)


def _linear_probe(train, labels, dev, targets):
    mean, scale = train.mean(0), np.maximum(train.std(0), 1e-8)
    x = np.column_stack(((train - mean) / scale, np.ones(len(train))))
    z = np.column_stack(((dev - mean) / scale, np.ones(len(dev))))
    def objective(w):
        logits = x @ w
        value = np.mean(np.logaddexp(0, logits) - labels * logits) + .0005 * (w[:-1] @ w[:-1])
        gradient = x.T @ (expit(logits) - labels) / len(x)
        gradient[:-1] += .001 * w[:-1]
        return value, gradient
    fit = minimize(objective, np.zeros(4), method="L-BFGS-B", jac=True,
                   options={"maxiter": 200, "ftol": 1e-12, "gtol": 1e-8})
    score = z @ fit.x
    return {"converged": bool(fit.success), "message": str(fit.message), "iterations": int(fit.nit),
            "weights": fit.x.tolist(), "train_mean": mean.tolist(), "train_scale": scale.tolist(),
            "development_loss": float(np.mean(np.logaddexp(0, score) - targets * score)),
            "development_accuracy": float(((score >= 0) == targets).mean()),
            "development_probability": expit(score).tolist()}


def _set_vector(net, values):
    start = 0
    with torch.no_grad():
        for parameter in net.parameters():
            count = parameter.numel()
            parameter.copy_(torch.as_tensor(values[start:start + count].reshape(parameter.shape)))
            start += count


def _statistics(values):
    values = np.asarray(values)
    return {"mean": float(values.mean()), "standard_error": float(values.std(ddof=1) / np.sqrt(len(values))),
            "replicates": values.tolist()}


def gradient_diagnostics(net, inputs, labels, directions, seed, protocol):
    x, y = torch.tensor(inputs), torch.tensor(labels)
    initial = np.concatenate([p.detach().numpy().ravel() for p in net.parameters()])
    projected = []
    for repetition in range(protocol["gradient_stochastic_repeats"]):
        net.zero_grad()
        logits = net(x, noise_seed=seed + repetition)
        functional.binary_cross_entropy_with_logits(logits, y).backward()
        gradient = np.concatenate([p.grad.numpy().ravel() for p in net.parameters()])
        projected.append(directions @ gradient)
    projected = np.asarray(projected)
    rows = []
    for index, direction in enumerate(directions):
        for step in protocol["perturbation_scales"]:
            plus, minus = [], []
            with torch.no_grad():
                for sign, losses in ((1, plus), (-1, minus)):
                    _set_vector(net, initial + sign * step * direction)
                    for repetition in range(protocol["gradient_stochastic_repeats"]):
                        logits = net(x, noise_seed=seed + repetition)
                        losses.append(float(functional.binary_cross_entropy_with_logits(logits, y)))
            finite = (np.asarray(plus) - minus) / (2 * step)
            discrepancy = projected[:, index] - finite
            rows.append({"direction": index, "scale": step, "finite_perturbation": _statistics(finite),
                         "surrogate": _statistics(projected[:, index]),
                         "surrogate_minus_finite": _statistics(discrepancy)})
    _set_vector(net, initial)
    return {"directions": directions.tolist(), "rows": rows,
            "caveat": "Finite perturbation is not an exact derivative; Monte Carlo uncertainty and perturbation bias both remain. A local moment gradcheck does not validate the composed stochastic-loss gradient."}


def main():
    torch.set_num_threads(1)
    protocol = json.loads((HERE / "NETWORK_DIAGNOSTIC_PROTOCOL.json").read_text())
    directory = HERE / "network_evidence"
    rng = np.random.default_rng(protocol["direction_seed"])
    for seed in protocol["model_seeds"]:
        train_x, train_y = task_data("order", "train", seed, 256)
        dev_x, dev_y = task_data("order", "development", seed, 128)
        for kind in protocol["gradient_models"]:
            destination = directory / f"diagnostic_order_{kind}_{seed}.json"
            if destination.exists():
                raise FileExistsError(destination)
            path = directory / f"fit_order_{kind}_{seed}.json"
            fit = json.loads(path.read_text())
            net = restore(kind, seed, fit["checkpoint"])
            directions = rng.normal(size=(3, 55))
            directions /= np.linalg.norm(directions, axis=1, keepdims=True)
            begin = time.perf_counter()
            result = {"schema": "hepta.renewal-network.diagnostic.v1", "task": "order", "kind": kind,
                      "seed": seed, "checkpoint_sha256": digest(path),
                      "protocol_sha256": digest(HERE / "NETWORK_DIAGNOSTIC_PROTOCOL.json"),
                      "diagnostic_source_sha256": digest(Path(__file__))}
            if kind == "first_passage":
                a, _, _ = _trace_features(net, train_x, seed + protocol["probe_noise_seed_base"], 4)
                b, counts, probability = _trace_features(net, dev_x, seed + protocol["probe_noise_seed_base"] + 1000, 4)
                result["probes"] = [_linear_probe(a.mean(0)[layer], train_y, b.mean(0)[layer], dev_y)
                                    for layer in range(2)]
                pred = probability.mean(0).clip(1e-12, 1 - 1e-12)
                decay = net.physical()["decay"].detach().numpy()
                result["native_ensemble_loss"] = float(np.mean(-dev_y * np.log(pred) - (1 - dev_y) * np.log1p(-pred)))
                result["native_ensemble_accuracy"] = float(((pred >= .5) == dev_y).mean())
                result["trace_memory"] = {"time_constants": decay.tolist(),
                                           "retention_0_75_seconds": np.exp(-.75 / decay).tolist(),
                                           "retention_1_25_seconds": np.exp(-1.25 / decay).tolist(),
                                           "mean_episode_count_by_layer_unit": counts.mean((0, 2)).tolist(),
                                           "zero_episode_count_fraction": (counts == 0).mean((0, 2)).tolist(),
                                           "class0_mean_trace": b[:, :, dev_y == 0].mean((0, 2)).tolist(),
                                           "class1_mean_trace": b[:, :, dev_y == 1].mean((0, 2)).tolist()}
                np.savez_compressed(directory / f"diagnostic_traces_{seed}.npz",
                                    train_trace=a, development_trace=b,
                                    development_counts=counts, development_probabilities=probability,
                                    train_labels=train_y, development_labels=dev_y)
            result["gradient"] = gradient_diagnostics(net, dev_x[:32], dev_y[:32], directions,
                                                       seed + protocol["gradient_noise_seed_base"], protocol)
            result["wall_seconds"] = time.perf_counter() - begin
            write_json(destination, result)
            print(json.dumps({"diagnostic": destination.name, "seconds": result["wall_seconds"],
                              "probe_losses": [p["development_loss"] for p in result.get("probes", [])]}), flush=True)


if __name__ == "__main__":
    main()
