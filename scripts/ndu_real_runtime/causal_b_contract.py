"""Prospective B design and structural audits; no real-effect claim is inferred."""

from collections import defaultdict
from dataclasses import asdict
import math
from pathlib import Path

from ndu_real_materials.common import strict_json
from .controllers import ControlPlan
from .metering import file_sha
from .training import validate_record
from .training_grid import JOINT_CONTROLLERS, PILOT_SEEDS
from .trajectory import V2_SCHEMA, validate_chains


def smoke_design(study_id, *, training_wall_seconds=390):
    """Explicit two-seed engineering pilot; the ordinary fit-grid default is four."""
    return {
        "study_id": study_id,
        "estimand": "matched_training",
        "evidence_scope": "engineering_training_smoke",
        "memory_modes": ["reset", "persistent"],
        "training_seeds": list(PILOT_SEEDS[:2]),
        "regimes": ["frozen", "joint"],
        "controller": {
            k: v for k, v in asdict(ControlPlan()).items() if k != "memory_mode"
        },
        "arms": {
            f"{core}_{controller}_{mode}": [core, controller, mode]
            for core in ("ordinary", "hepta")
            for controller in JOINT_CONTROLLERS
            for mode in ("reset", "persistent")
        },
        "training": {
            "observation_policy": "matched_episodes",
            "content_epochs": 2,
            "fit_epochs": 2,
            "batch_size": 32,
            "content_learning_rate": 0.003,
            "head_learning_rates": [0.003],
            "max_wall_seconds": 45,
        },
        "budgets": {
            "max_workers": 1,
            "training_wall_seconds": training_wall_seconds,
            "training_job_overhead_seconds": 15,
            "episode_wall_seconds": 60,
        },
        "fixed_schedule_candidates": [["WRITE_TEXT", "RENDER_IMAGE"]],
    }


def validate_design(design):
    expected = {
        (core, controller, mode)
        for core in ("ordinary", "hepta")
        for controller in JOINT_CONTROLLERS
        for mode in ("reset", "persistent")
    }
    if (
        design.get("estimand") != "matched_training"
        or design.get("memory_modes") != ["reset", "persistent"]
        or design["training"].get("observation_policy") != "matched_episodes"
        or {tuple(spec) for spec in design["arms"].values()} != expected
        or len(design["arms"]) != len(expected)
        or set(design["regimes"]) != {"frozen", "joint"}
        or not 2 <= len(design["training_seeds"]) <= 16
    ):
        raise ValueError(
            "B requires the complete paired training design and independent seeds"
        )
    ControlPlan(**design["controller"])
    budget = design["budgets"]
    for name, lower, upper in (
        ("training_wall_seconds", 1, 86400),
        ("training_job_overhead_seconds", 1, 60),
        ("episode_wall_seconds", 1, 3600),
    ):
        value = budget[name]
        if (
            type(value) not in (int, float)
            or not math.isfinite(value)
            or not lower <= value <= upper
        ):
            raise ValueError("Invalid finite B budget: " + name)
    if type(budget["max_workers"]) is not int or not 1 <= budget["max_workers"] <= 8:
        raise ValueError("B worker count outside its finite resource envelope")
    if len(design["fixed_schedule_candidates"]) != len(
        design["training"]["head_learning_rates"]
    ):
        raise ValueError(
            "Every arm needs the same prospectively declared tuning opportunities"
        )


def record_inventory(path, expected_sha256):
    path = Path(path)
    if (
        path.is_symlink()
        or not path.is_file()
        or path.stat().st_size > 512 * 1024 * 1024
    ):
        raise ValueError("B requires bounded original training JSONL")
    rows = []
    with path.open("rb") as stream:
        for number, raw in enumerate(stream, 1):
            if number > 10000 or len(raw) > 2 * 1024 * 1024:
                raise ValueError("B training observations exceed their finite bound")
            row = validate_record(strict_json(raw))
            if row["schema"] != V2_SCHEMA:
                raise ValueError(
                    "B does not convert legacy rows into persistent trajectories"
                )
            rows.append(row)
    if not rows or file_sha(path) != expected_sha256:
        raise ValueError(
            "Original B records are empty or differ from their frozen digest"
        )
    if len({row["record_id"] for row in rows}) != len(rows):
        raise ValueError("Duplicate B observation identity")
    return {
        "sha256": expected_sha256,
        "rows": len(rows),
        "complete_episodes": validate_chains(rows),
        "source_groups": len({row["source_group"] for row in rows}),
        "origin_run_ids": sorted({row["origin_run_id"] for row in rows}),
        "collection_memory_modes": sorted({row["memory_mode"] for row in rows}),
        "utility_profile_sha256s": sorted(
            {row["utility_profile_sha256"] for row in rows}
        ),
        "rubric_sha256s": sorted({row["rubric_sha256"] for row in rows}),
        "observed_successors": sum(
            row["next_candidate_features"] is not None for row in rows
        ),
        "material_authority_reverified_by_cloud_trainer": False,
    }


def paired_audit(grid, results):
    groups, checked = defaultdict(list), []
    for job in grid["jobs"]:
        groups[job["paired_memory_group"]].append(job)
    for identity, jobs in groups.items():
        complete = all(results[j["job_id"]]["status"] == "completed" for j in jobs)
        matched, prefit = None, {}
        if complete:
            rows = [strict_json(Path(j["receipt_path"]).read_bytes()) for j in jobs]
            signatures = []
            for row in rows:
                training = row[
                    "content_training" if row["stage"] == "content" else "fit_training"
                ]
                signatures.append(
                    {
                        "random_initial_parameters": row["initial_parameter_sha256"],
                        "records": row["records"]["sha256"],
                        "source": row["source_pins"],
                        "config": row["config"],
                        "policy": row["observation_policy"],
                        "partition": training["observation_partition_sha256"],
                        "batches": training["batch_schedule_sha256"],
                        "optimizer_steps": training["optimizer_steps"],
                    }
                )
                prefit[row["memory_mode"]] = row["prefit_parameter_sha256"]
            matched = signatures[0] == signatures[1]
        checked.append(
            {
                "paired_memory_group": identity,
                "job_ids": [j["job_id"] for j in jobs],
                "complete": complete,
                "same_initialization_data_batches_and_opportunities": matched,
                "initialization_scope": "seeded_constructor_before_pretraining_or_loading_content",
                "prefit_parameter_sha256_by_mode": prefit,
                "memory_specific_pretrained_content_may_differ": True,
            }
        )
    return checked


def initialization_audit(grid, results):
    evidence = defaultdict(list)
    for job in grid["jobs"]:
        if results[job["job_id"]]["status"] == "completed":
            receipt = strict_json(Path(job["receipt_path"]).read_bytes())
            evidence[job["seed"]].append(
                (job["core"], receipt["initial_parameter_sha256"])
            )
    return [
        {
            "training_seed": seed,
            "initialization_scope": "seeded_constructor_before_pretraining_or_loading_content",
            "completed_jobs_observed": len(rows),
            "cores_observed": sorted({row[0] for row in rows}),
            "initial_parameter_sha256s": sorted({row[1] for row in rows}),
            "all_observed_initializations_equal": len({row[1] for row in rows}) == 1
            if rows
            else None,
        }
        for seed in grid["intent"]["seeds"]
        for rows in [evidence[seed]]
    ]
