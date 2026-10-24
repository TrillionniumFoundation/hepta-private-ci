"""Source-disjoint learning curves; evaluation labels never enter predictors.

Budgets count real, distinct source groups selected from train without replacement.
This bounded research runner tests supplied frozen features and declared task
labels. It does not establish general task quality or authorize Cell promotion.
"""

import argparse
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import numpy as np

from cell_learning_baselines import FrozenBaselines, normalized_text
from cell_learning_metrics import calibrate_temperature, probabilities, task_metrics
from cell_learning_models import NumpyCellHead, canonical, normalize_features


@dataclass(frozen=True)
class Cohort:
    features: np.ndarray
    labels: np.ndarray
    rows: tuple
    split: str

    def __post_init__(self):
        features, labels = np.array(self.features, copy=True), np.array(self.labels, copy=True)
        normalize_features(features)
        if labels.shape != (len(features),) or labels.dtype.kind not in "iu":
            raise ValueError("cohort labels must be an integer vector")
        if len(self.rows) != len(features) or type(self.split) is not str:
            raise ValueError("cohort row count or split differs")
        rows = tuple(dict(row) for row in self.rows)
        for row in rows:
            if set(row) != {"source_id", "group_id", "text"}:
                raise ValueError("query rows may contain only source_id, group_id and text")
            if any(type(row[k]) is not str or not 1 <= len(row[k].encode()) <= 512
                   for k in ("source_id", "group_id")):
                raise ValueError("bounded source/group identifiers required")
            normalized_text(row["text"])
        features.flags.writeable = labels.flags.writeable = False
        object.__setattr__(self, "features", features)
        object.__setattr__(self, "labels", labels)
        object.__setattr__(self, "rows", rows)

    def digest(self):
        digest = hashlib.sha256(canonical([self.split, self.rows]))
        for array in (self.features, self.labels):
            digest.update(canonical([array.dtype.str, array.shape]))
            digest.update(array.tobytes(order="C"))
        return digest.hexdigest()


def validate_cohorts(train, calibration, holdout, classes):
    if type(classes) is not int or not 2 <= classes <= 256:
        raise ValueError("bounded task class count required")
    cohorts = (train, calibration, holdout)
    if tuple(c.split for c in cohorts) != ("train", "calibration", "holdout"):
        raise ValueError("cohort roles must be train, calibration, holdout")
    seen = {"source_id": set(), "group_id": set(), "text": set()}
    for cohort in cohorts:
        if (cohort.features.shape[1] != train.features.shape[1]
                or np.any(cohort.labels < 0) or np.any(cohort.labels >= classes)):
            raise ValueError("cohort feature widths or labels differ from task")
        for key in seen:
            values = [normalized_text(r[key]) if key == "text" else r[key] for r in cohort.rows]
            if key == "source_id" and len(set(values)) != len(values):
                raise ValueError("duplicate source IDs within a cohort")
            if seen[key].intersection(values):
                raise ValueError(f"cross-split overlap in {key}")
            seen[key].update(values)
    if len(np.unique(train.labels)) != classes:
        raise ValueError("training cohort lacks a declared class")


def training_order(train, classes, seed):
    """Deterministic round-robin classes; no group or normalized text repeats."""
    candidates = [[] for _ in range(classes)]
    for index, row in enumerate(train.rows):
        key = hashlib.sha256(canonical([seed, row["source_id"]])).digest()
        candidates[int(train.labels[index])].append((key, index))
    candidates = [sorted(items, reverse=True) for items in candidates]
    selected, used_groups, used_texts = [], set(), set()
    while any(candidates):
        for items in candidates:
            while items:
                _, index = items.pop()
                row = train.rows[index]
                text = normalized_text(row["text"])
                if row["group_id"] in used_groups or text in used_texts:
                    continue
                selected.append(index)
                used_groups.add(row["group_id"])
                used_texts.add(text)
                break
    return selected


def _score(logits, labels, temperature, threshold, eligible, sources, source_targets):
    p = probabilities(logits, temperature)
    result = {"semantic": task_metrics(p, labels, threshold=threshold, eligible=eligible),
              "logits": np.asarray(logits).tolist(), "probabilities": p.tolist(),
              "eligible": np.asarray(eligible).tolist(), "retrieved_source_ids": sources}
    if source_targets is None:
        result["exact_source_retrieval"] = {"status": "not_evaluated",
            "reason": "semantic labels do not supply source relevance gold"}
    elif sources is None:
        result["exact_source_retrieval"] = {"status": "not_applicable",
            "reason": "parameter-only prediction does not retrieve sources"}
    else:
        returned = [source is not None for source in sources]
        hits = [source is not None and source in target for source, target in zip(sources, source_targets)]
        result["exact_source_retrieval"] = {"status": "evaluated", "rows": len(labels),
            "returned": sum(returned), "hits": sum(hits), "hit_rate_all_rows": float(np.mean(hits)),
            "precision_when_returned": sum(hits) / sum(returned) if any(returned) else None}
    return result


def _fresh_replay(model_dir, root, features_path, identity_path, expected):
    output = model_dir / "replay_logits.npy"
    started = time.perf_counter_ns()
    subprocess.run([sys.executable, str(Path(__file__).resolve()), "replay", "--model", str(model_dir),
                    "--features", str(features_path), "--identity", str(identity_path),
                    "--output", str(output)], check=True, timeout=60, capture_output=True,
                   env={**os.environ, "OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1"})
    actual = np.load(output, allow_pickle=False)
    if actual.shape != expected.shape or not np.allclose(actual, expected, rtol=1e-12, atol=1e-12):
        raise ValueError("fresh-process prediction does not match the frozen live head")
    return {"matched": True, "bitwise_equal": bool(np.array_equal(actual, expected)),
            "max_absolute_error": float(np.max(np.abs(actual - expected))),
            "wall_ns": time.perf_counter_ns() - started,
            "output": str(output.relative_to(root)),
            "output_sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
            "child_inputs": ["frozen_head", "holdout_features", "feature_identity"],
            "test_labels_provided_to_child": False,
            "isolation_scope": "argument/input-file allowlist; child shares the parent filesystem"}


def run_curve(train, calibration, holdout, *, feature_identity, classes, output_dir,
              budgets=(8, 32, 128), seeds=(7, 17, 29), steps=200, rank=8,
              max_parameters=100000, threshold=0.7, retrieval_targets=None):
    """Run a fixed plan; return/write evidence without selecting a test-set winner."""
    validate_cohorts(train, calibration, holdout, classes)
    for values, name, lower, upper in ((budgets, "budgets", 1, 4096), (seeds, "seeds", 0, 2**32 - 1)):
        if (not isinstance(values, (list, tuple)) or not 1 <= len(values) <= 16
                or any(type(x) is not int or not lower <= x <= upper for x in values)
                or len(set(values)) != len(values)):
            raise ValueError(f"invalid bounded {name}")
    if type(threshold) not in (int, float) or not np.isfinite(threshold) or not 0 <= threshold <= 1:
        raise ValueError("invalid predeclared abstention threshold")
    if retrieval_targets is not None:
        if (len(retrieval_targets) != len(holdout.labels)
                or any(not isinstance(target, (list, tuple)) or not target
                       or any(type(x) is not str or not x or len(x.encode()) > 512 for x in target)
                       for target in retrieval_targets)):
            raise ValueError("source relevance gold must be separate nonempty ID lists")
    root = Path(output_dir).resolve()
    root.mkdir(parents=True, exist_ok=False)
    cohorts = (train, calibration, holdout)
    identity_bytes = canonical(feature_identity)
    if not identity_bytes or identity_bytes == b"null" or len(identity_bytes) > 65536:
        raise ValueError("bounded non-null feature identity required")
    module_names = ("cell_learning_curve.py", "cell_learning_models.py", "cell_learning_metrics.py",
                    "cell_learning_baselines.py")
    code_hashes = {name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
                   for name in module_names}
    plan = {"schema": "hepta.cell-learning-curve.v1", "feature_identity": feature_identity,
            "classes": classes, "budgets": list(budgets), "seeds": list(seeds), "steps": steps,
            "rank": rank, "max_parameters": max_parameters, "threshold": threshold,
            "learning_rate": 0.02, "l2": 0.001, "temperature_grid": [0.5, 1.0, 2.0, 4.0, 8.0],
            "arms": ["exact", "bm25", "dense_nearest", "prototype", "linear", "gated", "residual"],
            "controls": ["parameters_off", "shuffled_parameters", "fresh_process"],
            "cohorts": {c.split: {"rows": len(c.labels), "sha256": c.digest()} for c in cohorts},
            "source_sha256": code_hashes, "winner_selection": "none",
            "sampling": "train-only nested round-robin; unique source, group, normalized text",
            "provenance_authenticity_verified_by_runner": False}
    (root / "plan.json").write_bytes(canonical(plan) + b"\n")
    identity_path, features_path = root / "feature_identity.json", root / "holdout_features.npy"
    identity_path.write_bytes(identity_bytes)
    with features_path.open("xb") as stream:
        np.save(stream, holdout.features, allow_pickle=False)
    report = {"plan": plan, "plan_sha256": hashlib.sha256(canonical(plan)).hexdigest(),
              "holdout_source_ids": [r["source_id"] for r in holdout.rows], "runs": [],
              "unavailable": [], "evidence_kind": "supplied_task_empirical_evaluation"}
    overall_started = time.perf_counter_ns()
    for seed in seeds:
        order = training_order(train, classes, seed)
        for budget in budgets:
            indices = order[:budget]
            if len(indices) != budget or len(np.unique(train.labels[indices])) != classes:
                report["unavailable"].append({"seed": seed, "budget": budget,
                    "available_unique_sources": len(order),
                    "reason": "insufficient distinct source groups/texts or class coverage; no upsampling"})
                continue
            x, y = train.features[indices], train.labels[indices]
            rows = [train.rows[i] for i in indices]
            baseline = FrozenBaselines(x, y, rows, classes)
            run = {"seed": seed, "budget": budget, "training_source_ids": [r["source_id"] for r in rows],
                   "training_class_counts": np.bincount(y, minlength=classes).tolist(), "arms": {}}
            for arm in plan["arms"][:4]:
                cal = baseline.predict(arm, calibration.features, calibration.rows)
                temperature, calibration_report = calibrate_temperature(cal["logits"], calibration.labels)
                prediction = baseline.predict(arm, holdout.features, holdout.rows)
                score = _score(prediction["logits"], holdout.labels, temperature, threshold,
                               prediction["eligible"], prediction["retrieved_source_ids"], retrieval_targets)
                run["arms"][arm] = {**score, "temperature": temperature,
                    "calibration": calibration_report, "evaluation_cost": prediction["cost"],
                    "calibration_cost": cal["cost"], "trainable_parameters": 0}
            for mode in plan["arms"][4:]:
                head = NumpyCellHead(x.shape[1], classes, mode, rank, seed, max_parameters)
                training_report = head.train(x, y, steps=steps)
                temperature, calibration_report = calibrate_temperature(
                    head.predict_logits(calibration.features), calibration.labels)
                model_dir = root / f"seed-{seed}_n-{budget}_{mode}"
                head.save(model_dir, feature_identity)
                started = time.perf_counter_ns()
                logits = head.predict_logits(holdout.features)
                prediction_ns = time.perf_counter_ns() - started
                eligibility = np.ones(len(holdout.labels), dtype=bool)
                result = _score(logits, holdout.labels, temperature, threshold, eligibility, None, retrieval_targets)
                result.update(temperature=temperature, calibration=calibration_report, training=training_report,
                              artifact=str(model_dir.relative_to(root)), prediction_wall_ns=prediction_ns,
                              fresh_process=_fresh_replay(model_dir, root, features_path, identity_path, logits))
                result["controls"] = {}
                for control in ("parameters_off", "shuffled_parameters"):
                    altered = NumpyCellHead(x.shape[1], classes, mode, rank, seed, max_parameters)
                    rng = np.random.default_rng(seed)
                    for name, value in sorted(head.params.items()):
                        altered.params[name] = (np.zeros_like(value) if control == "parameters_off" else
                                               rng.permutation(value.ravel()).reshape(value.shape))
                    result["controls"][control] = _score(altered.predict_logits(holdout.features), holdout.labels,
                        temperature, threshold, eligibility, None, retrieval_targets)
                    result["controls"][control]["tensor_sha256"] = altered.digest()
                    result["controls"][control]["temperature_refitted"] = False
                run["arms"][mode] = result
            report["runs"].append(run)
            (root / "report.partial.json").write_bytes(canonical(report) + b"\n")
    if any(c.digest() != plan["cohorts"][c.split]["sha256"] for c in cohorts):
        raise ValueError("cohort mutated during the learning curve")
    if any(hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest() != digest
           for name, digest in code_hashes.items()):
        raise ValueError("runner implementation changed during the experiment")
    report["wall_ns"] = time.perf_counter_ns() - overall_started
    report["status"] = "complete" if not report["unavailable"] else "partial_budgets_unavailable"
    (root / "report.json").write_bytes(canonical(report) + b"\n")
    (root / "report.partial.json").unlink(missing_ok=True)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("replay",))
    for name in ("model", "features", "identity", "output"):
        parser.add_argument(f"--{name}", required=True)
    args = parser.parse_args()
    head = NumpyCellHead.load(args.model, json.loads(Path(args.identity).read_bytes()))
    logits = head.predict_logits(np.load(args.features, allow_pickle=False))
    with Path(args.output).open("xb") as stream:
        np.save(stream, logits, allow_pickle=False)


if __name__ == "__main__":
    main()
