#!/usr/bin/env python3
"""End-to-end standard-library NDU System-2 shadow event.

The orchestrator composes the repository's small qualification components:

``ndu_merton_sim``
    Gibbs/KL portfolio weights for an action/thinking/branch/stop router.
``short_horizon_fbsde_tree``
    A finite branch-tree conditional-moment calculation for ``X/P/B`` and
    ``Y/Z``.  This is an explicit shadow tree, not a learned FBSDE.
``multimodal_cell_contract``
    A deterministic Cell candidate with immutable parent and candidate
    snapshots.
``ndu_ledger_ope``
    Immutable decision/outcome receipts, delayed-outcome watermarks and OPE.

No provider, model endpoint, network call, artifact selection, or production
authority is invoked.  The returned JSON is intended as an auditable event
fixture for wiring and contract tests.
"""

from __future__ import annotations

import argparse
import json
import math
import random
from typing import Dict, Mapping, Tuple

from ndu_ledger_ope import DecisionReceipt, OutcomeReceipt, ReceiptLedger
from ndu_merton_sim import default_accounts, gibbs_portfolio, run as portfolio_run
from multimodal_cell_contract import (
    AUTHORITY,
    PROTOCOL_MODE,
    build_cell_bundle,
    build_feature_cache,
    digest_text,
)
from short_horizon_fbsde_tree import run as tree_run


EPS = 1.0e-10
CANDIDATES = ("action", "thinking", "branch", "stop")
ASSET_TO_CANDIDATE = {
    "direct_action": "action",
    "think_token": "thinking",
    "branch": "branch",
}
ACTION_TO_MODALITY = {
    "action": "text",
    "thinking": "image",
    "branch": "audio",
    "stop": "video",
}


def _clip(value: float, lower: float = 0.0, upper: float = 1.0) -> float:
    return max(lower, min(upper, float(value)))


def _sample(distribution: Mapping[str, float], rng: random.Random) -> str:
    threshold = rng.random()
    cumulative = 0.0
    last = next(iter(distribution))
    for name, probability in distribution.items():
        last = name
        cumulative += probability
        if threshold <= cumulative:
            return name
    return last


def _json_receipt(receipt: object) -> Dict[str, object]:
    if isinstance(receipt, DecisionReceipt):
        return {
            "decision_id": receipt.decision_id,
            "candidates": list(receipt.candidates),
            "propensity": dict(receipt.propensity),
            "seed": receipt.seed,
            "budget": receipt.budget,
            "support": list(receipt.support),
            "selected_action": receipt.selected_action,
        }
    if isinstance(receipt, OutcomeReceipt):
        return {
            "outcome_id": receipt.outcome_id,
            "decision_id": receipt.decision_id,
            "outcome": receipt.outcome,
            "watermark": receipt.watermark,
            "correction_of": receipt.correction_of,
            "observed": receipt.observed,
        }
    raise TypeError(type(receipt).__name__)


def _inference_portfolio(seed: int) -> Tuple[Dict[str, float], Dict[str, object]]:
    """Build a four-way candidate propensity from the Merton router.

    The portfolio implementation returns active mass plus an unallocated
    reserve.  We turn a fixed five-percent part of that mass into an explicit
    ``stop`` candidate so the behavior receipt has a complete, positive
    support and can be evaluated by OPE.
    """

    budget, reserve, assets, covariance = default_accounts()["inference"]
    selected_indices = [0, 1, 4]
    selected_assets = tuple(assets[index] for index in selected_indices)
    selected_covariance = tuple(
        tuple(covariance[i][j] for j in selected_indices)
        for i in selected_indices
    )
    weights, stopped, objective = gibbs_portfolio(
        selected_assets,
        selected_covariance,
        budget=budget,
        reserve=reserve,
        gamma=1.2,
        temperature=0.18,
        cost_shadow=0.06,
        stop_utility=0.05,
    )
    active = sum(weights)
    if stopped or active <= EPS:
        raw = {candidate: 1.0 / len(CANDIDATES) for candidate in CANDIDATES}
    else:
        active_scale = 0.95 / active
        raw = {"stop": 0.05}
        for weight, asset in zip(weights, selected_assets):
            raw[ASSET_TO_CANDIDATE[asset.name]] = max(1.0e-12, weight * active_scale)
    total = sum(raw.values())
    propensity = {candidate: raw.get(candidate, 0.0) / total for candidate in CANDIDATES}
    metadata = {
        "account": "inference",
        "budget": budget,
        "reserve": reserve,
        "objective": objective,
        "portfolio_stopped": stopped,
        "active_mass": active,
        "asset_weights": {asset.name: weight for asset, weight in zip(selected_assets, weights)},
    }
    return propensity, metadata


def _candidate_outcome(
    tree_value: float,
    cell_score: float,
    selected_action: str,
    difficulty: float,
) -> float:
    """Create a held-out deterministic outcome proxy for the shadow event."""

    action_bonus = {"action": 0.08, "thinking": 0.12, "branch": 0.10, "stop": -0.04}[selected_action]
    return _clip(0.5 + 0.16 * math.tanh(tree_value) + 0.28 * cell_score + action_bonus - 0.08 * difficulty)


def run(seed: int = 17) -> Dict[str, object]:
    """Run one deterministic prompt-to-receipt shadow event."""

    seed = int(seed)
    rng = random.Random(seed ^ 0x5EED)
    difficulty = rng.random()
    prompt_digest = digest_text("prompt-state-v1", seed, round(difficulty, 12))
    prompt_state = {
        "prompt_id": f"prompt-{prompt_digest[:16]}",
        "prompt_digest": prompt_digest,
        "difficulty": difficulty,
        "seed": seed,
        "state": {"X": 0.0, "P": 1.0, "B": 8.0},
    }

    portfolio_result = portfolio_run(seed)
    propensity, portfolio_metadata = _inference_portfolio(seed)
    selected_action = _sample(propensity, random.Random(seed ^ 0xA11CE))
    candidate_digest = digest_text(
        "candidate-set-v1", prompt_digest, tuple((name, propensity[name]) for name in CANDIDATES)
    )
    decision_id = f"decision-{candidate_digest[:16]}"
    budget = 8.0
    decision = DecisionReceipt.from_mapping(
        decision_id=decision_id,
        candidates=CANDIDATES,
        propensity=propensity,
        seed=seed,
        budget=budget,
        support=CANDIDATES,
        selected_action=selected_action,
    )

    # The tree is independent of provider dispatch and uses a separate reserve
    # so its B process cannot spend the entire prompt budget.
    tree_result = tree_run(seed=seed, horizon=4, local_horizon=2, budget=8.0, reserve_budget=1.0)

    # Build one Cell candidate from the selected route.  The cache and lineage
    # are deterministic and intentionally tiny for a qualification event.
    modality = ACTION_TO_MODALITY[selected_action]
    cache = build_feature_cache(
        seed,
        feature_dim=3,
        latent_dim=2,
        train_rows=4,
        future_rows=2,
    )
    bundle = build_cell_bundle(
        cache,
        modality,
        cell_index=seed % 1000,
        budget_updates=2,
        learning_rate=0.06,
    )
    row = cache.rows_for(modality)[0]
    prediction = bundle.model.predict(row)
    cell_score = _clip(1.0 - abs(prediction - row.task_target))
    outcome_value = _candidate_outcome(
        tree_result["global"]["value"], cell_score, selected_action, difficulty
    )

    ledger = ReceiptLedger()
    ledger.add_decision(decision)
    pending = OutcomeReceipt(
        outcome_id=f"outcome-pending-{decision_id}",
        decision_id=decision_id,
        outcome=None,
        watermark=1,
    )
    ledger.add_outcome(pending)
    ledger.advance_watermark(1)
    target_policy = {candidate: 1.0 / len(CANDIDATES) for candidate in CANDIDATES}
    delayed_estimate = ledger.evaluate("ips", target_policy, as_of=1)

    observed = OutcomeReceipt(
        outcome_id=f"outcome-observed-{decision_id}",
        decision_id=decision_id,
        outcome=outcome_value,
        watermark=2,
    )
    ledger.add_outcome(observed)
    ledger.advance_watermark(2)
    observed_ips = ledger.evaluate("ips", target_policy)
    observed_snips = ledger.evaluate("snips", target_policy)
    baseline = {candidate: 0.5 for candidate in CANDIDATES}
    observed_dr = ledger.evaluate("dr", target_policy, baseline=baseline)
    observed_ess = ledger.effective_sample_size(target_policy)

    lineage = {
        "initial_snapshot": bundle.initial_snapshot.as_dict(),
        "candidate_snapshot": bundle.candidate_snapshot.as_dict(),
        "candidate_snapshot_digest": bundle.candidate_snapshot.artifact_digest,
        "candidate_predecessor_matches_initial": bundle.candidate_snapshot.predecessor_digest == bundle.initial_snapshot.artifact_digest,
        "contract_digest": bundle.contract.digest,
        "parent_digest": cache.encoder_digest,
    }
    budget_report = {
        "prompt_budget": budget,
        "tree_initial": tree_result["budget"]["initial"],
        "tree_reserve": tree_result["budget"]["reserve"],
        "tree_global_spent": tree_result["budget"]["global_spent"],
        "tree_local_spent": tree_result["budget"]["local_spent"],
        "tree_constraints_ok": tree_result["budget"]["constraints_ok"],
        "portfolio_expected_cost": sum(
            propensity[candidate] * {"action": 1.0, "thinking": 0.55, "branch": 3.0, "stop": 0.0}[candidate]
            for candidate in CANDIDATES
        ),
        "cell_budget_flops": bundle.budget_flops,
    }
    protocol = {
        "mode": PROTOCOL_MODE,
        "authority": AUTHORITY,
        "production_authority": AUTHORITY,
        "provider_dispatch": False,
        "real_model_call": False,
        "artifact_selection": False,
        "learned_fbsde": False,
    }
    return {
        "seed": seed,
        "authority": AUTHORITY,
        "protocol": protocol,
        "prompt_state": prompt_state,
        "portfolio": {
            "propensity": propensity,
            "propensity_sum": sum(propensity.values()),
            "support": list(decision.support),
            "support_complete": set(decision.support) == set(CANDIDATES),
            "selected_action": selected_action,
            "candidate_set_digest": candidate_digest,
            "metadata": portfolio_metadata,
            "accounts": portfolio_result["accounts"],
        },
        "tree": {
            "best_path": tree_result["best_path"],
            "global_value": tree_result["global"]["value"],
            "local_value": tree_result["composed"]["value"],
            "local_composition_gap": tree_result["local_composition_gap"],
            "global_gap_detected": tree_result["global_gap_detected"],
            "Y0": tree_result["backward"]["Y0"],
            "Z0": tree_result["backward"]["Z0"],
            "z_finite": tree_result["z_finite"],
            "budget": tree_result["budget"],
        },
        "cell": {
            "modality": modality,
            "prediction": prediction,
            "task_target": row.task_target,
            "held_out_score": cell_score,
            "budget_flops": bundle.budget_flops,
            "lineage": lineage,
        },
        "receipts": {
            "decision": _json_receipt(decision),
            "pending_outcome": _json_receipt(pending),
            "observed_outcome": _json_receipt(observed),
        },
        "delayed_outcome": {
            "pending_watermark": pending.watermark,
            "observed_watermark": observed.watermark,
            "pending_excluded_from_ope": not delayed_estimate.valid,
            "observed_included_in_ope": observed_ips.valid,
        },
        "outcome": outcome_value,
        "ope": {
            "target_policy": target_policy,
            "delayed_as_of_1": delayed_estimate.to_dict(),
            "ips": observed_ips.to_dict(),
            "snips": observed_snips.to_dict(),
            "dr": observed_dr.to_dict(),
            "ess": observed_ess,
        },
        "budget": budget_report,
        "candidate_snapshot_digest": bundle.candidate_snapshot.artifact_digest,
    }


# Descriptive alias for callers that prefer an event-oriented API.
orchestrate = run


def main() -> None:
    parser = argparse.ArgumentParser(description="NDU System-2 standard-library shadow event")
    parser.add_argument("--seed", type=int, default=17)
    args = parser.parse_args()
    print(json.dumps(run(args.seed), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
