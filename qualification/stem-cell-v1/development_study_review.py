"""Read-only scoring AFTER immutable predictions, never training or selection.

Integrity diagnostics are not independently signed outcomes or NDU authority.
"""
from __future__ import annotations

import argparse
import hashlib
import math
from pathlib import Path

from development_study_data import StudyConfig, digest, phase, public_input, read_dataset, write_once


def score_predictions(predictions, rows, arms, classes):
    expected = {r["sample_id"]: r for r in rows if phase(r) not in {"base", "adapt", "extra", "calibration"}}
    if (not isinstance(predictions, list) or not {"frozen", "continued", "wider", "more_data"} <= set(arms)
            or len(predictions) != len(expected) * len(arms)
            or len(set(arms)) != len(arms) or not set(arms) <= {"frozen", "continued", "wider", "more_data", "split"}):
        raise ValueError("incomplete paired prediction census")
    scores, seen = {}, set()
    for p in predictions:
        if set(p) != {"sample_id", "arm", "input_fingerprint", "logits"}:
            raise ValueError("predictions cannot contain truth, score or unknown fields")
        key = (p["sample_id"], p["arm"])
        if key in seen or p["sample_id"] not in expected or p["arm"] not in arms:
            raise ValueError("duplicate or foreign prediction")
        seen.add(key)
        row, logits = expected[p["sample_id"]], p["logits"]
        if (p["input_fingerprint"] != digest(public_input(row)) or not isinstance(logits, list)
                or len(logits) != classes or any(type(v) not in (int, float) or not math.isfinite(v) for v in logits)):
            raise ValueError("input-bound finite logits required")
        values = [math.exp(v - max(logits)) for v in logits]
        probabilities = [v / sum(values) for v in values]
        correct = float(max(range(classes), key=logits.__getitem__) == row["label"])
        brier = sum((v - float(i == row["label"]))**2 for i, v in enumerate(probabilities))
        bucket = scores.setdefault(p["arm"], {}).setdefault(phase(row), {})
        bucket.setdefault(row["source_group"], []).append((correct, brier))
    report = {}
    for arm, splits in scores.items():
        report[arm] = {}
        for split, groups in splits.items():
            means = [(sum(x[0] for x in rows) / len(rows), sum(x[1] for x in rows) / len(rows))
                     for rows in groups.values()]
            report[arm][split] = {"rows": sum(len(v) for v in groups.values()),
                "source_groups": len(groups), "group_mean_accuracy": sum(v[0] for v in means) / len(means),
                "group_mean_brier": sum(v[1] for v in means) / len(means)}
    return {"arms": report, "statistical_superiority_established": False,
            "future_observations_authenticated": False, "production_authorized": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if (args.run / "FAILED.json").exists():
        raise ValueError("failed execution cannot be scored as a successful run")
    import json
    from study import reject_duplicate_evidence_fields, reject_nonstandard_evidence_number, parse_finite_evidence_float
    def read_record(name, limit):
        path = args.run / name
        if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= limit:
            raise ValueError("invalid bounded experiment file")
        with path.open("rb") as handle:
            raw = handle.read(limit + 1)
        if len(raw) > limit:
            raise ValueError("experiment file grew past its bound")
        parsed = json.loads(raw, object_pairs_hook=reject_duplicate_evidence_fields,
            parse_constant=reject_nonstandard_evidence_number, parse_float=parse_finite_evidence_float)
        return parsed, hashlib.sha256(raw).hexdigest()
    run, _ = read_record("run.json", 1024 * 1024)
    selection, selection_sha = read_record("selection.json", 1024 * 1024)
    predictions, predictions_sha = read_record("predictions.json", 64 * 1024 * 1024)
    if (selection_sha != run["sealed"]["selection_sha256"]
            or predictions_sha != run["sealed"]["predictions_sha256"]):
        raise ValueError("sealed experiment output changed")
    if run.get("schema") != "hepta.stem.structural-run.v2":
        raise ValueError("use the historical source for legacy unbound run scoring")
    # Old pre-v2 runs without a normalizer binding remain historical-only.
    from development_study_replay import verify_checkpoint_files
    verify_checkpoint_files(args.run, run["sealed"], selection)
    config = StudyConfig(**selection["config"]).validate()
    rows = read_dataset(args.dataset, run["dataset_sha256"], config)
    result = score_predictions(predictions, rows, tuple(selection["checkpoints"]), config.classes)
    result.update({"selected_arm": selection["selected_arm"], "origin": config.origin,
                   "time_basis": config.time_basis,
                   "source_sha": run["source_sha"], "sealed": run["sealed"]})
    write_once(args.output, result)


if __name__ == "__main__":
    main()
