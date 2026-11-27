"""Audit MEM5 result arithmetic and metadata without opening task references.

This deliberately does not import the frozen reader/summary implementation and
does not claim to replay actor sidecars, OCR, host effects or reference scoring.
"""

import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
HEAD = "5fa0d0e462cd1393f4f9e95565ff5993e9bad29a"
MODES = ("frozen_neural", "public_rule")
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


def reject_constant(value):
    raise ValueError("nonfinite JSON constant: " + value)


def unique_pairs(pairs):
    output = {}
    for key, value in pairs:
        if key in output:
            raise ValueError("duplicate JSON key: " + key)
        output[key] = value
    return output


def read(path):
    raw = path.read_bytes()
    return json.loads(
        raw, object_pairs_hook=unique_pairs, parse_constant=reject_constant
    ), {
        "path": str(path),
        "bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
    }


def canonical_sha(value):
    raw = json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()
    return hashlib.sha256(raw).hexdigest()


def probability(rows, outcome, condition=None):
    eligible = [r for r in rows if condition is None or r[condition] is True]
    missing_condition = sum(r[condition] is None for r in rows) if condition else 0
    observed_successes = sum(r[outcome] is True for r in eligible)
    missing_outcome = sum(r[outcome] is None for r in eligible)
    total_possible = len(eligible) + missing_condition
    unresolved = bool(missing_condition or missing_outcome)
    return {
        "numerator": observed_successes,
        "denominator": len(eligible),
        "planned_episodes": len(rows),
        "unknown_condition": missing_condition,
        "unknown_outcome": missing_outcome,
        "value": observed_successes / len(eligible)
        if eligible and not unresolved
        else None,
        "bounds": [
            observed_successes / total_possible,
            (observed_successes + missing_outcome + missing_condition) / total_possible,
        ]
        if total_possible
        else None,
        "status": "ZERO_DENOMINATOR"
        if not total_possible
        else "UNKNOWN"
        if unresolved
        else "OBSERVED",
    }


def audit(root):
    problems, checks = [], []

    def check(label, actual, expected):
        if actual != expected or type(actual) is not type(expected):
            problems.append({"check": label, "actual": actual, "expected": expected})
        else:
            checks.append(label)

    data, bindings = {}, {}
    for name in ("PLAN", "EVIDENCE", "REPORT", "RUN_RECEIPT"):
        data[name], bindings[name] = read(root / (name + ".json"))
    plan, evidence, report, receipt = (
        data[k] for k in ("PLAN", "EVIDENCE", "REPORT", "RUN_RECEIPT")
    )
    request, request_binding = read(ROOT / "request-5fa0d0e462cd.json")
    metadata, metadata_binding = read(ROOT / "metadata-selected-roster.json")
    source_inputs, source_binding = read(ROOT / "final-source-inputs.json")
    check("source_commit", plan["source_commit"], HEAD)
    check("request_canonical_binding", plan["request_sha256"], canonical_sha(request))
    check("plan_evidence_binding", evidence["plan_sha256"], bindings["PLAN"]["sha256"])
    check("report_plan_binding", report["plan_sha256"], bindings["PLAN"]["sha256"])
    check(
        "report_evidence_binding",
        report["evidence_sha256"],
        bindings["EVIDENCE"]["sha256"],
    )
    check("receipt_plan_binding", receipt["plan_sha256"], bindings["PLAN"]["sha256"])
    check(
        "receipt_report_binding", receipt["report_sha256"], bindings["REPORT"]["sha256"]
    )
    check("receipt_source_commit", receipt["source_commit"], HEAD)
    check("plan_source_roster", plan["source_pins"], request["source_pins"])
    inputs = {p["path"]: p for p in source_inputs}
    check(
        "source_pin_uniqueness",
        len({p["path"] for p in plan["source_pins"]}),
        len(plan["source_pins"]),
    )
    for pin in plan["source_pins"]:
        path = pin["path"]
        expected = inputs[path]
        for key in ("sha256", "bytes"):
            check("published_source." + path + "." + key, pin[key], expected[key])
        raw = (ROOT / "published-final" / path).read_bytes()
        check("local_source_bytes." + path, len(raw), pin["bytes"])
        check(
            "local_source_digest." + path,
            hashlib.sha256(raw).hexdigest(),
            pin["sha256"],
        )
    check(
        "reader_verified_sources",
        report["verified_source_sha256"],
        {p["path"]: p["sha256"] for p in plan["source_pins"]},
    )
    check("model_pin_roster", plan["model"], request["model"])
    for key in ("evaluator_sha256", "reference_index_sha256", "rubric_sha256"):
        check(key, plan[key], request["config"][key])
    check(
        "fixed_allocation",
        plan["groups_per_role"],
        {"development": 10, "retention_validation": 4},
    )
    check("fixed_salt", plan["selection_salt"], metadata["selection_salt"])
    check(
        "excluded_roster",
        sorted(plan["excluded_source_groups"]),
        sorted(metadata["excluded_source_groups"]),
    )
    check(
        "selector_algorithm_pin",
        plan["selector_profile_sha256"],
        request["selector_profile_sha256"],
    )
    check(
        "selector_algorithm_hash",
        plan["selector_profile_sha256"],
        canonical_sha(plan["selector_profile"]),
    )

    planned = plan["episodes"]
    check("planned_episodes", len(planned), 108)
    by_operation = {r["original_operation_id"]: r for r in planned}
    check("unique_planned_operations", len(by_operation), 108)
    cases = {r["id"]: r for r in metadata["selected_cases"]}
    check(
        "selected_case_roster", sorted({r["case_id"] for r in planned}), sorted(cases)
    )
    check("source_count", len({r["source_group_id"] for r in planned}), 14)
    pairs = defaultdict(list)
    for row in planned:
        op, mode = row["original_operation_id"], row["selector_mode"]
        case = cases[row["case_id"]]
        pairs[row["pair_id"]].append(row)
        for key, other in (
            ("source_group_id", "source_id"),
            ("split", "role"),
            ("episode_group", "episode_group"),
            ("task_family", "task_family"),
        ):
            check("planned_case." + op + "." + key, row[key], case[other])
        check(
            "public_packet." + op, row["public_case_sha256"], case["packet"]["sha256"]
        )
        check(
            "not_excluded." + op,
            row["source_group_id"] not in plan["excluded_source_groups"],
            True,
        )
        for key in ("parameters_sha256", "control_profile_sha256"):
            check("frozen_model." + op + "." + key, row[key], request["model"][key])
        check(
            "frozen_weights." + op,
            row["weights_sha256"],
            request["model"]["weights"]["sha256"],
        )
        selector = row["candidate_selector_profile"]
        check("selector_mode." + op, selector["mode"], mode)
        check(
            "selector_hash." + op,
            row["candidate_selector_profile_sha256"],
            canonical_sha(selector),
        )
        check(
            "memory." + op,
            row["candidate_memory_profile"],
            {
                "schema": "ndu.real.candidate-memory-profile.v1",
                "mode": "bounded",
                "max_entries": 128,
                "max_serialized_bytes": 524288,
            },
        )
        check(
            "memory_hash." + op,
            row["candidate_memory_profile_sha256"],
            canonical_sha(row["candidate_memory_profile"]),
        )
    check("pair_count", len(pairs), 54)
    changing = {
        "selector_mode",
        "original_operation_id",
        "candidate_selector_profile",
        "candidate_selector_profile_sha256",
    }
    for pair_id, pair in pairs.items():
        check(
            "pair_two_modes." + pair_id,
            sorted(r["selector_mode"] for r in pair),
            sorted(MODES),
        )
        if len(pair) == 2:
            check(
                "pair_frozen_inputs." + pair_id,
                {k: v for k, v in pair[0].items() if k not in changing},
                {k: v for k, v in pair[1].items() if k not in changing},
            )
    check("report_episode_count", report["planned_episodes"], 108)
    scored = report["episodes"]
    check("report_rows_count", len(scored), 108)
    check(
        "report_operations",
        sorted(r["original_operation_id"] for r in scored),
        sorted(by_operation),
    )
    check(
        "evidence_operations",
        sorted(r["original_operation_id"] for r in evidence["episodes"]),
        sorted(by_operation),
    )
    for row in scored:
        expected = by_operation[row["original_operation_id"]]
        for key in ("case_id", "source_group_id", "pair_id", "selector_mode"):
            check(
                "report_identity." + row["original_operation_id"] + "." + key,
                row[key],
                expected[key],
            )
        for key in EVENTS:
            check(
                "event_type." + row["original_operation_id"] + "." + key,
                row[key] is None or type(row[key]) is bool,
                True,
            )

    reconstructed = {}
    for mode in MODES:
        rows = [r for r in scored if r["selector_mode"] == mode]
        check("mode_denominator." + mode, len(rows), 54)
        panel = report["panels"][mode]
        expected = {
            "planned_episodes": len(rows),
            "evidence_status": dict(Counter(r["evidence_status"] for r in rows)),
            "terminal_status": dict(Counter(r["terminal_status"] for r in rows)),
            "events": {
                key: {
                    "true": sum(r[key] is True for r in rows),
                    "false": sum(r[key] is False for r in rows),
                    "unknown": sum(r[key] is None for r in rows),
                }
                for key in EVENTS
            },
            "unconditional_success": probability(rows, "unconditional_success"),
            "candidate_chain": {
                "raw_observed": probability(rows, "raw_observed"),
                "available": probability(rows, "available"),
                "selected_given_available": probability(rows, "selected", "available"),
                "delivered_given_selected": probability(
                    rows, "candidate_mediated_delivered", "selected"
                ),
            },
            "failure_attribution": dict(Counter(r["failure_stage"] for r in rows)),
        }
        shadows = [r["shadow"] for r in rows]
        expected["shadow_at_actual_anchor"] = {
            "planned_episodes": len(rows),
            "observed_supports": sum(r["available"] is not None for r in shadows),
            "unknown_supports": sum(r["available"] is None for r in shadows),
            "neural_correct": sum(r["frozen_neural"] is True for r in shadows),
            "public_rule_correct": sum(r["public_rule"] is True for r in shadows),
            "paired_transitions": dict(
                Counter(
                    str(r["frozen_neural"]) + "->" + str(r["public_rule"])
                    for r in shadows
                )
            ),
            "selection_given_available": {
                m: probability(shadows, m, "available") for m in MODES
            },
            "counterfactual_delivery_estimated": False,
        }
        check("complete_panel_arithmetic." + mode, panel, expected)
        reconstructed[mode] = expected
    paired_scores = defaultdict(dict)
    for row in scored:
        paired_scores[row["pair_id"]][row["selector_mode"]] = row[
            "unconditional_success"
        ]
    differences, unknown = [], 0
    for pair in paired_scores.values():
        if set(pair) == set(MODES) and all(v is not None for v in pair.values()):
            differences.append(int(pair["public_rule"]) - int(pair["frozen_neural"]))
        else:
            unknown += 1
    contrast = report["paired_terminal_contrast"]
    check("paired_planned", contrast["planned_pairs"], 54)
    check("paired_observed", contrast["observed_pairs"], len(differences))
    check("paired_unknown", contrast["unknown_pairs"], unknown)
    check(
        "paired_value",
        contrast["value"],
        sum(differences) / 54 if not unknown else None,
    )
    check(
        "paired_bounds",
        contrast["bounds"],
        [(sum(differences) - unknown) / 54, (sum(differences) + unknown) / 54],
    )
    check(
        "paired_outcomes",
        contrast["outcomes"],
        {k: differences.count(v) for k, v in (("loss", -1), ("tie", 0), ("win", 1))},
    )
    attempts = receipt["attempts"]
    check(
        "attempt_roster",
        sorted(r["original_operation_id"] for r in attempts),
        sorted(by_operation),
    )
    check(
        "attempt_terminal_counts",
        receipt["terminal_status_counts"],
        dict(Counter(r["status"] for r in attempts)),
    )
    check(
        "all_actor_completed_flag",
        receipt["all_actor_episodes_completed"],
        all(r["status"] == "Completed" for r in attempts),
    )
    check("receipt_episode_count", receipt["planned_episodes"], 108)
    check("receipt_source_count", receipt["source_group_count"], 14)
    for phase in ("before", "after"):
        check(
            "weights_" + phase,
            receipt["weights_sha256_" + phase],
            request["model"]["weights"]["sha256"],
        )
    for label, value in (("plan", plan), ("receipt", receipt), ("report", report)):
        check(label + ".scientific_acceptance", value["scientific_acceptance"], "HOLD")
        check(label + ".confirmation_evaluated", value["confirmation_evaluated"], False)
        check(label + ".production_adoption", value["production_adoption"], False)
    return {
        "schema": "mem5-independent-result-arithmetic-audit.v1",
        "status": "PASS" if not problems else "FAIL",
        "source_commit": HEAD,
        "checks_passed": len(checks),
        "problems": problems,
        "input_bindings": {
            **bindings,
            "frozen_request": request_binding,
            "preexecution_metadata_roster": metadata_binding,
            "published_source_inputs": source_binding,
        },
        "reconstructed_panels": reconstructed,
        "paired_terminal_contrast": contrast,
        "scope": "Independent arithmetic, all-planned roster and byte/source metadata audit; report rows accepted as inputs",
        "raw_actor_sidecars_replayed": False,
        "reference_evaluator_rerun": False,
        "authenticated_global_exposure_proved": False,
        "scientific_acceptance": "HOLD",
        "production_adoption": False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT / "run-result")
    parser.add_argument(
        "--output", type=Path, default=ROOT / "result-arithmetic-audit.json"
    )
    args = parser.parse_args()
    result = audit(args.root)
    args.output.write_text(
        json.dumps(result, sort_keys=True, indent=2, allow_nan=False) + "\n"
    )
    print(
        json.dumps(
            {
                "status": result["status"],
                "checks_passed": result["checks_passed"],
                "problems": len(result["problems"]),
                "output": str(args.output),
            }
        )
    )
    if result["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
