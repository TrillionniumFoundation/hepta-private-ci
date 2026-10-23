"""Model-free post-hoc paired audit of the immutable Hepta NDU v1 pilot.

Exploratory diagnostic only, NOT a preregistered confirmatory analysis.  The
randomization/sign-exchangeability null is an extra modelling assumption:
method assignment was not independently randomized for each source.
"""

import argparse
from collections import Counter, defaultdict
from hashlib import sha256
from itertools import product
import json
import math
from pathlib import Path
import zipfile

ARCHIVE_SHA256 = "2ac7d46df01fb3e24cd1004cef75ad0efd4076b5f1c9556b560e97546ffaceb5"
PREFIX = "hepta-ndu-evidence-v1-20261022/"
SCORES_SHA256 = "6cd7eefcd53139e816ecccd31b963461526260081ede0f07b0fbffb327dab013"
JOURNAL_SHA256 = "b9e7e0a53622b9b87e29507684684389aaf798e97bf53b0d4e93f44570786e39"
BASELINES = ("base", "static_cells", "learned_router", "best_of_n",
             "mean_only", "risk_actor_critic")
METHODS = BASELINES + ("ndu", "ablate_covariance", "ablate_fixed_weights",
                       "ablate_crossmodal", "ablate_missing_modality", "ablate_shuffled_pair")
NUM_TASKS = 64


def _decode_rows(raw):
    return [json.loads(line) for line in raw.decode("utf-8").splitlines() if line.strip()]


def _finite(value, minimum=None, maximum=None):
    if type(value) not in (int, float) or not math.isfinite(value):
        return False
    return (minimum is None or value >= minimum) and (maximum is None or value <= maximum)


def index_scores(rows):
    """Validate exact paired roster, types, score bounds, identities and duplicates."""
    by_task = defaultdict(dict)
    source_to_task = {}
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("score row must be an object")
        task, source, method = (row.get(x) for x in ("task_id", "source_id", "method"))
        if (not isinstance(task, str) or not task or not isinstance(source, str)
                or not source or method not in METHODS):
            raise ValueError("missing or invalid task/source/method")
        if task in by_task and method in by_task[task]:
            raise ValueError("duplicate task/method")
        if source in source_to_task and source_to_task[source] != task:
            raise ValueError("one source is aliased across task IDs")
        source_to_task[source] = task
        for key in ("quality", "loss", "severe", "coverage"):
            if not _finite(row.get(key), 0, 1):
                raise ValueError("invalid " + key)
        for key in ("wall_seconds", "cpu_seconds"):
            if not _finite(row.get(key), 0):
                raise ValueError("invalid " + key)
        if type(row.get("budget_exceeded")) is not bool:
            raise ValueError("invalid budget_exceeded")
        if abs(row["loss"] + row["quality"] - 1) > 1e-8:
            raise ValueError("loss must equal 1-quality")
        if task in by_task and any(existing["source_id"] != source for existing in by_task[task].values()):
            raise ValueError("task identity has multiple original sources")
        by_task[task][method] = row
    if (len(by_task) != NUM_TASKS or len(rows) != NUM_TASKS * len(METHODS)
            or any(set(group) != set(METHODS) for group in by_task.values())):
        raise ValueError("not an exact 64-source x 12-method complete paired roster")
    return dict(sorted(by_task.items()))


def exact_signflip(values, limit=20):
    """Exact conditional sign-flip p-values, retaining ties in the 64-source mean."""
    if not values or not all(_finite(v) for v in values):
        raise ValueError("missing or nonfinite paired differences")
    nonzero = [v for v in values if abs(v) > 1e-12]
    if len(nonzero) > limit:
        raise ValueError("exact enumeration would exceed the explicit nonzero cap")
    observed = sum(nonzero)
    distributions = [sum(sign * val for sign, val in zip(signs, nonzero))
                     for signs in product((-1, 1), repeat=len(nonzero))]
    tolerance = 1e-10
    return {"nonzero_pairs": len(nonzero),
            "wins": sum(v > 1e-12 for v in values),
            "losses": sum(v < -1e-12 for v in values),
            "ties": len(values) - len(nonzero),
            "mean_quality_delta": sum(values) / len(values),
            "one_sided_ndu_superiority_p": sum(v >= observed - tolerance for v in distributions) / len(distributions),
            "two_sided_exchangeable_p": sum(abs(v) >= abs(observed) - tolerance for v in distributions) / len(distributions)}


def holm_one_sided(p_values):
    """Familywise adjusted Holm p for the six NDU-greater-than-baseline claims."""
    pairs = sorted(p_values.items(), key=lambda kv: (kv[1], kv[0]))
    adjusted, previous = {}, 0.0
    count = len(pairs)
    for i, (name, value) in enumerate(pairs):
        if not _finite(value, 0, 1):
            raise ValueError("invalid unadjusted p")
        previous = max(previous, min(1.0, (count - i) * value))
        adjusted[name] = previous
    return adjusted


def audit_order(journal, indexed):
    """Reconcile all full rows and log deterministic rotated method order."""
    if len(journal) != NUM_TASKS * len(METHODS):
        raise ValueError("missing full-journal rows")
    positions = defaultdict(Counter)
    order_sets = defaultdict(list)
    for r in journal:
        task, method = r.get("task_id"), r.get("method")
        if task not in indexed or method not in indexed[task]:
            raise ValueError("full-journal key not in compact scores")
        if r.get("split") != "test":
            raise ValueError("non-test full-journal row")
        score, compact = r.get("score", {}), indexed[task][method]
        for key in ("source_id", "quality", "loss", "severe", "coverage", "wall_seconds", "budget_exceeded"):
            if score.get(key) != compact.get(key):
                raise ValueError("full/compact mismatch for " + key)
        order_sets[task].append(method)
    # The journal is task-contiguous: preserve order, not a keyed sorted rejoin.
    if len(order_sets) != NUM_TASKS:
        raise ValueError("missing tasks in full-journal")
    for task, methods in order_sets.items():
        if len(methods) != len(METHODS) or set(methods) != set(METHODS):
            raise ValueError("invalid method execution order")
        for index, method in enumerate(methods):
            positions[method][index] += 1
    minimum, maximum = NUM_TASKS // len(METHODS), math.ceil(NUM_TASKS / len(METHODS))
    balanced = all(minimum <= positions[m][pos] <= maximum
                   for m in METHODS for pos in range(len(METHODS)))
    if not balanced:
        raise ValueError("execution order not balanced over method positions")
    return {"balanced_positions": balanced, "minimum_per_position": minimum,
            "maximum_per_position": maximum,
            "ndu_position_counts": {str(i): positions["ndu"][i] for i in range(len(METHODS))},
            "all_scores_full_journal_reconciled": len(journal)}


def audit_bundle(path):
    archive = Path(path)
    if sha256(archive.read_bytes()).hexdigest() != ARCHIVE_SHA256:
        raise ValueError("immutable archive SHA256 mismatch")
    with zipfile.ZipFile(archive) as bundle:
        score_bytes = bundle.read(PREFIX + "results/test-scores.jsonl")
        journal_bytes = bundle.read(PREFIX + "raw/test.episodes.jsonl")
    if sha256(score_bytes).hexdigest() != SCORES_SHA256 or sha256(journal_bytes).hexdigest() != JOURNAL_SHA256:
        raise ValueError("pinned result/journal digest mismatch")
    indexed = index_scores(_decode_rows(score_bytes))
    journal = _decode_rows(journal_bytes)
    order = audit_order(journal, indexed)
    results = {}
    for baseline in BASELINES:
        deltas = [by["ndu"]["quality"] - by[baseline]["quality"] for by in indexed.values()]
        item = exact_signflip(deltas)
        item.update({"mean_wall_delta_seconds": sum(by["ndu"]["wall_seconds"] - by[baseline]["wall_seconds"]
                                                    for by in indexed.values()) / NUM_TASKS,
                     "mean_wall_ratio": sum(by["ndu"]["wall_seconds"] for by in indexed.values())
                     / sum(by[baseline]["wall_seconds"] for by in indexed.values()),
                     "coverage_delta": sum(by["ndu"]["coverage"] - by[baseline]["coverage"]
                                           for by in indexed.values()) / NUM_TASKS})
        results[baseline] = item
    holm = holm_one_sided({m: p["one_sided_ndu_superiority_p"] for m, p in results.items()})
    for name, p in holm.items():
        results[name]["holm_six_one_sided_p"] = p
    long_tails = []
    for task, by in indexed.items():
        r = by["ndu"]
        if r["budget_exceeded"]:
            raw = next(a for a in journal if a["task_id"] == task and a["method"] == "ndu")
            cost = next(x for x in raw["costs"] if x["component"] == "encoder")
            long_tails.append({"task_id": task, "source_id": r["source_id"],
                               "wall_seconds": r["wall_seconds"],
                               "encoder_seconds": cost["wall_seconds"],
                               "actual_control_decisions": len([x for x in raw["controls"] if x.get("checkpoint_changed")])})
    return {
        "schema": "hepta.ndu-v1-posthoc-paired-sensitivity.v1",
        "status": "exploratory_posthoc_only", "archive_sha256": ARCHIVE_SHA256,
        "compact_sha256": SCORES_SHA256, "full_journal_sha256": JOURNAL_SHA256,
        "tasks": NUM_TASKS, "episodes": len(journal), "methods": list(METHODS),
        "method_execution_order": order,
        "ndu_budget_exceeded": sorted(long_tails, key=lambda x: x["source_id"]),
        "comparisons": results,
        "interpretation_limits": [
            "Exact sign-flip p-values condition on exchangeability under the null; methods were not independently randomized within source.",
            "Holm corrects six one-sided NDU-superiority comparisons only; analysis was defined after original test access.",
            "No new samples, rerun decoder outputs, added seed, strict equal-cost allocation, multiplicity-adjusted confirmatory claim or causal attribution.",
            "Zero-quality incomplete/over-budget episodes are included in every all-source comparison.",
            "The original NDU v1 scoring/protocol/test rows must not be changed or promoted based on this supplement."
        ]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", help="Exact frozen v1 portable ZIP; not an arbitrary repack")
    parser.add_argument("--output", help="Optional JSON report file")
    args = parser.parse_args()
    result = json.dumps(audit_bundle(args.archive), indent=2, ensure_ascii=False, allow_nan=False) + "\n"
    if args.output:
        Path(args.output).write_text(result, encoding="utf-8")
    else:
        print(result, end="")


if __name__ == "__main__":
    main()
