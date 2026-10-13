"""Class-incremental Cell consolidation on verified, previously encoded features.

Invoked after the existing physical Stem study; never downloads or runs another
Encoder. No prior task label, task ID or future outcome is supplied at inference.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
from pathlib import Path
import time

import torch
from safetensors.torch import load, save

from cell_consolidation import (ARMS, ConsolidationConfig, fit_consolidation, metrics,
                                outputs, select_retained, training_partition)
from development_study import prepare_views
from development_study_data import StudyConfig, digest, phase, read_dataset, write_once
from development_study_replay import read_bytes, record, replay


MAX_ERROR = 1e-5


def source_features(source_run, dataset):
    """Reuse the existing full saved-tensor replay, then bind the bytes read here."""
    source_run = Path(source_run)
    upstream, run_sha = record(source_run / "run.json")
    replay(source_run, dataset)
    selection, selection_sha = record(source_run / "selection.json")
    if (record(source_run / "run.json")[1] != run_sha
            or selection_sha != upstream["sealed"]["selection_sha256"]
            or upstream.get("real_weights_executed") is not True):
        raise ValueError("changed source or missing physical-weight execution record")
    config = StudyConfig(**selection["config"]).validate()
    if config.origin != "public_retrospective" or config.time_basis != "publisher_partition":
        raise ValueError("this declared class-incremental diagnostic is public retrospective only")
    rows = read_dataset(dataset, upstream["dataset_sha256"], config)
    raw = read_bytes(source_run / "replay-features.safetensors", 16_777_216)
    if hashlib.sha256(raw).hexdigest() != upstream["sealed"]["replay"]["features_sha256"]:
        raise ValueError("source feature bytes changed")
    tensors = load(raw)
    if set(tensors) != {"features"}:
        raise ValueError("unexpected source feature inventory")
    return rows, tensors["features"], {"run_sha256": run_sha,
        "source_sha": upstream["source_sha"], "dataset_sha256": upstream["dataset_sha256"],
        "features_sha256": hashlib.sha256(raw).hexdigest(),
        "source_encoder_parameters": upstream.get("encoder_parameters"),
        "current_encoder_calls": 0, "prospective_outcomes": False}


def execute(rows, features, origin, output, config=ConsolidationConfig()):
    """Seal configuration and training-derived candidates before evaluation truth."""
    config.validate()
    if any(len(r["options"]) != config.classes for r in rows):
        raise ValueError("fixed output schema mismatch")
    inputs, _ = prepare_views(rows)
    truth = {r["sample_id"]: r["label"] for r in rows if phase(r) in ("base", "adapt")}
    calibration = [i for i, r in enumerate(rows) if phase(r) == "calibration"]
    evaluated = [i for i, r in enumerate(rows) if phase(r) == "held_out"]
    if not calibration or not evaluated:
        raise ValueError("calibration and held-out required")
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    start_cpu, start_wall = time.process_time_ns(), time.perf_counter_ns()
    try:
        plan = {"schema": "hepta.cell.consolidation-plan.v1", "config": asdict(config),
            "source": origin, "class_names": rows[0]["options"],
            "input_digest": digest(inputs),
            "implementation": {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                               for p in sorted(Path(__file__).parent.glob("*.py"))},
            "torch": torch.__version__, "threads": torch.get_num_threads(),
            "production_authorized": False}
        plan_sha = write_once(output / "plan.json", plan)
        models, mean, scale, costs, partition = fit_consolidation(inputs, truth, features, config)
        inventory = {}
        for name, model in models.items():
            raw = save({k: v.detach().contiguous() for k, v in model.state_dict().items()})
            with (output / f"{name}.safetensors").open("xb") as handle:
                handle.write(raw)
            inventory[name] = hashlib.sha256(raw).hexdigest()
        raw = save({"mean": mean, "scale": scale})
        with (output / "normalizer.safetensors").open("xb") as handle:
            handle.write(raw)
        norm_sha = hashlib.sha256(raw).hexdigest()
        with torch.no_grad():
            calibration_logits = outputs(models, (features[calibration]-mean)/scale)
            cal_scores = {name: metrics(value, torch.tensor([rows[i]["label"] for i in calibration]),
                [rows[i]["source_group"] for i in calibration], config)
                for name, value in calibration_logits.items()}
        decision = select_retained(cal_scores, config)
        selection_sha = write_once(output / "selection.json", {**decision,
            "calibration_metrics": cal_scores, "partition": partition, "costs": costs,
            "checkpoints": inventory, "normalizer_sha256": norm_sha})
        # All six inference rules run without task IDs or labels; only scores use truth.
        indices = calibration + evaluated
        predicted = outputs(models, (features[indices]-mean)/scale)
        predictions = [{"sample_id": inputs[i]["sample_id"], "arm": name,
            "input_fingerprint": inputs[i]["input_fingerprint"], "logits": vector}
            for name in ARMS for i, vector in zip(indices, predicted[name].tolist())]
        prediction_sha = write_once(output / "predictions.json", predictions)
        result = {"schema": "hepta.cell.consolidation-run.v1", "plan_sha256": plan_sha,
            "selection_sha256": selection_sha, "predictions_sha256": prediction_sha,
            "current_encoder_calls": 0, "cpu_ns": time.process_time_ns()-start_cpu,
            "wall_ns": time.perf_counter_ns()-start_wall, "production_authorized": False}
        write_once(output / "run.json", result)
        return result
    except Exception as error:
        write_once(output / "FAILED.json", {"error_type": type(error).__name__, "message": str(error),
            "cpu_ns": time.process_time_ns()-start_cpu, "wall_ns": time.perf_counter_ns()-start_wall})
        raise


def affine_logits(tensors, features, classes):
    """Independent FiLM equation, no call to trained module/factory forward."""
    width = features.shape[1]
    shapes = {"gamma": (width,), "beta": (width,), "readout.weight": (classes, width), "readout.bias": (classes,)}
    if set(tensors) != set(shapes) or any(v.dtype != torch.float32 or tuple(v.shape) != shapes[k]
        or not torch.isfinite(v).all() for k, v in tensors.items()):
        raise ValueError("invalid exact FiLM tensor inventory")
    result = (features*tensors["gamma"]+tensors["beta"]) @ tensors["readout.weight"].T+tensors["readout.bias"]
    if not torch.isfinite(result).all():
        raise ValueError("nonfinite independently computed logits")
    return result


def review_rows(rows, features, origin, output, *, score_held_out=True):
    """Check original sealed bytes and recompute predictions/retention before scoring."""
    if type(score_held_out) is not bool:
        raise ValueError("invalid review scoring mode")
    output = Path(output)
    if (output / "FAILED.json").exists():
        raise ValueError("failed consolidation is not scoreable")
    run, run_sha = record(output / "run.json")
    if run["schema"] != "hepta.cell.consolidation-run.v1" or run["current_encoder_calls"] != 0:
        raise ValueError("invalid consolidation execution profile")
    plan, plan_sha = record(output / "plan.json")
    selection, selection_sha = record(output / "selection.json")
    preds, preds_sha = record(output / "predictions.json", 16_777_216)
    if (plan_sha != run["plan_sha256"] or selection_sha != run["selection_sha256"]
        or preds_sha != run["predictions_sha256"] or plan["source"] != origin):
        raise ValueError("consolidation source/sealed files changed")
    raw_config = dict(plan["config"])
    raw_config["old_classes"] = tuple(raw_config["old_classes"])
    config = ConsolidationConfig(**raw_config).validate()
    inputs, _ = prepare_views(rows)
    if digest(inputs) != plan["input_digest"] or plan["class_names"] != rows[0]["options"]:
        raise ValueError("consolidation input meanings changed")
    truth = {r["sample_id"]: r["label"] for r in rows if phase(r) in ("base", "adapt")}
    old, new, memory = training_partition(inputs, truth, config)
    if selection["partition"] != {"old": old, "new": new, "memory": memory}:
        raise ValueError("training/replay partition changed")
    normalizer_raw = read_bytes(output / "normalizer.safetensors", 1_048_576)
    if hashlib.sha256(normalizer_raw).hexdigest() != selection["normalizer_sha256"]:
        raise ValueError("normalizer bytes changed")
    norm = load(normalizer_raw)
    expected_norm = {"mean": features[old].mean(0), "scale": features[old].std(0, unbiased=False).clamp_min(1e-6)}
    if set(norm) != set(expected_norm) or any(norm[k].dtype != torch.float32 or not torch.equal(norm[k], v)
                                           for k, v in expected_norm.items()):
        raise ValueError("normalizer did not use only old training data")
    indices = [i for i, r in enumerate(rows) if phase(r) in ("calibration", "held_out")]
    x = (features[indices]-norm["mean"])/norm["scale"]
    logits = {}
    if set(selection["checkpoints"]) != set(ARMS)-{"teacher_mean"}:
        raise ValueError("incomplete consolidation controls")
    for name, expected in selection["checkpoints"].items():
        raw = read_bytes(output / f"{name}.safetensors", 1_048_576)
        if hashlib.sha256(raw).hexdigest() != expected:
            raise ValueError("checkpoint bytes changed")
        logits[name] = affine_logits(load(raw), x, config.classes)
    import math
    logits["teacher_mean"] = torch.logsumexp(torch.stack((
        torch.log_softmax(logits["frozen"], -1), torch.log_softmax(logits["new_only"], -1))), 0)-math.log(2)
    if type(preds) is not list or len(preds) != len(indices)*len(ARMS):
        raise ValueError("incomplete consolidation prediction census")
    by_key = {}
    for p in preds:
        if type(p) is not dict or set(p) != {"arm", "sample_id", "input_fingerprint", "logits"}:
            raise ValueError("invalid consolidation prediction row")
        key = (p["arm"], p["sample_id"])
        if key in by_key:
            raise ValueError("duplicate consolidation prediction")
        by_key[key] = p
    maximum = 0.
    for name, values in logits.items():
        for i, value in zip(indices, values):
            p = by_key.pop((name, inputs[i]["sample_id"]), None)
            if p is None or p["input_fingerprint"] != inputs[i]["input_fingerprint"]:
                raise ValueError("prediction identity mismatch")
            if type(p["logits"]) is not list or any(type(v) not in (int, float) for v in p["logits"]):
                raise ValueError("untyped consolidation prediction values")
            actual = torch.tensor(p["logits"], dtype=torch.float32)
            if actual.shape != value.shape or not torch.isfinite(actual).all():
                raise ValueError("invalid consolidation prediction values")
            delta = float((value-actual).abs().max())
            if delta > MAX_ERROR or value.argmax() != actual.argmax():
                raise ValueError("consolidation logits fail independent reconstruction")
            maximum = max(maximum, delta)
    if by_key:
        raise ValueError("unexpected consolidation predictions")
    scores = {}
    for p in (("calibration", "held_out") if score_held_out else ("calibration",)):
        mask = [j for j, i in enumerate(indices) if phase(rows[i]) == p]
        labels = torch.tensor([rows[indices[j]]["label"] for j in mask])
        groups = [rows[indices[j]]["source_group"] for j in mask]
        scores[p] = {n: metrics(v[mask], labels, groups, config) for n, v in logits.items()}
    # Recompute the retained decision, not trust a chosen name in a rehashed file.
    decision = select_retained(scores["calibration"], config)
    if any(selection[k] != v for k, v in decision.items()):
        raise ValueError("calibration decision does not reproduce")
    pending = [(selection["calibration_metrics"], scores["calibration"])]
    while pending:
        a, b = pending.pop()
        if isinstance(b, dict):
            if not isinstance(a, dict) or set(a) != set(b):
                raise ValueError("calibration metric schema changed")
            pending.extend((a[k], b[k]) for k in b)
        elif type(a) not in (int, float) or not math.isfinite(a) or abs(a-b) > 1e-6:
            raise ValueError("calibration measurements changed")
    parameter_count = (config.classes+2)*features.shape[1]+config.classes
    costs = selection["costs"]
    if (costs["head_parameters"] != parameter_count or costs["single_head_weight_bytes"] != 4*parameter_count
        or costs["two_teacher_weight_bytes"] != 8*parameter_count or costs["current_encoder_calls"] != 0
        or any(costs[n]["steps"] != config.steps for n in ("parent_training", "new_only", "label_replay", "distilled", "all_old_replay"))):
        raise ValueError("declared parameter/step accounting does not match the protocol")
    return {"schema": "hepta.cell.consolidation-review.v1", "run_sha256": run_sha,
        "selected_arm": decision["selected_arm"], "scores": scores, "prediction_rows": len(preds),
        "unique_held_out_inputs": sum(phase(r) == "held_out" for r in rows),
        "max_abs_logit_error": maximum, "argmax_reversals": 0, "current_encoder_calls": 0,
        "statistical_superiority_established": False, "production_authorized": False}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-run", type=Path, required=True)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--review-run", type=Path)
    args = parser.parse_args()
    torch.set_num_threads(2)
    rows, features, origin = source_features(args.source_run, args.dataset)
    if args.review_run:
        write_once(args.output, review_rows(rows, features, origin, args.review_run))
    else:
        execute(rows, features, origin, args.output)
