"""Independent post-hoc 2x2 attribution audit of the *frozen synthetic* report.

This does not import the experimental trainer, scorer or actor. An aggregate
report cannot establish source-level paired randomness, physical-cost equality,
future generalization or independent outcome custody. Never promote based on it.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

SCHEMA = "hepta.ndu-v5.factorial-development-summary.v1"
EXPECTED_SEEDS = (17, 29, 43)
ARMS = (
    "supervised|static",
    "supervised|ndu_contextual",
    "ndu_risk|static",
    "ndu_risk|ndu_contextual",
)
METRICS = ("mean_loss", "cvar90_loss", "mean_cost_units",
           "query_rate", "refine_rate")
SOURCES_PER_SEED = 512
HEAD_FORWARDS = 2048
EPS = 1e-12


def _number(value, label):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError(f"nonfinite or unsupported {label}")
    return float(value)


def _validate_arm(row, label):
    if type(row) is not dict:
        raise ValueError(f"missing frozen arm {label}")
    fields = {key: _number(row.get(key), f"{label}.{key}") for key in METRICS}
    if (fields["mean_loss"] < 0
        or fields["cvar90_loss"] + EPS < fields["mean_loss"]
        or not 4 <= fields["mean_cost_units"] <= 7
        or not 0 <= fields["query_rate"] <= 1
        or not 0 <= fields["refine_rate"] <= 1):
        raise ValueError(f"invalid decoded-loss or modeled cost in {label}")
    if (type(row.get("test_sources")) is not int
        or row["test_sources"] != SOURCES_PER_SEED
        or type(row.get("head_forward_calls")) is not int
        or row["head_forward_calls"] != HEAD_FORWARDS
        or type(row.get("query_executions")) is not int
        or not 0 <= row["query_executions"] <= SOURCES_PER_SEED):
        raise ValueError(f"incomplete source/forward/action census in {label}")
    if abs(fields["query_rate"] -
           row["query_executions"] / SOURCES_PER_SEED) > EPS:
        raise ValueError(f"mismatched realized query-rate in {label}")
    return fields


def audit_factorial(report):
    if (type(report) is not dict
        or report.get("schema") != SCHEMA
        or report.get("status") != "DEVELOPMENT_ONLY_HOLD_NO_GO"
        or type(report.get("seeds")) is not list
        or len(report["seeds"]) != len(EXPECTED_SEEDS)):
        raise ValueError("not the frozen scoped development factorial")
    observed_seeds = [row.get("seed") for row in report["seeds"]
                      if type(row) is dict]
    if observed_seeds != list(EXPECTED_SEEDS):
        raise ValueError("noncanonical, duplicated or missing seed census")

    seed_results = []
    for seedrow in report["seeds"]:
        seed = seedrow["seed"]
        arms = seedrow.get("arms")
        if type(arms) is not dict or set(arms) != set(ARMS):
            raise ValueError(f"unpaired or additional factorial arm: {seed}")
        scores = {key: _validate_arm(arms[key], f"{seed}:{key}")
                  for key in ARMS}
        ss, sn, ns, nn = (scores[key] for key in ARMS)
        # Negative deltas mean smaller independently decoded terminal loss.
        seed_results.append({
            "seed": seed,
            "train_effect_under_static": ns["mean_loss"] - ss["mean_loss"],
            "train_effect_under_dynamic": nn["mean_loss"] - sn["mean_loss"],
            "control_effect_under_supervised": sn["mean_loss"] - ss["mean_loss"],
            "control_effect_under_ndu_training": nn["mean_loss"] - ns["mean_loss"],
            "factorial_interaction": (
                nn["mean_loss"] - ns["mean_loss"]
                - sn["mean_loss"] + ss["mean_loss"]),
            "joint_minus_supervised_static_loss": nn["mean_loss"] - ss["mean_loss"],
            "joint_minus_supervised_static_cvar90": nn["cvar90_loss"] - ss["cvar90_loss"],
            "joint_minus_ndu_static_cvar90": nn["cvar90_loss"] - ns["cvar90_loss"],
            "joint_minus_ndu_static_cost": nn["mean_cost_units"] - ns["mean_cost_units"],
            "joint_refine_rate": nn["refine_rate"],
            "joint_query_rate": nn["query_rate"],
            "joint_control_worsens_loss": (
                nn["mean_loss"] > ns["mean_loss"] + EPS),
            "all_arms_equal_actual_modeled_cost": (
                max(row["mean_cost_units"] for row in scores.values()) -
                min(row["mean_cost_units"] for row in scores.values()) <= EPS),
        })

    def avg(field):
        # Aggregate at TRAINING-SEED level, not as 3*512 independent seeds.
        return math.fsum(s[field] for s in seed_results) / len(seed_results)

    # Post-hoc diagnostic gates, NOT preregistered confirmatory thresholds.
    gates = {
        "all_seed_control_loss_nonregression": not any(
            row["joint_control_worsens_loss"] for row in seed_results),
        "all_seed_joint_cvar_nonregression_vs_ndu_static": all(
            row["joint_minus_ndu_static_cvar90"] <= EPS for row in seed_results),
        "actual_dynamic_modal_refinement_seen": any(
            row["joint_refine_rate"] > 0 for row in seed_results),
        "all_four_arms_equal_realized_modeled_cost": all(
            row["all_arms_equal_actual_modeled_cost"] for row in seed_results),
        "physical_end_to_end_meter_attested": False,
        "real_natural_multimodal_generation_confirmed": False,
        "prospective_multi_seed_superiority_confirmed": False,
    }
    return {
        "schema": "hepta.ndu-v5.factorial-credit-posthoc-audit.v1",
        "status": "DEVELOPMENT_ONLY_HOLD_NO_GO",
        "seeds_are_independent_training_units": len(EXPECTED_SEEDS),
        "groups_per_seed_reported_not_reauthenticated": SOURCES_PER_SEED,
        "arms": list(ARMS),
        "per_seed": seed_results,
        "seed_mean_interaction": avg("factorial_interaction"),
        "seed_mean_joint_vs_base_loss": avg("joint_minus_supervised_static_loss"),
        "seed_mean_joint_vs_base_cvar90": avg("joint_minus_supervised_static_cvar90"),
        "seed_mean_joint_vs_ndu_static_cvar90": avg("joint_minus_ndu_static_cvar90"),
        "source_level_pairs_replayed_here": False,
        "original_outcomes_independently_signed_here": False,
        "real_physical_decoder_costs_measured_here": False,
        "gates": gates,
        "all_scientific_blockers_closed": False,
    }


def audit_frozen_file(path):
    raw = Path(path).read_bytes()
    report = json.loads(raw)
    result = audit_factorial(report)
    result["input_sha256"] = hashlib.sha256(raw).hexdigest()
    return result


if __name__ == "__main__":
    frozen = Path(__file__).with_name("development-report.json")
    print(json.dumps(audit_frozen_file(frozen), indent=2, sort_keys=True))
