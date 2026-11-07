//! Separate semantic output from the full committed decision/cost audit record.

use codex_hepta_contracts::Sha256Digest;
use codex_hepta_neuron::CellDecisionReceiptV1;
use codex_hepta_types::AuthorityPosture;

use crate::CircuitCellErrorV1;
use crate::circuit_cell_binding::push_text;

/// Circuit successors consume these exact bytes through their frozen encoder.
/// This schema carries an advisory decision and never an effect capability.
pub fn circuit_cell_output_schema_v1() -> Sha256Digest {
    Sha256Digest::for_bytes(b"hepta.circuit.cell-policy-output.v1")
}

pub(super) fn encode_receipt(
    receipt: &CellDecisionReceiptV1,
) -> Result<Vec<u8>, CircuitCellErrorV1> {
    if receipt.authority != AuthorityPosture::DENY_ALL
        || receipt.policy.is_empty()
        || receipt.policy.len() > 256
    {
        return Err(CircuitCellErrorV1::InvalidReceipt);
    }
    let mut bytes = b"hepta.circuit.committed-cell-decision.v1\0".to_vec();
    for id in [
        &receipt.operation_id,
        &receipt.scope.agent_id,
        &receipt.scope.cell_id,
        &receipt.scope.run_id,
        &receipt.selected_candidate,
    ] {
        push_text(&mut bytes, id.as_str());
    }
    for digest in [
        receipt.operation_digest,
        receipt.semantic_request_digest,
        receipt.scope.principal_digest,
        receipt.bundle_digest,
        receipt.source_frontier,
        receipt.checkpoint_before,
        receipt.checkpoint_after,
        receipt.model_output_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    bytes.extend_from_slice(&receipt.confidence_ppm.to_be_bytes());
    bytes.extend_from_slice(&receipt.ood_ppm.to_be_bytes());
    bytes.push(u8::from(receipt.deadline_exceeded));
    let cost = &receipt.cost;
    for quantity in [
        cost.model_latency_micros,
        cost.queue_age_micros,
        cost.resident_bytes,
        cost.transient_allocation_bytes,
        cost.checkpoint_bytes,
        cost.consumed_input_bytes as u64,
        cost.truncated_input_bytes as u64,
    ] {
        bytes.extend_from_slice(&quantity.to_be_bytes());
    }
    bytes.extend_from_slice(&(receipt.policy.len() as u32).to_be_bytes());
    for entry in &receipt.policy {
        push_text(&mut bytes, entry.candidate_id.as_str());
        bytes.push(u8::from(entry.allowed));
        bytes.extend_from_slice(&entry.probability_ppm.to_be_bytes());
    }
    // The only admitted authority encoding is DENY_ALL.
    bytes.push(0);
    if bytes.len() > 65_536 {
        return Err(CircuitCellErrorV1::InvalidReceipt);
    }
    Ok(bytes)
}

/// Exclude operation IDs, checkpoints and cost from the semantic output so an
/// unchanged policy remains unchanged across feedback activations. The separate
/// completion receipt binds every omitted audit field to the same invocation.
pub(super) fn encode_output(
    receipt: &CellDecisionReceiptV1,
) -> Result<Vec<u8>, CircuitCellErrorV1> {
    if receipt.authority != AuthorityPosture::DENY_ALL
        || receipt.policy.is_empty()
        || receipt.policy.len() > 256
    {
        return Err(CircuitCellErrorV1::InvalidReceipt);
    }
    let mut bytes = b"hepta.circuit.cell-policy-output.v1\0".to_vec();
    bytes.extend_from_slice(receipt.scope.digest().as_array());
    bytes.extend_from_slice(receipt.bundle_digest.as_array());
    push_text(&mut bytes, receipt.selected_candidate.as_str());
    bytes.extend_from_slice(&receipt.confidence_ppm.to_be_bytes());
    bytes.extend_from_slice(&receipt.ood_ppm.to_be_bytes());
    bytes.push(u8::from(receipt.deadline_exceeded));
    bytes.extend_from_slice(&(receipt.policy.len() as u32).to_be_bytes());
    for entry in &receipt.policy {
        push_text(&mut bytes, entry.candidate_id.as_str());
        bytes.push(u8::from(entry.allowed));
        bytes.extend_from_slice(&entry.probability_ppm.to_be_bytes());
    }
    if bytes.len() > 65_536 {
        return Err(CircuitCellErrorV1::InvalidReceipt);
    }
    Ok(bytes)
}
