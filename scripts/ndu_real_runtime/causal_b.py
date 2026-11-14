"""Finite matched-training B pilots; structural qualification is not adoption.

--training-only consumes original train-only v2 JSONL without images or a sealed
evaluator. It produces checkpoints/receipts for a separate source-pinned real
deployment evaluation. No episode is counted as another independent training fit.
"""

import argparse
from collections import Counter
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
import json
import os
from pathlib import Path
import time

from ndu_real_materials.common import strict_json
from .controllers import ControlPlan
from .metering import _usage, atomic_json, canonical_sha, file_sha
from .objective import utility_profile
from .study import now
from .training import FitConfig, _source_pins
from .training_grid import JOINT_CONTROLLERS, fit_grid, model_index
from .causal_b_contract import (
    initialization_audit,
    paired_audit,
    record_inventory,
    smoke_design as smoke_design,
    validate_design,
)


def run_matched_grid(root, records, design, config, *, records_sha256=None):
    """Admit only immediately runnable jobs; never queue work past the deadline."""
    from .pipeline import run_training_job

    started, initial_cpu = time.perf_counter(), _usage()
    root, records = Path(root), Path(records)
    validate_design(design)
    budget, training = design["budgets"], design["training"]
    deadline = started + budget["training_wall_seconds"]
    records_sha256 = records_sha256 or file_sha(records)
    inventory = record_inventory(records, records_sha256)
    if (
        inventory["utility_profile_sha256s"]
        != [canonical_sha(utility_profile(ControlPlan(**design["controller"])))]
        or len(inventory["rubric_sha256s"]) != 1
        or not inventory["observed_successors"]
    ):
        raise ValueError(
            "B records need observed successors and one matching utility/rubric profile"
        )
    plans = {}
    for mode in design["memory_modes"]:
        path = root / ("training-control-" + mode + ".json")
        atomic_json(
            path,
            {
                "control": {**design["controller"], "memory_mode": mode},
                "episode_wall_seconds": budget["episode_wall_seconds"],
                "fixed_schedule": design["fixed_schedule_candidates"][0],
                "seed": 0,
            },
        )
        plans[mode] = path
    grid = fit_grid(
        str(records),
        records_sha256,
        str(root / "models" / "independent"),
        python=config["python"],
        seeds=design["training_seeds"],
        head_lrs=training["head_learning_rates"],
        config=FitConfig(
            content_epochs=training["content_epochs"],
            fit_epochs=training["fit_epochs"],
            batch_size=training["batch_size"],
            content_lr=training["content_learning_rate"],
            latency_weight=design["controller"].get("latency_weight", 0.01),
            max_wall_seconds=training["max_wall_seconds"],
        ),
        control_plans=plans,
        observation_policy="matched_episodes",
        regimes=design["regimes"],
    )
    timeout = training["max_wall_seconds"] + budget["training_job_overhead_seconds"]
    for job in grid["jobs"]:
        job["timeout_seconds"] = timeout
        job["source_pins"] = grid["intent"]["source_pins"]
    grid["admission_budget"] = budget
    grid["record_inventory"] = inventory
    # Prioritize the full main contrast across all seeds before extra comparators;
    # the ordering and the entire denominator are frozen before any job starts.
    grid["jobs"].sort(
        key=lambda j: (
            j["phase"] != "content",
            j["trial_index"] or 0,
            ("shared", *JOINT_CONTROLLERS).index(j["controller"]),
            j["core"],
            j["seed"],
            j["memory_mode"],
        )
    )
    atomic_json(root / "fit-plan.json", grid)
    atomic_json(root / "model-index.planned.json", model_index(grid))
    results, pending = {}, {}
    with (root / "training-events.jsonl").open("x", buffering=1) as ledger:

        def retain(value):
            ledger.write(json.dumps({"at": now(), **value}, allow_nan=False) + "\n")
            ledger.flush()
            os.fsync(ledger.fileno())

        with ProcessPoolExecutor(max_workers=budget["max_workers"]) as pool:
            for phase in ("content", "fit"):
                todo = [job for job in grid["jobs"] if job["phase"] == phase]
                while todo or pending:
                    while todo and len(pending) < budget["max_workers"]:
                        job = todo.pop(0)
                        blocked = any(
                            results[d]["status"] != "completed"
                            for d in job["depends_on"]
                        )
                        status = (
                            "budget_stopped"
                            if time.perf_counter() + timeout > deadline
                            else ("blocked_by_failed_dependency" if blocked else None)
                        )
                        if status:
                            results[job["job_id"]] = {
                                "original_operation_id": job["job_id"],
                                "status": status,
                                "admitted": False,
                                "weights_sha256": None,
                                "receipt_sha256": None,
                                "dependency_statuses": {
                                    d: results[d]["status"] for d in job["depends_on"]
                                },
                            }
                            retain(
                                {
                                    "event": "not_admitted",
                                    "result": results[job["job_id"]],
                                }
                            )
                            continue
                        retain({"event": "dispatch_admitted", "job_id": job["job_id"]})
                        pending[
                            pool.submit(
                                run_training_job, job, config, root / "training-jobs"
                            )
                        ] = job
                    if not pending:
                        continue
                    finished, _ = wait(pending, timeout=1, return_when=FIRST_COMPLETED)
                    for future in finished:
                        job = pending.pop(future)
                        try:
                            results[job["job_id"]] = {
                                **future.result(),
                                "admitted": True,
                            }
                        except BaseException as error:
                            results[job["job_id"]] = {
                                "original_operation_id": job["job_id"],
                                "status": "unresolved",
                                "admitted": True,
                                "error": str(error),
                            }
                        retain(
                            {
                                "event": "terminal_observed",
                                "result": results[job["job_id"]],
                            }
                        )
    index = model_index(grid)
    by_output = {job["output"]: results[job["job_id"]] for job in grid["jobs"]}
    for row in index["content"] + index["fits"]:
        observed = by_output[row["directory"]]
        row.update(
            {
                key: observed.get(key)
                for key in ("status", "weights_sha256", "receipt_sha256")
            }
        )
    atomic_json(root / "model-index.json", index)
    audit = paired_audit(grid, results)
    admitted = [row for row in results.values() if row["admitted"]]
    envelope_complete = all(
        row.get("wall_seconds") is not None and row.get("cpu_seconds") is not None
        for row in admitted
    )
    result = {
        "schema": "ndu.real.causal-b.training-result.v1",
        "grid_id": grid["grid_id"],
        "fit_plan_sha256": file_sha(root / "fit-plan.json"),
        "planned_jobs": len(grid["jobs"]),
        "status_counts": dict(Counter(r["status"] for r in results.values())),
        "results": results,
        "paired_training_audit": audit,
        "initialization_audit": initialization_audit(grid, results),
        "independent_seed_groups_planned": len(design["training_seeds"]),
        "independent_seed_groups_complete": sum(
            all(
                results[j["job_id"]]["status"] == "completed"
                for j in grid["jobs"]
                if j["seed"] == seed
            )
            for seed in design["training_seeds"]
        ),
        "episode_seeds_are_independent_fits": False,
        "campaign_wall_seconds": time.perf_counter() - started,
        "observer_envelope_cpu_seconds": _usage() - initial_cpu,
        "sum_job_wall_seconds": sum(r["wall_seconds"] for r in admitted)
        if envelope_complete
        else None,
        "sum_job_cpu_seconds": sum(r["cpu_seconds"] for r in admitted)
        if envelope_complete
        else None,
        "job_costs_overlap_campaign_envelope": True,
        "budget_overrun_seconds": max(0.0, time.perf_counter() - deadline),
        "hard_phase_limit_enforced_by_parent_runtime": False,
        "admission_rule": "remaining phase time must cover the entire subprocess timeout; admitted originals are drained",
        "upstream_collection_costs_included": False,
        "energy_joules": None,
        "provider_charges": None,
        "scientific_admission": "HOLD",
        "adoption_authorized": False,
    }
    atomic_json(root / "fit-results.json", result)
    return index


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--design", type=Path, required=True)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--records", type=Path)
    parser.add_argument("--records-sha256")
    parser.add_argument("--training-only", action="store_true")
    args = parser.parse_args(argv)
    design, config = (
        strict_json(args.design.read_bytes()),
        strict_json(args.config.read_bytes()),
    )
    validate_design(design)
    config.setdefault("pillow_path", config["scripts_root"])
    if (
        any(
            not Path(config[k]).is_absolute()
            for k in ("python", "scripts_root", "repository_root")
        )
        or not args.root.is_absolute()
    ):
        parser.error("Absolute runtime and fresh output paths are required")
    if Path(config["repository_root"]).resolve() != Path(__file__).resolve().parents[2]:
        parser.error("Execution config and imported source checkout differ")
    if not args.training_only:
        if args.records is not None:
            parser.error(
                "External observations use --training-only; full real runs collect their own records"
            )
        from .pipeline import execute

        return execute(config, args.design, args.root)
    if (
        args.records is None
        or args.records_sha256 is None
        or not args.records.is_absolute()
    ):
        parser.error(
            "Training-only requires absolute original --records and --records-sha256"
        )
    inventory = record_inventory(args.records, args.records_sha256)
    pins = {
        **_source_pins(),
        **{
            "scripts/ndu_real_runtime/" + name + ".py": file_sha(
                Path(__file__).with_name(name + ".py")
            )
            for name in (
                "causal_b",
                "causal_b_contract",
                "training_grid",
                "pipeline",
                "matrix",
            )
        },
    }
    args.root.mkdir(parents=True, exist_ok=False)
    plan_pin = atomic_json(
        args.root / "CAUSAL_B_PLAN.json",
        {
            "schema": "ndu.real.causal-b.plan.v1",
            "registered_at": now(),
            "design": design,
            "config": config,
            "records": inventory,
            "design_sha256": file_sha(args.design),
            "config_sha256": file_sha(args.config),
            "records_path": str(args.records),
            "source_pins": pins,
            "independent_replicate_unit": "training seed; all arms and trials are paired",
            "deployment_evaluated": False,
            "upstream_costs_separately_required": True,
        },
    )
    status, error = "completed", None
    try:
        run_matched_grid(
            args.root, args.records, design, config, records_sha256=args.records_sha256
        )
        if file_sha(args.records) != args.records_sha256 or any(
            file_sha(Path(config["repository_root"]) / name) != digest
            for name, digest in pins.items()
        ):
            raise ValueError("Frozen B records or execution source changed")
        result = strict_json((args.root / "fit-results.json").read_bytes())
        if any(
            row["same_initialization_data_batches_and_opportunities"] is False
            for row in result["paired_training_audit"]
        ):
            raise ValueError(
                "A completed B pair violated its matched training contract"
            )
        if any(
            row["all_observed_initializations_equal"] is False
            for row in result["initialization_audit"]
        ):
            raise ValueError(
                "An independent seed did not share identical initial parameter bytes"
            )
        if result["status_counts"].get("completed", 0) != result["planned_jobs"]:
            status = "incomplete"
    except BaseException as exception:
        status, error = (
            "failed",
            {"type": type(exception).__name__, "message": str(exception)},
        )
    atomic_json(
        args.root / "CAUSAL_B_RESULT.json",
        {
            "schema": "ndu.real.causal-b.result.v1",
            "status": status,
            "error": error,
            "plan_sha256": plan_pin,
            "finished_at": now(),
            "training_only": True,
            "deployment_evaluated": False,
            "scientific_admission": "HOLD",
            "adoption_authorized": False,
            "original_attempts_must_not_be_replayed": True,
        },
    )
    return 0 if status == "completed" else 2 if status == "incomplete" else 1


if __name__ == "__main__":
    raise SystemExit(main())
