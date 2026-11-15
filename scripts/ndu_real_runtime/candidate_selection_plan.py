"""Prospective released-source selector plans; never a sealed-role release.

Prior plan bytes are pinned before source selection. They extend, rather than
replace, the original training/tuning/quarantine exclusions. Task/reference
bytes are opened only after the complete released cohort has been selected.
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

SCHEMA = "ndu.real.candidate-selection-request.v1"
PLAN_SCHEMA = "ndu.real.candidate-selection-plan.v1"
SELECTION_SALT = "mem5-fixed-support-20261110-4b3362-v1"
BASELINE_MEM_PLAN_SHA256 = (
    "488639ca2bd2b25d5c90c77b3adaf58bd8133932bb2cb1bf70fc547447d187d5"
)
MODES = ("frozen_neural", "public_rule")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def prior_source_groups(request, catalog, materials):
    """Read bounded prior plan metadata; hashes are not authenticity evidence."""
    pins = request["prior_episode_plan_pins"]
    require(
        isinstance(pins, list) and 1 <= len(pins) <= 128,
        "Pinned prior episode plans are required",
    )
    require(
        all(
            isinstance(pin, dict)
            and set(pin) == {"path", "sha256", "bytes"}
            and isinstance(pin["sha256"], str)
            and re.fullmatch(r"[0-9a-f]{64}", pin["sha256"])
            for pin in pins
        ),
        "Closed prior plan byte bindings required",
    )
    digests = [pin["sha256"] for pin in pins]
    require(
        len(digests) == len(set(digests)) and BASELINE_MEM_PLAN_SHA256 in digests,
        "Prior plan roster must uniquely cover the original MEM campaign",
    )
    cases = {case["id"]: case for case in catalog["cases"]}
    groups, receipts = set(), []
    for pin in pins:
        require(
            type(pin.get("bytes")) is int and 1 <= pin["bytes"] <= 8 * 1024**2,
            "Prior plan must have an explicit bounded byte identity",
        )
        path = Path(pin["path"])
        raw = (
            read_bound(path.parent, {**pin, "path": path.name})
            if path.is_absolute()
            else read_bound(materials, pin)
        )
        plan = strict_json(raw)
        require(
            plan.get("schema") in {"ndu.real.candidate-retention-plan.v1", PLAN_SCHEMA}
            and plan.get("registry_sha256") == request["registry_sha256"]
            and plan.get("reference_index_sha256")
            == request["config"]["reference_index_sha256"],
            "Prior plan belongs to another protocol or material registry",
        )
        rows = plan.get("episodes")
        require(
            isinstance(rows, list) and 1 <= len(rows) <= 16384,
            "Complete bounded prior episode metadata required",
        )
        seen, current = set(), set()
        for row in rows:
            require(isinstance(row, dict), "Prior episode metadata must be objects")
            operation, cid, sid = (
                row.get(k)
                for k in ("original_operation_id", "case_id", "source_group_id")
            )
            require(
                all(
                    isinstance(v, str)
                    and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,255}", v)
                    for v in (operation, cid, sid)
                )
                and operation not in seen,
                "Prior episode identity is missing, malformed or duplicated",
            )
            case = cases.get(cid)
            require(
                case is not None
                and case["source_id"] == sid
                and case["role"] == row.get("split")
                and case["episode_group"] == row.get("episode_group"),
                "Prior source/role/episode differs from released catalog metadata",
            )
            seen.add(operation)
            current.add(sid)
        inherited = plan.get("excluded_source_groups")
        require(
            isinstance(inherited, list)
            and len(inherited) <= 16384
            and all(
                isinstance(sid, str)
                and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,255}", sid)
                for sid in inherited
            )
            and len(inherited) == len(set(inherited)),
            "Prior inherited exclusions must be complete bounded source IDs",
        )
        groups.update(inherited)
        groups.update(current)
        receipts.append(
            {
                "pin": dict(pin),
                "episode_count": len(rows),
                "source_groups": sorted(current),
                "inherited_excluded_source_groups": sorted(inherited),
            }
        )
    return groups, receipts


def freeze(request, output):
    """Freeze both selector modes with one bounded memory and frozen model."""
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
        request.get("selection_salt") == SELECTION_SALT,
        "Prespecified source selection salt differs",
    )
    require(
        type(request.get("max_workers")) is int and 1 <= request["max_workers"] <= 2,
        "At most two workers are supported",
    )
    require(
        request.get("selector_profile_sha256") == canonical_sha(PROFILE),
        "Public selector policy differs from its frozen profile",
    )
    require(
        request.get("groups_per_role") == {"development": 10, "retention_validation": 4}
        and all(type(n) is int for n in request["groups_per_role"].values()),
        "Frozen 10+4 source-group allocation differs",
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
        "Both selector modes require the same frozen 60-second objective",
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
    memory = {
        "schema": PROFILE_SCHEMA,
        "mode": "bounded",
        "max_entries": 128,
        "max_serialized_bytes": 524288,
    }
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
            selector = validate_profile(
                {
                    "schema": PROFILE["schema"],
                    "mode": mode,
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
                "selector_mode": mode,
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
        "selector_profile": PROFILE,
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
