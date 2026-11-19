"""Equal worker CPU allowance sensitivity with complete failure denominators.

Teacher preparation, fitting and serialization share each POSIX worker limit.
Shared roster construction, supervision and evaluation remain separate scopes.
"""

import argparse
from dataclasses import asdict
import hashlib
import json
import math
from pathlib import Path
import statistics

from .budget_sensitivity import CPU_CAPS, MAX_EPOCHS, run_budget_worker
from .evaluation import evaluate
from .learning import Learner
from .policies import Controller
from .run import (
    SEEDS,
    digest,
    encode,
    examples_for_training,
    profiles,
    scenarios,
    source_manifest,
    write_json,
)


def expected_rosters(plan):
    profiles = [profile["digest"] for profile in plan["profiles"]]
    axes = (profiles, plan["training_seeds"], plan["cpu_caps_seconds"], plan["methods"])
    scenario_ids = [scenario["id"] for scenario in plan["confirmation"]]
    if any(not axis or len(axis) != len(set(axis)) for axis in (*axes, scenario_ids)):
        raise ValueError("CPU plan has an empty or duplicated roster dimension")
    workers = {
        f"{profile[:12]}-{seed}-{cap}-{method}": (profile, seed, cap, method)
        for profile in profiles
        for seed in axes[1]
        for cap in axes[2]
        for method in axes[3]
    }
    expected_count = math.prod(len(axis) for axis in axes)
    comparisons = {
        (worker, scenario) for worker in workers for scenario in scenario_ids
    }
    if (
        len(workers) != expected_count
        or plan["expected_workers"] != expected_count
        or plan["expected_comparison_rows"] != len(comparisons)
    ):
        raise ValueError(
            "CPU plan has a collision or inconsistent Cartesian denominator"
        )
    return workers, comparisons


def validate_complete(plan, receipts, rows):
    """Reject missing/duplicate workers or rows, including NoCandidate rows."""
    workers, comparisons = expected_rosters(plan)
    by_id = {}
    for receipt in receipts:
        key = receipt["id"]
        actual = (
            receipt["profile_id"],
            receipt["seed"],
            receipt["hard_worker_cpu_seconds"],
            receipt["method"],
        )
        if (
            key in by_id
            or workers.get(key) != actual
            or receipt["candidate_status"] not in ("Available", "NoCandidate")
        ):
            raise ValueError("Duplicate or mismatched CPU worker identity")
        if receipt.get("parent_error") is not None or receipt["source_drift"]:
            raise ValueError("CPU worker evidence failed parent/source validation")
        by_id[key] = receipt
    if set(by_id) != set(workers):
        raise ValueError("CPU worker roster is incomplete")
    seen = set()
    for row in rows:
        key = (row["attempt_id"], row["scenario_id"])
        if key in seen or key not in comparisons:
            raise ValueError("Duplicate or unexpected CPU comparison identity")
        receipt = by_id[key[0]]
        if (
            (
                row["profile_id"],
                row["training_seed"],
                row["cpu_cap_seconds"],
                row["method"],
            )
            != workers[key[0]]
            or row["candidate_status"] != receipt["candidate_status"]
            or row["worker_cpu_seconds"] != receipt["worker_inclusive_cpu_seconds"]
            or row["retained_epochs"] != receipt["completed_epochs"]
            or row["parameters_sha256"] != receipt["parameters_sha256"]
        ):
            raise ValueError("CPU comparison is bound to a different worker receipt")
        if row["candidate_status"] == "Available":
            if (
                any(
                    type(row[field]) not in (int, float)
                    or not math.isfinite(row[field])
                    for field in ("value", "policy_gap")
                )
                or row["policy_gap"] < -1e-10
            ):
                raise ValueError("Available CPU candidate has no valid exact result")
        elif row["value"] is not None or row["policy_gap"] is not None:
            raise ValueError("Unavailable CPU candidate acquired a fabricated score")
        seen.add(key)
    if seen != comparisons:
        raise ValueError(
            "CPU comparison roster is incomplete, including unavailable cases"
        )


def run(output):
    output.mkdir(parents=True, exist_ok=False)
    sources = source_manifest()
    profile_roster = [(digest(asdict(profile)), profile) for profile in profiles()]
    confirmation = scenarios("confirmation")
    plan = {
        "schema": "hepta.ctrl1.cpu-campaign.v1",
        "sources": sources,
        "profiles": [
            {"digest": key, **asdict(profile)} for key, profile in profile_roster
        ],
        "training_seeds": SEEDS,
        "cpu_caps_seconds": CPU_CAPS,
        "max_epochs": MAX_EPOCHS,
        "methods": ("actor_critic", "distillation"),
        "confirmation": [
            {"id": key, **asdict(scenario)} for key, scenario in confirmation
        ],
        "expected_workers": len(profile_roster) * len(SEEDS) * len(CPU_CAPS) * 2,
        "expected_comparison_rows": len(profile_roster)
        * len(SEEDS)
        * len(CPU_CAPS)
        * 2
        * len(confirmation),
        "selection": "last complete epoch; no development/test checkpoint selection",
        "scope": "matched worker CPU allowance; complete physical pipeline cost is not equated",
    }
    expected_rosters(plan)
    write_json(output / "PLAN.json", plan)
    receipts, rows = [], []
    failure, caught, active, current, phase = None, None, False, None, "shared_roster"
    attempts = (output / "attempts.jsonl").open("xb")

    def event(value):
        attempts.write(encode(value) + b"\n")
        attempts.flush()

    try:
        for profile_id, profile in profile_roster:
            phase = "shared_roster"
            examples, roster_cost = examples_for_training(profile)
            write_json(
                output / f"shared-roster-{profile_id[:12]}.json",
                {
                    "costs": roster_cost,
                    "examples": [
                        {"scenario": asdict(s), "public_post_base_state": asdict(state)}
                        for s, state in examples
                    ],
                },
            )
            with (output / f"results-{profile_id[:12]}.jsonl").open(
                "xb"
            ) as result_file:
                for seed in SEEDS:
                    for cap in CPU_CAPS:
                        for method in plan["methods"]:
                            current = f"{profile_id[:12]}-{seed}-{cap}-{method}"
                            phase, active = "worker", True
                            event({"id": current, "status": "Started"})
                            receipt = run_budget_worker(
                                examples,
                                profile,
                                seed,
                                method,
                                cap,
                                output / "workers" / current,
                            )
                            receipt["id"], receipt["profile_id"] = current, profile_id
                            receipts.append(receipt)
                            if receipt.get("parent_error") is not None:
                                raise RuntimeError(
                                    f"Post-worker validation failed: {receipt['parent_error']}"
                                )
                            event(
                                {
                                    "id": current,
                                    "status": receipt["candidate_status"],
                                    "worker_status": receipt["worker"]["status"],
                                    "termination": receipt["termination"]["kind"],
                                }
                            )
                            active, phase = False, "confirmation_evaluation"
                            learner = None
                            if receipt["candidate_status"] == "Available":
                                learner = Learner.from_record(
                                    json.loads(
                                        Path(receipt["checkpoint_path"]).read_bytes()
                                    )
                                )
                            for scenario_id, scenario in confirmation:
                                row = {
                                    "attempt_id": current,
                                    "profile_id": profile_id,
                                    "training_seed": seed,
                                    "cpu_cap_seconds": cap,
                                    "method": method,
                                    "scenario_id": scenario_id,
                                    "candidate_status": receipt["candidate_status"],
                                    "worker_cpu_seconds": receipt[
                                        "worker_inclusive_cpu_seconds"
                                    ],
                                    "retained_epochs": receipt["completed_epochs"],
                                    "parameters_sha256": receipt["parameters_sha256"],
                                }
                                if learner is not None:
                                    row.update(
                                        evaluate(
                                            scenario,
                                            profile,
                                            Controller("fast", profile, learner),
                                        )
                                    )
                                else:
                                    row.update(
                                        {
                                            "value": None,
                                            "policy_gap": None,
                                            "reason": receipt["termination"]["kind"],
                                        }
                                    )
                                rows.append(row)
                                result_file.write(encode(row) + b"\n")
                            print(
                                json.dumps(
                                    {
                                        "attempt": current,
                                        "candidate": receipt["candidate_status"],
                                        "epochs": receipt["completed_epochs"],
                                        "cpu": receipt["worker_inclusive_cpu_seconds"],
                                    }
                                ),
                                flush=True,
                            )
        phase = "qualification"
        if sources != source_manifest():
            raise RuntimeError("CPU sensitivity source drift; no final qualification")
        validate_complete(plan, receipts, rows)
        summary = []
        for profile_id, _ in profile_roster:
            for cap in CPU_CAPS:
                for method in plan["methods"]:
                    group = [
                        r
                        for r in receipts
                        if r["profile_id"] == profile_id
                        and r["method"] == method
                        and r["hard_worker_cpu_seconds"] == cap
                    ]
                    outcomes = [
                        r
                        for r in rows
                        if r["profile_id"] == profile_id
                        and r["method"] == method
                        and r["cpu_cap_seconds"] == cap
                        and r["value"] is not None
                    ]
                    summary.append(
                        {
                            "profile_id": profile_id,
                            "cpu_cap_seconds": cap,
                            "method": method,
                            "attempts": len(group),
                            "available": sum(
                                r["candidate_status"] == "Available" for r in group
                            ),
                            "mean_worker_cpu_seconds": statistics.mean(
                                r["worker_inclusive_cpu_seconds"] for r in group
                            ),
                            "mean_retained_epochs": statistics.mean(
                                r["completed_epochs"] for r in group
                            ),
                            "mean_value_available_only": statistics.mean(
                                r["value"] for r in outcomes
                            )
                            if outcomes
                            else None,
                            "mean_policy_gap_available_only": statistics.mean(
                                r["policy_gap"] for r in outcomes
                            )
                            if outcomes
                            else None,
                        }
                    )
        report = {
            "schema": "hepta.ctrl1.cpu-report.v1",
            "status": "COMPLETED_CPU_ALLOWANCE_SENSITIVITY",
            "plan_sha256": digest(plan),
            "worker_attempts": len(receipts),
            "comparison_rows": len(rows),
            "available": sum(r["candidate_status"] == "Available" for r in receipts),
            "unavailable": sum(r["candidate_status"] != "Available" for r in receipts),
            "total_worker_cpu_seconds": sum(
                r["worker_inclusive_cpu_seconds"] for r in receipts
            ),
            "summary": summary,
            "authority": "none",
            "limitations": [
                "POSIX worker CPU and wall limits only",
                "three training seeds; descriptive results",
                "known finite model; no real-task or full energy/money qualification",
            ],
        }
    except BaseException as error:
        caught = error
        failure = {
            "phase": phase,
            "worker_id": current,
            "error_type": type(error).__name__,
            "message": str(error)[:2000],
        }
        event(
            {
                "id": current if active else "campaign",
                "status": "ParentFailed",
                **failure,
            }
        )
        write_json(output / "FAILURE.json", failure)
        report = {
            "schema": "hepta.ctrl1.cpu-report.v1",
            "status": "FAILED_CPU_ALLOWANCE_SENSITIVITY",
            "plan_sha256": digest(plan),
            "worker_attempts": len(receipts),
            "comparison_rows": len(rows),
            "expected_workers": plan["expected_workers"],
            "expected_comparison_rows": plan["expected_comparison_rows"],
            "failure": failure,
            "authority": "none",
        }
    finally:
        attempts.close()
        write_json(output / "RECEIPTS.json", receipts)
        write_json(output / "REPORT.json", report)
        inventory = {
            str(path.relative_to(output)): {
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "bytes": path.stat().st_size,
            }
            for path in sorted(output.rglob("*"))
            if path.is_file()
        }
        write_json(
            output / "ARTIFACTS.json",
            {
                "plan_sha256": digest(plan),
                "status": report["status"],
                "files": inventory,
            },
        )
    if failure is not None:
        raise caught
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = run(args.output)
    print(
        json.dumps(
            {
                key: result[key]
                for key in (
                    "status",
                    "worker_attempts",
                    "comparison_rows",
                    "available",
                    "unavailable",
                )
            }
        )
    )
