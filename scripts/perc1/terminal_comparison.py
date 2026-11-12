"""Describe a frozen, byte-bound paired panel; never authorize scientific adoption.

``compare(frozen, originals)`` accepts original JSON bytes keyed by their SHA-256.
The manifest fixes task/source identities, seeds, per-seed arm component pins,
three single-component ablations, failure scoring and every result SHA. Results
retain all attempts and terminal outcomes. Missing measurements use explicit null.

Costs are either an exclusive eight-stage partition or one inclusive envelope;
the envelope and its stage diagnostics are never added. Shared loading must be
charged inside the declared execution boundary; this reader does no amortization.
Byte consistency does not authenticate owners, independence, timing or costs.
"""

import argparse
from collections import Counter
import json
from pathlib import Path
from statistics import mean

from .schema import canonical, digest, exact, identifier, integer, real, require, sha

CONTROLS = (
    "direct_roi_ocr",
    "full_ocr",
    "public_feature_rule",
    "fixed_region",
    "random_region",
)
COMPONENTS = ("encoding", "selection", "decoding")
STAGES = (
    "capture",
    "encoding",
    "shared_load",
    "selection",
    "decoding",
    "retry",
    "delivery",
    "recovery",
)
METRICS = ("wall_ns", "cpu_ns", "energy_joules", "provider_microcredits")
STATUSES = ("COMPLETED", "FAILED", "CANCELLED", "UNKNOWN")
MAX_BYTES = 4 * 1024 * 1024


def _decode(raw):
    require(
        type(raw) is bytes and 0 < len(raw) <= MAX_BYTES,
        "bounded original JSON bytes required",
    )

    def pairs(items):
        value = {}
        for key, item in items:
            require(key not in value, "duplicate JSON key")
            value[key] = item
        return value

    def constant(value):
        raise ValueError("nonfinite JSON constant: " + value)

    return json.loads(raw, object_pairs_hook=pairs, parse_constant=constant)


def _metrics(value):
    exact(value, " ".join(METRICS))
    for metric, number in value.items():
        if number is not None:
            if metric.endswith("_ns") or metric == "provider_microcredits":
                integer(number)
            else:
                real(number, 0)
    return value


def _cost(value, weights):
    exact(value, "accounting complete stages envelope")
    require(type(value["complete"]) is bool, "cost completeness must be explicit")
    exact(value["stages"], " ".join(STAGES))
    stages = {stage: _metrics(v) for stage, v in value["stages"].items()}
    mode = value["accounting"]
    require(
        mode in ("exclusive_stages", "inclusive_envelope"), "unknown cost accounting"
    )
    if mode == "inclusive_envelope":
        envelope = _metrics(value["envelope"])
        for stage in stages.values():
            for metric in METRICS:
                if stage[metric] is not None and envelope[metric] is not None:
                    require(
                        stage[metric] <= envelope[metric],
                        "inclusive envelope excludes a stage cost",
                    )
    else:
        require(
            value["envelope"] is None, "exclusive stages cannot also charge an envelope"
        )
        envelope = None
    missing = [
        f"{stage}.{metric}"
        for stage in STAGES
        for metric in METRICS
        if stages[stage][metric] is None
    ]
    if envelope is not None:
        missing += [
            f"envelope.{metric}" for metric in METRICS if envelope[metric] is None
        ]
    totals = {}
    for metric in METRICS:
        known = value["complete"] and all(
            stages[stage][metric] is not None for stage in STAGES
        )
        totals[metric] = (
            (
                envelope[metric]
                if envelope is not None
                else sum(stages[s][metric] for s in STAGES)
            )
            if known
            else None
        )
        if totals[metric] is not None:
            real(totals[metric], 0)
    # Even a zero utility weight cannot conceal an unknown physical dimension.
    weighted = (
        real(sum(totals[m] * weights[m] for m in METRICS), 0)
        if all(v is not None for v in totals.values())
        else None
    )
    return {
        "by_metric": totals,
        "weighted_cost": weighted,
        "missing_measurements": missing,
        "declared_complete": value["complete"],
    }


def _summary(pairs):
    groups = sorted({p["source_group"] for p in pairs})
    metrics = ("quality_delta", "cost_delta", "net_delta")
    per_group = {}
    for group in groups:
        rows = [p for p in pairs if p["source_group"] == group]
        per_group[group] = {
            m: mean(p[m] for p in rows) if all(p[m] is not None for p in rows) else None
            for m in metrics
        }
    return {
        "pair_count": len(pairs),
        "task_count": len({p["task_id"] for p in pairs}),
        "source_group_count": len(groups),
        "pairs": pairs,
        "per_source_group": per_group,
        "equal_source_group_mean": {
            m: mean(per_group[g][m] for g in groups)
            if groups and all(per_group[g][m] is not None for g in groups)
            else None
            for m in metrics
        },
    }


def compare(frozen, originals):
    """Reject incomplete/altered rosters; report descriptive effects with HOLD."""
    exact(
        frozen, "schema tasks seeds arms ablations cost_weights failure_quality results"
    )
    require(frozen["schema"] == "perc1.terminal-panel.v1", "panel schema")
    require(
        type(frozen["tasks"]) is list and 0 < len(frozen["tasks"]) <= 2048,
        "task roster",
    )
    tasks, source_for_task_bytes = {}, {}
    for task in frozen["tasks"]:
        exact(task, "task_id source_group task_sha256 target_known")
        task_id = identifier(task["task_id"])
        identifier(task["source_group"])
        digest(task["task_sha256"])
        require(
            type(task["target_known"]) is bool and task_id not in tasks,
            "duplicate task or invalid public target declaration",
        )
        previous = source_for_task_bytes.setdefault(
            task["task_sha256"], task["source_group"]
        )
        require(
            previous == task["source_group"],
            "same task bytes relabeled as different sources",
        )
        tasks[task_id] = task
    seeds = frozen["seeds"]
    require(type(seeds) is list and 0 < len(seeds) <= 16, "seed roster")
    for seed in seeds:
        integer(seed)
    require(len(set(seeds)) == len(seeds), "duplicate seed")
    arms = frozen["arms"]
    require(
        type(arms) is dict
        and set(CONTROLS) | {"candidate"} <= set(arms)
        and len(arms) <= 32,
        "required control missing",
    )
    for arm, by_seed in arms.items():
        identifier(arm)
        require(
            type(by_seed) is dict and set(by_seed) == {str(s) for s in seeds},
            "arm seed roster",
        )
        for components in by_seed.values():
            exact(components, " ".join(COMPONENTS))
            for pin in components.values():
                digest(pin)
    exact(frozen["ablations"], " ".join(COMPONENTS))
    require(
        len(set(frozen["ablations"].values())) == 3, "distinct ablation arms required"
    )
    for stage, baseline in frozen["ablations"].items():
        require(baseline in arms and baseline != "candidate", "missing ablation arm")
        for seed in seeds:
            left, right = arms["candidate"][str(seed)], arms[baseline][str(seed)]
            require(
                {c for c in COMPONENTS if left[c] != right[c]} == {stage},
                "ablation changes more than its declared component",
            )
    weights = exact(frozen["cost_weights"], " ".join(METRICS))
    for weight in weights.values():
        real(weight, 0)
    exact(frozen["failure_quality"], "FAILED CANCELLED")
    for score in frozen["failure_quality"].values():
        require(
            score is None or type(score) in (int, float) and score == 0,
            "failure quality must explicitly be zero or unknown",
        )
    require(
        len(tasks) * len(seeds) * len(arms) <= 16384
        and type(frozen["results"]) is list,
        "result roster bound",
    )
    expected = {(task, seed, arm) for task in tasks for seed in seeds for arm in arms}
    pins = {}
    for binding in frozen["results"]:
        exact(binding, "task_id seed arm sha256")
        key = (
            identifier(binding["task_id"]),
            integer(binding["seed"]),
            identifier(binding["arm"]),
        )
        require(
            key in expected and key not in pins,
            "unexpected or duplicate result binding",
        )
        pins[key] = digest(binding["sha256"])
    require(set(pins) == expected, "incomplete paired result roster")
    require(len(set(pins.values())) == len(pins), "original result reused across cells")
    require(
        type(originals) is dict and set(originals) == set(pins.values()),
        "missing or extra original result bytes",
    )
    rows = {}
    for key, pin in pins.items():
        raw = originals[pin]
        require(type(raw) is bytes and sha(raw) == pin, "original result SHA mismatch")
        row = _decode(raw)
        exact(
            row,
            "schema task_id source_group task_sha256 seed arm components information status quality attempts recoveries costs",
        )
        require(row["schema"] == "perc1.terminal-result.v1", "result schema")
        task_id, seed, arm = key
        require(
            (row["task_id"], integer(row["seed"]), row["arm"]) == key,
            "result identity mismatch",
        )
        task = tasks[task_id]
        require(
            row["source_group"] == task["source_group"]
            and row["task_sha256"] == task["task_sha256"],
            "task/source binding mismatch",
        )
        require(
            row["components"] == arms[arm][str(seed)], "executed component pin mismatch"
        )
        oracle = arm == "direct_roi_ocr" and not task["target_known"]
        require(
            row["information"] == ("hidden_roi" if oracle else "public"),
            "private ROI leaked into a fair arm or public ROI was misclassified",
        )
        require(row["status"] in STATUSES, "invalid terminal status")
        if row["status"] == "COMPLETED":
            quality = real(row["quality"], 0, 1)
        else:
            require(
                row["quality"] is None, "uncompleted original quality must remain null"
            )
            quality = frozen["failure_quality"].get(row["status"])
        attempts, recoveries = integer(row["attempts"], 1), integer(row["recoveries"])
        cost = _cost(row["costs"], weights)
        weighted = cost["weighted_cost"]
        rows[key] = {
            "task_id": task_id,
            "source_group": task["source_group"],
            "seed": seed,
            "arm": arm,
            "result_sha256": pin,
            "status": row["status"],
            "reported_quality": row["quality"],
            "utility_quality": quality,
            "attempts": attempts,
            "recoveries": recoveries,
            "cost": cost,
            "net_utility": real(quality - weighted)
            if quality is not None and weighted is not None
            else None,
            "comparison_role": "oracle_upper_bound" if oracle else "fair",
        }
    comparisons = {}
    for name, baseline in [
        *(("candidate_vs_" + c, c) for c in CONTROLS),
        *frozen["ablations"].items(),
    ]:
        fair, oracle_pairs = [], []
        for task_id in tasks:
            for seed in seeds:
                left, right = (
                    rows[task_id, seed, "candidate"],
                    rows[task_id, seed, baseline],
                )
                pair = {
                    "task_id": task_id,
                    "source_group": tasks[task_id]["source_group"],
                    "seed": seed,
                    "candidate_result_sha256": left["result_sha256"],
                    "baseline_result_sha256": right["result_sha256"],
                    "statuses": [left["status"], right["status"]],
                }
                for metric, lv, rv in (
                    (
                        "quality_delta",
                        left["utility_quality"],
                        right["utility_quality"],
                    ),
                    (
                        "cost_delta",
                        left["cost"]["weighted_cost"],
                        right["cost"]["weighted_cost"],
                    ),
                ):
                    pair[metric] = (
                        real(lv - rv) if lv is not None and rv is not None else None
                    )
                pair["net_delta"] = (
                    real(pair["quality_delta"] - pair["cost_delta"])
                    if all(pair[m] is not None for m in ("quality_delta", "cost_delta"))
                    else None
                )
                (
                    oracle_pairs
                    if right["comparison_role"] == "oracle_upper_bound"
                    else fair
                ).append(pair)
        comparisons[name] = {
            "baseline": baseline,
            "fair": _summary(fair),
            "oracle_upper_bound": _summary(oracle_pairs),
        }
    return {
        "schema": "perc1.terminal-comparison.v1",
        "status": "HOLD",
        "adoption": "NoUpdate",
        "structural_validation": "PASS",
        "scientific_qualified": False,
        "manifest_sha256": sha(frozen),
        "task_count": len(tasks),
        "source_group_count": len({t["source_group"] for t in tasks.values()}),
        "seed_count": len(seeds),
        "row_count": len(rows),
        "rows": list(rows.values()),
        "status_counts": dict(Counter(row["status"] for row in rows.values())),
        "attempts": sum(row["attempts"] for row in rows.values()),
        "recoveries": sum(row["recoveries"] for row in rows.values()),
        "comparisons": comparisons,
        "source_independence_verified": False,
        "owner_signatures_verified": False,
        "preregistration_verified": False,
        "physical_costs_verified": False,
        "scope": "Declared roster and original byte consistency only; group means are descriptive, not independent sample counts or causal evidence. Shared costs require attribution inside original execution boundaries; no retrospective amortization or nested-envelope addition.",
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument(
        "--originals",
        type=Path,
        required=True,
        help="Directory of <result-sha256>.json files",
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    code = 0

    def read(path):
        require(
            path.is_file() and not path.is_symlink(),
            f"original must be a regular file: {path}",
        )
        with path.open("rb") as stream:
            raw = stream.read(MAX_BYTES + 1)
        require(len(raw) <= MAX_BYTES, "original exceeds byte bound")
        return raw

    try:
        raw = read(args.manifest)
        require(sha(raw) == digest(args.manifest_sha256), "manifest byte pin mismatch")
        frozen = _decode(raw)
        pins = [digest(binding["sha256"]) for binding in frozen["results"]]
        originals = {pin: read(args.originals / (pin + ".json")) for pin in pins}
        report = compare(frozen, originals)
        report["manifest_file_sha256"] = sha(raw)
    except (OSError, ValueError, KeyError, TypeError, RecursionError) as error:
        code = 2
        report = {
            "schema": "perc1.terminal-comparison.v1",
            "status": "INVALID_EVIDENCE",
            "scientific_qualified": False,
            "adoption": "NoUpdate",
            "error_type": type(error).__name__,
            "reason": str(error),
        }
    report["requested_manifest_sha256"] = args.manifest_sha256
    with args.output.open("xb") as stream:
        stream.write(canonical(report) + b"\n")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
