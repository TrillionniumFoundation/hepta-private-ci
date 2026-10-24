"""Open final labels only after every registered Cell-field path is sealed.

Intervals are paired, class-stratified source-component bootstrap summaries,
conditional on these fitted models. They are pointwise and do not establish
seed-population, simultaneous-family, prospective or distribution-free claims.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import itertools
import json
from pathlib import Path
import time

import numpy as np

from cell_learning_models import canonical
from cell_field_features import file_hash


def verify_pre_evaluation(root, protocol):
    root = Path(root)
    seal = json.loads((root / "pre_evaluation_seal.json").read_bytes())
    files = seal["files"]
    actual = {str(p.relative_to(root)) for p in root.rglob("*") if p.is_file()
              and p != root / "pre_evaluation_seal.json"}
    if actual != set(files) or seal["final_labels_opened"] is not False:
        raise ValueError("incomplete inventory or final labels already opened during training")
    for name, item in files.items():
        path = root / name
        if (path.is_symlink() or not path.resolve().is_relative_to(root.resolve())
                or path.stat().st_size != item["bytes"] or file_hash(path) != item["sha256"]):
            raise ValueError("pre-evaluation file identity mismatch: " + name)
    runs = json.loads((root / "runs.json").read_bytes())
    plan = json.loads(Path(protocol).read_bytes())
    if (file_hash(protocol) != seal["protocol_sha256"]
            or runs["protocol_sha256"] != seal["protocol_sha256"]):
        raise ValueError("protocol changed after frozen execution")
    expected = set(itertools.product(plan["seeds"], plan["head_modes"],
                                    plan["action_masks"], plan["policies"]))
    keys = [(r["seed"], r["head"], r["mask"], r["policy"]) for r in runs["records"]]
    if len(keys) != len(expected) or set(keys) != expected or seal["record_count"] != len(expected):
        raise ValueError("registered condition census incomplete or duplicated")
    initials = runs["initial_order"]
    initial_keys = [(r["seed"], r["head"]) for r in initials]
    expected_initials = set(itertools.product(plan["seeds"], plan["head_modes"]))
    if len(initial_keys) != len(expected_initials) or set(initial_keys) != expected_initials:
        raise ValueError("initial-state census incomplete or duplicated")
    for initial in initials:
        if initial["status"] not in ("completed", "failed"):
            raise ValueError("unrecognized initial-state disposition")
        if initial["status"] == "completed":
            required = {initial["path"] + "/" + name for name in ("manifest.json", "state.npz")}
            if not required <= set(files):
                raise ValueError("initial checkpoint missing from the sealed inventory")
    for record in runs["records"]:
        index = record["initial_index"]
        if (type(index) is not int or not 0 <= index < len(initials)
                or initial_keys[index] != (record["seed"], record["head"])
                or record["status"] not in ("completed", "failed")):
            raise ValueError("condition differs from its initial-state identity")
        if record["status"] == "completed":
            if initials[index]["status"] != "completed":
                raise ValueError("completed condition has an invalid initial state")
            paths = record["paths"]
            required = {paths[k] for k in ("reference", "controller", "trajectory", "tangent", "receipts")}
            required |= {paths["checkpoint"] + "/" + name for name in ("manifest.json", "state.npz")}
            required |= {paths["head"] + "/" + name for name in ("manifest.json", "weights.npz")}
            if not required <= set(files):
                raise ValueError("completed condition artifacts missing from sealed inventory")
    return seal, runs, plan


def validate_probabilities(values):
    values = np.asarray(values)
    if (values.ndim != 2 or values.shape[1] != 4 or len(values) == 0
            or not np.isfinite(values).all() or np.any(values < 0)
            or not np.allclose(values.sum(axis=1), 1, rtol=0, atol=1e-12)):
        raise ValueError("finite normalized four-class probabilities required")


def metrics(probabilities, labels):
    values, labels = np.asarray(probabilities), np.asarray(labels)
    validate_probabilities(values)
    if (labels.ndim != 1 or values.shape != (len(labels), 4)
            or labels.dtype.kind not in "iu" or set(labels.tolist()) != set(range(4))):
        raise ValueError("valid four-class probabilities and labels required")
    prediction = np.argmax(values, axis=1)
    correct = (prediction == labels).astype(float)
    losses = -np.log(np.maximum(values[np.arange(len(labels)), labels], np.finfo(float).tiny))
    one_hot = np.eye(4)[labels]
    return {"rows": len(labels), "accuracy": float(correct.mean()),
            "balanced_accuracy": float(np.mean([correct[labels == c].mean() for c in range(4)])),
            "nll": float(losses.mean()),
            "brier": float(np.mean(np.square(values - one_hot).sum(axis=1)))}, losses, correct


def stratified_draws(labels, rng, count):
    """One independent source component per row; pair all methods and seeds."""
    draws = [rng.choice(np.flatnonzero(labels == label),
                        (count, int(np.sum(labels == label))), replace=True) for label in range(4)]
    return np.concatenate(draws, axis=1)


def evaluate(run_directory, data, protocol, output):
    began, cpu_began = time.perf_counter_ns(), time.process_time_ns()
    root, data, destination = Path(run_directory), Path(data), Path(output)
    seal, runs, plan = verify_pre_evaluation(root, protocol)
    receipt_bytes = (data / "data_receipt.json").read_bytes()
    receipt = json.loads(receipt_bytes)
    if hashlib.sha256(receipt_bytes).hexdigest() != runs["data_receipt_sha256"]:
        raise ValueError("source cohort receipt changed")
    with np.load(root / "predictions.npz", allow_pickle=False) as archive:
        probabilities = archive["probabilities"]
        initial = archive["initial_probabilities"]
    if (probabilities.shape != (len(runs["records"]), len(runs["source_ids"]), 4)
            or initial.shape != (len(runs["initial_order"]), len(runs["source_ids"]), 4)):
        raise ValueError("prediction census or ordered row shape differs")
    for number, info in enumerate(runs["initial_order"]):
        if info["status"] == "completed":
            validate_probabilities(initial[number])
    for number, info in enumerate(runs["records"]):
        if info["status"] == "completed":
            validate_probabilities(probabilities[number])
    source_bytes = (data / "sources.json").read_bytes()
    if hashlib.sha256(source_bytes).hexdigest() != receipt["files"]["sources.json"]["sha256"]:
        raise ValueError("source grouping changed")
    sources = json.loads(source_bytes)["rows"]
    if [row["source_id"] for row in sources] != runs["source_ids"]:
        raise ValueError("prediction rows differ from source order")
    if len({row["component_id"] for row in sources}) != len(sources):
        raise ValueError("source components are not disjoint")
    destination.mkdir(parents=True, exist_ok=False)
    access = {"schema": "hepta.cell-field-final-label-access.v1",
              "pre_evaluation_seal_sha256": file_hash(root / "pre_evaluation_seal.json"),
              "verified_files": len(seal["files"]), "verified_registered_conditions": len(runs["records"]),
              "before_final_label_open_utc": datetime.now(timezone.utc).isoformat(),
              "source_sha256": file_hash(__file__), "scope": "local execution sequencing; no host attestation"}
    (destination / "label_access.json").write_bytes(canonical(access) + b"\n")
    # The only final-label read occurs after all policy outputs and checkpoints verify.
    payload = (data / "final_labels.json").read_bytes()
    if hashlib.sha256(payload).hexdigest() != receipt["files"]["final_labels.json"]["sha256"]:
        raise ValueError("final labels differ from the pre-model preparation")
    final = json.loads(payload)["roles"]
    if set(final) != {"old_test", "future_may", "future_june"}:
        raise ValueError("unexpected final evaluation roles")
    per_run, per_initial, scores, draws = [], [], {}, {}
    rng = np.random.default_rng(plan["bootstrap_seed"])
    for role in ("old_test", "future_may", "future_june"):
        row = final[role]
        indices, labels = np.asarray(row["indices"]), np.asarray(row["labels"])
        expected_indices = [i for i, source in enumerate(sources) if source["role"] == role]
        if (indices.ndim != 1 or indices.dtype.kind not in "iu"
                or indices.tolist() != expected_indices or labels.shape != indices.shape
                or labels.dtype.kind not in "iu" or set(labels.tolist()) != set(range(4))):
            raise ValueError("final role indices or labels are incomplete or invalid")
        if ([sources[i]["source_id"] for i in indices] != row["source_ids"]
                or any(sources[i]["role"] != role for i in indices)):
            raise ValueError("final role source identity mismatch")
        draws[role] = stratified_draws(labels, rng, plan["bootstrap_replicates"])
        for number, info in enumerate(runs["initial_order"]):
            if info.get("status", "completed") != "completed":
                per_initial.append({"initial_index": number, "seed": info["seed"],
                                    "head": info["head"], "role": role,
                                    "status": "failed", "metrics": None,
                                    "error": info.get("error")})
                continue
            summary, _, _ = metrics(initial[number, indices], labels)
            per_initial.append({"initial_index": number, "seed": info["seed"],
                                "head": info["head"], "role": role, **summary})
        for number, info in enumerate(runs["records"]):
            base = {key: info[key] for key in ("run_id", "seed", "head", "mask", "policy", "status")}
            if info["status"] != "completed":
                per_run.append({**base, "role": role, "metrics": None, "error": info.get("error")})
                continue
            summary, losses, correct = metrics(probabilities[number, indices], labels)
            before, _, _ = metrics(initial[info["initial_index"], indices], labels)
            per_run.append({**base, "role": role, **summary,
                            "nll_change_from_warmup": summary["nll"] - before["nll"],
                            "accuracy_change_from_warmup": summary["accuracy"] - before["accuracy"]})
            scores[(info["seed"], info["head"], info["mask"], info["policy"], role)] = (losses, correct)
    contrasts = []
    pairs = (("loss2", "myopic"), ("extended", "loss2"), ("full", "loss2"), ("loss2", "zero"))
    for head, mask, role, pair in itertools.product(plan["head_modes"], plan["action_masks"],
                                                   ("old_test", "future_may", "future_june"), pairs):
        left, right = pair
        keys = [(seed, head, mask, method, role) for seed in plan["seeds"] for method in pair]
        if any(key not in scores for key in keys):
            contrasts.append({"head": head, "mask": mask, "role": role, "left": left,
                              "right": right, "status": "incomplete_registered_conditions"})
            continue
        for index, metric in enumerate(("nll", "accuracy")):
            delta = np.mean([scores[(seed, head, mask, left, role)][index]
                             - scores[(seed, head, mask, right, role)][index] for seed in plan["seeds"]], axis=0)
            bootstrap = delta[draws[role]].mean(axis=1)
            contrasts.append({"head": head, "mask": mask, "role": role, "left": left,
                "right": right, "metric": metric, "status": "completed",
                "difference_left_minus_right": float(delta.mean()),
                "pointwise_percentile_95": np.quantile(bootstrap, [0.025, 0.975]).tolist(),
                "source_components": len(delta), "fixed_model_seeds": plan["seeds"]})
    summary = {"schema": "hepta.cell-field-evaluation.v1", "protocol_sha256": seal["protocol_sha256"],
        "pre_evaluation_seal_sha256": access["pre_evaluation_seal_sha256"],
        "final_labels_sha256": hashlib.sha256(payload).hexdigest(),
        "records": per_run, "initial": per_initial, "contrasts": contrasts,
        "bootstrap": {"replicates": plan["bootstrap_replicates"], "seed": plan["bootstrap_seed"],
                      "stratification": "four source classes; shared resamples across policies and seeds",
                      "scope": "pointwise; conditional on fitted models and selected historical cohort; no multiplicity or seed-population claim"},
        "resources": {"wall_ns": time.perf_counter_ns() - began,
                      "cpu_ns": time.process_time_ns() - cpu_began},
        "evaluation_source_sha256": file_hash(__file__), "authority": "DENY_ALL"}
    (destination / "evaluation.json").write_bytes(canonical(summary) + b"\n")
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for argument in ("run-directory", "data", "protocol", "output"):
        parser.add_argument("--" + argument, required=True)
    result = evaluate(**vars(parser.parse_args()))
    print(json.dumps({"scored_rows": len(result["records"]), "contrasts": len(result["contrasts"])}))
