"""Source-bound prospective selector diagnostics with all planned denominators.

Only this offline reader opens released references. Each shadow comparison uses
one actual offered support; shadow choices are not terminal counterfactuals.
"""

from collections import defaultdict
import hashlib
from pathlib import Path

from ndu_real_materials.common import read_bound, read_relative, strict_json
from ndu_real_materials.evaluator import canonical, evaluate
from .candidate_retention_report import (
    PINS,
    REQUIRED_SOURCES,
    _digest,
    canonical_sha,
    evaluate_episode,
    unknown_episode,
)
from .candidate_selector import PROFILE, validate_profile
from .selector_runtime import read_selector_audit

from .selector_report_summary import MODES, summarize

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
        )
    }
)


def validate_plan(plan):
    if (
        plan.get("schema") != "ndu.real.candidate-selection-plan.v1"
        or plan.get("evaluation_role") != "prospective_development_validation"
        or plan.get("confirmation_evaluated") is not False
        or plan.get("selector_profile") != PROFILE
        or plan.get("selector_profile_sha256") != canonical_sha(PROFILE)
    ):
        raise ValueError("prospective released selector plan/profile required")
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
        *digest_fields[:-1],
        "case_id",
        "source_group_id",
        "episode_group",
        "split",
        "source_width",
        "source_height",
        "task_family",
        "candidate_memory_profile",
    )
    excluded = set(plan["excluded_source_groups"])
    for row in planned:
        operation = row["original_operation_id"]
        selector = validate_profile(row["candidate_selector_profile"])
        if (
            not isinstance(operation, str)
            or not operation
            or operation in operations
            or row["selector_mode"] not in MODES
            or selector["mode"] != row["selector_mode"]
            or any(not _digest(row.get(k)) for k in digest_fields)
            or row["candidate_selector_profile_sha256"] != canonical_sha(selector)
            or row["candidate_memory_profile"].get("mode") != "bounded"
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
            or {r["selector_mode"] for r in pair} != set(MODES)
            or any(pair[0][k] != pair[1][k] for k in fixed)
        ):
            raise ValueError(
                "paired selectors changed frozen support inputs/model/budget"
            )
    return planned


def shadow_choices(root, expected, reference, trajectory, audits, selector_pins):
    steps = trajectory["steps"]
    if len(audits) != len(steps) or len(steps) > 8:
        raise ValueError("complete bounded original memory step chain required")
    if len(selector_pins) != len(steps) or any(p is None for p in selector_pins):
        raise FileNotFoundError("missing complete selector sidecar chain")
    target = canonical(reference["expected_text"], reference["field"])
    previous, diagnostics = None, []
    for i, (step, memory, pin) in enumerate(zip(steps, audits, selector_pins)):
        if memory is None:
            raise FileNotFoundError("missing original memory audit")
        read_bound(root, pin, limit=4 * 1024**2)
        expected_dir = (
            Path("episodes") / expected["original_operation_id"] / "actor-output"
        )
        relative = Path(pin["path"])
        if relative.parent != expected_dir:
            raise ValueError("selector sidecar belongs to another operation")
        if step.get("selector_audit") != {**pin, "path": relative.name}:
            raise ValueError("selector trajectory and evidence bindings differ")
        value = read_selector_audit(
            root / expected_dir,
            {**pin, "path": relative.name},
            {
                "scope": {
                    "original_operation_id": expected["original_operation_id"],
                    "case_id": expected["case_id"],
                    "source_image_sha256": expected["source_sha256"],
                    "source_width": expected["source_width"],
                    "source_height": expected["source_height"],
                },
                "bindings": {k: expected[k] for k in (*PINS, "public_case_sha256")},
                "step": i,
                "profile": expected["candidate_selector_profile"],
                "profile_sha256": expected["candidate_selector_profile_sha256"],
                "observation": memory["value"]["observation"],
                "action": step["action"],
                "memory_audit_sha256": memory["sha256"],
                "previous_audit_sha256": previous,
            },
            memory["value"],
        )
        previous = pin["sha256"]
        result = {k: None for k in ("available", *MODES)}
        if value["observation_processed"]:
            receipt, roster = value["receipt"], value["candidates"]
            if receipt["field"] != reference["field"]:
                raise ValueError("shadow field differs from original reference field")

            def correct(candidate):
                return canonical(candidate["text"], reference["field"]) == target

            result = {
                "available": any(map(correct, roster)),
                "frozen_neural": correct(roster[receipt["frozen_neural_index"]]),
                "public_rule": correct(roster[receipt["public_rule_index"]]),
            }
        diagnostics.append(result)
    writes = [i for i, s in enumerate(steps) if s["action"]["action"] == "WRITE_TEXT"]
    anchor = writes[-1] if writes else len(steps) - 1
    return (
        diagnostics[anchor] if diagnostics else {k: None for k in ("available", *MODES)}
    )


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
        evidence.get("schema") != "ndu.real.candidate-selection-evidence.v1"
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
            if row["evidence_status"] == "VERIFIED":
                row["shadow"] = shadow_choices(
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
        except FileNotFoundError as error:
            row = unknown_episode(expected, str(error))
        except (OSError, KeyError, ValueError, TypeError, IndexError) as error:
            row = unknown_episode(expected, str(error), rejected=True)
        rows.append(row)
    for pin in plan["source_pins"]:
        read_bound(REPOSITORY, pin)
    return {
        **summarize(planned, rows),
        "plan_sha256": expected_plan_sha256,
        "evidence_sha256": expected_manifest_sha256,
        "verified_source_sha256": verified,
    }
