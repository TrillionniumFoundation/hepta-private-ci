"""Independently reconstruct saved AV metrics and validation-only selection.

Does not import the fitted model or av_probe.score. CE uses the explicitly
declared 1e-15 floor; omitting it caused the retained initial audit discrepancy.
"""

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text())


def reconstruct(path):
    with np.load(path, allow_pickle=False) as raw:
        probability, labels = raw["probabilities"], raw["labels"]
        if (probability.ndim != 2 or labels.shape != (len(probability),)
                or not np.isfinite(probability).all() or np.any(probability < 0)
                or not np.allclose(probability.sum(1), 1, atol=1e-12, rtol=0)
                or np.any(labels < 0) or np.any(labels >= probability.shape[1])):
            raise ValueError(f"Invalid probability or target table: {path}")
        correct = probability.argmax(1) == labels
        target_probability = probability[np.arange(len(labels)), labels]
        metrics = dict(accuracy=float(correct.mean()),
            ce=float(-np.log(np.maximum(target_probability, 1e-15)).mean()),
            examples=len(labels))
        actors = {}
        for actor in np.unique(raw["actor_ids"]):
            mask = raw["actor_ids"] == actor
            actors[str(actor)] = dict(accuracy=float(correct[mask].mean()), examples=int(mask.sum()))
        identity = hashlib.sha256()
        for key in ("labels", "sample_ids", "actor_ids", "input_array_sha256"):
            identity.update(key.encode())
            identity.update(np.ascontiguousarray(raw[key]).tobytes())
        return metrics, actors, identity.hexdigest(), int((target_probability < 1e-15).sum())


def audit(results):
    results = Path(results)
    protocol, summary = read_json(results / "protocol.json"), read_json(results / "summary.json")
    source = Path(__file__).with_name("av_probe.py")
    all_selection = read_json(results / "SELECTION_COMPLETE.json")
    report = dict(source_hash_matches_frozen_protocol=digest(source) == protocol["source_sha256"],
        protocol_hash_matches_summary=digest(results / "protocol.json") == summary["protocol_sha256"],
        probability_floor=1e-15, auditor_sha256=digest(__file__), tasks={})
    for task in protocol["tasks"]:
        directory = results / task
        candidates, selection = read_json(directory / "candidates.json"), read_json(directory / "selection.json")
        expected_grid = [(kind, alpha, temperature) for kind in protocol["families"]
                         for alpha in protocol["alphas"] for temperature in protocol["temperatures"]]
        actual_grid = [(row["family"], row["alpha"], row["temperature"]) for row in candidates]
        maximum_error, tables, floor_count, identities = 0., 0, 0, {}
        recomputed = []
        for candidate in candidates:
            for split in ("train", "validation"):
                metrics, _, identity, floored = reconstruct(directory / (candidate["id"] + f"_{split}_predictions.npz"))
                tables += 1
                floor_count += floored
                identities.setdefault(split, set()).add(identity)
                maximum_error = max(maximum_error, *(abs(metrics[key] - candidate[split][key]) for key in metrics))
                if split == "validation":
                    recomputed.append((metrics["ce"], candidate["id"]))
        best_id = min(enumerate(recomputed), key=lambda row: (row[1][0], row[0]))[1][1]
        test_tables, actor_match = 0, True
        for path in sorted(directory.glob("test_*.npz")):
            condition = path.stem.removeprefix("test_")
            metrics, actors, _, floored = reconstruct(path)
            stated = summary["results"][task][condition]
            maximum_error = max(maximum_error, *(abs(metrics[key] - stated[key]) for key in metrics))
            expected_actors = {row["actor"]: {key: row[key] for key in ("accuracy", "examples")}
                               for row in stated["actors"]}
            actor_match = actor_match and actors == expected_actors
            test_tables += 1
            floor_count += floored
        with np.load(directory / "selected_encoder.npz", allow_pickle=False) as chosen:
            with np.load(directory / (selection["id"] + ".npz"), allow_pickle=False) as candidate:
                checkpoint_arrays_match = (set(chosen.files) == set(candidate.files) and
                    all(np.array_equal(chosen[key], candidate[key]) for key in chosen.files))
        row = dict(candidate_count=len(candidates), exact_declared_candidate_grid=actual_grid == expected_grid,
            candidate_prediction_tables=tables, test_prediction_tables=test_tables,
            maximum_metric_error=maximum_error, target_probabilities_below_floor=floor_count,
            identical_inputs_and_targets_across_candidates=all(len(value) == 1 for value in identities.values()),
            selection_is_min_validation_ce=best_id == selection["id"],
            selected_sha_matches=digest(directory / "selected_encoder.npz") == selection["checkpoint_sha256"],
            selected_arrays_match_candidate=checkpoint_arrays_match,
            selection_records_match=selection == all_selection[task] == summary["selections"][task],
            test_actor_metrics_match=actor_match)
        row["passed"] = (maximum_error <= 1e-12 and len(candidates) == len(expected_grid)
            and all(row[key] for key in ("exact_declared_candidate_grid", "identical_inputs_and_targets_across_candidates",
                "selection_is_min_validation_ce", "selected_sha_matches", "selected_arrays_match_candidate",
                "selection_records_match", "test_actor_metrics_match")))
        report["tasks"][task] = row
    report["all_passed"] = (report["source_hash_matches_frozen_protocol"]
        and report["protocol_hash_matches_summary"] and all(row["passed"] for row in report["tasks"].values()))
    report["scope"] = "Saved-table identities, metrics, declared selection and model identity; not independent data relabeling or fresh-actor validation"
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--results", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    report = audit(args.results)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
    print(json.dumps(report, indent=2))
    if not report["all_passed"]:
        raise SystemExit("AV audit failed; output retained")
