"""Causal native transport, profile identity, and explicitly counted owner work."""

import json
from pathlib import Path

from experiments.free_boundary_neuron.owner.common import Native, digest, sha, write


__all__ = [
    "Native",
    "digest",
    "sha",
    "write",
    "DEFAULT_CREDIT",
    "model_payload",
    "permit",
    "encoder_proof",
    "open_request",
    "charge",
]

DEFAULT_CREDIT = {
    "eta": 0.005,
    "pmax": 0.08,
    "kappa": 0.5,
    "balance_cap": 32.0,
    "initial_balance": 16.0,
    "initial_price": 0.02,
    "frozen_price": 0.02,
    "quote": 2.0,
}


def model_payload(neural, *, grid_points=1001, credit=None):
    return {
        "schema": "hepta.adaptive-neuron.readout.v2",
        "neural": neural,
        "credit": dict(DEFAULT_CREDIT if credit is None else credit),
        "grid_points": grid_points,
    }


def permit(root):
    write(
        Path(root) / "RESEARCH_PERMIT.json",
        {
            "schema": "hepta.adaptive-neuron.local-research-permit.v2",
            "allowed_root": str(Path(root).resolve()),
            "external_effects": False,
            "production_authority": False,
            "scope": "User-authorized local synthetic evidence, original owner, trained SNN and research resource credit only; no production ledger or signature admission.",
        },
    )


def encoder_proof(model, destination):
    payload = json.loads(Path(model).read_text())
    if payload["schema"] != "hepta.adaptive-neuron.readout.v2":
        raise ValueError("trained readout profile required")
    proof = {
        "schema": "hepta.adaptive-neuron.numeric-domain-proof.v2",
        "model_sha256": sha(model),
        "confidence_target": "validated_numeric_domain_contract",
        "semantic_quality_qualification": False,
        "proof_kind": "algebraic_bounds_and_per_request_checks",
        "scope": "Bounded binary observation, reliability/cost integer encoding, deadline <=16, finite checked weights and state, and clipped native drive <=7 Q24. No task-success or statistical calibration claim.",
    }
    write(destination, proof)
    return proof


def open_request(
    case,
    organ,
    model,
    calibration,
    policy,
    context,
    budget,
    *,
    expires=64,
    account_sequence=0,
):
    reliability, cost, deadline = context
    return {
        "case": case,
        "organ": organ,
        "expires": expires,
        "context": {
            "reliability_ppm": round(reliability * 1_000_000),
            "cost_ppm": round(cost * 1_000_000),
            "deadline": int(deadline),
        },
        "budget": float(budget),
        "expected_account_sequence": account_sequence,
        "model": str(Path(model).resolve()),
        "model_sha256": sha(model),
        "calibration": str(Path(calibration).resolve()),
        "calibration_sha256": sha(calibration),
        "policy": policy,
    }


def charge(rows):
    additive = (
        "original_journal_replay_steps",
        "event_validation_kernel_steps",
        "event_validation_readout_calls",
        "event_validation_snn_cell_updates",
        "event_validation_spikes",
        "event_validation_bellman_terms",
        "boundary_build_terms",
        "account_validation_native_credit_calls",
        "profile_weight_scalars_validated",
        "native_credit_finalizations",
        "new_credit_records",
    )
    result = {key: 0 for key in additive}
    result.update(
        rpc_count=len(rows),
        failed_requests=0,
        owner_ticks=0,
        model_calls=0,
        actual_snn_cell_updates=0,
        actual_spikes=0,
        actual_input_multiply_accumulates=0,
        actual_readout_multiply_accumulates=0,
        actual_resource_work=0.0,
        bellman_query_terms=0,
        physical_rpc_micros=0,
        native_tick_micros=0,
        model_latency_micros=0,
        journal_bytes_written=0,
        peak_transient_allocation_bytes=0,
    )
    for row in rows:
        envelope = row["response"]
        result["physical_rpc_micros"] += envelope["physical_rpc_micros"]
        if not envelope["ok"]:
            result["failed_requests"] += 1
            continue
        value = envelope["result"]
        for key in additive:
            result[key] += value.get(key, 0)
        if value.get("native_transition_executed"):
            result["owner_ticks"] += 1
            result["model_calls"] += value["actual_model_calls"]
            result["bellman_query_terms"] += value["actual_bellman_terms"]
            for key in (
                "actual_snn_cell_updates",
                "actual_spikes",
                "actual_input_multiply_accumulates",
                "actual_readout_multiply_accumulates",
                "actual_resource_work",
            ):
                result[key] += value[key]
            result["native_tick_micros"] += value["execution_micros"]
            result["model_latency_micros"] += value["model_latency_micros"]
            result["journal_bytes_written"] += value["journal_bytes_written"]
            result["peak_transient_allocation_bytes"] = max(
                result["peak_transient_allocation_bytes"],
                value["transient_allocation_bytes"],
            )
    result["all_original_kernel_executions"] = (
        result["owner_ticks"]
        + result["original_journal_replay_steps"]
        + result["event_validation_kernel_steps"]
    )
    result["all_neural_cell_updates"] = (
        result["actual_snn_cell_updates"] + result["event_validation_snn_cell_updates"]
    )
    result["all_native_credit_finalizations"] = (
        result["account_validation_native_credit_calls"]
        + result["native_credit_finalizations"]
    )
    return result
