"""Secondary original-Hepta two-tick feedback experiment.

Law: draft A~N(0,1), hidden error E~N(0,.8^2), target Y=A+E,
public self-evaluation S=Y+N(0,.6^2). Read back the delivered draft and
the self-evaluation, then write/read R=S-A as text and PNG. Repair delivers
A+kappa*R at cost .12. Only training labels fit kappa and residual variance.

Each native arm trains its own 21-coefficient linear logistic head of the
second tick's activation/eligibility. That tick gets zero fresh drive.
The head never receives R, Y, or counterfactual improvement directly.
Analytic call-minus-put is a deterministic re-encoding of acquired feedback,
not a new information source or an asserted expansion of the function class.

Frozen choices: 600 full-batch gradient steps, rate .15, L2 in
{.001,.01,.1}, and probability thresholds {0,.1,...,1}. Development
selection maximizes realized paired-label utility, then prefers fewer
repairs, stronger regularization and the larger threshold on exact ties.
The history reference has the same 21-coefficient head and all the same
selection opportunities, with polynomial/RBF features of the acquired R.
"""

import hashlib
import json
from pathlib import Path
import shutil
import tarfile
import time

import numpy as np
from scipy.special import expit

from .analytic import event_probs
from .transport import ArtifactTransport, file_digest


ARMS = ("numeric", "analytic_probability", "zero", "state_reset", "matched_history")
Q24 = 1 << 24
REPAIR_COST = 0.12
HEAD_UPDATES = 600
HEAD_RATE = 0.15
HEAD_L2 = (0.001, 0.01, 0.1)
THRESHOLDS = tuple(float(x) / 10 for x in range(11))


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False,
                                     separators=(",", ":")).encode()).hexdigest()


def build_feedback_dataset(seed, n, split):
    if type(n) is not int or n <= 0:
        raise ValueError("Positive integer trajectory count required")
    rng = np.random.default_rng(seed)
    draft = rng.normal(size=n)
    error = 0.8 * rng.normal(size=n)
    target = draft + error
    return {"initial_output": draft, "self_evaluation": target + 0.6 * rng.normal(size=n),
            "target": target, "ids": np.array([f"feedback:{split}:{seed}:{i}" for i in range(n)]),
            "seed": int(seed), "split": str(split), "law": "gaussian_noisy_self_evaluation_v1"}


def _data_digest(data):
    return _digest({key: value.tolist() if isinstance(value, np.ndarray) else value
                    for key, value in data.items()})


def _new_transport(root, name, scope):
    directory = Path(root) / name
    if directory.exists():
        raise FileExistsError("Feedback evidence scope already exists: " + str(directory))
    return ArtifactTransport(directory, scope)


def _archive(transport):
    """Retain every byte in one archive before deleting our own temporary tree."""
    receipt = transport.save_receipts()
    archive = transport.root.with_suffix(".tar.gz")
    if archive.exists():
        raise FileExistsError("Feedback evidence archive already exists")
    started = time.perf_counter_ns()
    inventory = {}
    for path in sorted(transport.root.rglob("*")):
        if path.is_symlink():
            raise ValueError("Unexpected symbolic link in feedback evidence")
        if path.is_file():
            inventory[str(path.relative_to(transport.root))] = {
                "sha256": file_digest(path), "bytes": path.stat().st_size}
    manifest_path = transport.root / "ARCHIVE_MANIFEST.json"
    with manifest_path.open("x") as stream:
        json.dump({"schema": "hepta.feedback-archive-manifest.v1", "files": inventory},
                  stream, sort_keys=True, allow_nan=False)
    manifest_sha = file_digest(manifest_path)
    expected = {**inventory, "ARCHIVE_MANIFEST.json": {
        "sha256": manifest_sha, "bytes": manifest_path.stat().st_size}}
    with tarfile.open(archive, "w:gz") as stream:
        stream.add(transport.root, arcname=transport.root.name)
    verified = set()
    with tarfile.open(archive, "r:gz") as stream:
        for member in stream:
            if member.isdir():
                continue
            if not member.isfile() or not member.name.startswith(transport.root.name + "/"):
                raise ValueError("Unexpected archive member type or path")
            relative = member.name[len(transport.root.name) + 1:]
            if relative not in expected or relative in verified:
                raise ValueError("Unexpected or duplicate archive evidence file")
            digest = hashlib.sha256()
            with stream.extractfile(member) as content:
                for block in iter(lambda: content.read(1 << 20), b""):
                    digest.update(block)
            if digest.hexdigest() != expected[relative]["sha256"] or member.size != expected[relative]["bytes"]:
                raise ValueError("Archive evidence differs from source file")
            verified.add(relative)
    if verified != set(expected):
        raise ValueError("Archive omitted evidence files; originals retained")
    archive_sha = file_digest(archive)
    shutil.rmtree(transport.root)
    return {"archive_path": str(archive), "archive_sha256": archive_sha,
            "archive_bytes": archive.stat().st_size, "archive_ns": time.perf_counter_ns() - started,
            "receipt_member": transport.root.name + "/TRANSPORT_RECEIPTS.jsonl",
            "receipt_sha256": receipt["receipt_sha256"], "observations": receipt["observations"],
            "deliveries": receipt["deliveries"], "files": receipt["files"],
            "manifest_member": transport.root.name + "/ARCHIVE_MANIFEST.json", "manifest_sha256": manifest_sha,
            "all_file_sha256_verified_before_removal": True, "verified_archive_files": len(verified)}


def _acquire(data, row, arm, transport):
    """Only the two registered public fields can cross the acquisition boundary."""
    case = str(data["ids"][row])
    initial = transport.deliver(case, arm, "initial", float(data["initial_output"][row]), "preview")
    initial_ns = time.perf_counter_ns()
    observation = float(transport.observer(case, arm, "self_evaluation", float(data["self_evaluation"][row])))
    observed_ns = time.perf_counter_ns()
    feedback = transport.deliver(case, arm, "feedback", observation - initial, "self_evaluation_residual")
    readback = transport.receipts[-1]
    # Both hashes are of actual reopened artifact bytes. No path, arm or target
    # enters the digest, so paired arms with equal readbacks share input identity.
    readback_digest = _digest({key: readback[key] for key in ("text_sha256", "image_sha256")})
    return {"case": case, "initial_readback": float(initial), "self_evaluation_readback": observation,
            "feedback_readback": float(feedback), "readback_digest": readback_digest,
            "initial_readback_ns": initial_ns, "self_evaluation_readback_ns": observed_ns,
            "feedback_readback_ns": time.perf_counter_ns(),
            "feedback_text_path": readback["text_path"], "feedback_image_path": readback["image_path"],
            "feedback_text_sha256": readback["text_sha256"], "feedback_image_sha256": readback["image_sha256"]}


def _encoding(feedback, arm, calibration):
    if arm == "zero":
        evidence = 0.0
    elif arm == "numeric":
        evidence = float(np.clip(feedback / calibration["numeric_scale"], -1.0, 1.0))
    else:
        probabilities = event_probs(calibration["kappa"] * feedback,
                                    calibration["conditional_variance"], 0.0, 0.0)
        evidence = float(probabilities[2] - probabilities[0])
    return evidence, int(np.rint(evidence * Q24))


def native_features(receipt):
    ticks = receipt["ticks"]
    if (len(ticks) != 2 or receipt.get("original_sparse_tick_calls") != 2
            or any(t["authority"] != "DENY_ALL" or not t["requires_calibration"] for t in ticks)
            or ticks[1]["drive_q24"] != [0] * 10):
        raise ValueError("Invalid original-Hepta two-tick receipt")
    expected = "0" * 64 if receipt["checkpoint_reset_intervention"] else ticks[0]["checkpoint_after"]
    if ticks[1]["checkpoint_before"] != expected:
        raise ValueError("Broken native checkpoint chain")
    feature = np.array([1.0] + [value / Q24 for key in ("activation_q24", "eligibility_q24")
                               for value in ticks[1][key]], dtype=float)
    if feature.shape != (21,) or not np.isfinite(feature).all():
        raise ValueError("Invalid 21-coefficient native state feature")
    return feature


def _history_features(feedback, calibration):
    z = float(feedback) / calibration["history_scale"]
    radial = np.exp(-0.5 * ((z - np.asarray(calibration["history_centers"])) / 0.5) ** 2)
    return np.concatenate(([1.0, z, z * z, z * z * z], radial))


def _state_feature(public, arm, calibration, native):
    if arm == "matched_history":
        return _history_features(public["feedback_readback"], calibration), None
    evidence, quantized = _encoding(public["feedback_readback"], arm, calibration)
    before = time.perf_counter_ns()
    receipt = native.tick_pair(public["case"], public["readback_digest"], quantized,
                               reset_before_readout=arm == "state_reset")
    receipt.update(feedback_q24=quantized, evidence_drive=evidence,
                   readback_digest=public["readback_digest"], started_ns=before,
                   completed_ns=time.perf_counter_ns())
    return native_features(receipt), receipt


def _repairs(probability, threshold):
    if threshold == 0.0:
        return np.ones_like(probability, dtype=bool)
    if threshold == 1.0:
        return np.zeros_like(probability, dtype=bool)
    return probability >= threshold


def _fit_head(train_x, dev_x, labels, dev_gain, dev_stop_utility):
    center, scale = train_x[:, 1:].mean(0), train_x[:, 1:].std(0)
    scale = np.where(scale > 1e-8, scale, 1.0)
    x = np.column_stack([np.ones(len(train_x)), (train_x[:, 1:] - center) / scale])
    z = np.column_stack([np.ones(len(dev_x)), (dev_x[:, 1:] - center) / scale])
    candidates = []
    for strength in HEAD_L2:
        weights = np.zeros(21)
        for _ in range(HEAD_UPDATES):
            regularizer = strength * weights
            regularizer[0] = 0.0
            gradient = x.T @ (expit(x @ weights) - labels) / len(x) + regularizer
            weights -= HEAD_RATE * gradient
        probability = expit(z @ weights)
        raw = np.concatenate(([weights[0] - np.dot(weights[1:], center / scale)], weights[1:] / scale))
        fit = {"weights": raw.tolist(), "l2": strength, "gradient_updates": HEAD_UPDATES,
               "gradient_norm": float(np.linalg.norm(gradient)),
               "initial_logloss": float(np.log(2.0)),
               "final_training_logloss": float(np.mean(np.logaddexp(0, x @ weights) - labels * (x @ weights))),
               "parameter_l2_change": float(np.linalg.norm(raw)), "initial_parameter_sha256": _digest([0.0] * 21),
               "final_parameter_sha256": _digest(raw.tolist()),
               "varying_state_coordinates": int(np.sum(train_x[:, 1:].std(0) > 1e-8))}
        for threshold in THRESHOLDS:
            actions = _repairs(probability, threshold)
            utility = float(np.mean(dev_stop_utility + actions * dev_gain))
            candidates.append({"threshold": threshold, "development_paired_label_utility": utility,
                               "development_repairs": int(actions.sum()), "l2": strength, "fit": fit})
    best = max(candidates, key=lambda r: (r["development_paired_label_utility"], -r["development_repairs"],
                                          r["l2"], r["threshold"]))
    model = {"weights": best["fit"]["weights"], "threshold": best["threshold"], "l2": best["l2"]}
    return model, {"selected_fit": best["fit"], "candidates": [
        {key: value for key, value in candidate.items() if key != "fit"} for candidate in candidates],
        "train_feature_sha256": _digest(train_x.tolist()), "train_label_sha256": _digest(labels.tolist()),
        "native_kernel_parameters_trained": False, "head_coefficients": 21}


def fit_feedback_models(training, development, native, artifact_root):
    if training["split"] != "train" or development["split"] != "development":
        raise ValueError("Only training and development splits may fit feedback models")
    if set(training["ids"]) & set(development["ids"]) or training["seed"] == development["seed"]:
        raise ValueError("Training and development feedback trajectories must be independent")
    began, cpu_began = time.perf_counter_ns(), time.process_time_ns()
    native_before = (native.calls, native.original_sparse_ticks, native.wall_ns)
    transport = {name: _new_transport(artifact_root, name + "_readbacks", "feedback_" + name)
                 for name in ("train", "development")}
    public = {"train": [_acquire(training, i, "train_acquisition", transport["train"])
                        for i in range(len(training["ids"]))],
              "development": [_acquire(development, i, "development_acquisition", transport["development"])
                              for i in range(len(development["ids"]))]}
    residual = np.array([r["feedback_readback"] for r in public["train"]])
    error = training["target"] - np.array([r["initial_readback"] for r in public["train"]])
    kappa = float(np.clip(np.dot(error, residual) / max(np.dot(residual, residual), 1e-12), 0.0, 1.0))
    scale = max(float(np.std(residual)), 1e-6)
    calibration = {"kappa": kappa, "conditional_variance": max(float(np.mean((error - kappa * residual) ** 2)), 1e-6),
                   "numeric_scale": 3.0 * scale, "history_scale": scale,
                   "history_centers": np.quantile(residual / scale, np.linspace(0.05, 0.95, 17)).tolist(),
                   "source": "training_only", "repair_cost": REPAIR_COST}
    scope_records, matrices, gains, stop_utility = {}, {}, {}, {}
    for name, data in (("train", training), ("development", development)):
        matrices[name], native_rows = {}, {}
        for arm in ARMS:
            values = [_state_feature(row, arm, calibration, native) for row in public[name]]
            matrices[name][arm] = np.stack([value[0] for value in values])
            native_rows[arm] = [value[1] for value in values]
        repaired = []
        for row in public[name]:
            proposal = row["initial_readback"] + kappa * row["feedback_readback"]
            repaired.append(transport[name].deliver(row["case"], name + "_acquisition",
                            "repair_label", proposal, "supervised_potential_repair"))
        initial = np.array([row["initial_readback"] for row in public[name]])
        stop_error = (initial - data["target"]) ** 2
        gain = stop_error - (np.asarray(repaired) - data["target"]) ** 2 - REPAIR_COST
        gains[name], stop_utility[name] = gain, 1.0 - stop_error
        scope_records[name] = {"public_rows": public[name], "native_rows": native_rows,
                              "potential_repair_readbacks": repaired, "repair_improvement_labels": gain.tolist(),
                              "positive_improvement_labels": (gain > 0).astype(int).tolist(),
                              "private_targets_for_supervised_labels": data["target"].tolist(),
                              "dataset_sha256": _data_digest(data), "trajectories": len(initial),
                              "state_feature_checks": {arm: {
                                  "varying_coordinates_excluding_intercept": int(np.sum(matrices[name][arm][:, 1:].std(0) > 1e-8)),
                                  "all_state_coordinates_zero": bool(np.all(matrices[name][arm][:, 1:] == 0.0))}
                                  for arm in ARMS}}
    heads, head_receipts = {}, {}
    labels = (gains["train"] > 0).astype(float)
    for arm in ARMS:
        heads[arm], head_receipts[arm] = _fit_head(matrices["train"][arm], matrices["development"][arm],
                                                 labels, gains["development"], stop_utility["development"])
    models = {"schema": "hepta.analytic-event.feedback-models.v1", "calibration": calibration, "heads": heads,
              "native_binary_sha256": native.receipt["binary_sha256"],
              "training_ids_sha256": _digest(training["ids"].tolist()),
              "training_dataset_sha256": _data_digest(training), "development_dataset_sha256": _data_digest(development)}
    archives = {name: _archive(value) for name, value in transport.items()}
    native_accounting = {"requests": native.calls - native_before[0],
                         "original_sparse_ticks": native.original_sparse_ticks - native_before[1],
                         "adapter_roundtrip_ns": native.wall_ns - native_before[2],
                         "kernel_tick_ns": sum(tick["native_ns"] for scope in scope_records.values()
                             for native_rows in scope["native_rows"].values() for row in native_rows if row
                             for tick in row["ticks"])}
    if native_accounting["requests"] != 4 * (len(training["ids"]) + len(development["ids"])) or native_accounting["original_sparse_ticks"] != 2 * native_accounting["requests"]:
        raise ValueError("Feedback training native-accounting discrepancy")
    return models, {"schema": "hepta.analytic-event.feedback-training.v1", "scopes": scope_records,
                    "head_receipts": head_receipts, "archives": archives, "model_sha256": _digest(models),
                    "head_updates": HEAD_UPDATES, "head_rate": HEAD_RATE, "head_l2": list(HEAD_L2),
                    "thresholds": list(THRESHOLDS), "wall_ns": time.perf_counter_ns() - began,
                    "cpu_ns": time.process_time_ns() - cpu_began, "native_accounting": native_accounting,
                    "confirmation_used": False}


def evaluate_feedback_chain(models, data, native, artifact_root):
    if models["native_binary_sha256"] != native.receipt["binary_sha256"]:
        raise ValueError("Feedback evaluation must use the trained, frozen native build")
    if _digest(data["ids"].tolist()) == models["training_ids_sha256"]:
        raise ValueError("Training trajectories are not evaluation evidence")
    began, cpu_began = time.perf_counter_ns(), time.process_time_ns()
    native_before = (native.calls, native.original_sparse_ticks, native.wall_ns)
    transport = _new_transport(artifact_root, "evaluation_readbacks", "feedback_evaluation")
    calibration, rows, summary = models["calibration"], [], {}
    for arm in ARMS:
        head, arm_rows = models["heads"][arm], []
        for index, identity in enumerate(data["ids"]):
            started, cpu_started = time.perf_counter_ns(), time.process_time_ns()
            public = _acquire(data, index, arm, transport)
            feature, native_receipt = _state_feature(public, arm, calibration, native)
            # For native arms the only predictive input here is the actual
            # second-tick state. The public scalar is not a head argument.
            score = float(feature @ np.asarray(head["weights"]))
            probability = float(expit(score))
            repair = bool(_repairs(np.asarray([probability]), head["threshold"])[0])
            action = "repair" if repair else "stop"
            decision_ns = time.perf_counter_ns()
            proposal = public["initial_readback"] + (calibration["kappa"] * public["feedback_readback"] if repair else 0.0)
            delivered = float(transport.deliver(str(identity), arm, "final", proposal, action))
            final_readback_ns = time.perf_counter_ns()
            # First private target read in this online episode: after the action
            # and final delivery, never during feedback acquisition or selection.
            score_started_ns = time.perf_counter_ns()
            target = float(data["target"][index])
            paid_cost = REPAIR_COST if repair else 0.0
            squared_error = (delivered - target) ** 2
            potential = public["initial_readback"] + calibration["kappa"] * public["feedback_readback"]
            gain = (public["initial_readback"] - target) ** 2 - (potential - target) ** 2 - REPAIR_COST
            arm_rows.append({**public, "arm": arm, "native": native_receipt,
                "head_features": feature.tolist(), "head_score": score, "head_probability": probability,
                "head_threshold": head["threshold"], "action": action, "decision_ns": decision_ns,
                "proposed_final_prediction": proposal, "delivered_prediction": delivered,
                "final_readback_ns": final_readback_ns, "score_started_ns": score_started_ns,
                "terminal_target": target, "paid_cost": paid_cost, "squared_error": squared_error,
                "utility": 1.0 - squared_error - paid_cost, "repair_improvement_if_taken": gain,
                "profitable_choice": repair == (gain > 0), "actual_transport": True,
                "model_sha256": _digest(models), "elapsed_ns": time.perf_counter_ns() - started,
                "cpu_ns": time.process_time_ns() - cpu_started})
        rows.extend(arm_rows)
        utility = np.array([row["utility"] for row in arm_rows])
        summary[arm] = {"trajectories": len(arm_rows), "mean_utility": float(utility.mean()),
            "mean_squared_error": float(np.mean([row["squared_error"] for row in arm_rows])),
            "mean_action_cost": float(np.mean([row["paid_cost"] for row in arm_rows])),
            "repair_count": sum(row["action"] == "repair" for row in arm_rows),
            "severe_loss_fraction": float(np.mean(utility < -2.0)),
            "profitable_choice_fraction": float(np.mean([row["profitable_choice"] for row in arm_rows])),
            "varying_state_coordinates_excluding_intercept": int(np.sum(np.asarray([row["head_features"][1:] for row in arm_rows]).std(0) > 1e-8)),
            "native_ticks": sum(0 if row["native"] is None else 2 for row in arm_rows),
            "wall_ns": sum(row["elapsed_ns"] for row in arm_rows), "cpu_ns": sum(row["cpu_ns"] for row in arm_rows)}
    numeric = [row for row in rows if row["arm"] == "numeric"]
    for arm in ARMS:
        selected = [row for row in rows if row["arm"] == arm]
        summary[arm]["action_disagreements_with_numeric"] = sum(a["action"] != b["action"] for a, b in zip(selected, numeric))
        summary[arm]["state_value_disagreements_with_numeric"] = None if arm == "matched_history" else sum(
            a["head_features"] != b["head_features"] for a, b in zip(selected, numeric))
    archive = _archive(transport)
    native_accounting = {"requests": native.calls - native_before[0],
                         "original_sparse_ticks": native.original_sparse_ticks - native_before[1],
                         "adapter_roundtrip_ns": native.wall_ns - native_before[2],
                         "kernel_tick_ns": sum(tick["native_ns"] for row in rows if row["native"]
                                               for tick in row["native"]["ticks"])}
    if native_accounting["requests"] != 4 * len(data["ids"]) or native_accounting["original_sparse_ticks"] != 2 * native_accounting["requests"]:
        raise ValueError("Feedback evaluation native-accounting discrepancy")
    return {"schema": "hepta.analytic-event.feedback-evaluation.v1", "rows": rows, "summary": summary,
            "archive": archive, "dataset_sha256": _data_digest(data), "model_sha256": _digest(models),
            "wall_ns": time.perf_counter_ns() - began, "cpu_ns": time.process_time_ns() - cpu_began,
            "native_accounting": native_accounting,
            "private_target_first_read_after_final_delivery": True, "actual_transport": True,
            "scope": "secondary original sparse two-tick bridge; no production-owner authority"}
