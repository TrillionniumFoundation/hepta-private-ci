"""Independent raw-record arithmetic and checkpoint replay; no training imports."""

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path

import numpy as np


MAX_ERRORS = defaultdict(float)
COUNTS = Counter()


def require(condition, message):
    COUNTS["checks"] += 1
    if not condition:
        raise ValueError(message)


def close(actual, expected, name, tolerance=1e-9):
    a, b = np.asarray(actual), np.asarray(expected)
    require(a.shape == b.shape, f"{name}: shape differs")
    require(np.isfinite(a).all() and np.isfinite(b).all(), f"{name}: nonfinite")
    error = float(np.max(np.abs(a - b))) if a.size else 0.0
    MAX_ERRORS[name] = max(MAX_ERRORS[name], error)
    require(error <= tolerance, f"{name}: error {error}")


def digest(*arrays):
    h = hashlib.sha256()
    for data in arrays:
        a = np.asarray(data, dtype="<f8", order="C")
        h.update(json.dumps(list(a.shape)).encode())
        h.update(a.tobytes(order="C"))
    return h.hexdigest()


def truth(x, panel, expected):
    d, sigma = panel["dimension"], panel["noise"]
    b = np.linspace(-0.25, 0.45, d)
    a = np.linspace(0.5, 1.0, d) / np.sqrt(d)
    projection = np.einsum("...d,d->...", x, a)
    damping = np.exp(-sigma * sigma * np.dot(a, a) / 2) if expected else 1.0
    result = -np.sum(np.square(x - b), axis=-1) / (2 * d)
    result += panel["complementarity"] * x[..., 0] * x[..., 1] / d
    result += 0.15 * damping * np.sin(projection)
    if expected:
        result -= sigma * sigma / 2
    grad = -(x - b) / d + (0.15 * damping * np.cos(projection))[..., None] * a
    grad[..., 0] += panel["complementarity"] * x[..., 1] / d
    grad[..., 1] += panel["complementarity"] * x[..., 0] / d
    return result, grad


def options(x, panel, settings):
    d = panel["dimension"]
    shifts, names = [np.zeros(d)], ["STOP_keep"]
    for j in range(d):
        for sign, label in ((1, "plus"), (-1, "minus")):
            move = np.zeros(d)
            move[j] = sign * settings["action_step"]
            shifts.append(move)
            names.append(f"adjust_{j}_{label}")
    if panel["capacity"] >= 2:
        for sign, label in ((1, "plus"), (-1, "minus")):
            move = np.zeros(d)
            move[:2] = sign * settings["action_step"]
            shifts.append(move)
            names.append("joint_" + label)
    costs = [panel["adjustment"] * float(move @ move)
             + panel["load_cost"] * sum(move[j] != 0 for j in range(panel["resident"], d))
             for move in shifts] + [settings["reset_cost"]]
    targets = np.empty((len(x), len(costs), d))
    targets[:, :-1, :] = x[:, None, :] + np.asarray(shifts)
    targets[:, -1, :] = 0
    chance = np.ones(len(costs))
    chance[-1] = panel["reset_probability"]
    return targets, np.asarray(costs), chance, names + ["reset"]


def utility_table(x, panel, settings):
    targets, cost, chance, names = options(x, panel, settings)
    v0 = truth(x, panel, True)[0]
    destination = truth(targets, panel, True)[0]
    mean_quality = v0[:, None] + chance * (destination - v0[:, None])
    return mean_quality - cost, mean_quality, cost, names


def model_output(model, x, gradient=False):
    mean, scale = np.asarray(model["mean"]), np.asarray(model["scale"])
    p = [np.asarray(item) for item in model["parameters"]]
    n, d = x.shape
    if model["family"] == "neural":
        w, bias, head, out_bias = p
        hidden = np.tanh(x @ w + bias)
        output = (hidden @ head + out_bias) * scale + mean
        if model["kind"] == "value" and gradient:
            out = np.zeros_like(x)
            for j in range(d):
                out[:, j] = np.sum((1 - hidden * hidden) * head[:, 0] * w[j], axis=1) * scale[0]
            return out
    else:
        basis = [np.ones(n)] + [x[:, j] for j in range(d)]
        derivatives = [np.zeros_like(x)] + [np.tile(e, (n, 1)) for e in np.eye(d)]
        if model["family"] == "quadratic":
            for i in range(d):
                for j in range(i, d):
                    basis.append(x[:, i] * x[:, j])
                    derivative = np.zeros_like(x)
                    derivative[:, i] += x[:, j]
                    derivative[:, j] += x[:, i]
                    derivatives.append(derivative)
        phi = np.asarray(basis).T
        output = (phi @ p[0]) * scale + mean
        if model["kind"] == "value" and gradient:
            return sum(g * coefficient for g, coefficient in zip(derivatives, p[0][:, 0])) * scale[0]
    return output / model["noise"] if model["kind"] == "z_gradient" else output


def replay(model, x, panel, settings):
    destination, cost, chance, _ = options(x, panel, settings)
    shape = destination.shape
    if model["kind"] == "value":
        values = model_output(model, destination.reshape(-1, shape[-1])).reshape(shape[:2])
        gain = values - model_output(model, x)
    else:
        nodes, weights = np.polynomial.legendre.leggauss(4)
        nodes, weights = (nodes + 1) / 2, weights / 2
        move = destination - x[:, None, :]
        probes = x[:, None, None, :] + move[:, :, None, :] * nodes[None, None, :, None]
        gradients = model_output(model, probes.reshape(-1, shape[-1]), True).reshape(probes.shape)
        gain = np.einsum("naqd,nad,q->na", gradients, move, weights)
    return np.argmax(chance * gain - cost, axis=1)


def check_case(case, settings):
    p, seed = case["panel"], case["seed"]
    d, n = p["dimension"], settings["test_n"]
    x = np.asarray(case["public_test_states"])
    require(x.shape == (n, d), "test states shape")
    raw_train = case["training_observations"]
    train_x, samples = np.asarray(raw_train["states"]), np.asarray(raw_train["outcomes"])
    require(train_x.shape == (settings["train_n"], d), "training anchors shape")
    require(samples.shape == (len(train_x), 1 + 2 * d, settings["mc_replicates"]), "training outcomes shape")
    offsets = np.zeros((1 + 2 * d, d))
    for j in range(d):
        offsets[1 + j * 2, j], offsets[2 + j * 2, j] = settings["stencil_step"], -settings["stencil_step"]
    train_locations = train_x[:, None, :] + offsets
    data_hash = digest(train_locations, samples)
    shared = case["shared_acquisition_and_truth"]
    require(data_hash == shared["observations_sha256"], "raw training observation hash")
    require(shared["synthetic_quality_evaluations"] == samples.size, "synthetic quality census")
    eps, reset = np.asarray(case["evaluation_noise"]), np.asarray(case["evaluation_reset_success"])
    require(eps.shape == x.shape and reset.shape == (n,) and reset.dtype == bool, "evaluation noise/reset shape")
    require(digest(x, eps, reset) == shared["evaluation_sha256"], "evaluation hash")
    expected, expected_quality, fees, names = utility_table(x, p, settings)
    require(case["action_names"] == names, "legal actions and ordering")
    fixed_choice = int(np.argmax(utility_table(train_x, p, settings)[0].mean(axis=0)))
    require(case["fixed_action"] == fixed_choice, "fixed reference training-only optimization")
    destination = options(x, p, settings)[0]
    destination[:, -1, :] = np.where(reset[:, None], np.zeros_like(x), x)
    realized = truth(destination + p["noise"] * eps[:, None, :], p, False)[0]
    arms = {(f, k) for f in settings["families"] for k in settings["targets"]}
    arms |= {("reference", "exact"), ("reference", "fixed_known_model"), ("action_ablation", "frozen")}
    observed = [(r["family"], r["kind"]) for r in case["records"]]
    require(set(observed) == arms and len(observed) == len(arms), "complete unique 12-arm roster")
    summaries, lookup = [], {}
    for row in case["records"]:
        family, kind = row["family"], row["kind"]
        COUNTS["records"] += 1
        if p["noise"] == 0 and kind == "z_gradient":
            require(row["status"] == "unidentified" and "raw" not in row, "zero-noise Z is retained unidentified")
            require(row["failed_cpu_ns"] >= 0 and row["failed_wall_ns"] >= 0, "unidentified work costs")
            COUNTS["unidentified"] += 1
            continue
        require(row["status"] == "complete", "unexpected failed or omitted arm")
        raw, metrics = row["raw"], row["metrics"]
        chosen = np.asarray(raw["choices"])
        require(chosen.shape == (n,) and np.issubdtype(chosen.dtype, np.integer), "choice shape/type")
        require(np.all((0 <= chosen) & (chosen < len(names))), "illegal choice")
        if "model" in row:
            model, fit = row["model"], row["training"]
            require((model["family"], model["kind"], model["noise"]) == (family, kind, p["noise"]), "model identity")
            require(digest(model["mean"], model["scale"], *model["parameters"]) == fit["parameter_sha256"], "checkpoint byte digest")
            require(fit["source_observations_sha256"] == data_hash, "common observation access")
            target = samples.mean(axis=2)
            if kind == "value":
                target = target.reshape(-1, 1)
            else:
                target = (target[:, 1::2] - target[:, 2::2]) / (2 * settings["stencil_step"])
                if kind == "z_gradient":
                    target *= p["noise"]
            scale = target.std(axis=0)
            close(model["mean"], target.mean(axis=0), "normalization_mean", 1e-13)
            close(model["scale"], np.where(scale == 0, 1, scale), "normalization_scale", 1e-13)
            require((fit["observations_used"], fit["outputs"]) == target.shape, "training label census")
            require(fit["trainable_parameters"] == sum(np.asarray(a).size for a in model["parameters"]), "effective parameter census")
            require(fit["updates"] == (settings["neural_updates"] if family == "neural" else 1), "recorded update census")
            reconstructed = replay(model, x, p, settings)
            gradient = model_output(model, x, True)
            v, g = truth(x, p, True)
            close(row["calibration"]["gradient_mse"], np.mean((gradient - g) ** 2), "gradient_mse")
            if kind == "value":
                close(row["calibration"]["value_mse"], np.mean((model_output(model, x)[:, 0] - v) ** 2), "value_mse")
            else:
                require(row["calibration"]["value_mse"] is None, "gradient critic cannot identify value offset")
            curls = []
            for i in range(d):
                for j in range(i + 1, d):
                    hi, hj = np.eye(d)[i] * 1e-5, np.eye(d)[j] * 1e-5
                    ji = (model_output(model, x + hi, True) - model_output(model, x - hi, True)) / 2e-5
                    jj = (model_output(model, x + hj, True) - model_output(model, x - hj, True)) / 2e-5
                    curls.extend(np.abs(ji[:, j] - jj[:, i]).tolist())
            close(row["calibration"]["mean_abs_curl"], np.mean(curls), "curl", 1e-8)
            COUNTS["checkpoints"] += 1
        elif kind == "exact":
            reconstructed = np.argmax(expected, axis=1)
        else:
            reconstructed = np.full(n, fixed_choice if kind == "fixed_known_model" else 0)
        require(np.array_equal(chosen, reconstructed), "checkpoint/reference decision mismatch")
        COUNTS["decisions"] += len(chosen)
        ix = np.arange(n)
        selected_fees, selected_quality = fees[chosen], realized[ix, chosen]
        selected_expected = expected[ix, chosen]
        close(raw["fees"], selected_fees, "raw_fees", 1e-14)
        close(raw["observed_quality"], selected_quality, "raw_observed_quality", 1e-12)
        close(raw["expected_net"], selected_expected, "raw_expected_net", 1e-12)
        net = selected_quality - selected_fees
        cpu, wall = np.asarray(raw["cpu_ns"]), np.asarray(raw["wall_ns"])
        require(cpu.shape == wall.shape == (n,) and np.all(cpu >= 0) and np.all(wall >= 0), "timing roster")
        computed = {"expected_net_value": selected_expected.mean(), "expected_quality": expected_quality[ix, chosen].mean(),
                    "observed_quality": selected_quality.mean(), "mean_fee": selected_fees.mean(),
                    "expected_regret": np.mean(expected.max(axis=1) - selected_expected),
                    "observed_net_value": net.mean(), "observed_net_p05": np.quantile(net, 0.05),
                    "stop_no_update_fraction": np.mean(chosen == 0), "wall_p95_ns": np.quantile(wall, 0.95),
                    "wall_p99_ns": np.quantile(wall, 0.99), "inference_cpu_ns": int(cpu.sum())}
        for key, value in computed.items():
            close(metrics[key], value, key)
        require(row["training"]["cpu_ns"] >= 0 and row["training"]["wall_ns"] >= 0, "training costs retained")
        summary = {"panel": p["name"], "seed": seed, "arm": family + "/" + kind,
                   **{k: float(v) for k, v in computed.items()},
                   "training_cpu_s": row["training"]["cpu_ns"] / 1e9,
                   "gradient_mse": row.get("calibration", {}).get("gradient_mse"),
                   "parameters": row["training"]["trainable_parameters"]}
        summaries.append(summary)
        lookup[(family, kind)] = row
        COUNTS["complete"] += 1
    if p["noise"] > 0:
        for family in settings["families"]:
            a, b = lookup[(family, "direct_gradient")], lookup[(family, "z_gradient")]
            require(a["raw"]["choices"] == b["raw"]["choices"], "Z scaling changed a decision")
            close(model_output(a["model"], x), model_output(b["model"], x), "direct_Z_gradient", 1e-10)
            COUNTS["equivalent_Z_pairs"] += 1
    return summaries


def review(source, expected_commit):
    envelope = json.loads((source / "RESULT.json").read_text())
    data = envelope["data"]
    registration = json.loads((source.parents[1] / "REGISTRATION.json").read_text())
    require(registration["source_commit"] == expected_commit, "source publication identity")
    require(data["protocol"] == registration["protocol"]["structure"], "frozen protocol equality")
    require(envelope["source_binding"] == registration["source_binding"], "source manifest binding")
    settings = data["protocol"]
    required = {(p["name"], seed) for p in settings["panels"] for seed in settings["seeds"]}
    panels = {p["name"]: p for p in settings["panels"]}
    identities, paths, summaries, errors = [], set(), [], []
    for entry in data["case_files"]:
        try:
            require(entry["path"] not in paths and Path(entry["path"]).name == entry["path"], "duplicate or invalid shard path")
            paths.add(entry["path"])
            payload = (source / entry["path"]).read_bytes()
            require(len(payload) == entry["bytes"] and hashlib.sha256(payload).hexdigest() == entry["sha256"], "shard byte integrity")
            case = json.loads(payload)
            identities.append((case["panel"]["name"], case["seed"]))
            require(case["panel"] == panels[case["panel"]["name"]], "frozen intervention definition")
            summaries.extend(check_case(case, settings))
        except (ValueError, TypeError, KeyError, IndexError) as error:
            errors.append({"path": entry["path"], "type": type(error).__name__, "error": str(error)})
    require(set(identities) == required and len(identities) == len(required), "full 55-case roster")
    require(COUNTS["records"] == data["record_count"], "reported record count")
    require(COUNTS["unidentified"] == data["unidentified_count"], "reported unidentified count")
    grouped = defaultdict(list)
    for row in summaries:
        grouped[(row["panel"], row["arm"])].append(row)
    panel_means = [{"panel": panel, "arm": arm, "seeds": [r["seed"] for r in rows],
                    **{key: float(np.mean([r[key] for r in rows])) for key in (
                        "expected_net_value", "expected_regret", "observed_net_value", "mean_fee", "training_cpu_s", "inference_cpu_ns")},
                    "gradient_mse": None if rows[0]["gradient_mse"] is None else float(np.mean([r["gradient_mse"] for r in rows])),
                    "parameters": sorted({r["parameters"] for r in rows})}
                   for (panel, arm), rows in sorted(grouped.items())]
    pairs = []
    for panel in panels:
        baseline = {r["seed"]: r for r in grouped[(panel, "quadratic/value")]}
        for candidate in ("linear/direct_gradient", "neural/direct_gradient", "neural/value"):
            rows = grouped[(panel, candidate)]
            differences = [r["expected_net_value"] - baseline[r["seed"]]["expected_net_value"] for r in rows]
            pairs.append({"panel": panel, "candidate": candidate, "reference": "quadratic/value",
                          "paired_expected_net_differences": differences,
                          "mean": float(np.mean(differences)), "positive_seeds": sum(x > 1e-12 for x in differences),
                          "negative_seeds": sum(x < -1e-12 for x in differences)})
    return {"scope": "All raw-record arithmetic and checkpoint inference replay; no retraining or independent administrative provenance.",
            "created_at_utc": datetime.now(timezone.utc).isoformat(), "source_commit": expected_commit,
            "input_result_sha256": hashlib.sha256((source / "RESULT.json").read_bytes()).hexdigest(),
            "source_binding": envelope["source_binding"], "all_checks_passed": not errors,
            "errors": errors, "counts": dict(COUNTS), "maximum_arithmetic_errors": dict(MAX_ERRORS),
            "panel_arm_means": panel_means, "consistent_baseline_descriptive_pairs": pairs,
            "per_seed_summaries": summaries,
            "limits": ["Timing summaries are recomputed from recorded clocks, not independently measured.",
                       "Label/update receipts and hashes do not independently prove the optimizer execution.",
                       "Seven intervention categories are not a matched-capacity or matched-CPU efficacy experiment.",
                       "Five seeds per panel are descriptive; no winner selection, superiority test or future-window claim.",
                       "Action credits omit a physical-compute tariff; no complete net-gain or amortization conclusion."]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--source-commit", required=True)
    args = parser.parse_args()
    result = review(args.source, args.source_commit)
    with args.output.open("x") as stream:
        json.dump(result, stream, sort_keys=True, separators=(",", ":"), allow_nan=False)
        stream.write("\n")
    print(json.dumps({k: result[k] for k in ("all_checks_passed", "counts", "errors", "maximum_arithmetic_errors")}, sort_keys=True))
    raise SystemExit(0 if result["all_checks_passed"] else 1)
