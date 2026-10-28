"""Paired descriptive feedback summaries from complete, audited frozen executions."""

import gzip
import hashlib
import json
from pathlib import Path

import numpy as np

from ..statistics import paired_interval


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _calibration(probability, label):
    probability, label = np.asarray(probability, float), np.asarray(label, bool)
    if not np.isfinite(probability).all() or np.any((probability < 0) | (probability > 1)):
        raise ValueError("Invalid predicted improvement probability")
    bins, error = [], 0.0
    assignment = np.minimum((10 * probability).astype(int), 9)
    for index in range(10):
        selected = assignment == index
        n = int(selected.sum())
        p = float(probability[selected].mean()) if n else None
        y = float(label[selected].mean()) if n else None
        if n:
            error += n / len(label) * abs(p - y)
        bins.append({"bin": index, "count": n, "probability": p, "frequency": y})
    clipped = np.clip(probability, 1e-12, 1 - 1e-12)
    return {"ece": error, "brier": float(np.mean((probability - label) ** 2)),
            "clipped_binary_nll": float(np.mean(-label.astype(float) * np.log(clipped)
                                                - (~label).astype(float) * np.log1p(-clipped))),
            "nll_probability_clip": [1e-12, 1 - 1e-12], "bins": bins}


def summarize(run_dir, protocol):
    run_dir = Path(run_dir)
    frozen = json.loads((run_dir / "FREEZE.json").read_text())
    registration = protocol["feedback"]
    collected = {arm: [] for arm in registration["arms"]}
    receipts, mechanism = [], []
    for seed in registration["seeds"]:
        directory = run_dir / "feedback_confirmation" / f"seed_{seed}"
        summary = json.loads((directory / "SUMMARY.json").read_text())
        audit = json.loads((directory / "AUDIT.json").read_text())
        model_name = f"feedback_training/seed_{seed}/MODELS.json"
        if (not audit["passed"] or summary["models_file_sha256"] != frozen["artifacts_sha256"][model_name]
                or summary["rows_sha256"] != _sha(directory / "ROWS.json.gz")
                or summary["data_file_sha256"] != _sha(directory / "DATA.npz")):
            raise ValueError("Feedback evidence does not match frozen/audited bytes")
        with gzip.open(directory / "ROWS.json.gz", "rt") as stream:
            rows = json.load(stream)
        selected = {}
        for arm in registration["arms"]:
            ordered = sorted((row for row in rows if row["arm"] == arm), key=lambda row: row["case"])
            ids = [row["case"] for row in ordered]
            if len(ids) != registration["confirmation_rows"] or len(set(ids)) != len(ids):
                raise ValueError("Feedback trajectory coverage differs from registration")
            selected[arm] = {key: np.asarray([row[key] for row in ordered]) for key in (
                "utility", "cost", "squared_error", "wall_ns", "repair", "score", "improvement_label")}
            selected[arm]["ids"] = ids
            for row in ordered:
                if abs(row["utility"] - (1 - row["squared_error"] - row["cost"])) > 1e-12:
                    raise ValueError("Feedback utility accounting mismatch")
            collected[arm].append(selected[arm])
        reference_ids = selected[registration["arms"][0]]["ids"]
        if any(item["ids"] != reference_ids for item in selected.values()):
            raise ValueError("Unpaired feedback trajectories")
        mechanism.append({"seed": seed,
            "analytic_vs_numeric_action_disagreements": int(np.sum(selected["analytic"]["repair"] != selected["numeric"]["repair"])),
            "event_vs_numeric_action_disagreements": int(np.sum(selected["event"]["repair"] != selected["numeric"]["repair"])),
            "event_vs_direct_quantization_action_disagreements": int(np.sum(selected["event"]["repair"] != selected["quantized"]["repair"])),
            "gaussian_vs_probit_action_disagreements": int(np.sum(selected["gaussian"]["repair"] != selected["probit"]["repair"]))})
        receipts.append({"seed": seed, "episodes": audit["episodes"],
            "native_ticks_replayed": audit["native_ticks_replayed"], "audit_passed": True,
            "evaluation_wall_ns": summary["wall_ns"], "evaluation_parent_cpu_ns": summary["cpu_ns"],
            "native_roundtrip_ns": summary["native_roundtrip_ns"], "audit_wall_ns": audit["wall_ns"]})
    arms = {}
    for arm, seeds in collected.items():
        flat = {key: np.concatenate([item[key] for item in seeds]) for key in (
            "utility", "cost", "squared_error", "wall_ns", "repair", "score", "improvement_label")}
        arms[arm] = {key: float(flat[key].mean()) for key in ("utility", "cost", "squared_error", "wall_ns")}
        arms[arm].update(episodes=len(flat["utility"]), repairs=int(flat["repair"].sum()),
                         calibration=_calibration(flat["score"], flat["improvement_label"]))
    contrasts = {}
    settings = registration["statistics"]
    for index, (candidate, baseline) in enumerate(registration["contrasts"]):
        delta = np.asarray([a["utility"] - b["utility"]
                            for a, b in zip(collected[candidate], collected[baseline])])
        contrast = paired_interval(delta, settings["bootstrap_replicates"],
                                   settings["bootstrap_seed"] + index, settings["interval_alpha"])
        contrast.update(candidate=candidate, baseline=baseline, descriptive_only=True,
                        production_superiority_established=False)
        contrasts[candidate + "_vs_" + baseline] = contrast
    return {"schema": "hepta.analytic-event.round2.feedback-results.v1", "arms": arms,
            "contrasts": contrasts, "mechanism": mechanism, "execution_receipts": receipts,
            "complete": True, "frozen_model_binding": True,
            "episodes": sum(row["episodes"] for row in receipts),
            "native_ticks_replayed": sum(row["native_ticks_replayed"] for row in receipts),
            "scope": "Five new seeds; paired trajectory secondary comparisons; no multiplicity-adjusted promotion claim"}
