"""Independent terminal scoring for the bounded COCO grounding experiment.

The scorer consumes references only after generation. A valid annotation PNG
is evidence of an executed annotation plan, not learned pixel generation.
Bootstrap intervals are descriptive source-cluster intervals, not p-values.
"""

import argparse
from collections import defaultdict
import hashlib
import io
import json
import math
from pathlib import Path
import re

import numpy as np
from PIL import Image

BASELINES = ("base", "static_cells", "learned_router", "best_of_n", "mean_only",
             "risk_actor_critic", "ndu")
ABLATIONS = ("ablate_covariance", "ablate_fixed_weights", "ablate_crossmodal",
             "ablate_missing_modality", "ablate_shuffled_pair")
METHODS = BASELINES + ABLATIONS
MODEL_COMPONENTS = {"encoder", "backbone", "generator", "model"}
REQUIRED_COST_COMPONENTS = {"encoder", "backbone", "cell", "controller", "critic",
                            "verifier", "render", "communication"}
TEXT = re.compile(r"There are (\d+) (.+?) instances\. "
                  r"(?:The largest instance is on the (left|right)\.|(No largest instance\.))")


def finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def normalized_label(value):
    return " ".join(value.casefold().split()) if isinstance(value, str) else ""


def validate_boxes(boxes):
    if not isinstance(boxes, list) or len(boxes) > 256:
        raise ValueError("boxes must be a list with at most 256 entries")
    for box in boxes:
        if (not isinstance(box, (list, tuple)) or len(box) != 4
                or not all(finite(v) and 0 <= v <= 1 for v in box)
                or box[0] >= box[2] or box[1] >= box[3]):
            raise ValueError("boxes require finite normalized positive-area XYXY coordinates")
    return boxes


def largest_side(boxes):
    if not boxes:
        return "none"
    box = max(boxes, key=lambda b: (b[2] - b[0]) * (b[3] - b[1]))
    return "left" if (box[0] + box[2]) / 2 < 0.5 else "right"


def iou(a, b):
    overlap = max(0.0, min(a[2], b[2]) - max(a[0], b[0])) * max(
        0.0, min(a[3], b[3]) - max(a[1], b[1]))
    union = ((a[2] - a[0]) * (a[3] - a[1])
             + (b[2] - b[0]) * (b[3] - b[1]) - overlap)
    return overlap / union


def matching_score(predicted, reference, threshold=0.5):
    """Maximum-cardinality bipartite matching; each reference counts once.

    Descending IoU and stable indices break ties. Augmenting paths avoid the
    incorrect greedy matching that can miss a valid second match.
    """
    predicted, reference = validate_boxes(predicted), validate_boxes(reference)
    adjacency = [sorted((j for j, gold in enumerate(reference) if iou(box, gold) >= threshold),
                        key=lambda j: (-iou(box, reference[j]), j)) for box in predicted]
    assigned = {}

    def augment(index, visited):
        for target in adjacency[index]:
            if target not in visited:
                visited.add(target)
                if target not in assigned or augment(assigned[target], visited):
                    assigned[target] = index
                    return True
        return False

    for index in range(len(predicted)):
        augment(index, set())
    matches = len(assigned)
    f1 = 2 * matches / (len(predicted) + len(reference)) if predicted or reference else 1.0
    return {"matches": matches, "predicted_count": len(predicted),
            "reference_count": len(reference), "box_f1": f1}


def parse_text(text):
    match = TEXT.fullmatch(text.strip()) if isinstance(text, str) else None
    if not match:
        return None
    count, label, side, empty = match.groups()
    if (int(count) == 0) != bool(empty):
        return None
    return {"count": int(count), "label": normalized_label(label), "largest_side": side or "none"}


def measured_costs(episode):
    rows = episode.get("costs")
    if not isinstance(rows, list) or not rows:
        raise ValueError("missing measured costs cannot be treated as zero")
    wall, calls = 0.0, 0
    for row in rows:
        if (not isinstance(row, dict) or not isinstance(row.get("component"), str)
                or not row["component"] or type(row.get("calls")) is not int or row["calls"] < 0
                or not finite(row.get("wall_seconds")) or row["wall_seconds"] < 0):
            raise ValueError("invalid measured cost component")
        if "generated_tokens" in row and (type(row["generated_tokens"]) is not int
                                           or row["generated_tokens"] < 0):
            raise ValueError("invalid generated-token measurement")
        wall += row["wall_seconds"]
        if row["component"] in MODEL_COMPONENTS:
            calls += row["calls"]
    missing = REQUIRED_COST_COMPONENTS - {row["component"] for row in rows}
    if missing:
        raise ValueError("missing measured cost components: " + ", ".join(sorted(missing)))
    if wall <= 0:
        raise ValueError("all-zero measured time is not a complete execution receipt")
    if "actual_wall_seconds" in episode:
        actual = episode["actual_wall_seconds"]
        if not finite(actual) or actual <= 0 or not math.isclose(wall, actual, rel_tol=1e-5, abs_tol=1e-4):
            raise ValueError("exclusive cost ledger disagrees with measured episode wall time")
    unit = episode.get("budget_unit", "wall_seconds")
    if unit not in ("wall_seconds", "model_calls"):
        raise ValueError("unsupported budget unit")
    cap = episode.get("budget_cap")
    if not finite(cap) or cap <= 0:
        raise ValueError("a positive finite budget cap is required")
    spent = wall if unit == "wall_seconds" else calls
    return {"wall_seconds": wall, "model_calls": calls, "budget_spent": spent,
            "budget_unit": unit, "budget_exceeded": spent > cap + 1e-9}


def verify_artifact(episode, reference, artifact_root):
    path_value, expected = episode.get("artifact_path"), episode.get("artifact_sha256")
    if not isinstance(path_value, str) or not path_value or not isinstance(expected, str):
        raise ValueError("missing annotation artifact path or digest")
    path = Path(path_value)
    if not path.is_absolute():
        path = Path(artifact_root) / path
    if not path.is_file() or not 0 < path.stat().st_size <= 32 * 1024 * 1024:
        raise ValueError("annotation artifact is missing or exceeds the byte limit")
    payload = path.read_bytes()
    if hashlib.sha256(payload).hexdigest() != expected:
        raise ValueError("annotation artifact digest mismatch")
    with Image.open(io.BytesIO(payload)) as image:
        if image.format != "PNG" or list(image.size) != reference["image_size"]:
            raise ValueError("annotation artifact format or dimensions differ from reference")
        image.load()
    return True


def validate_references(references):
    result = {}
    for row in references:
        task = row.get("task_id")
        if not isinstance(task, str) or not task or task in result:
            raise ValueError("missing or duplicate reference task ID")
        boxes = validate_boxes(row.get("boxes"))
        size = row.get("image_size")
        if (not isinstance(size, list) or len(size) != 2
                or any(type(v) is not int or not 0 < v <= 16384 for v in size)
                or size[0] * size[1] > 16_777_216 or not normalized_label(row.get("label"))
                or type(row.get("count")) is not int or row["count"] != len(boxes)
                or row.get("largest_side") != largest_side(boxes)
                or not isinstance(row.get("source_id"), (str, int))):
            raise ValueError("inconsistent reference count, side, label, source, or dimensions")
        result[task] = row
    if not result:
        raise ValueError("empty reference cohort")
    return result


def score_episode(episode, reference, artifact_root="."):
    errors, output_errors = [], []
    try:
        cost = measured_costs(episode)
    except ValueError as exc:
        errors.append(str(exc))
        cost = {"wall_seconds": None, "model_calls": None, "budget_spent": None,
                "budget_unit": episode.get("budget_unit", "wall_seconds"), "budget_exceeded": True}
    try:
        boxes = validate_boxes(episode.get("boxes"))
    except ValueError as exc:
        boxes = []
        output_errors.append(str(exc))
    completed = episode.get("termination") in ("completed", "stop", "budget_exhausted")
    artifact_ok = False
    if completed or episode.get("artifact_path") is not None or episode.get("artifact_sha256") is not None:
        try:
            artifact_ok = verify_artifact(episode, reference, artifact_root)
        except (ValueError, OSError) as exc:
            errors.append(str(exc))
    match = matching_score(boxes, reference["boxes"])
    text = parse_text(episode.get("text"))
    label = normalized_label(episode.get("label"))
    count_ok = len(boxes) == reference["count"]
    side_ok = largest_side(boxes) == reference["largest_side"]
    label_ok = bool(label) and label == normalized_label(reference["label"])
    consistency = text == {"count": len(boxes), "label": label, "largest_side": largest_side(boxes)}
    valid_output = completed and artifact_ok and not output_errors and not cost["budget_exceeded"]
    quality = (5 * match["box_f1"] + 2 * count_ok + side_ok
               + label_ok + consistency) / 10 if valid_output else 0.0
    severe = not (valid_output and count_ok and side_ok and label_ok and consistency and match["box_f1"] >= 0.5)
    return {"task_id": reference["task_id"], "source_id": str(reference["source_id"]),
            "method": episode.get("method"), "seed": episode.get("seed"),
            "budget_cap": episode.get("budget_cap"), **cost, **match,
            "count_correct": count_ok, "largest_side_correct": side_ok, "label_correct": label_ok,
            "text_consistent": consistency, "artifact_valid": artifact_ok,
            "coverage": float(valid_output), "quality": float(quality), "loss": float(1 - quality),
            "severe": float(severe), "validation_errors": errors, "output_errors": output_errors}


def cvar(losses, alpha=0.9):
    values = np.asarray(losses, dtype=float)
    if values.ndim != 1 or not len(values) or not np.isfinite(values).all() or not 0 <= alpha < 1:
        raise ValueError("CVaR requires finite nonempty losses and alpha in [0,1)")
    tail = len(values) * (1 - alpha)
    whole = min(len(values), math.floor(tail))
    ordered = np.sort(values)[::-1]
    total = ordered[:whole].sum()
    if whole < len(values):
        total += (tail - whole) * ordered[whole]
    return float(total / tail)


def paired_source_bootstrap(candidate, baseline, *, alpha=0.9, samples=2000, seed=20261022):
    """Cluster paired episodes by source, keeping repeated seeds together."""
    if type(samples) is not int or samples < 1:
        raise ValueError("bootstrap samples must be a positive integer")
    left = {(r["task_id"], r["seed"]): r for r in candidate}
    right = {(r["task_id"], r["seed"]): r for r in baseline}
    if len(left) != len(candidate) or len(right) != len(baseline) or set(left) != set(right) or not left:
        raise ValueError("paired bootstrap requires identical, unique task/seed rosters")
    groups = defaultdict(list)
    for key, row in left.items():
        if row["source_id"] != right[key]["source_id"]:
            raise ValueError("paired source identity mismatch")
        groups[row["source_id"]].append(key)
    if any(not finite(r["wall_seconds"]) for r in candidate + baseline):
        raise ValueError("paired costs are missing")
    group_keys = list(sorted(groups))
    rng, draws = np.random.default_rng(seed), []
    for _ in range(samples):
        keys = [key for i in rng.integers(len(group_keys), size=len(group_keys)) for key in groups[group_keys[i]]]
        a, b = [left[k] for k in keys], [right[k] for k in keys]
        draws.append([np.mean([r["quality"] for r in a]) - np.mean([r["quality"] for r in b]),
                      cvar([r["loss"] for r in a], alpha) - cvar([r["loss"] for r in b], alpha),
                      np.mean([r["wall_seconds"] for r in a]) - np.mean([r["wall_seconds"] for r in b]),
                      np.mean([r["coverage"] for r in a]) - np.mean([r["coverage"] for r in b])])
    intervals = np.quantile(draws, [0.025, 0.975], axis=0)
    return {"source_groups": len(groups), "resamples": samples,
            "interval_type": "descriptive paired source-cluster percentile 95%; not multiplicity-adjusted",
            "deltas": {key: {"low": float(intervals[0, i]), "high": float(intervals[1, i])}
                       for i, key in enumerate(("quality", "cvar", "wall_seconds", "coverage"))}}


def empirical_frontier(points):
    """Return nondominated comparable points; missing measurements never win."""
    fields = ("quality", "cvar", "wall_seconds", "coverage")
    valid = [p for p in points if all(finite(p.get(k)) for k in fields)]
    result = []
    for point in valid:
        dominated = False
        for other in valid:
            if other is point or (other["budget_unit"], other["budget_cap"]) != (point["budget_unit"], point["budget_cap"]):
                continue
            weak = (other["quality"] >= point["quality"] and other["cvar"] <= point["cvar"]
                    and other["wall_seconds"] <= point["wall_seconds"] and other["coverage"] >= point["coverage"])
            if weak and any(other[k] != point[k] for k in fields):
                dominated = True
                break
        if not dominated:
            result.append(point["point_id"])
    return result


def evaluate(references, episodes, *, artifact_root=".", alpha=0.9, bootstrap_samples=2000):
    refs = validate_references(references)
    errors, scored, buckets, seen = [], [], defaultdict(list), set()
    for episode in episodes:
        task, method, seed = episode.get("task_id"), episode.get("method"), episode.get("seed")
        if task not in refs or method not in METHODS or type(seed) is not int or seed < 0:
            errors.append("unknown task/method or invalid seed")
            continue
        config = (episode.get("budget_unit", "wall_seconds"), episode.get("budget_cap"))
        if config[0] not in ("wall_seconds", "model_calls") or not finite(config[1]) or config[1] <= 0:
            errors.append("invalid budget configuration")
            continue
        key = (method, *config, task, seed)
        if key in seen:
            errors.append(f"duplicate episode: {key}")
            continue
        seen.add(key)
        if (not isinstance(episode.get("controls"), list)
                or not all(isinstance(episode.get(k), str) and episode[k] for k in ("model_revision", "policy_version"))):
            errors.append(f"missing execution identity or controls: {key}")
        row = score_episode(episode, refs[task], artifact_root)
        errors.extend(f"{key}: {error}" for error in row["validation_errors"])
        scored.append(row)
        buckets[(method, *config)].append(row)
    configs = {(key[1], key[2]) for key in buckets}
    if not configs:
        errors.append("no evaluable episodes")
    for config in configs:
        seeds = {r["seed"] for key, rows in buckets.items() if key[1:] == config for r in rows}
        roster = {(task, seed) for task in refs for seed in seeds}
        for method in METHODS:
            rows = buckets.get((method, *config), [])
            if {(r["task_id"], r["seed"]) for r in rows} != roster:
                errors.append(f"incomplete task/seed roster: {method}, {config}")
    points, comparisons = [], []
    for key, rows in sorted(buckets.items()):
        measured = all(finite(r["wall_seconds"]) for r in rows)
        point = {"point_id": f"{key[0]}:{key[1]}:{key[2]}", "method": key[0], "budget_unit": key[1],
                 "budget_cap": key[2], "episodes": len(rows), "source_groups": len({r["source_id"] for r in rows}),
                 **{name: float(np.mean([r[name] for r in rows])) for name in ("quality", "coverage", "severe", "box_f1")},
                 "cvar": cvar([r["loss"] for r in rows], alpha),
                 "wall_seconds": float(np.mean([r["wall_seconds"] for r in rows])) if measured else None,
                 "budget_exceeded": sum(r["budget_exceeded"] for r in rows)}
        points.append(point)
    for config in sorted(configs):
        candidate = buckets.get(("ndu", *config), [])
        for method in BASELINES[:-1]:
            baseline = buckets.get((method, *config), [])
            try:
                comparison = paired_source_bootstrap(candidate, baseline, alpha=alpha, samples=bootstrap_samples)
                comparisons.append({"candidate": "ndu", "baseline": method, "budget_unit": config[0],
                                    "budget_cap": config[1], **comparison})
            except ValueError as exc:
                errors.append(f"comparison {method}, {config}: {exc}")
    return {"schema": "hepta.ndu-grounded-evaluation.v1", "engineering_pass": not errors,
            "experiment_pass": False, "production_pass": False, "alpha": alpha,
            "quality_rule": "0.5*box_F1 + 0.2*count + 0.1*largest_side + 0.1*label + 0.1*text_consistency; invalid/incomplete/over-budget=0",
            "severe_rule": "invalid/incomplete/over-budget OR count/side/label/text error OR box_F1<0.5",
            "artifact_scope": "PNG byte integrity and original dimensions; no independent pixel-generation or overlay-geometry claim",
            "cost_scope": "sum of exclusive durations, checked against episode wall receipt when present; failed/resampled work must be included upstream",
            "experiment_blockers": ["Descriptive observed-frontier report does not establish confirmatory improvement or verify strategy/training provenance."],
            "errors": sorted(set(errors)), "required_methods": list(METHODS), "points": points,
            "empirical_frontier": empirical_frontier(points) if not errors else [],
            "paired_comparisons": comparisons, "scores": scored}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--references", required=True)
    parser.add_argument("--episodes", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--artifact-root")
    parser.add_argument("--alpha", type=float, default=0.9)
    parser.add_argument("--bootstrap-samples", type=int, default=2000)
    args = parser.parse_args()
    def read(path):
        return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]
    report = evaluate(read(args.references), read(args.episodes),
                      artifact_root=args.artifact_root or Path(args.episodes).parent,
                      alpha=args.alpha, bootstrap_samples=args.bootstrap_samples)
    Path(args.output).write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    print(json.dumps({k: report[k] for k in ("engineering_pass", "experiment_pass", "production_pass", "errors")}))
    return 0 if report["engineering_pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
