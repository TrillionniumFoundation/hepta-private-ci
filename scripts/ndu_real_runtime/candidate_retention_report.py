"""Offline, source-pinned candidate-retention diagnostics with complete denominators.

Only this evaluator reads private references. O/C/S describe the final WRITE_TEXT
decision, or the final actor decision when no write occurred. D additionally
requires an executed candidate write and independently correct final delivery.
Initial/no-op and bypass successes remain separate from that mediated path.
"""

import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path

from ndu_real_materials.common import read_bound, read_relative, strict_json
from ndu_real_materials.evaluator import canonical, evaluate


SCHEMA = "ndu.real.candidate-retention-report.v1"
EVENTS = (
    "raw_observed",
    "available",
    "selected",
    "candidate_mediated_delivered",
    "unconditional_success",
    "initial_correct",
    "no_op_success",
    "bypass_success",
    "did_write_text",
)
PINS = ("weights_sha256", "parameters_sha256", "control_profile_sha256")
REQUIRED_SOURCES = {
    "scripts/ndu_real_runtime/" + name + ".py"
    for name in (
        "candidate_retention_report",
        "actor",
        "episode",
        "candidate_memory",
        "candidate_runtime",
        "ocr",
        "neural",
        "controllers",
        "action_effects",
        "metering",
        "span_meter",
    )
} | {
    "scripts/ndu_real_materials/common.py",
    "scripts/ndu_real_materials/evaluator.py",
}


def canonical_sha(value):
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()
    ).hexdigest()


def _digest(value):
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(c in "0123456789abcdef" for c in value)
    )


def unknown_episode(expected, reason, *, rejected=False, terminal_status="Unknown"):
    return {
        "original_operation_id": expected["original_operation_id"],
        "case_id": expected["case_id"],
        "source_group_id": expected["source_group_id"],
        "pair_id": expected.get("pair_id", expected["case_id"]),
        "mode": expected["candidate_memory_profile"]["mode"],
        "evidence_status": "REJECTED" if rejected else "UNKNOWN",
        "terminal_status": terminal_status,
        "timeout_reported": None,
        "reason": reason,
        "failure_stage": "unknown",
        **dict.fromkeys(EVENTS),
    }


def _correct_delivery(score, packet):
    if score is None:
        return None
    required = packet["requirements"]
    return (
        score.get("committed_output_preserved") is True
        and (not required["text"] or score.get("text_quality") == 1.0)
        and (not required["image"] or score.get("image_pass") is True)
    )


def evaluate_episode(
    expected, reference, public_case, result, trajectory, audits, deliveries, scores
):
    """Evaluate already byte-bound objects; generate() owns file and source checks.

    deliveries/scores have ``initial`` and ``final`` keys. Audit list entries are
    ``{"value": decoded sidecar, "sha256": exact_file_digest, "bytes": int}``.
    Missing evidence is unknown. Contradictory identity or provenance is rejected.
    """
    row = unknown_episode(expected, "missing episode evidence")
    if result is None:
        return row
    if not isinstance(result, dict):
        return unknown_episode(expected, "result must be an object", rejected=True)
    row["terminal_status"] = result.get("terminal_status", "Unknown")
    row["timeout_reported"] = row["terminal_status"] == "Timeout" or (
        isinstance(result.get("error"), dict)
        and result["error"].get("type") in {"TimeoutError", "TimeoutExpired"}
    )
    profile = expected["candidate_memory_profile"]
    profile_sha = canonical_sha(profile)
    scope = {
        key: expected[key]
        for key in (
            "original_operation_id",
            "case_id",
            "source_width",
            "source_height",
        )
    }
    scope["source_image_sha256"] = expected["source_sha256"]
    try:
        if (
            profile.get("schema") != "ndu.real.candidate-memory-profile.v1"
            or profile.get("mode") not in {"current_only", "bounded"}
            or type(profile.get("max_entries")) is not int
            or not 1 <= profile["max_entries"] <= 128
            or type(profile.get("max_serialized_bytes")) is not int
            or not 1 <= profile["max_serialized_bytes"] <= 16 * 1024**2
        ):
            raise ValueError("invalid frozen memory profile")
        if expected["split"] not in {"train", "development", "retention_validation"}:
            raise ValueError("sealed or unknown evaluation role")
        if profile_sha != expected["candidate_memory_profile_sha256"]:
            raise ValueError("memory profile differs from frozen identity")
        expected_result = {
            key: expected[key]
            for key in (
                "original_operation_id",
                "case_id",
                "source_group_id",
                "episode_group",
                "split",
                "source_sha256",
                "control_profile_sha256",
                "candidate_memory_profile_sha256",
            )
        }
        expected_result["model_sha256"] = expected["weights_sha256"]
        if "control_plan_sha256" in expected:
            if not _digest(expected["control_plan_sha256"]):
                raise ValueError("invalid full control-plan identity")
            expected_result["control_plan_sha256"] = expected["control_plan_sha256"]
        if any(result.get(k) != v for k, v in expected_result.items()):
            raise ValueError(
                "result source, episode, weights or profile identity differs"
            )
        if reference is None or public_case is None:
            return row
        if (
            any(
                reference.get(k) != expected[v]
                for k, v in (
                    ("case_id", "case_id"),
                    ("source_group", "source_group_id"),
                    ("episode_group", "episode_group"),
                    ("role", "split"),
                )
            )
            or reference["source_image"]["sha256"] != expected["source_sha256"]
            or public_case.get("case_id") != expected["case_id"]
            or public_case.get("source_size")
            != {
                "width": expected["source_width"],
                "height": expected["source_height"],
            }
        ):
            raise ValueError("private reference or public packet identity differs")
        target = canonical(reference["expected_text"], reference["field"])
        if target is None or not public_case["requirements"]["text"]:
            raise ValueError(
                "text-candidate attribution requires a scorable text target"
            )
        initial, final = deliveries.get("initial"), deliveries.get("final")
        for delivery in (initial, final):
            if delivery is not None and delivery.get("case_id") != expected["case_id"]:
                raise ValueError("delivery case differs")
        if initial is not None and (
            initial.get("text") != public_case["initial_delivery"]["text"]
        ):
            raise ValueError("initial public text differs from delivery snapshot")
        if final is not None and result.get("output_text_sha256") != canonical_sha(
            final["text"]
        ):
            raise ValueError("final delivered text differs from host result")
        row["initial_correct"] = _correct_delivery(scores.get("initial"), public_case)
        content_correct = _correct_delivery(scores.get("final"), public_case)
        row["final_content_correct"] = content_correct
        row["unconditional_success"] = (
            content_correct
            if row["terminal_status"] == "Completed"
            else False
            if row["terminal_status"] in {"Failed", "BudgetStop", "Timeout"}
            else None
        )
        if trajectory is None or not isinstance(trajectory.get("steps"), list):
            return row
        steps = trajectory["steps"]
        if len(steps) > 8:
            raise ValueError("trajectory exceeds frozen action horizon")
        if result.get("actions") != [step["action"]["action"] for step in steps]:
            raise ValueError("result and executed trajectory actions disagree")
        writes = [
            i
            for i, step in enumerate(steps)
            if step["action"]["action"] == "WRITE_TEXT"
        ]
        row["did_write_text"] = bool(writes)
        row["no_op_success"] = (
            False
            if writes or row["unconditional_success"] is False
            else row["initial_correct"]
            if row["unconditional_success"] is True
            else None
        )
        if (
            not steps
            or len(audits) != len(steps)
            or any(item is None for item in audits)
        ):
            row["reason"] = "missing complete actor candidate sidecar chain"
            return row
        seen, diagnostic, previous = {}, [], None
        for i, (step, bound) in enumerate(zip(steps, audits)):
            audit = bound["value"]
            link = step.get("candidate_audit", {})
            if (
                audit.get("schema") != "ndu.real.candidate-audit.v1"
                or audit.get("scope") != scope
                or audit.get("step") != i
                or audit.get("previous_audit_sha256") != previous
                or audit.get("profile") != profile
                or audit.get("profile_sha256") != profile_sha
                or audit.get("public_case_sha256") != expected["public_case_sha256"]
                or any(audit.get(k) != expected[k] for k in PINS)
                or audit.get("action") != step.get("action")
                or link.get("sha256") != bound["sha256"]
                or link.get("bytes") != bound["bytes"]
            ):
                raise ValueError(
                    "candidate sidecar chain, identity or executed action differs"
                )
            previous = bound["sha256"]
            raw, offered = audit["raw_candidates"], audit["offered_candidates"]
            processed = audit.get("observation_processed")
            selected = audit.get("selected_index")
            if (
                type(processed) is not bool
                or not isinstance(raw, list)
                or not isinstance(offered, list)
            ):
                raise ValueError("invalid observation status or candidate roster")
            if len(raw) > 128 or len(offered) > profile["max_entries"]:
                raise ValueError("candidate roster exceeds frozen cap")
            if not processed:
                if (
                    raw
                    or offered
                    or selected is not None
                    or audit["offered_observed_steps"]
                ):
                    raise ValueError("unprocessed decision claims candidate evidence")
                prior_observed = any(
                    item["raw_observed"] is True for item in diagnostic
                )
                diagnostic.append(
                    {
                        "step": i,
                        "raw_observed": True if prior_observed else None,
                        "available": None,
                        "selected": None,
                    }
                )
                continue
            if not all(
                _digest(audit.get(k))
                for k in ("raw_features_sha256", "offered_features_sha256")
            ):
                raise ValueError("processed candidates lack feature identities")
            for candidate in raw + offered:
                box = candidate.get("bbox")
                if (
                    set(candidate) != {"text", "bbox", "origin"}
                    or not isinstance(candidate["text"], str)
                    or len(candidate["text"].encode()) > 8192
                    or candidate["origin"]
                    not in {"pixel_ocr", "registered_public_text", "no_recognized_text"}
                    or not isinstance(box, list)
                    or len(box) != 4
                    or any(type(v) is not int for v in box)
                    or not 0 <= box[0] < box[2] <= expected["source_width"]
                    or not 0 <= box[1] < box[3] <= expected["source_height"]
                ):
                    raise ValueError("invalid bounded public candidate")
            seen[i] = {canonical_sha(candidate) for candidate in raw}
            origins = audit["offered_observed_steps"]
            if len(origins) != len(offered) or any(
                type(origin) is not int
                or canonical_sha(candidate) not in seen.get(origin, set())
                for candidate, origin in zip(offered, origins)
            ):
                raise ValueError("offered candidate has no observed same-scope origin")
            if profile["mode"] == "current_only" and any(
                origin != i for origin in origins
            ):
                raise ValueError("current-only arm contains historical candidates")
            if selected is not None and (
                type(selected) is not int or not 0 <= selected < len(offered)
            ):
                raise ValueError("selected candidate index is invalid")
            correct = lambda c: canonical(c["text"], reference["field"]) == target
            observation_seen = any(
                correct(c)
                for item in audits[: i + 1]
                for c in item["value"]["raw_candidates"]
            )
            diagnostic.append(
                {
                    "step": i,
                    "raw_observed": observation_seen,
                    "available": any(map(correct, offered)),
                    "selected": correct(offered[selected])
                    if selected is not None
                    else False,
                }
            )
        anchor = writes[-1] if writes else len(steps) - 1
        row.update(
            {
                key: diagnostic[anchor][key]
                for key in ("raw_observed", "available", "selected")
            }
        )
        row["anchor_step"], row["decision_diagnostics"] = anchor, diagnostic
        wrote_selected = False
        if writes:
            audit = audits[anchor]["value"]
            index = audit["selected_index"]
            wrote_selected = index is not None and (
                audit["action"]["arguments"].get("text")
                == audit["offered_candidates"][index]["text"]
            )
            if final is None:
                row["reason"] = "missing final delivery snapshot"
                return row
            if final["text"] != audit["action"]["arguments"].get("text"):
                raise ValueError("last executed write is not the final delivered text")
        row["wrote_selected_candidate"] = wrote_selected
        row["candidate_mediated_delivered"] = (
            False
            if not writes
            else (
                bool(
                    row["selected"] and wrote_selected and row["unconditional_success"]
                )
                if row["selected"] is not None
                and row["unconditional_success"] is not None
                else None
            )
        )
        row["bypass_success"] = (
            bool(
                row["unconditional_success"]
                and not row["no_op_success"]
                and not row["candidate_mediated_delivered"]
            )
            if row["unconditional_success"] is not None
            and row["candidate_mediated_delivered"] is not None
            and row["no_op_success"] is not None
            else None
        )
        stage = (
            "initial_no_op_success"
            if row["no_op_success"]
            else "candidate_success"
            if row["candidate_mediated_delivered"]
            else "bypass_success"
            if row["bypass_success"]
            else "unknown"
            if any(row[k] is None for k in ("raw_observed", "available", "selected"))
            else "perception_unavailable"
            if not row["raw_observed"]
            else "candidate_unavailable_at_decision"
            if not row["available"]
            else "selection_error"
            if not row["selected"]
            else "selected_not_written"
            if not wrote_selected
            else "delivery_failure"
        )
        row.update(failure_stage=stage, evidence_status="VERIFIED", reason=None)
        return row
    except (KeyError, TypeError, ValueError, IndexError) as error:
        return unknown_episode(
            expected, str(error), rejected=True, terminal_status=row["terminal_status"]
        )


def probability(rows, event, *, given=None):
    """Return exact counts, unknowns and conservative bounds; zero is not unknown."""
    eligible = rows if given is None else [r for r in rows if r[given] is True]
    unknown_condition = 0 if given is None else sum(r[given] is None for r in rows)
    numerator = sum(r[event] is True for r in eligible)
    unknown_outcome = sum(r[event] is None for r in eligible)
    maximum_denominator = len(eligible) + unknown_condition
    return {
        "numerator": numerator,
        "denominator": len(eligible),
        "planned_episodes": len(rows),
        "unknown_condition": unknown_condition,
        "unknown_outcome": unknown_outcome,
        "value": numerator / len(eligible)
        if eligible and not unknown_condition and not unknown_outcome
        else None,
        "bounds": [
            numerator / maximum_denominator,
            (numerator + unknown_outcome + unknown_condition) / maximum_denominator,
        ]
        if maximum_denominator
        else None,
        "status": "ZERO_DENOMINATOR"
        if not maximum_denominator
        else "UNKNOWN"
        if unknown_condition or unknown_outcome
        else "OBSERVED",
    }


def build_report(planned_roster, evaluated_rows):
    planned = {e["original_operation_id"]: e for e in planned_roster}
    if not planned or len(planned) != len(planned_roster):
        raise ValueError("nonempty unique planned operation roster required")
    found = {}
    for row in evaluated_rows:
        identity = row["original_operation_id"]
        if identity not in planned or identity in found:
            raise ValueError("unexpected or duplicate evaluated operation")
        expected = planned[identity]
        if (
            row["case_id"] != expected["case_id"]
            or row["mode"] != expected["candidate_memory_profile"]["mode"]
        ):
            raise ValueError("evaluated row reassigned its case or arm")
        found[identity] = row
    rows = [
        found.get(identity, unknown_episode(e, "planned operation has no evidence"))
        for identity, e in planned.items()
    ]
    panels = {}
    for mode in sorted({r["mode"] for r in rows}):
        arms = [r for r in rows if r["mode"] == mode]
        for stratum, chosen in (
            ("all_planned", arms),
            ("initial_incorrect", [r for r in arms if r["initial_correct"] is False]),
            ("initial_correct", [r for r in arms if r["initial_correct"] is True]),
            ("initial_unknown", [r for r in arms if r["initial_correct"] is None]),
        ):
            panels[mode + "/" + stratum] = {
                "planned_episodes": len(chosen),
                "terminal_status": dict(Counter(r["terminal_status"] for r in chosen)),
                "evidence_status": dict(Counter(r["evidence_status"] for r in chosen)),
                "failure_stage": dict(Counter(r["failure_stage"] for r in chosen)),
                "reported_timeouts": sum(r["timeout_reported"] is True for r in chosen),
                "p_raw_observed": probability(chosen, "raw_observed"),
                "p_available": probability(chosen, "available"),
                "p_available_given_observed": probability(
                    chosen, "available", given="raw_observed"
                ),
                "p_selected_given_available": probability(
                    chosen, "selected", given="available"
                ),
                "p_delivered_given_selected": probability(
                    chosen, "candidate_mediated_delivered", given="selected"
                ),
                "p_unconditional_success": probability(chosen, "unconditional_success"),
                "no_op_successes": sum(r["no_op_success"] is True for r in chosen),
                "bypass_successes": sum(r["bypass_success"] is True for r in chosen),
            }
    pairs = defaultdict(dict)
    for row in rows:
        if row["mode"] in pairs[row["pair_id"]]:
            raise ValueError("duplicate memory arm within planned pair")
        pairs[row["pair_id"]][row["mode"]] = row["unconditional_success"]
    differences, lower, upper = [], 0, 0
    for arms in pairs.values():
        baseline, bounded = arms.get("current_only"), arms.get("bounded")
        lower += (int(bounded) if bounded is not None else 0) - (
            int(baseline) if baseline is not None else 1
        )
        upper += (int(bounded) if bounded is not None else 1) - (
            int(baseline) if baseline is not None else 0
        )
        if baseline is not None and bounded is not None:
            differences.append(int(bounded) - int(baseline))
    return {
        "schema": SCHEMA,
        "planned_episodes": len(rows),
        "episodes": rows,
        "panels": panels,
        "paired_unconditional_success_difference": {
            "contrast": "bounded - current_only",
            "planned_pairs": len(pairs),
            "observed_pairs": len(differences),
            "unknown_pairs": len(pairs) - len(differences),
            "value": sum(differences) / len(pairs)
            if len(differences) == len(pairs)
            else None,
            "bounds": [lower / len(pairs), upper / len(pairs)],
            "observed_outcomes": {
                label: differences.count(value)
                for label, value in (("loss", -1), ("tie", 0), ("win", 1))
            },
            "sampling_uncertainty": "not estimated; finite descriptive panel only",
        },
        "anchor_rule": "last WRITE_TEXT decision; otherwise final actor decision",
        "candidate_correctness": "frozen independent text normalizer; image quality separately scored",
        "candidate_unavailability_scope": "observed earlier but absent from the offered decision roster; physical eviction requires separate receipt evidence",
        "conditional_rates_are_not_causal_selection_effects": True,
        "all_planned_denominator_is_primary": True,
        "scientific_acceptance": "HOLD",
        "confirmatory_use": False,
        "production_adoption": False,
        "provider_authenticity_verified": False,
        "full_cost_adjusted": False,
    }


def generate(root, material_root, expected_plan_sha256, expected_manifest_sha256):
    root, material_root = Path(root), Path(material_root)
    if not all(map(_digest, (expected_plan_sha256, expected_manifest_sha256))):
        raise ValueError("expected plan and evidence digests required")
    plan_raw = read_relative(root, "PLAN.json", limit=8 * 1024**2)
    evidence_raw = read_relative(root, "EVIDENCE.json", limit=16 * 1024**2)
    if (
        hashlib.sha256(plan_raw).hexdigest() != expected_plan_sha256
        or hashlib.sha256(evidence_raw).hexdigest() != expected_manifest_sha256
    ):
        raise ValueError("plan or evidence manifest differs from expected bytes")
    plan, manifest = strict_json(plan_raw), strict_json(evidence_raw)
    if (
        plan.get("schema") != "ndu.real.candidate-retention-plan.v1"
        or manifest.get("schema") != "ndu.real.candidate-retention-evidence.v1"
        or manifest.get("plan_sha256") != expected_plan_sha256
    ):
        raise ValueError("plan/evidence schema or binding differs")
    repository = Path(__file__).resolve().parents[2]
    verified = {}
    for binding in plan["source_pins"]:
        if binding["path"] in verified:
            raise ValueError("duplicate source pin")
        read_bound(repository, binding)
        verified[binding["path"]] = binding["sha256"]
    if (
        not REQUIRED_SOURCES <= verified.keys()
        or verified["scripts/ndu_real_materials/evaluator.py"]
        != plan["evaluator_sha256"]
    ):
        raise ValueError("complete frozen execution and evaluator source pins required")
    planned = plan["episodes"]
    pairs = defaultdict(list)
    for expected in planned:
        if any(
            not _digest(expected.get(key))
            for key in (
                *PINS,
                "source_sha256",
                "public_case_sha256",
                "candidate_memory_profile_sha256",
            )
        ):
            raise ValueError(
                "episode lacks source, parameters, public packet or profile pins"
            )
        pairs[expected.get("pair_id", expected["case_id"])].append(expected)
    for pair in pairs.values():
        if {e["candidate_memory_profile"]["mode"] for e in pair} != {
            "current_only",
            "bounded",
        } or len(pair) != 2:
            raise ValueError("each planned pair needs both distinct memory modes")
        fixed = (
            *PINS,
            "case_id",
            "source_sha256",
            "public_case_sha256",
            "source_group_id",
            "episode_group",
            "split",
            "source_width",
            "source_height",
        )
        if any("control_plan_sha256" in e for e in pair):
            if any(not _digest(e.get("control_plan_sha256")) for e in pair):
                raise ValueError("both paired arms require the full control-plan pin")
            fixed += ("control_plan_sha256",)
        if any(pair[0][key] != pair[1][key] for key in fixed) or any(
            pair[0]["candidate_memory_profile"][key]
            != pair[1]["candidate_memory_profile"][key]
            for key in ("max_entries", "max_serialized_bytes")
        ):
            raise ValueError(
                "paired arms changed frozen model, inputs, control or candidate budget"
            )
    evidence = {e["original_operation_id"]: e for e in manifest["episodes"]}
    if len(evidence) != len(manifest["episodes"]) or not evidence.keys() <= {
        e["original_operation_id"] for e in planned
    }:
        raise ValueError("duplicate or unplanned evidence operation")
    index_raw = read_relative(
        material_root, "private/reference-index.v2.json", limit=8 * 1024**2
    )
    if hashlib.sha256(index_raw).hexdigest() != plan["reference_index_sha256"]:
        raise ValueError("independent reference index pin differs")
    index = strict_json(index_raw)
    if index.get("schema") != "ndu.real.reference-index.v2":
        raise ValueError("role-bound reference index required")
    rows = []
    for expected in planned:
        item = evidence.get(expected["original_operation_id"])
        if item is None:
            continue
        try:
            if (
                expected["split"]
                not in {"train", "development", "retention_validation"}
                or index["case_roles"][expected["case_id"]] != expected["split"]
            ):
                raise ValueError("sealed or reassigned reference role")
            reference = strict_json(
                read_bound(material_root, index["cases"][expected["case_id"]])
            )
            objects = {}
            for key in (
                "result",
                "trajectory",
                "public_case",
                "initial_delivery",
                "final_delivery",
            ):
                binding = item.get(key)
                objects[key] = (
                    None if binding is None else strict_json(read_bound(root, binding))
                )
            if (
                item.get("public_case") is not None
                and item["public_case"]["sha256"] != expected["public_case_sha256"]
            ):
                raise ValueError("public case bytes differ from frozen packet")
            audits = [
                None
                if binding is None
                else {
                    "value": strict_json(read_bound(root, binding)),
                    "sha256": binding["sha256"],
                    "bytes": binding["bytes"],
                }
                for binding in item.get("audits", [])
            ]
            deliveries, scores = {}, {}
            for phase in ("initial", "final"):
                binding = item.get(phase + "_delivery")
                deliveries[phase] = objects[phase + "_delivery"]
                scores[phase] = None
                if binding is not None:
                    path = root / binding["path"]
                    scores[phase] = evaluate(
                        material_root,
                        expected["case_id"],
                        path.parent,
                        path,
                        expected_index_sha256=plan["reference_index_sha256"],
                        expected_rubric_sha256=plan["rubric_sha256"],
                    )
                    if (
                        scores[phase]["delivery_sha256"] != binding["sha256"]
                        or scores[phase]["evaluator_source_sha256"]
                        != plan["evaluator_sha256"]
                    ):
                        raise ValueError("independent scoring bytes or source changed")
            rows.append(
                evaluate_episode(
                    expected,
                    reference,
                    objects["public_case"],
                    objects["result"],
                    objects["trajectory"],
                    audits,
                    deliveries,
                    scores,
                )
            )
        except FileNotFoundError as error:
            rows.append(unknown_episode(expected, str(error)))
        except (KeyError, ValueError, TypeError) as error:
            rows.append(unknown_episode(expected, str(error), rejected=True))
    for binding in plan["source_pins"]:
        read_bound(repository, binding)
    return {
        **build_report(planned, rows),
        "plan_sha256": expected_plan_sha256,
        "evidence_sha256": expected_manifest_sha256,
        "verified_source_sha256": verified,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--material-root", required=True, type=Path)
    parser.add_argument("--expected-plan-sha256", required=True)
    parser.add_argument("--expected-manifest-sha256", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    report = generate(
        args.root,
        args.material_root,
        args.expected_plan_sha256,
        args.expected_manifest_sha256,
    )
    with args.output.open("x") as stream:
        json.dump(report, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
    print(
        json.dumps(
            {
                "planned_episodes": report["planned_episodes"],
                "scientific_acceptance": "HOLD",
            }
        )
    )


if __name__ == "__main__":
    main()
