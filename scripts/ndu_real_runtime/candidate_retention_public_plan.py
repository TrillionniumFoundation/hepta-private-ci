"""MEM6 working-state retention with the exact MEM5 public selector fixed.

This is a fresh released-source experiment, not cross-session memory. Model,
OCR, schedule, admission caps and selector are shared; only pool retention
changes. All original MEM and MEM5 source groups remain excluded.
"""

from dataclasses import asdict
import hashlib
from pathlib import Path
import re

from ndu_real_materials.common import (
    binding,
    read_bound,
    read_relative,
    strict_json,
    write_json,
)
from .objective import canonical_sha
from .candidate_selection_plan import (
    BASELINE_MEM_PLAN_SHA256,
    prior_source_groups,
    require,
)

SCHEMA = "ndu.real.candidate-retention-public-request.v1"
PLAN_SCHEMA = "ndu.real.candidate-retention-public-plan.v1"
SELECTION_SALT = "mem6-fixed-public-retention-20261110-v1"
MEM5_PLAN_SHA256 = "e33050d4b01484f8b820730117ed57659476e9e1e922ffdd43673dee7a081f9d"
REQUIRED_PRIOR_PLANS = {BASELINE_MEM_PLAN_SHA256, MEM5_PLAN_SHA256}
MODES = ("current_only", "bounded")


def sampling_profile(request):
    groups = request.get("groups_per_role")
    require(
        isinstance(groups, dict)
        and set(groups) == {"development", "retention_validation"}
        and all(type(n) is int and 1 <= n <= 64 for n in groups.values())
        and request.get("selection_salt") == SELECTION_SALT,
        "Prespecified released source allocation and MEM6 salt required",
    )
    return {"selection_salt": SELECTION_SALT, "groups_per_role": dict(groups)}


def verify_cohort(plan, materials):
    """Rebuild the complete metadata-only cohort from independently pinned inputs."""
    from . import run_candidate_retention as legacy

    catalog = strict_json(legacy.read_pin(plan["catalog"], materials))
    manifest = strict_json(legacy.read_pin(plan["exclusion_manifest"], materials))
    request = {
        **plan,
        "excluded_source_groups": sorted({
            group for role in ("training", "tuning")
            for group in manifest["groups"][role]
        }),
        "prior_episode_plan_pins": [item["pin"] for item in plan["prior_episode_plans"]],
        "config": {"reference_index_sha256": plan["reference_index_sha256"]},
    }
    excluded, _ = legacy.exclusions(request, catalog, materials)
    prior, receipts = prior_source_groups(request, catalog, materials)
    excluded.update(prior)
    legacy.read_pin(plan["training_records"], materials)
    require(
        receipts == plan["prior_episode_plans"]
        and sorted(prior) == plan["prior_episode_source_groups"]
        and sorted(excluded) == plan["excluded_source_groups"],
        "Prior/exposure exclusion metadata differs from pinned original bytes",
    )
    selected = legacy.select_cases(
        catalog, excluded, plan["groups_per_role"], plan["selection_salt"]
    )
    fields = (
        "original_operation_id", "pair_id", "case_id", "source_group_id",
        "episode_group", "split", "task_family", "public_case_sha256",
        "retention_mode",
    )
    expected, run_order = [], []
    for case in selected:
        pair_id = plan["experiment_id"] + "-" + canonical_sha(
            [case["id"], plan["selection_salt"]]
        )[:20]
        modes = MODES if int(canonical_sha([pair_id, "order"])[0], 16) % 2 == 0 else tuple(reversed(MODES))
        operations = []
        for mode in modes:
            operation = pair_id + "-" + mode
            expected.append((
                operation, pair_id, case["id"], case["source_id"],
                case["episode_group"], case["role"], case["task_family"],
                case["packet"]["sha256"], mode,
            ))
            operations.append(operation)
        run_order.append(operations)
    require(
        expected == [tuple(row[key] for key in fields) for row in plan["episodes"]]
        and run_order == plan["paired_run_order"],
        "Full frozen source/episode/family roster or paired order differs",
    )


def freeze(request, output):
    """Freeze retained/current-only observations under one public selector."""
    from . import run_candidate_retention as legacy
    from .candidate_selector import PROFILE, validate_profile
    from .candidate_runtime import PROFILE_SCHEMA

    require(
        request.get("schema") == SCHEMA
        and isinstance(request.get("source_commit"), str)
        and re.fullmatch(r"[0-9a-f]{40}", request["source_commit"]),
        "Frozen selection request and exact source identity required",
    )
    require(
        isinstance(request.get("experiment_id"), str)
        and re.fullmatch(r"[A-Za-z0-9_-]{1,64}", request["experiment_id"]),
        "Bounded experiment identity required",
    )
    require(
        type(request.get("max_workers")) is int and 1 <= request["max_workers"] <= 2,
        "At most two workers are supported",
    )
    require(
        request.get("selector_profile_sha256") == canonical_sha(PROFILE),
        "Public selector policy differs from its frozen profile",
    )
    sampling = sampling_profile(request)
    require(
        request.get("sampling_profile_sha256") == canonical_sha(sampling),
        "Source allocation must be bound before reading source metadata",
    )
    require(
        REQUIRED_PRIOR_PLANS <= {
            pin.get("sha256") for pin in request["prior_episode_plan_pins"]
        },
        "Both original retention and MEM5 plans must be excluded",
    )
    legacy.verify_sources(request)
    config, materials = request["config"], Path(request["config"]["material_root"])
    catalog = strict_json(legacy.read_pin(request["catalog"], materials))
    excluded, training_groups = legacy.exclusions(request, catalog, materials)
    prior_groups, prior_receipts = prior_source_groups(request, catalog, materials)
    excluded.update(prior_groups)
    selected = legacy.select_cases(
        catalog, excluded, request["groups_per_role"], SELECTION_SALT
    )
    # Selection above reads metadata only. These are released-role identity reads.
    index_raw = read_relative(
        materials, "private/reference-index.v2.json", limit=8 * 1024**2
    )
    require(
        hashlib.sha256(index_raw).hexdigest() == config["reference_index_sha256"],
        "Reference index changed",
    )
    index = strict_json(index_raw)
    require(
        index.get("schema") == "ndu.real.reference-index.v2"
        and index["rubric"]["sha256"] == config["rubric_sha256"],
        "Reference/rubric identity differs",
    )
    read_bound(materials, index["rubric"])
    control, model_receipt = legacy.load_model(request, training_groups)
    require(
        config["episode_wall_seconds"] == 60
        and config["latency_weight"] == control.latency_weight,
        "Both retention modes require the same frozen 60-second objective",
    )
    write_json(output / "MODEL.json", model_receipt)
    write_json(
        output / "CONTROL.json",
        {
            "control": asdict(control),
            "episode_wall_seconds": 60.0,
            "fixed_schedule": legacy.SCHEDULE,
            "seed": 0,
        },
    )
    control_pin = binding(output / "CONTROL.json", output)
    episodes, jobs = [], []
    for case in selected:
        require(
            index["case_roles"][case["id"]] == case["role"]
            and index["cases"][case["id"]] == case["reference"],
            "Catalog role/reference differs from the pinned private index",
        )
        packet = strict_json(read_bound(materials, case["packet"]))
        reference = strict_json(read_bound(materials, case["reference"]))
        require(
            packet["case_id"] == case["id"]
            and all(
                reference[k] == case[v]
                for k, v in (
                    ("case_id", "id"),
                    ("role", "role"),
                    ("source_group", "source_id"),
                    ("episode_group", "episode_group"),
                )
            ),
            "Original source/episode identity differs",
        )
        pair_id = (
            request["experiment_id"]
            + "-"
            + canonical_sha([case["id"], SELECTION_SALT])[:20]
        )
        order = (
            MODES
            if int(canonical_sha([pair_id, "order"])[0], 16) % 2 == 0
            else tuple(reversed(MODES))
        )
        pair = []
        for mode in order:
            memory = {
                "schema": PROFILE_SCHEMA,
                "mode": mode,
                "max_entries": 128,
                "max_serialized_bytes": 524288,
            }
            selector = validate_profile(
                {
                    "schema": PROFILE["schema"],
                    "mode": "public_rule",
                    "profile_sha256": canonical_sha(PROFILE),
                }
            )
            expected = {
                "original_operation_id": pair_id + "-" + mode,
                "pair_id": pair_id,
                "case_id": case["id"],
                "source_group_id": case["source_id"],
                "episode_group": case["episode_group"],
                "split": case["role"],
                "task_family": case["task_family"],
                "selector_mode": "public_rule",
                "retention_mode": mode,
                "source_sha256": reference["source_image"]["sha256"],
                "source_width": packet["source_size"]["width"],
                "source_height": packet["source_size"]["height"],
                "weights_sha256": request["model"]["weights"]["sha256"],
                "parameters_sha256": request["model"]["parameters_sha256"],
                "control_profile_sha256": request["model"]["control_profile_sha256"],
                "control_plan_sha256": control_pin["sha256"],
                "public_case_sha256": case["packet"]["sha256"],
                "candidate_memory_profile": dict(memory),
                "candidate_memory_profile_sha256": canonical_sha(memory),
                "candidate_selector_profile": selector,
                "candidate_selector_profile_sha256": canonical_sha(selector),
            }
            episodes.append(expected)
            pair.append({"case": case, "expected": expected})
        jobs.append(pair)
    plan = {
        "schema": PLAN_SCHEMA,
        "experiment_id": request["experiment_id"],
        "source_commit": request["source_commit"],
        "source_pins": request["source_pins"],
        "request_sha256": canonical_sha(request),
        "catalog": request["catalog"],
        "exclusion_manifest": request["exclusion_manifest"],
        "training_records": request["training_records"],
        "exposure_ledgers": request["exposure_ledgers"],
        "registry_sha256": request["registry_sha256"],
        "prior_episode_plans": prior_receipts,
        "excluded_source_groups": sorted(excluded),
        "prior_episode_source_groups": sorted(prior_groups),
        "groups_per_role": request["groups_per_role"],
        "selection_salt": SELECTION_SALT,
        "sampling_profile_sha256": canonical_sha(sampling),
        "selector_profile": PROFILE,
        "fixed_selector_mode": "public_rule",
        "memory_scope": "within_episode_working_state",
        "cross_session_memory_evaluated": False,
        "selector_profile_sha256": canonical_sha(PROFILE),
        "control_plan": control_pin,
        "ocr_inventory": legacy.ocr_inventory(config),
        "evaluator_sha256": config["evaluator_sha256"],
        "reference_index_sha256": config["reference_index_sha256"],
        "rubric_sha256": config["rubric_sha256"],
        "model": request["model"],
        "episodes": episodes,
        "paired_run_order": [
            [x["expected"]["original_operation_id"] for x in pair] for pair in jobs
        ],
        "evaluation_role": "prospective_development_validation",
        "confirmation_evaluated": False,
        "independent_training_repeats": 0,
        "frozen_checkpoint_count": 1,
        "scientific_acceptance": "HOLD",
        "production_adoption": False,
    }
    require(
        legacy.file_sha(legacy.REPOSITORY / "scripts/ndu_real_materials/evaluator.py")
        == config["evaluator_sha256"],
        "Frozen evaluator source differs",
    )
    write_json(output / "PLAN.json", plan)
    return plan, jobs

