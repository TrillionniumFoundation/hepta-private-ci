"""Heteroscedastic, cost-conditioned feedback through original sparse ticks.

Private targets enter supervised fitting and final scoring only. All policy
inputs are reopened numeric artifacts. Analytic event probabilities predict
positive realized repair gain, not merely the sign of a residual.
"""

from dataclasses import asdict
import hashlib
import itertools
import json
import math
from pathlib import Path
import time

import numpy as np
from scipy.special import expit, ndtr

from ..feedback_chain import _archive, native_features
from ..transport import ArtifactTransport
from .pulse import EventDecoder, PulseConfig, SignedEventNeuron


ARMS = ("gaussian", "probit", "numeric", "analytic", "event", "quantized", "history", "zero", "reset")
NATIVE_ARMS = ("numeric", "analytic", "event", "quantized", "zero", "reset")
L2 = (0.001, 0.01, 0.1)
THRESHOLDS = tuple(float(x) / 10 for x in range(11))
UPDATES, RATE, Q24 = 600, 0.15, 1 << 24
POWERS = tuple(p for p in itertools.product(range(4), repeat=3) if sum(p) <= 3)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def dataset_digest(data):
    return digest({k: v.tolist() if isinstance(v, np.ndarray) else v for k, v in data.items()})


def build_dataset(seed, n, split):
    if type(n) is not int or n <= 0 or split not in ("train", "development", "confirmation"):
        raise ValueError("Positive count and declared split required")
    rng = np.random.default_rng(seed)
    initial = rng.normal(size=n)
    error = 0.8 * rng.normal(size=n)
    noise = rng.choice([0.04, 0.36, 1.44], size=n)
    cost = rng.choice([0.03, 0.12, 0.48], size=n)
    target = initial + error
    return {"initial_output": initial, "self_evaluation": target + np.sqrt(noise) * rng.normal(size=n),
            "sensor_variance": noise, "repair_cost": cost, "target": target,
            "ids": np.asarray([f"feedback2:{split}:{seed}:{i}" for i in range(n)]),
            "seed": int(seed), "split": split, "law": "heteroscedastic_gaussian_public_cost_v2"}


def acquire(data, row, arm, transport):
    case = str(data["ids"][row])
    initial = transport.deliver(case, arm, "initial", data["initial_output"][row], "preview")
    observed = transport.observer(case, arm, "self_evaluation", data["self_evaluation"][row])
    noise = transport.observer(case, arm, "sensor_variance", data["sensor_variance"][row])
    cost = transport.observer(case, arm, "repair_cost", data["repair_cost"][row])
    residual = transport.deliver(case, arm, "feedback", observed - initial, "self_evaluation_residual")
    public = {"initial": float(initial), "residual": float(residual),
              "sensor_variance": float(noise), "repair_cost": float(cost)}
    return {"case": case, "public": public, "public_sha256": digest(public),
            "acquired_ns": time.perf_counter_ns()}


def posterior(calibration, public, arm):
    residual, noise, cost = (public[k] for k in ("residual", "sensor_variance", "repair_cost"))
    if not all(math.isfinite(x) for x in public.values()) or noise <= 0 or cost <= 0:
        raise ValueError("Finite public values, positive noise/cost required")
    alpha, scale = calibration["error_variance"], calibration["noise_scale"]
    kappa = alpha / (alpha + scale * noise)
    mean, variance = kappa * residual, alpha * scale * noise / (alpha + scale * noise)
    if arm == "probit":
        # Independent dense joint-Gaussian conditioning, rather than reusing
        # the scalar posterior update used by the analytic arm.
        covariance = np.asarray([[alpha, alpha], [alpha, alpha + scale * noise]])
        solved = np.linalg.solve(covariance[1:, 1:], np.asarray([residual, alpha])[None, :])
        mean = float(covariance[0, 1:] @ solved[:, 0])
        variance = float(covariance[0, 0] - covariance[0, 1:] @ solved[:, 1])
    codec = None
    if arm in ("event", "quantized"):
        config = PulseConfig(**{**calibration["event_config"],
                               "mode": "error_feedback" if arm == "event" else "direct_quantization"})
        neuron, receiver = SignedEventNeuron(config), EventDecoder(config)
        packets = [neuron.update(0.0, alpha, 0.0, "propagation")]
        receiver.apply(packets[0])
        packets.append(neuron.update(mean, variance, 1.0, "observed"))
        receiver.apply(packets[1])
        # The policy receives the independent packet receiver, never an encoder residual.
        mean, variance = receiver.readout()
        codec = {"packets": packets, "decoder": receiver.snapshot(),
                 "encoder": neuron.snapshot(), "logical_unit_events": sum(abs(x) for p in packets for x in p["counts"]),
                 "packet_bytes": sum(len(json.dumps(p, sort_keys=True, separators=(",", ":")).encode()) for p in packets)}
    amount = mean
    if amount == 0.0:
        probability, event, threshold = 0.0, "empty_positive_gain_event", None
    else:
        threshold = (amount * amount + cost) / (2.0 * amount)
        if amount > 0:
            probability, event = float(ndtr((mean - threshold) / math.sqrt(variance))), "call: E>threshold"
        else:
            probability, event = float(ndtr((threshold - mean) / math.sqrt(variance))), "put: E<threshold"
    return {"mean": mean, "variance": variance, "repair_amount": amount,
            "expected_gain": 2.0 * amount * mean - amount * amount - cost,
            "improvement_probability": probability, "event": event, "threshold": threshold, "codec": codec}


def features(acquired, arm, calibration, native):
    public = acquired["public"]
    law = posterior(calibration, public, arm)
    if arm in ("gaussian", "probit"):
        return None, [], law
    raw = np.asarray([public["residual"], math.log(public["sensor_variance"]), math.log(public["repair_cost"])])
    z = (raw - np.asarray(calibration["public_center"])) / np.asarray(calibration["public_scale"])
    if arm == "history":
        polynomial = [float(np.prod(z ** power)) for power in POWERS]
        radial = np.exp(-0.5 * np.sum((np.asarray(calibration["history_centers"]) - z) ** 2, axis=1))
        return np.concatenate((polynomial, radial)), [], law
    if arm == "numeric":
        drives = np.tanh(z / 3.0)
    else:
        logv = (math.log(law["variance"]) - calibration["logvar_center"]) / calibration["logvar_scale"]
        drives = np.asarray([2.0 * law["improvement_probability"] - 1.0, math.tanh(logv / 3.0), math.tanh(z[2] / 3.0)])
    if arm == "zero":
        drives = np.zeros(3)
    native_rows, vector = [], []
    for channel, drive in enumerate(drives):
        quantized = int(round(float(drive) * Q24))
        started = time.perf_counter_ns()
        row = native.tick_pair(acquired["case"] + f"/channel{channel}", acquired["public_sha256"],
                               quantized, reset_before_readout=arm == "reset")
        row.update(channel=channel, evidence_drive=float(drive), feedback_q24=quantized,
                   public_sha256=acquired["public_sha256"], started_ns=started, completed_ns=time.perf_counter_ns())
        vector.extend(native_features(row).tolist())
        native_rows.append(row)
    return np.asarray(vector), native_rows, law


def fit_head(train_x, dev_x, labels, dev_gain, dev_stop):
    center, scale = train_x.mean(0), train_x.std(0)
    center[0], scale[0] = 0.0, 1.0
    scale = np.where(scale > 1e-8, scale, 1.0)
    x, z = (train_x - center) / scale, (dev_x - center) / scale
    candidates = []
    for strength in L2:
        weight = np.zeros(x.shape[1])
        for _ in range(UPDATES):
            penalty = strength * weight
            penalty[0] = 0.0
            gradient = x.T @ (expit(x @ weight) - labels) / len(x) + penalty
            weight -= RATE * gradient
        raw = weight / scale
        raw[0] -= np.dot(raw, center)
        score = expit(dev_x @ raw)
        for threshold in THRESHOLDS:
            action = np.ones(len(score), bool) if threshold == 0 else (np.zeros(len(score), bool) if threshold == 1 else score >= threshold)
            candidates.append({"threshold": threshold, "l2": strength, "utility": float(np.mean(dev_stop + action * dev_gain)),
                               "repairs": int(action.sum()), "weights": raw.tolist(),
                               "gradient_norm": float(np.linalg.norm(gradient)),
                               "training_logloss": float(np.mean(np.logaddexp(0.0, x @ weight) - labels * (x @ weight)))})
    best = max(candidates, key=lambda c: (c["utility"], -c["repairs"], c["l2"], c["threshold"]))
    model = {k: best[k] for k in ("weights", "threshold", "l2")}
    receipt = {"selected": {k: v for k, v in best.items() if k != "weights"},
               "candidates": [{k: v for k, v in c.items() if k != "weights"} for c in candidates],
               "coefficients": len(best["weights"]), "updates_per_l2": UPDATES,
               "initial_weights_sha256": digest([0.0] * len(best["weights"])), "final_weights_sha256": digest(best["weights"]),
               "parameter_l2_change": float(np.linalg.norm(best["weights"])),
               "training_feature_sha256": digest(train_x.tolist()), "training_label_sha256": digest(labels.tolist())}
    return model, receipt


def fit(training, development, native, output):
    if training["split"] != "train" or development["split"] != "development" or set(training["ids"]) & set(development["ids"]):
        raise ValueError("Disjoint train/development data required")
    output = Path(output)
    started, cpu = time.perf_counter_ns(), time.process_time_ns()
    before = (native.calls, native.original_sparse_ticks, native.wall_ns)
    transports, acquired = {}, {}
    for name, data in (("train", training), ("development", development)):
        directory = output / (name + "_readbacks")
        if directory.exists():
            raise FileExistsError(directory)
        transports[name] = ArtifactTransport(directory, "feedback2_" + name)
        acquired[name] = [acquire(data, i, name + "_acquisition", transports[name]) for i in range(len(data["ids"]))]
    error = training["target"] - np.asarray([r["public"]["initial"] for r in acquired["train"]])
    residual = np.asarray([r["public"]["residual"] for r in acquired["train"]])
    noise = np.asarray([r["public"]["sensor_variance"] for r in acquired["train"]])
    alpha, noise_scale = max(float(np.mean(error ** 2)), 1e-8), max(float(np.mean((residual - error) ** 2 / noise)), 1e-8)
    raw = np.asarray([[r["public"]["residual"], math.log(r["public"]["sensor_variance"]), math.log(r["public"]["repair_cost"])] for r in acquired["train"]])
    center, scale = raw.mean(0), np.maximum(raw.std(0), 1e-8)
    standardized = (raw - center) / scale
    centers = standardized[np.linspace(0, len(raw) - 1, 43).astype(int)]
    logv = np.log(alpha * noise_scale * noise / (alpha + noise_scale * noise))
    calibration = {"error_variance": alpha, "noise_scale": noise_scale, "public_center": center.tolist(),
                   "public_scale": scale.tolist(), "history_centers": centers.tolist(),
                   "logvar_center": float(logv.mean()), "logvar_scale": max(float(logv.std()), 1e-8),
                   "event_config": asdict(PulseConfig()), "source": "training_only"}
    matrices, gains, labels, scopes, archives = {}, {}, {}, {}, {}
    for name, data in (("train", training), ("development", development)):
        matrices[name], gains[name], labels[name], scopes[name] = {}, {}, {}, {}
        for arm in ARMS:
            values = []
            for row, public in enumerate(acquired[name]):
                feature, native_rows, law = features(public, arm, calibration, native)
                potential = transports[name].deliver(public["case"], arm, "potential_repair",
                    public["public"]["initial"] + law["repair_amount"], "supervised_potential_repair")
                stop_error = (public["public"]["initial"] - float(data["target"][row])) ** 2
                gain = stop_error - (potential - float(data["target"][row])) ** 2 - public["public"]["repair_cost"]
                values.append({"acquired": public, "feature": None if feature is None else feature.tolist(),
                               "native": native_rows, "posterior": law, "potential_repair": potential,
                               "realized_gain_label": gain, "stop_utility": 1.0 - stop_error})
            scopes[name][arm] = values
            if values[0]["feature"] is not None:
                matrices[name][arm] = np.asarray([v["feature"] for v in values])
            gains[name][arm] = np.asarray([v["realized_gain_label"] for v in values])
            labels[name][arm] = (gains[name][arm] > 0).astype(float)
        archives[name] = _archive(transports[name])
    heads, receipts = {}, {}
    dev_stop = np.asarray([v["stop_utility"] for v in scopes["development"]["gaussian"]])
    for arm in (*NATIVE_ARMS, "history"):
        heads[arm], receipts[arm] = fit_head(matrices["train"][arm], matrices["development"][arm], labels["train"][arm], gains["development"][arm], dev_stop)
    model = {"schema": "hepta.feedback-models.v2", "calibration": calibration, "heads": heads,
             "native_binary_sha256": native.receipt["binary_sha256"], "training_dataset_sha256": dataset_digest(training),
             "development_dataset_sha256": dataset_digest(development), "training_ids_sha256": digest(training["ids"].tolist())}
    receipt = {"schema": "hepta.feedback-training.v2", "model_sha256": digest(model), "scopes": scopes,
               "head_receipts": receipts, "archives": archives, "confirmation_used": False,
               "gaussian_mle": {"initial_parameters": [1.0, 1.0], "fitted_parameters": [alpha, noise_scale],
                   "parameter_l2_change": float(np.linalg.norm(np.asarray([alpha, noise_scale]) - 1.0)),
                   "initial_joint_nll": float(np.mean(0.5 * (np.log(2 * np.pi) + error ** 2) + 0.5 * (np.log(2 * np.pi * noise) + (residual - error) ** 2 / noise))),
                   "fitted_joint_nll": float(np.mean(0.5 * (np.log(2 * np.pi * alpha) + error ** 2 / alpha) + 0.5 * (np.log(2 * np.pi * noise_scale * noise) + (residual - error) ** 2 / (noise_scale * noise))))},
               "wall_ns": time.perf_counter_ns() - started, "cpu_ns": time.process_time_ns() - cpu,
               "native_requests": native.calls - before[0], "native_ticks": native.original_sparse_ticks - before[1],
               "native_roundtrip_ns": native.wall_ns - before[2]}
    return model, receipt


def decision(model, arm, feature, law):
    if arm == "gaussian":
        return bool(law["expected_gain"] > 0), law["improvement_probability"]
    if arm == "probit":
        # For this symmetric Gaussian posterior and repair amount a=E[E|R],
        # P(2*a*E-a²-c>0)>1/2 iff a²-c>0. This identity is task-specific.
        return bool(law["improvement_probability"] > 0.5), law["improvement_probability"]
    head = model["heads"][arm]
    score = float(expit(np.dot(feature, head["weights"])))
    threshold = head["threshold"]
    return (True if threshold == 0 else False if threshold == 1 else score >= threshold), score


def evaluate(model, data, native, output):
    if model["native_binary_sha256"] != native.receipt["binary_sha256"] or digest(data["ids"].tolist()) == model["training_ids_sha256"]:
        raise ValueError("Binary identity mismatch or training contamination")
    started, cpu = time.perf_counter_ns(), time.process_time_ns()
    before = (native.calls, native.original_sparse_ticks, native.wall_ns)
    directory = Path(output) / "evaluation_readbacks"
    if directory.exists():
        raise FileExistsError(directory)
    transport = ArtifactTransport(directory, "feedback2_evaluation")
    rows, summary = [], {}
    for arm in ARMS:
        arm_rows = []
        for index in range(len(data["ids"])):
            began = time.perf_counter_ns()
            acquired = acquire(data, index, arm, transport)
            feature, native_rows, law = features(acquired, arm, model["calibration"], native)
            repair, score = decision(model, arm, feature, law)
            decision_ns = time.perf_counter_ns()
            proposed = acquired["public"]["initial"] + (law["repair_amount"] if repair else 0.0)
            delivered = transport.deliver(acquired["case"], arm, "final", proposed, "repair" if repair else "stop")
            final_ns = time.perf_counter_ns()
            cost = acquired["public"]["repair_cost"] if repair else 0.0
            error = (delivered - float(data["target"][index])) ** 2
            gain_label = (acquired["public"]["initial"] - float(data["target"][index])) ** 2 - (acquired["public"]["initial"] + law["repair_amount"] - float(data["target"][index])) ** 2 - acquired["public"]["repair_cost"]
            result = {"case": acquired["case"], "arm": arm, "acquired": acquired, "posterior": law,
                      "feature": None if feature is None else feature.tolist(), "native": native_rows,
                      "repair": bool(repair), "score": score, "delivered": delivered, "cost": cost,
                      "squared_error": error, "utility": 1.0 - error - cost,
                      "improvement_label": bool(gain_label > 0), "decision_ns": decision_ns,
                      "final_readback_ns": final_ns, "score_started_ns": time.perf_counter_ns(),
                      "wall_ns": time.perf_counter_ns() - began, "model_sha256": digest(model)}
            rows.append(result)
            arm_rows.append(result)
        score = np.clip([r["score"] for r in arm_rows], 1e-12, 1 - 1e-12)
        label = np.asarray([r["improvement_label"] for r in arm_rows], float)
        summary[arm] = {k: float(np.mean([r[k] for r in arm_rows])) for k in ("utility", "cost", "squared_error", "wall_ns")}
        summary[arm].update(repairs=sum(r["repair"] for r in arm_rows), episodes=len(arm_rows),
                            improvement_nll=float(np.mean(-label * np.log(score) - (1 - label) * np.log1p(-score))))
    archive = _archive(transport)
    return {"schema": "hepta.feedback-evaluation.v2", "model_sha256": digest(model), "dataset_sha256": dataset_digest(data),
            "rows": rows, "summary": summary, "archive": archive,
            "wall_ns": time.perf_counter_ns() - started, "cpu_ns": time.process_time_ns() - cpu,
            "native_requests": native.calls - before[0], "native_ticks": native.original_sparse_ticks - before[1],
            "native_roundtrip_ns": native.wall_ns - before[2]}
