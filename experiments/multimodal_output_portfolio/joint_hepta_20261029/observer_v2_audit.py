"""Recompute observer diagnostics from preserved training predictions and labels.

This command reads no natural media, generator target, calibration prediction or
model checkpoint. The empirical diagnostics do not themselves certify an observer.
"""

import argparse
from collections import Counter, defaultdict
import gzip
import json
from pathlib import Path

from .natural_data import digest, write_new
from .natural_eval import source_weights


def training_rows(allocation):
    rows = [{**event, "source_id": source["source_id"], "fold": source["fold"]}
            for source in allocation["selected"] if source["study_role"] == "observer_train"
            for event in source["events"][:source["retained_event_count"]]]
    if not rows or {r["fold"] for r in rows} != set(range(5)):
        raise ValueError("Complete original source folds required")
    folds = defaultdict(set)
    for row in rows:
        folds[row["source_id"]].add(row["fold"])
    if any(len(value) != 1 for value in folds.values()):
        raise ValueError("A source leaked across observer folds")
    return rows


def support_diagnostics(rows, ontology, kind):
    import numpy as np
    weights = source_weights(rows)
    labels = np.asarray([r[kind + "_id"] for r in rows])
    support = {label: {r["source_id"] for r in rows if r[kind + "_id"] == label}
               for label in sorted(map(int, ontology[kind]))}
    fold_labels = {held: {r[kind + "_id"] for r in rows if r["fold"] != held} for held in range(5)}
    unseen = np.asarray([r[kind + "_id"] not in fold_labels[r["fold"]] for r in rows])
    groups = defaultdict(list)
    for i, row in enumerate(rows):
        groups[(row["source_id"], round(row["window_start_seconds"] * 8))].append(i)
    conflict_mass, conflicting_windows = 0.0, 0
    for indices in groups.values():
        mass = defaultdict(float)
        for i in indices:
            mass[int(labels[i])] += float(weights[i])
        if len(mass) > 1:
            conflicting_windows += 1
            conflict_mass += sum(mass.values()) - max(mass.values())
    overlap = np.asarray([
        max(0., min(r["target_end_seconds"], r[kind + "_interval_seconds"][1])
            - max(r["target_start_seconds"], r[kind + "_interval_seconds"][0]))
        / (r["target_end_seconds"] - r["target_start_seconds"]) for r in rows])
    return {
        "classes": len(support), "present_classes": sum(bool(v) for v in support.values()),
        "absent_class_ids": [int(k) for k, v in support.items() if not v],
        "per_class": [{"class_id": int(label), "name": ontology[kind][str(label)],
                       "original_sources": len(sources), "events": int((labels == label).sum()),
                       "source_uniform_mass": float(weights[labels == label].sum())}
                      for label, sources in support.items()],
        "oof_label_absent_from_training_fold_mass": float(weights[unseen].sum()),
        "classes_with_less_than_three_sources_mass": float(sum(w for w, r in zip(weights, rows, strict=True)
                                                               if len(support[r[kind + "_id"]]) < 3)),
        "target_label_coverage_event_quantiles": np.quantile(overlap, [0, .25, .5, .75, 1]).tolist(),
        "target_label_covers_less_than_quarter_source_mass": float(weights[overlap < .25].sum()),
        "contradictory_identical_window_groups": conflicting_windows,
        "empirical_media_only_top1_upper_bound_from_exact_window_conflicts": 1. - conflict_mass,
        "interpretation": "Absent labels and short coverage are observed constraints, not proof that 60% is impossible. The exact-window bound is empirical and conditions on a deterministic media-only prediction."
    }


def audit_predictions(report, majority, rows, kind, ontology):
    import numpy as np
    weights = source_weights(rows)
    labels = np.asarray([r[kind + "_id"] for r in rows])
    source_ids = [r["source_id"] for r in rows]
    classes = sorted(map(int, ontology[kind]))
    expected_majority = []
    for row in rows:
        training = [r for r in rows if r["fold"] != row["fold"]]
        mass = {label: 0. for label in classes}
        for w, training_row in zip(source_weights(training), training, strict=True):
            mass[training_row[kind + "_id"]] += float(w)
        expected_majority.append(max(classes, key=lambda label: mass[label]))
    for candidate, name in ((report, "out_of_fold"), (majority, "majority_control")):
        predicted = candidate["predictions"]
        if (candidate["labels"] != labels.tolist() or candidate["source_ids"] != source_ids
                or len(predicted) != len(rows) or any(value not in classes for value in predicted)
                or (name == "majority_control" and predicted != expected_majority)):
            raise ValueError("OOF evidence does not match original training labels or folds")
        recomputed = float(weights @ (np.asarray(predicted) == labels))
        if not np.isfinite(candidate["source_uniform_accuracy"]) or abs(recomputed - candidate["source_uniform_accuracy"]) > 1e-12:
            raise ValueError("OOF summary differs from its actual predictions")
    predictions = np.asarray(report["predictions"])
    confusion = defaultdict(float)
    for weight, actual, predicted in zip(weights, labels, predictions, strict=True):
        confusion[(int(actual), int(predicted))] += float(weight)
    return {"source_uniform_accuracy": report["source_uniform_accuracy"],
            "majority_source_uniform_accuracy": majority["source_uniform_accuracy"],
            "delta_to_majority": report["source_uniform_accuracy"] - majority["source_uniform_accuracy"],
            "confusion_source_mass": [{"actual": a, "predicted": p, "mass": mass}
                                      for (a, p), mass in sorted(confusion.items())]}


def audit_archive(root, output):
    root = Path(root)
    names = ("OBSERVER_FREEZE.json.gz", "ALLOCATION.json.gz")
    payloads = {name: gzip.decompress((root / name).read_bytes()) for name in names}
    freeze, allocation = (json.loads(payloads[name]) for name in names)
    body = dict(allocation)
    expected = body.pop("allocation_sha256")
    if digest(body) != expected or freeze["allocation_sha256"] != expected:
        raise ValueError("Preserved allocation identity changed")
    rows = training_rows(allocation)
    result = {"schema": "hepta.observer-archived-diagnostic.v2", "original_allocation_sha256": expected,
              "input_sha256": {name: digest(data) for name, data in payloads.items()},
              "original_sources": len({r["source_id"] for r in rows}), "events": len(rows),
              "original_development_passed": freeze["development_passed"], "modalities": {},
              "fresh_media_read": False, "new_training": False, "semantic_qualification": False}
    for kind in ("action", "sound"):
        selected = freeze["selected"][kind]
        result["modalities"][kind] = {"selected": selected["candidate"],
            "support": support_diagnostics(rows, allocation["ontology"], kind),
            "predictions": audit_predictions(selected["out_of_fold"], selected["majority_control"],
                                             rows, kind, allocation["ontology"])}
    write_new(output, result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = audit_archive(args.archive, args.output)
    print(json.dumps({"sources": result["original_sources"], "events": result["events"],
                      "original_development_passed": result["original_development_passed"]}))
