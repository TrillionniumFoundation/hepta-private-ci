"""Independent paired-outcome and paid-work science gate for HDCF CellBank.

A bounded original-input diagnostic. It does not evaluate a stochastic FBSDE,
issue FinalUse, authenticate model publishers or promote a live Cell Split.
Counting 32 questions from one BANKING77 publisher is NOT 32 independent
source families. Statistical p-values are descriptive and cannot grant authority.
"""
from __future__ import annotations

import math

from independent_head_replay import MODES, audit_head_replay
from physical_bank import Denied, digest, score, validate_bundle


def _require(condition: bool, why: str) -> None:
    if not condition:
        raise Denied(why)


def _mcnemar_exact(wins: int, losses: int) -> float:
    """Two-sided conditional exact sign probability for discordant paired cases.

    Handles d=0 explicitly; n<=1024 is the current maximum heldout count.
    Does not assume source-family independence or prove task-level efficacy.
    """
    d = wins + losses
    if d == 0:
        return 1.0
    p = math.ldexp(1.0, -d)  # 2**(-d), stable through d<=1024.
    tail = p
    for k in range(min(wins, losses)):
        p *= (d - k) / (k + 1)
        tail += p
    return min(1.0, tail * 2.0)


def _correct(probability: float, target: int) -> bool:
    return (probability >= 0.5) == bool(target)


def audit_paired_utility(bundle, trial, labels, *, steps=256, seed=7347, lr=0.05) -> dict:
    """Verify all real scalar updates, then score paired choices/cost coverage.

    No entropy/price preference can change a frozen task label, principal,
    authorization, or externally provided objective. Every arm's expense is
    counted even if it failed to improve accuracy, but wall/CPU provenance
    remains self-reported and is NOT independently attested.
    """
    fit, held, d = validate_bundle(bundle)
    replay = audit_head_replay(bundle, trial, steps=steps, seed=seed, lr=lr)
    outcome = score(trial, labels)
    _require(outcome["trial_identity"] == replay["trial_identity"] and
             replay["original_prediction_rows_replayed"] == len(held) * len(MODES),
             "independent replay and outcome identities differ")
    expected = {(id_, family, bundle["types"][kind]) for id_, family, kind, _ in held}
    targets = {}
    for record in labels["targets"]:
        key = record["id"], record["family"], record["type"]
        _require(key in expected and key not in targets, "blind target population changed")
        targets[key] = record["target"]
    _require(len(targets) == len(held), "incomplete independent blind labels")
    by_mode = {}
    for mode in MODES:
        pred = trial["predictions"][mode]
        found = {}
        for p in pred:
            key = p["id"], p["family"], p["type"]
            _require(key in expected and key not in found, "changed prediction population")
            # Prediction finite/probability envelope is already checked in replay.
            found[key] = _correct(p["p1"], targets[key])
        _require(len(found) == len(targets), "missing paired prediction")
        by_mode[mode] = found
    groups = sorted({family for _, family, _ in expected})
    _require(len(groups) <= 1024, "oversized grouping")
    pairs = {}
    baseline = by_mode["frozen"]
    for name in MODES:
        if name == "frozen":
            continue
        candidate = by_mode[name]
        wins = sum(bool(candidate[key] and not baseline[key]) for key in targets)
        losses = sum(bool(baseline[key] and not candidate[key]) for key in targets)
        both = sum(bool(baseline[key] and candidate[key]) for key in targets)
        neither = len(targets) - (wins + losses + both)
        _require(min(wins, losses, both, neither) >= 0, "invalid paired accounting")
        pairs[name] = {
            "candidate_only_correct": wins, "baseline_only_correct": losses,
            "both_correct": both, "neither_correct": neither,
            "paired_questions": len(targets),
            "nominal_case_level_mcnemar_exact_two_sided": _mcnemar_exact(wins, losses),
            "test_is_independent_source_family": False,
            "statistical_superiority_certified": False,
        }
    paid = {"physical_head_train_sgd_updates": 0,
            "estimated_head_parameter_touches": 0,
            "reported_cpu_ns_unattested": 0,
            "reported_wall_ns_unattested": 0}
    for arm in MODES:
        record = trial["arms"][arm]
        paid["physical_head_train_sgd_updates"] += record["actual_sgd_steps"]
        paid["estimated_head_parameter_touches"] += record["estimated_parameter_touches"]
        paid["reported_cpu_ns_unattested"] += record["observed_train_cpu_ns"]
        paid["reported_wall_ns_unattested"] += record["observed_train_wall_ns"]
    _require(paid["physical_head_train_sgd_updates"] == 3 * steps and
             paid["estimated_head_parameter_touches"] > 0 and
             paid["reported_cpu_ns_unattested"] > 0,
             "lost update/cost accounting")
    return {
        "schema": "hepta.hdcf.paired-science-hold.v1",
        "trial_identity": trial["trial_identity"],
        "blind_label_digest": digest(labels),
        "matched_case_census": len(targets),
        "source_partition_families_present": groups,
        "independent_publisher_source_families_verified": 0,
        "observed_prospective_future_windows": 0,
        "matched_parameter_count_per_arm": trial["head_params_per_arm"],
        "observed_full_encoder_plus_reader_training_tco": None,
        "charged_known_work": paid,
        "nominal_case_level_pairs": pairs,
        "independent_replay": replay,
        "score": outcome,
        "qualifying_task_benefit": False,
        "ndu_incremental_net_utility_verified": False,
        "physical_cell_split_authorized": False,
        "native_execution_authorized": False,
        "production_authorized": False,
        "disposition": "HOLD_NO_GO",
    }
