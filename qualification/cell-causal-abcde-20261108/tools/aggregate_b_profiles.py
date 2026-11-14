#!/usr/bin/env python3
"""Describe each planned B profile from exact original rows after frozen analysis.

This is a reporting supplement, not an additional inferential protocol. The
input spec binds the original analysis report, its helper, locally recovered
original input bytes, the frozen source root and a fresh output prefix.
"""

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import statistics


def read(binding, limit=256 * 1024 * 1024):
    path = Path(binding["path"])
    if not path.is_absolute() or path.is_symlink() or not path.is_file():
        raise ValueError("Absolute regular original file required")
    if type(binding["bytes"]) is not int or not 0 <= binding["bytes"] <= limit:
        raise ValueError("Bounded input size required")
    raw = path.read_bytes()
    if (
        len(raw) != binding["bytes"]
        or hashlib.sha256(raw).hexdigest() != binding["sha256"]
    ):
        raise ValueError("Original byte binding differs")
    return raw


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--spec-sha256", required=True)
    args = parser.parse_args()
    spec_binding = {
        "path": str(args.spec),
        "sha256": args.spec_sha256,
        "bytes": args.spec.stat().st_size,
    }
    spec = json.loads(read(spec_binding, 1024 * 1024))
    if spec["schema"] != "hepta.causal-b.profile-aggregation-inputs.v1":
        raise ValueError("Unknown aggregation input schema")
    helper_raw = read(spec["helper"], 1024 * 1024)
    report = json.loads(read(spec["analysis_report"], 16 * 1024 * 1024))
    if report["analysis_helper_sha256"] != hashlib.sha256(helper_raw).hexdigest():
        raise ValueError("Aggregation must reuse the executed frozen helper")
    module_spec = importlib.util.spec_from_file_location(
        "analyze_b_profiles", spec["helper"]["path"]
    )
    helper = importlib.util.module_from_spec(module_spec)
    exec(compile(helper_raw, spec["helper"]["path"], "exec"), helper.__dict__)
    helper.require(
        set(spec["inputs"]) == set(helper.ARTIFACTS), "Incomplete original input roster"
    )
    for name, binding in spec["inputs"].items():
        original = report["input_bindings"][name]
        helper.require(
            (binding["sha256"], binding["bytes"])
            == (original["sha256"], original["bytes"]),
            "Recovered input differs from original analyzed bytes",
        )
    raw = {name: helper.read_bound(value) for name, value in spec["inputs"].items()}
    data = {
        name: helper.strict_json(value)
        for name, value in raw.items()
        if name != "paired_rows"
    }
    rows = [helper.strict_json(line) for line in raw["paired_rows"].splitlines()]
    plan = data["plan"]
    _, _, canonical_sha, source_pins = helper.load_frozen_analysis(
        plan, Path(spec["source_root"])
    )
    mapping = helper.condition_map(plan["design"])
    cases, splits = helper.selected_cases(data["selected"])
    fits, profiles, gates = helper.training_and_selection_gates(
        plan, data["selection_lock"], data["fit_results"], mapping
    )
    mapped, outcomes = helper.map_rows(
        rows,
        plan,
        cases,
        fits,
        profiles,
        mapping,
        spec["inputs"]["selection_lock"]["sha256"],
        canonical_sha,
    )
    helper.require(
        mapping == report["condition_mapping"]
        and gates == report["gates"]
        and outcomes == report["outcomes"],
        "Profile reporting differs from the frozen original analysis",
    )
    by_coordinate = {
        (row["fit_id"], row["regime"], row["arm"], row["case_id"]): row
        for row in mapped
    }
    chosen = {
        (item["fit_id"], item["regime"], item["arm"]): item["profile_id"]
        for item in profiles.values()
    }
    summaries = []
    for fit in fits:
        for regime in plan["design"]["regimes"]:
            for arm, condition in mapping.items():
                for split, selected in splits.items():
                    observations = {
                        case["case_id"]: by_coordinate.get(
                            (fit, regime, arm, case["case_id"])
                        )
                        for case in selected
                    }
                    observed = [row for row in observations.values() if row is not None]
                    metrics = {}
                    for metric in helper.METRICS:
                        unknown = [
                            case_id
                            for case_id, row in observations.items()
                            if row is None
                            or row["terminal_status"] not in helper.TERMINAL
                            or not helper.finite(row["metric_values"][metric])
                        ]
                        complete = bool(selected) and not unknown
                        groups = defaultdict(lambda: defaultdict(list))
                        if complete:
                            for case in selected:
                                groups[case["source_group_id"]][
                                    case["task_family"]
                                ].append(
                                    observations[case["case_id"]]["metric_values"][
                                        metric
                                    ]
                                )
                        metrics[metric] = {
                            "planned_rows": len(selected),
                            "known_rows": len(selected) - len(unknown),
                            "unknown_case_ids": unknown,
                            "complete": complete,
                            "mean": statistics.mean(
                                statistics.mean(
                                    statistics.mean(values)
                                    for values in families.values()
                                )
                                for families in groups.values()
                            )
                            if complete
                            else None,
                        }
                    wall = [
                        row["deployment_wall_seconds"]
                        for row in observed
                        if helper.finite(row.get("deployment_wall_seconds"))
                        and row["deployment_wall_seconds"] >= 0
                    ]
                    summaries.append(
                        {
                            "fit_id": fit,
                            "training_seed": fits[fit]["training_seed"],
                            "regime": regime,
                            "arm": arm,
                            "condition_id": condition,
                            "profile_id": chosen.get((fit, regime, arm)),
                            "split": split,
                            "planned_rows": len(selected),
                            "observed_rows": len(observed),
                            "missing_case_ids": [
                                case
                                for case, row in observations.items()
                                if row is None
                            ],
                            "original_terminal_status_counts": dict(
                                Counter(
                                    row["original_terminal_status"] for row in observed
                                )
                            ),
                            "analysis_terminal_status_counts": dict(
                                Counter(row["terminal_status"] for row in observed)
                            ),
                            "metrics": metrics,
                            "deployment_wall_known_rows": len(wall),
                            "deployment_wall_seconds_observed_sum": sum(wall),
                            "deployment_wall_seconds_mean_if_complete": statistics.mean(
                                wall
                            )
                            if wall and len(wall) == len(selected)
                            else None,
                        }
                    )
    result = {
        "schema": "hepta.causal-b.profile-descriptions.v1",
        "observed_utc": datetime.now(timezone.utc).isoformat(),
        "aggregation_helper_sha256": hashlib.sha256(
            Path(__file__).read_bytes()
        ).hexdigest(),
        "spec_binding": spec_binding,
        "original_analysis_report": spec["analysis_report"],
        "original_input_bindings": report["input_bindings"],
        "local_input_bindings": spec["inputs"],
        "source_bindings": source_pins,
        "gates": gates,
        "outcomes": outcomes,
        "weighting": "Within each training fit and split, average cases within family, families within source group, then equally weight source groups. Any missing/unresolved required metric leaves that profile mean unknown.",
        "cost_scope": "Observed deployment wall only; sums with missing measurements are partial, not complete improvement costs.",
        "profile_summaries": summaries,
        "inferential_use": False,
        "scientific_acceptance": "HOLD",
        "adoption_authorized": False,
    }
    for value in [
        spec["analysis_report"],
        spec["helper"],
        *spec["inputs"].values(),
        *source_pins.values(),
    ]:
        read(value)
    output = Path(spec["output_prefix"])
    helper.require(output.is_absolute(), "Absolute fresh output required")
    output.parent.mkdir(parents=True, exist_ok=True)
    with Path(str(output) + ".json").open("x") as stream:
        json.dump(result, stream, indent=2, ensure_ascii=False, allow_nan=False)
        stream.write("\n")
    lines = [
        "Per-profile descriptions only; all planned rows retained; scientific HOLD.",
        "fit | regime | condition | split | score | deployment utility | observed/planned | original statuses",
    ]
    for item in summaries:
        lines.append(
            " | ".join(
                str(value)
                for value in [
                    item["fit_id"],
                    item["regime"],
                    item["condition_id"],
                    item["split"],
                    item["metrics"]["failure_adjusted_score"]["mean"],
                    item["metrics"]["deployment_utility"]["mean"],
                    f"{item['observed_rows']}/{item['planned_rows']}",
                    item["original_terminal_status_counts"],
                ]
            )
        )
    with Path(str(output) + ".txt").open("x") as stream:
        stream.write("\n".join(lines) + "\n")
    print(
        json.dumps(
            {
                "profiles_by_split": len(summaries),
                "output_prefix": str(output),
                "scientific_acceptance": "HOLD",
            }
        )
    )


if __name__ == "__main__":
    main()
