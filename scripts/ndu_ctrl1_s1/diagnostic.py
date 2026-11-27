"""Post-pilot cheap-control comparison; historical data never becomes a holdout.

Run with --retained pointing at the sealed primary_repeat_2 directory. The
report has no adoption path. It reuses known scenarios and reports each fixed
rule once per scenario, separately from the three historical training seeds.
"""

import argparse
from dataclasses import asdict
from fractions import Fraction
import hashlib
from itertools import product
import json
import math
from pathlib import Path
import platform
import time

from ndu_ctrl1.evaluation import evaluate
from ndu_ctrl1.model import ACTIONS, Profile, Scenario
from ndu_ctrl1.run import ROSTER, digest, source_manifest, write_json

from .rules import RuleController

BASE_COMMIT = "b2646b4cbf19817145c9cb680d95333a267d19f4"


def binding(path):
    raw = path.read_bytes()
    return {"sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}


def validate_roster(plan):
    raw_profiles = plan["profiles"]
    raw_scenarios = plan["scenarios"]["confirmation"]
    profiles = {row["digest"]: row for row in raw_profiles}
    scenarios = {row["id"]: row for row in raw_scenarios}
    seeds, controllers = plan["training_seeds"], plan["controller_roster"]
    if not (
        len(raw_profiles) == len(profiles) == 4
        and len(raw_scenarios) == len(scenarios) == 8
        and len(seeds) == len(set(seeds)) == 3
        and all(type(seed) is int for seed in seeds)
        and controllers == list(ROSTER)
    ):
        raise ValueError("Missing, duplicate or incompatible original roster")
    return profiles, scenarios, seeds, controllers


def read_retained(root):
    """Validate all consumed original bytes and the exact comparison roster.

    This checks content integrity against the supplied artifact manifest. The
    manifest is a binding, not authenticated proof of original execution.
    """
    artifacts = json.loads((root / "ARTIFACTS.json").read_text())["files"]
    consumed = {"ARTIFACTS.json": binding(root / "ARTIFACTS.json")}

    def read(name):
        actual = binding(root / name)
        if actual != artifacts.get(name):
            raise ValueError(f"Retained byte binding mismatch: {name}")
        consumed[name] = actual
        return (root / name).read_text()

    plan = json.loads(read("PLAN.json"))
    profiles, scenarios, seeds, controllers = validate_roster(plan)
    expected = set(product(profiles, scenarios, seeds, controllers))
    expected_files = {
        f"results-{pid[:12]}-{seed}.jsonl" for pid in profiles for seed in seeds
    }
    if {p.name for p in root.glob("results-*.jsonl")} != expected_files:
        raise ValueError("Missing or extra original result files")
    rows, keys = [], set()
    for name in sorted(expected_files):
        for line in read(name).splitlines():
            row = json.loads(line)
            key = tuple(
                row[x]
                for x in ("profile_id", "scenario_id", "training_seed", "controller")
            )
            if key not in expected or key in keys:
                raise ValueError("Duplicate or unplanned historical comparison")
            if type(row["value"]) not in (int, float) or not math.isfinite(
                row["value"]
            ):
                raise ValueError("Nonfinite historical value")
            if set(row["actions"]) != set(ACTIONS) or any(
                type(x) not in (int, float) or not math.isfinite(x) or x < 0
                for x in row["actions"].values()
            ):
                raise ValueError("Invalid historical action occupancy")
            if (
                row["budget_violations"] != 0
                or row["evaluation"] != "exact_environment"
            ):
                raise ValueError("Historical comparison has an incompatible scope")
            keys.add(key)
            rows.append(row)
    if keys != expected or len(keys) != plan["expected_comparison_rows"]:
        raise ValueError("Incomplete historical denominator")
    return plan, rows, consumed


def summarize(plan, retained, new):
    profiles, scenarios, seeds, controllers = validate_roster(plan)
    for rows, fields, expected in (
        (
            new,
            ("profile_id", "scenario_id", "controller"),
            set(product(profiles, scenarios, RuleController.RULES)),
        ),
        (
            retained,
            ("profile_id", "scenario_id", "training_seed", "controller"),
            set(product(profiles, scenarios, seeds, controllers)),
        ),
    ):
        keys = [tuple(row[field] for field in fields) for row in rows]
        if len(keys) != len(set(keys)) or set(keys) != expected:
            raise ValueError("Incomplete or duplicate diagnostic denominator")
        if any(
            type(row["value"]) not in (int, float) or not math.isfinite(row["value"])
            for row in rows
        ):
            raise ValueError("Invalid diagnostic value")
    summaries = {}
    for spec in plan["profiles"]:
        pid = spec["digest"]
        fresh = [r for r in new if r["profile_id"] == pid]
        original = [r for r in retained if r["profile_id"] == pid]
        means = {
            name: math.fsum(r["value"] for r in fresh if r["controller"] == name) / 8
            for name in RuleController.RULES
        }
        best = max(means, key=means.get)
        baseline = {r["scenario_id"]: r for r in fresh if r["controller"] == best}
        contrasts = {}
        for name in plan["controller_roster"]:
            paired = [r for r in original if r["controller"] == name]
            deltas = [baseline[r["scenario_id"]]["value"] - r["value"] for r in paired]
            contrasts[name] = {
                "historical_paired_rows": len(paired),
                "distinct_scenarios": 8,
                "historical_training_seeds": 3,
                "baseline_minus_historical_mean": math.fsum(deltas) / len(deltas),
                "minimum_delta": min(deltas),
                "maximum_delta": max(deltas),
                "win_tie_loss": [
                    sum(x > 1e-12 for x in deltas),
                    sum(abs(x) <= 1e-12 for x in deltas),
                    sum(x < -1e-12 for x in deltas),
                ],
            }
        summaries[pid] = {
            "rule_means": means,
            "retrospective_best_rule": best,
            "contrasts": contrasts,
        }
    coverage = {
        name: {
            action: sum(
                r["actions"][action] > 0 for r in retained if r["controller"] == name
            )
            for action in ACTIONS
        }
        for name in plan["controller_roster"]
    }
    return {
        "schema": "hepta.ctrl1.s1-baseline-diagnostic.v1",
        "scope": "EXPLORATORY_POST_PILOT; reused scenarios, no fresh confirmation",
        "scientific_qualification": "HOLD",
        "production_adoption": "NoUpdate",
        "full_physical_cost_qualified": False,
        "new_training_runs": 0,
        "historical_rows": len(retained),
        "new_exact_rule_evaluations": len(new),
        "selection": "Retrospective per-profile mean; never a deployable per-case oracle",
        "action_coverage_historical_rows_of_96": coverage,
        "coverage_denominator": "4 profiles x 8 scenarios x 3 historical training seeds; not 96 independent tasks",
        "profiles": summaries,
        "limits": [
            "Same hard simulation caps and public kernel; actual compute consumption differs.",
            "Original neural-free finite environment only; no native memory, tool or verifier owner.",
            "New rule repeated against three historical seeds is still one deterministic result per scenario.",
            "CPU timers include cache and host effects; credits are declared prices, not physical cost.",
        ],
    }


def run(retained_root, output):
    plan, old, consumed = read_retained(retained_root)
    output.mkdir(parents=True, exist_ok=False)
    sources = source_manifest()
    for path in sorted(Path(__file__).parent.glob("*.py")):
        sources[f"scripts/ndu_ctrl1_s1/{path.name}"] = binding(path)
    diagnostic_plan = {
        "schema": "hepta.ctrl1.s1-diagnostic-plan.v1",
        "scope": "Post-pilot analysis designed after original outcomes were known",
        "base_commit": BASE_COMMIT,
        "sources": sources,
        "consumed_historical_bindings": consumed,
        "rules": RuleController.RULES,
        "expected_new_evaluations": len(plan["profiles"])
        * len(plan["scenarios"]["confirmation"])
        * len(RuleController.RULES),
        "python": platform.python_version(),
        "system": platform.system(),
        "scientific_qualification": "HOLD",
        "production_adoption": "NoUpdate",
    }
    write_json(output / "PLAN.json", diagnostic_plan)
    rows = []
    started_wall, started_cpu = time.perf_counter_ns(), time.process_time_ns()
    with (
        (output / "attempts.jsonl").open("x") as attempts,
        (output / "results.jsonl").open("x") as results,
    ):

        def event(value):
            attempts.write(json.dumps(value, sort_keys=True, allow_nan=False) + "\n")
            attempts.flush()

        for spec, case, rule in product(
            plan["profiles"], plan["scenarios"]["confirmation"], RuleController.RULES
        ):
            pid, sid = spec["digest"], case["id"]
            identity = {"profile_id": pid, "scenario_id": sid, "controller": rule}
            event({**identity, "status": "Started"})
            try:
                profile = Profile(**{k: v for k, v in spec.items() if k != "digest"})
                params = {k: v for k, v in case.items() if k != "id"}
                for key in ("prior", "signal_accuracy", "repair_success"):
                    params[key] = Fraction(params[key])
                scenario = Scenario(**params)
                if (
                    digest(asdict(profile)) != pid
                    or f"confirmation-{digest(asdict(scenario))[:16]}" != sid
                ):
                    raise ValueError("Historical profile/scenario ID mismatch")
                controller = RuleController(rule, profile)
                row = {
                    **identity,
                    **evaluate(scenario, profile, controller),
                    "controller_meter": controller.counters,
                }
                results.write(json.dumps(row, sort_keys=True, allow_nan=False) + "\n")
                results.flush()
                rows.append(row)
            except Exception as exc:
                event(
                    {
                        **identity,
                        "status": "Failed",
                        "error": type(exc).__name__,
                        "detail": str(exc),
                    }
                )
                raise
            event({**identity, "status": "Completed"})
    report = summarize(plan, old, rows)
    report["evaluation_batch"] = {
        "wall_ns": time.perf_counter_ns() - started_wall,
        "cpu_ns": time.process_time_ns() - started_cpu,
        "scope": "from completed PLAN write through summary computation; excludes historical reads, source hashing and final report writes; contains nested oracle/controller timers, do not add them",
    }
    write_json(output / "REPORT.json", report)
    write_json(
        output / "ARTIFACTS.json",
        {p.name: binding(p) for p in sorted(output.iterdir()) if p.is_file()},
    )
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--retained", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    report = run(args.retained, args.output)
    print(
        json.dumps(
            {
                "rows": report["new_exact_rule_evaluations"],
                "qualification": report["scientific_qualification"],
            }
        )
    )
