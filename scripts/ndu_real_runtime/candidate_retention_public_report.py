"""Independent MEM6 retention reader with fixed-public-selector provenance.

Retained versus current-only outcomes are actual paired actor deliveries, while
sidecars verify the fixed selector on each actor's actual support. This evaluates
working state only, and preserves unknowns, failures, no-ops and raw cost bounds.
"""

from collections import Counter, defaultdict
import hashlib
import math
from pathlib import Path

from ndu_real_materials.common import read_bound, read_relative, strict_json
from ndu_real_materials.evaluator import evaluate
from .candidate_retention_report import (
    PINS,
    REQUIRED_SOURCES,
    _digest,
    build_report,
    canonical_sha,
    evaluate_episode,
    probability,
    unknown_episode,
)
from .candidate_selector import PROFILE, validate_profile
from .candidate_selection_report import shadow_choices
from .candidate_runtime import validate_profile as validate_memory
from .candidate_retention_inference import source_inference

from .candidate_retention_public_plan import (
    MODES,
    PLAN_SCHEMA,
    REQUIRED_PRIOR_PLANS,
    sampling_profile,
    verify_cohort,
)

RELEASED = {"development", "retention_validation"}
REPOSITORY = Path(__file__).resolve().parents[2]
SOURCES = (
    REQUIRED_SOURCES
    | {"experiments/multimodal_output_portfolio/joint_hepta_20261029/hepta_core.py"}
    | {
        "scripts/ndu_real_runtime/" + name + ".py"
        for name in (
            "candidate_selector",
            "selector_runtime",
            "candidate_selection_report",
            "selector_report_summary",
            "candidate_selection_plan",
            "run_candidate_selection",
            "objective",
            "run_candidate_retention",
            "candidate_retention_public_plan",
            "candidate_retention_public_report",
            "run_candidate_retention_public",
            "candidate_retention_inference",
        )
    }
)


def validate_plan(plan):
    if (
        plan.get("schema") != PLAN_SCHEMA
        or plan.get("evaluation_role") != "prospective_development_validation"
        or plan.get("confirmation_evaluated") is not False
        or plan.get("selector_profile") != PROFILE
        or plan.get("selector_profile_sha256") != canonical_sha(PROFILE)
        or plan.get("fixed_selector_mode") != "public_rule"
        or plan.get("memory_scope") != "within_episode_working_state"
        or plan.get("cross_session_memory_evaluated") is not False
        or plan.get("sampling_profile_sha256") != canonical_sha(sampling_profile(plan))
    ):
        raise ValueError(
            "prospective released fixed-public retention plan/profile required"
        )
    planned = plan["episodes"]
    if not isinstance(planned, list) or not 1 <= len(planned) <= 16384:
        raise ValueError("complete bounded planned episode roster required")
    pairs, operations, case_pairs = defaultdict(list), set(), {}
    digest_fields = (
        *PINS,
        "source_sha256",
        "public_case_sha256",
        "control_plan_sha256",
        "candidate_memory_profile_sha256",
        "candidate_selector_profile_sha256",
    )
    fixed = (
        *PINS,
        "source_sha256",
        "public_case_sha256",
        "control_plan_sha256",
        "candidate_selector_profile_sha256",
        "case_id",
        "source_group_id",
        "episode_group",
        "split",
        "source_width",
        "source_height",
        "task_family",
        "candidate_selector_profile",
    )
    excluded = set(plan["excluded_source_groups"])
    prior = plan["prior_episode_plans"]
    if not REQUIRED_PRIOR_PLANS <= {item["pin"]["sha256"] for item in prior}:
        raise ValueError("both original MEM and MEM5 plans must remain excluded")
    if any(
        not set(item[key]) <= excluded
        for item in prior
        for key in ("source_groups", "inherited_excluded_source_groups")
    ):
        raise ValueError("prior source exclusions were dropped")
    for row in planned:
        operation = row["original_operation_id"]
        selector = validate_profile(row["candidate_selector_profile"])
        memory = validate_memory(row["candidate_memory_profile"])
        if (
            not isinstance(operation, str)
            or not operation
            or operation in operations
            or row["selector_mode"] != "public_rule"
            or selector["mode"] != "public_rule"
            or row["retention_mode"] != memory["mode"]
            or any(not _digest(row.get(k)) for k in digest_fields)
            or row["candidate_selector_profile_sha256"] != canonical_sha(selector)
            or memory["max_entries"] != 128
            or memory["max_serialized_bytes"] != 524288
            or row["candidate_memory_profile_sha256"]
            != canonical_sha(row["candidate_memory_profile"])
            or row["split"] not in RELEASED
            or row["source_group_id"] in excluded
        ):
            raise ValueError(
                "invalid, duplicated, exposed or sealed planned selector episode"
            )
        if case_pairs.setdefault(row["case_id"], row["pair_id"]) != row["pair_id"]:
            raise ValueError("one original case cannot become multiple planned pairs")
        operations.add(operation)
        pairs[row["pair_id"]].append(row)
    for pair in pairs.values():
        if (
            len(pair) != 2
            or {r["retention_mode"] for r in pair} != set(MODES)
            or any(pair[0][k] != pair[1][k] for k in fixed)
        ):
            raise ValueError(
                "paired retention changed fixed selector, inputs/model/budget"
            )
    for role, count in plan["groups_per_role"].items():
        if len({r["source_group_id"] for r in planned if r["split"] == role}) != count:
            raise ValueError("planned source allocation differs from frozen request")
    return planned


def summarize(planned, rows):
    qualified = []
    for row in rows:
        verified = (
            row.get("fixed_selector_audit_verified") is True
            and row["evidence_status"] == "VERIFIED"
        )
        qualified.append({
            **row,
            "observed_terminal_success": row.get(
                "observed_terminal_success", row["unconditional_success"]
            ),
            "intervention_verified": verified,
            "unconditional_success": row["unconditional_success"] if verified else None,
        })
    report = build_report(planned, qualified)
    all_rows = report["episodes"]
    original = {row["original_operation_id"]: row for row in planned}
    for row in all_rows:
        row["split"] = original[row["original_operation_id"]]["split"]
    costs, sources, terminal_facts = {}, {}, {}
    attempt_statuses = {}
    for mode in MODES:
        arm = [r for r in all_rows if r["mode"] == mode]
        attempt_statuses[mode] = dict(Counter(
            r.get("attempt_terminal_status", "Unknown") for r in arm
        ))
        for row in arm:
            row.setdefault("observed_terminal_success", None)
        terminal_facts[mode] = probability(arm, "observed_terminal_success")
        costs[mode] = {}
        for key in (
            "attempt_wall_seconds", "attempt_cpu_seconds", "deployment_wall_seconds"
        ):
            observed = [
                r["costs"][key]
                for r in arm
                if r.get("costs", {}).get(key) is not None
            ]
            costs[mode][key] = {
                "observed_episodes": len(observed),
                "unknown_episodes": len(arm) - len(observed),
                "sum_observed": sum(observed),
                "sum_complete": sum(observed) if len(observed) == len(arm) else None,
            }
    for source in sorted({r["source_group_id"] for r in planned}):
        roster = [r for r in planned if r["source_group_id"] == source]
        panel = build_report(
            roster, [r for r in all_rows if r["source_group_id"] == source]
        )
        sources[source] = {
            "planned_episodes": panel["planned_episodes"],
            "paired_success": panel["paired_unconditional_success_difference"],
        }
    return {
        **report,
        "schema": "ndu.real.candidate-retention-public-report.v1",
        "fixed_selector_mode": "public_rule",
        "selector_profile_sha256": canonical_sha(PROFILE),
        "memory_scope": "within_episode_working_state",
        "cross_session_memory_evaluated": False,
        "source_group_count": len(sources),
        "by_source_group": sources,
        "source_level_inference": source_inference(all_rows),
        "costs": costs,
        "observed_terminal_success": terminal_facts,
        "attempt_terminal_statuses": attempt_statuses,
        "primary_contrast_requires_verified_intervention": True,
        "cost_accounting": (
            "Attempt and deployment envelopes overlap; never sum levels. "
            "Episode wall sums are not campaign wall time."
        ),
        "energy_joules": None,
        "provider_charges": None,
    }


def episode_costs(root, item, expected, result):
    costs = dict.fromkeys(
        ("attempt_wall_seconds", "attempt_cpu_seconds", "deployment_wall_seconds")
    )
    attempt = (
        None if item.get("attempt") is None
        else strict_json(read_bound(root, item["attempt"]))
    )
    if attempt is not None:
        if (
            attempt.get("original_operation_id") != expected["original_operation_id"]
            or attempt.get("selector_mode") != "public_rule"
        ):
            raise ValueError("attempt cost was reassigned to another operation or selector")
        costs.update(
            attempt_wall_seconds=attempt.get("wall_seconds"),
            attempt_cpu_seconds=attempt.get("cpu_seconds"),
        )
    if result is not None:
        costs["deployment_wall_seconds"] = result.get("deployment_meter", {}).get(
            "wall_seconds"
        )
    if any(
        value is not None
        and (
            type(value) not in (int, float) or not math.isfinite(value) or value < 0
        )
        for value in costs.values()
    ):
        raise ValueError("observed costs must be finite, nonnegative or unknown")
    return costs


def generate(root, material_root, expected_plan_sha256, expected_manifest_sha256):
    root, material_root = Path(root), Path(material_root)
    if not all(map(_digest, (expected_plan_sha256, expected_manifest_sha256))):
        raise ValueError("explicit plan/evidence digests required")
    raw = read_relative(root, "PLAN.json", limit=8 * 1024**2)
    evidence_raw = read_relative(root, "EVIDENCE.json", limit=16 * 1024**2)
    if (
        hashlib.sha256(raw).hexdigest() != expected_plan_sha256
        or hashlib.sha256(evidence_raw).hexdigest() != expected_manifest_sha256
    ):
        raise ValueError("original plan or evidence bytes differ")
    plan, evidence = strict_json(raw), strict_json(evidence_raw)
    planned = validate_plan(plan)
    if (
        evidence.get("schema") != "ndu.real.candidate-retention-public-evidence.v1"
        or evidence.get("plan_sha256") != expected_plan_sha256
    ):
        raise ValueError("selector evidence schema/plan binding differs")
    verified = {}
    for pin in plan["source_pins"]:
        if pin["path"] in verified:
            raise ValueError("duplicate source pin")
        read_bound(REPOSITORY, pin)
        verified[pin["path"]] = pin["sha256"]
    if (
        not SOURCES <= verified.keys()
        or verified["scripts/ndu_real_materials/evaluator.py"]
        != plan["evaluator_sha256"]
    ):
        raise ValueError(
            "complete frozen execution/reader/evaluator source pins required"
        )
    verify_cohort(plan, material_root)
    items = {r["original_operation_id"]: r for r in evidence["episodes"]}
    if len(items) != len(evidence["episodes"]) or not items.keys() <= {
        r["original_operation_id"] for r in planned
    }:
        raise ValueError("duplicate or unplanned evidence operation")
    index_raw = read_relative(
        material_root, "private/reference-index.v2.json", limit=8 * 1024**2
    )
    if hashlib.sha256(index_raw).hexdigest() != plan["reference_index_sha256"]:
        raise ValueError("released reference index differs")
    index = strict_json(index_raw)
    if (
        index.get("schema") != "ndu.real.reference-index.v2"
        or index["rubric"]["sha256"] != plan["rubric_sha256"]
    ):
        raise ValueError("role-bound reference index/rubric required")
    read_bound(material_root, index["rubric"])
    rows = []
    for expected in planned:
        item = items.get(expected["original_operation_id"])
        row = unknown_episode(expected, "missing planned episode evidence")
        objects = {}
        observed_terminal = None
        try:
            if item is None:
                rows.append(row)
                continue
            cid = expected["case_id"]
            if (
                index["case_roles"][cid] != expected["split"]
                or expected["split"] not in RELEASED
            ):
                raise ValueError("sealed or reassigned source role")
            reference = strict_json(read_bound(material_root, index["cases"][cid]))
            objects = {
                k: None
                if item.get(k) is None
                else strict_json(read_bound(root, item[k]))
                for k in (
                    "result",
                    "trajectory",
                    "public_case",
                    "initial_delivery",
                    "final_delivery",
                )
            }
            if not isinstance(reference, dict) or any(
                value is not None and not isinstance(value, dict)
                for value in objects.values()
            ):
                raise ValueError("episode evidence objects must be JSON objects")
            if (
                item.get("public_case")
                and item["public_case"]["sha256"] != expected["public_case_sha256"]
            ):
                raise ValueError("public packet binding differs")
            if (
                objects["result"] is not None
                and objects["result"].get("candidate_selector_profile_sha256")
                != expected["candidate_selector_profile_sha256"]
            ):
                raise ValueError(
                    "actual result selector profile differs from frozen mode"
                )
            audits = [
                None
                if pin is None
                else {
                    "value": strict_json(read_bound(root, pin)),
                    "sha256": pin["sha256"],
                    "bytes": pin["bytes"],
                }
                for pin in item.get("audits", [])
            ]
            scores = {}
            for phase in ("initial", "final"):
                pin = item.get(phase + "_delivery")
                scores[phase] = None
                if pin is not None:
                    path = root / pin["path"]
                    score = evaluate(
                        material_root,
                        cid,
                        path.parent,
                        path,
                        expected_index_sha256=plan["reference_index_sha256"],
                        expected_rubric_sha256=plan["rubric_sha256"],
                    )
                    if (
                        score["delivery_sha256"] != pin["sha256"]
                        or score["evaluator_source_sha256"] != plan["evaluator_sha256"]
                    ):
                        raise ValueError(
                            "independent scoring bytes or implementation differs"
                        )
                    scores[phase] = score
            row = evaluate_episode(
                expected,
                reference,
                objects["public_case"],
                objects["result"],
                objects["trajectory"],
                audits,
                {p: objects[p + "_delivery"] for p in ("initial", "final")},
                scores,
            )
            observed_terminal = row["unconditional_success"]
            if row["evidence_status"] == "VERIFIED":
                shadow_choices(
                    root,
                    expected,
                    reference,
                    objects["trajectory"],
                    audits,
                    item.get("selector_audits", []),
                )
                selector_pins = item["selector_audits"]
                if (
                    objects["result"].get("selector_audit_chain_sha256")
                    != selector_pins[-1]["sha256"]
                ):
                    raise ValueError(
                        "final result differs from selector audit chain tail"
                    )
                row["fixed_selector_audit_verified"] = True
        except FileNotFoundError as error:
            row = unknown_episode(expected, str(error))
        except (OSError, KeyError, ValueError, TypeError, IndexError, AttributeError) as error:
            row = unknown_episode(expected, str(error), rejected=True)
        row["observed_terminal_success"] = observed_terminal
        try:
            result = objects.get("result")
            row["costs"] = episode_costs(
                root, item, expected, result if isinstance(result, dict) else None
            )
            if item.get("attempt") is not None:
                attempt = strict_json(read_bound(root, item["attempt"]))
                status = attempt.get("status", "Unknown")
                if status not in {"Completed", "Failed", "BudgetStop", "Timeout", "Unknown"}:
                    raise ValueError("invalid original attempt terminal status")
                row["attempt_terminal_status"] = status
        except (OSError, KeyError, ValueError, TypeError, AttributeError) as error:
            row["cost_error"] = str(error)
        rows.append(row)
    for pin in plan["source_pins"]:
        read_bound(REPOSITORY, pin)
    return {
        **summarize(planned, rows),
        "plan_sha256": expected_plan_sha256,
        "evidence_sha256": expected_manifest_sha256,
        "verified_source_sha256": verified,
    }

