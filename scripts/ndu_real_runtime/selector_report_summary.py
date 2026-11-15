"""All-planned primary outcomes and within-support shadow diagnostics."""

from collections import Counter, defaultdict

from .candidate_retention_report import EVENTS, probability, unknown_episode

MODES = ("frozen_neural", "public_rule")


def summarize(planned, rows):
    by_id = {r["original_operation_id"]: r for r in rows}
    if len(by_id) != len(rows) or not by_id.keys() <= {
        r["original_operation_id"] for r in planned
    }:
        raise ValueError("duplicate or unplanned scored episode")
    full = []
    for expected in planned:
        row = dict(
            by_id.get(
                expected["original_operation_id"],
                unknown_episode(expected, "missing planned episode evidence"),
            )
        )
        row["candidate_memory_mode"] = expected["candidate_memory_profile"]["mode"]
        row["mode"] = row["selector_mode"] = expected["selector_mode"]
        row.setdefault(
            "shadow", {k: None for k in ("available", "frozen_neural", "public_rule")}
        )
        full.append(row)
    panels = {}
    for mode in MODES:
        subset = [r for r in full if r["selector_mode"] == mode]
        panels[mode] = {
            "planned_episodes": len(subset),
            "evidence_status": dict(Counter(r["evidence_status"] for r in subset)),
            "terminal_status": dict(Counter(r["terminal_status"] for r in subset)),
            "events": {
                k: {
                    "true": sum(r[k] is True for r in subset),
                    "false": sum(r[k] is False for r in subset),
                    "unknown": sum(r[k] is None for r in subset),
                }
                for k in EVENTS
            },
            "unconditional_success": probability(subset, "unconditional_success"),
            "candidate_chain": {
                "raw_observed": probability(subset, "raw_observed"),
                "available": probability(subset, "available"),
                "selected_given_available": probability(
                    subset, "selected", given="available"
                ),
                "delivered_given_selected": probability(
                    subset, "candidate_mediated_delivered", given="selected"
                ),
            },
            "failure_attribution": dict(Counter(r["failure_stage"] for r in subset)),
            "shadow_at_actual_anchor": {
                "planned_episodes": len(subset),
                "observed_supports": sum(
                    r["shadow"]["available"] is not None for r in subset
                ),
                "unknown_supports": sum(
                    r["shadow"]["available"] is None for r in subset
                ),
                "neural_correct": sum(
                    r["shadow"]["frozen_neural"] is True for r in subset
                ),
                "public_rule_correct": sum(
                    r["shadow"]["public_rule"] is True for r in subset
                ),
                "paired_transitions": dict(
                    Counter(
                        str(r["shadow"]["frozen_neural"])
                        + "->"
                        + str(r["shadow"]["public_rule"])
                        for r in subset
                    )
                ),
                "selection_given_available": {
                    k: probability([r["shadow"] for r in subset], k, given="available")
                    for k in MODES
                },
                "counterfactual_delivery_estimated": False,
            },
        }
    paired = defaultdict(dict)
    for row in full:
        paired[row["pair_id"]][row["selector_mode"]] = row["unconditional_success"]
    differences = [
        int(r["public_rule"]) - int(r["frozen_neural"])
        for r in paired.values()
        if set(r) == set(MODES) and all(v is not None for v in r.values())
    ]
    unknown = len(paired) - len(differences)
    return {
        "schema": "ndu.real.candidate-selection-report.v1",
        "planned_episodes": len(planned),
        "episodes": full,
        "panels": panels,
        "paired_terminal_contrast": {
            "estimand": "public_rule minus frozen_neural unconditional success",
            "planned_pairs": len(paired),
            "observed_pairs": len(differences),
            "unknown_pairs": unknown,
            "value": sum(differences) / len(paired) if paired and not unknown else None,
            "bounds": [
                (sum(differences) - unknown) / len(paired),
                (sum(differences) + unknown) / len(paired),
            ]
            if paired
            else None,
            "outcomes": {
                label: differences.count(value)
                for label, value in (("loss", -1), ("tie", 0), ("win", 1))
            },
            "sampling_uncertainty": "not estimated; source-group dependence retained",
        },
        "anchor_rule": "last WRITE_TEXT decision; otherwise final actual actor decision",
        "shadow_stratified_by_actual_selector_mode": True,
        "all_planned_denominator_is_primary": True,
        "evaluation_role": "prospective_development_validation",
        "confirmation_evaluated": False,
        "scientific_acceptance": "HOLD",
        "production_adoption": False,
        "provider_authenticity_verified": False,
        "full_cost_adjusted": False,
        "exposure_roster_authenticity_established": False,
    }
