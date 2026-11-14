"""Replay frozen real profiles solely to qualify v2 metering integration.

Uses one already observed development source, five registered workflows and
all original arms/regimes from the first fit. It does not fit models, estimate
benefit, retune policies, read confirmation, or consume a FinalUse grant.
"""

import argparse
from collections import Counter
import copy
import json
import math
from pathlib import Path
import sys

from .metering import CATEGORIES, atomic_json, canonical_sha, file_sha


def pinned(path, digest):
    if file_sha(path) != digest:
        raise ValueError(
            "Diagnostic input differs from the independent pin: " + str(path)
        )
    return json.loads(Path(path).read_bytes())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("plan", "selected", "lock", "code_manifest"):
        parser.add_argument("--" + name.replace("_", "-"), type=Path, required=True)
        parser.add_argument("--" + name.replace("_", "-") + "-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--predecessor-result", type=Path)
    parser.add_argument("--predecessor-result-sha256")
    parser.add_argument("--predecessor-native-job-id")
    args = parser.parse_args()
    plan = pinned(args.plan, args.plan_sha256)
    selected = pinned(args.selected, args.selected_sha256)
    lock = pinned(args.lock, args.lock_sha256)
    manifest = pinned(args.code_manifest, args.code_manifest_sha256)
    if (
        plan["selected_sources_sha256"] != args.selected_sha256
        or lock["pilot_plan_sha256"] != args.plan_sha256
        or plan["confirmation_actor_access_authorized"]
        or plan["adoption_authorized"]
    ):
        raise ValueError(
            "Original research boundary differs from the diagnostic contract"
        )
    code_root = Path(__file__).resolve().parents[2]
    for binding in manifest["files"]:
        if file_sha(code_root / binding["path"]) != binding["sha256"]:
            raise ValueError("Diagnostic code does not match its frozen package")
    for binding in plan["source_pins"]:
        if file_sha(binding["path"]) != binding["sha256"]:
            raise ValueError("Original code-v3 source changed before diagnostic")
    config = copy.deepcopy(plan["execution"])
    original_root = config["repository_root"]
    config.update(
        repository_root=str(code_root), scripts_root=str(code_root / "scripts")
    )
    config["runtime_roots"] = [
        str(code_root) if item == original_root else item
        for item in config["runtime_roots"]
    ]
    if Path(config["python"]).resolve() != Path(sys.executable).resolve():
        raise ValueError("Use the original pinned runtime interpreter")
    sys.path.insert(0, config["pillow_path"])
    from .study import run_requests

    source = sorted(selected["groups"]["pilot_new"])[0]
    candidates = [
        row for row in selected["cases"]["pilot_new"] if row["source_id"] == source
    ]
    families = {
        "text_sufficient",
        "text_image_complementary",
        "selective_refinement",
        "preparation_required",
        "continuation_not_worthwhile",
    }
    if len(candidates) != 5 or {row["task_family"] for row in candidates} != families:
        raise ValueError(
            "The observed source does not contain all five registered workflows"
        )
    if any(row["role"] != "development" for row in candidates):
        raise ValueError("Diagnostic accepts already observed development only")
    fit_id = plan["independent_fit_roster"][0]["fit_id"]
    profiles = [
        row["profile"] for row in lock["selected"] if row["profile"]["fit_id"] == fit_id
    ]
    expected = {
        (regime, arm)
        for regime in plan["design"]["regimes"]
        for arm in plan["design"]["arms"]
    }
    if (
        len(profiles) != len(expected)
        or {(p["regime"], p["arm"]) for p in profiles} != expected
    ):
        raise ValueError("Original locked profile roster is incomplete")
    for profile in profiles:
        if (
            file_sha(profile["weights"]) != profile["model_sha256"]
            or file_sha(profile["control_plan"]) != profile["control_plan_sha256"]
        ):
            raise ValueError("Original model/control plan bytes changed")
    predecessors, previous = {}, None
    if any(
        (
            args.predecessor_result,
            args.predecessor_result_sha256,
            args.predecessor_native_job_id,
        )
    ):
        if not all(
            (
                args.predecessor_result,
                args.predecessor_result_sha256,
                args.predecessor_native_job_id,
            )
        ):
            raise ValueError("Every predecessor binding is required")
        previous = pinned(args.predecessor_result, args.predecessor_result_sha256)
        if (
            previous["run_id"] == args.run_id
            or previous["source_group_id"] != source
            or previous["fit_id"] != fit_id
            or previous["original_plan_sha256"] != args.plan_sha256
            or previous["original_lock_sha256"] != args.lock_sha256
            or previous["original_selected_sha256"] != args.selected_sha256
        ):
            raise ValueError("Predecessor is not the same diagnostic roster")
        for binding in previous["bindings"]:
            relative = Path(binding["relative_output"])
            if relative.is_absolute() or ".." in relative.parts:
                raise ValueError("Unsafe predecessor artifact path")
            result = pinned(
                args.predecessor_result.parent / relative / "result.json",
                binding["result_sha256"],
            )
            key = (result["regime"], result["arm"], result["task_family"])
            expected_id = "meter-v2-" + canonical_sha([previous["run_id"], *key])[:32]
            if key in predecessors or result["original_operation_id"] != expected_id:
                raise ValueError("Duplicate or incorrectly bound predecessor operation")
            predecessors[key] = result
        if set(predecessors) != {
            (regime, arm, family) for regime, arm in expected for family in families
        }:
            raise ValueError("Predecessor attempt inventory is incomplete")
    args.output.mkdir(mode=0o700, parents=True, exist_ok=False)
    requests = []
    for profile in sorted(profiles, key=lambda value: (value["regime"], value["arm"])):
        for case in sorted(candidates, key=lambda value: value["task_family"]):
            identity = (
                "meter-v2-"
                + canonical_sha(
                    [
                        args.run_id,
                        profile["regime"],
                        profile["arm"],
                        case["task_family"],
                    ]
                )[:32]
            )
            current = copy.deepcopy(profile)
            predecessor = predecessors.get(
                (profile["regime"], profile["arm"], case["task_family"])
            )
            current.update(
                original_operation_id=identity,
                retry_of=None,
                original_policy_sha256=profile["policy_sha256"],
                policy_sha256=canonical_sha(
                    {
                        "controller": profile["controller"],
                        "control_plan_sha256": profile["control_plan_sha256"],
                        "diagnostic_code_manifest_sha256": args.code_manifest_sha256,
                    }
                ),
            )
            if predecessor is not None:
                current["instrumentation_predecessor_operation_id"] = predecessor[
                    "original_operation_id"
                ]
                if predecessor["terminal_status"] == "Failed":
                    current["retry_of"] = predecessor["original_operation_id"]
            requests.append(
                {
                    "config": config,
                    "case": case,
                    "profile": current,
                    "output": str(args.output / "episodes" / f"{len(requests):04d}"),
                    "training": False,
                }
            )
    contract = {
        "schema": "ndu.real.meter-diagnostic.v2",
        "run_id": args.run_id,
        "original_plan_sha256": args.plan_sha256,
        "original_lock_sha256": args.lock_sha256,
        "original_selected_sha256": args.selected_sha256,
        "code_manifest_sha256": args.code_manifest_sha256,
        "fit_id": fit_id,
        "source_group_id": source,
        "planned_episodes": len(requests),
        "profile_count": len(profiles),
        "registered_workflows": sorted(families),
        "budgets": plan["design"]["budgets"],
        "model_fits": 0,
        "scientific_admission": "HOLD",
        "confirmation_access_authorized": False,
        "adoption_authorized": False,
        "native_owner_authentication": "SEPARATE_REQUIRED",
        "statistical_use": "integration diagnostic only; already observed development source",
    }
    contract.update(
        predecessor_result_sha256=args.predecessor_result_sha256,
        predecessor_native_job_id=args.predecessor_native_job_id,
        predecessor_run_id=None if previous is None else previous["run_id"],
        retry_of_failed_predecessor_count=sum(
            r["profile"]["retry_of"] is not None for r in requests
        ),
        revalidation_predecessor_count=sum(
            "instrumentation_predecessor_operation_id" in r["profile"]
            and r["profile"]["retry_of"] is None
            for r in requests
        ),
    )
    atomic_json(args.output / "DIAGNOSTIC_CONTRACT.json", contract)
    phase = run_requests(
        args.output,
        "qualification",
        requests,
        plan["design"]["budgets"]["max_workers"],
        plan["design"]["budgets"]["phase_wall_seconds"],
    )
    counts, reconciliation, costs, issues, bindings = (
        Counter(),
        Counter(),
        Counter(),
        [],
        [],
    )
    unknown = wall = outer_wall = outer_cpu = 0.0
    missing_meters = missing_outer = 0
    for original in phase["attempts"]:
        if "output" not in original:
            issues.append({"kind": "unresolved_original", "record": original})
            missing_meters += 1
            missing_outer += 1
            continue
        directory = Path(original["output"])
        outer = json.loads((directory / "original-attempt.json").read_bytes())
        outer_wall += outer["wall_seconds"]
        outer_cpu += outer["cpu_seconds"]
        result = json.loads((directory / "result.json").read_bytes())
        counts[result["terminal_status"]] += 1
        meter = result.get("deployment_meter", {})
        reconciliation[meter.get("interval_reconciliation", "MISSING")] += 1
        if (
            result["terminal_status"] == "Failed"
            or meter.get("interval_reconciliation")
            != "EXACT_MONOTONIC_INTERVALS_SAME_HOST"
        ):
            issues.append(
                {
                    "kind": "episode_or_meter_failure",
                    "output": str(directory),
                    "error": result.get("error"),
                }
            )
        duration = meter.get("wall_seconds")
        classified = meter.get("costs", {})
        gap = meter.get("observed_unclassified_overhead_seconds")
        numeric = lambda value: (
            type(value) in (int, float) and math.isfinite(value) and value >= 0
        )
        if not numeric(duration):
            missing_meters += 1
            issues.append(
                {"kind": "missing_deployment_meter", "output": str(directory)}
            )
        else:
            wall += duration
            partition_valid = (
                meter.get("interval_reconciliation")
                == "EXACT_MONOTONIC_INTERVALS_SAME_HOST"
                and all(numeric(classified.get(key)) for key in CATEGORIES)
                and numeric(gap)
                and abs(sum(classified.values()) + gap - duration) < 1e-6
            )
            if partition_valid:
                for category in CATEGORIES:
                    costs[category] += classified[category]
                unknown += gap
            else:
                unknown += duration
                issues.append(
                    {
                        "kind": "unclassified_deployment_envelope",
                        "output": str(directory),
                    }
                )
        bindings.append(
            {
                "relative_output": str(directory.relative_to(args.output)),
                "result_sha256": file_sha(directory / "result.json"),
                "attempt_sha256": file_sha(directory / "original-attempt.json"),
                "source_sha256": result.get("source_sha256"),
                "model_sha256": result.get("model_sha256"),
                "output_text_sha256": result.get("output_text_sha256"),
                "output_image_sha256": result.get("output_image_sha256"),
                "evaluator_sha256": result.get("score_components", {}).get(
                    "evaluator_source_sha256"
                ),
                "rubric_sha256": result.get("score_components", {}).get(
                    "rubric_sha256"
                ),
            }
        )
    for binding in manifest["files"]:
        if file_sha(code_root / binding["path"]) != binding["sha256"]:
            issues.append(
                {"kind": "diagnostic_source_changed", "path": binding["path"]}
            )
    summary = {
        **contract,
        "observed_episodes": sum(counts.values()),
        "terminal_counts": dict(counts),
        "interval_reconciliation_counts": dict(reconciliation),
        "issues": issues,
        "not_started_requests": phase["not_started_requests"],
        "phase_result_sha256": file_sha(
            args.output / "qualification/phase-result.json"
        ),
        "observed_category_wall_seconds": dict(costs),
        "observed_unclassified_seconds": unknown,
        "sum_episode_wall_seconds": wall,
        "sum_is_elapsed_campaign_time": False,
        "missing_deployment_meter_count": missing_meters,
        "deployment_wall_sum_complete": missing_meters == 0,
        "sum_outer_task_wall_seconds": outer_wall,
        "sum_outer_task_process_and_reaped_children_cpu_seconds": outer_cpu,
        "missing_outer_attempt_count": missing_outer,
        "outer_costs_additive_with_deployment": False,
        "energy_joules": None,
        "provider_charges": None,
        "full_physical_cost_complete": False,
        "bindings": bindings,
        "qualification_status": "PASSED"
        if not issues and sum(counts.values()) == len(requests)
        else "FAILED",
    }
    atomic_json(args.output / "DIAGNOSTIC_RESULT.json", summary)
    print(
        json.dumps(
            {key: value for key, value in summary.items() if key != "bindings"},
            sort_keys=True,
        ),
        flush=True,
    )
    return 0 if summary["qualification_status"] == "PASSED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
