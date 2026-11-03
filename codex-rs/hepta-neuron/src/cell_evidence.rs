use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use crate::CellHeadOutputV1;
use crate::CellHeadV1;
use crate::NeuronRuntimeOutputV1;

const PPM_LIMIT_V1: u32 = 1_000_000;

/// Evidence that binds one per-Cell head output to one authenticated local
/// runtime receipt and its calibrated/OOD/resource measurements.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellEvidenceV1 {
    pub cell_id: StableId,
    pub generation: Generation,
    pub encoder_digest: Digest32,
    pub head_digest: Digest32,
    pub action_digest: Digest32,
    pub value_q24: i64,
    pub uncertainty_q24: i64,
    pub runtime_receipt_digest: Digest32,
    pub model_runtime_binding_digest: Digest32,
    pub confidence_ppm: u32,
    pub ood_ppm: u32,
    pub abstain: bool,
    pub resource_receipt: crate::NeuronResourceReceiptV1,
    pub evidence_digest: Digest32,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum CellEvidenceError {
    EmptyDigest(&'static str),
    CellBindingMismatch,
    HeadBindingMismatch,
    AuthorityViolation,
    RuntimeReceiptInvalid,
    InvalidPpm,
}

impl fmt::Display for CellEvidenceError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for CellEvidenceError {}

/// Bind a deterministic CellHead output to a real NeuronRuntime output.
///
/// The runtime receipt is validated independently, and the already-produced
/// model binding digest is retained as evidence. The function grants no
/// authority and never mutates the runtime or Cell state.
pub fn bind_cell_evidence_v1(
    head: &CellHeadV1,
    output: &CellHeadOutputV1,
    runtime: &NeuronRuntimeOutputV1,
) -> Result<CellEvidenceV1, CellEvidenceError> {
    if &output.cell_id != head.cell_id() {
        return Err(CellEvidenceError::CellBindingMismatch);
    }
    if output.head_digest != head.head_digest() {
        return Err(CellEvidenceError::HeadBindingMismatch);
    }
    if output.action_digest.is_zero() {
        return Err(CellEvidenceError::EmptyDigest("action"));
    }
    if runtime.signal.model_runtime_digest.is_zero() {
        return Err(CellEvidenceError::EmptyDigest("model runtime binding"));
    }
    if runtime.signal.temporal_state_digest.is_zero() {
        return Err(CellEvidenceError::EmptyDigest("temporal state"));
    }
    if runtime.tick.checkpoint_after.is_zero() {
        return Err(CellEvidenceError::EmptyDigest("checkpoint"));
    }
    if runtime.signal.authority.grants_any() {
        return Err(CellEvidenceError::AuthorityViolation);
    }
    if runtime.tick.confidence_ppm > PPM_LIMIT_V1 || runtime.tick.ood_ppm > PPM_LIMIT_V1 {
        return Err(CellEvidenceError::InvalidPpm);
    }
    let runtime_receipt_digest = runtime
        .model_runtime
        .semantic_digest()
        .map_err(|_| CellEvidenceError::RuntimeReceiptInvalid)?;

    let evidence = CellEvidenceV1 {
        cell_id: output.cell_id.clone(),
        generation: head.generation(),
        encoder_digest: head.encoder_digest(),
        head_digest: output.head_digest,
        action_digest: output.action_digest,
        value_q24: output.value_q24,
        uncertainty_q24: output.uncertainty_q24,
        runtime_receipt_digest,
        model_runtime_binding_digest: runtime.signal.model_runtime_digest,
        confidence_ppm: runtime.tick.confidence_ppm,
        ood_ppm: runtime.tick.ood_ppm,
        abstain: output.abstain || runtime.tick.abstain || runtime.signal.abstain,
        resource_receipt: runtime.tick.resource_receipt.clone(),
        evidence_digest: Digest32::ZERO,
    };
    let evidence_digest = canonical_cell_evidence_digest_v1(&evidence, runtime);
    Ok(CellEvidenceV1 {
        evidence_digest,
        ..evidence
    })
}

/// Canonical digest for a Cell/runtime evidence binding.
pub fn canonical_cell_evidence_digest_v1(
    evidence: &CellEvidenceV1,
    runtime: &NeuronRuntimeOutputV1,
) -> Digest32 {
    let mut bytes = b"hepta.neuron.cell-evidence.v1".to_vec();
    push_id(&mut bytes, &evidence.cell_id);
    bytes.extend_from_slice(&evidence.generation.get().to_be_bytes());
    bytes.extend_from_slice(evidence.encoder_digest.as_array());
    bytes.extend_from_slice(evidence.head_digest.as_array());
    bytes.extend_from_slice(evidence.action_digest.as_array());
    bytes.extend_from_slice(&evidence.value_q24.to_be_bytes());
    bytes.extend_from_slice(&evidence.uncertainty_q24.to_be_bytes());
    bytes.extend_from_slice(evidence.runtime_receipt_digest.as_array());
    bytes.extend_from_slice(evidence.model_runtime_binding_digest.as_array());
    bytes.extend_from_slice(&evidence.confidence_ppm.to_be_bytes());
    bytes.extend_from_slice(&evidence.ood_ppm.to_be_bytes());
    bytes.push(u8::from(evidence.abstain));
    push_resource_receipt(&mut bytes, &evidence.resource_receipt);

    push_id(&mut bytes, &runtime.tick.tick_id);
    bytes.extend_from_slice(runtime.tick.checkpoint_before.as_array());
    bytes.extend_from_slice(runtime.tick.checkpoint_after.as_array());
    bytes.extend_from_slice(runtime.tick.activation_digest.as_array());
    bytes.extend_from_slice(&runtime.tick.sparsity_ppm.to_be_bytes());
    bytes.extend_from_slice(runtime.tick.threshold_digest.as_array());
    bytes.extend_from_slice(runtime.tick.eligibility_digest.as_array());
    bytes.extend_from_slice(&runtime.tick.prediction_error_q24.to_be_bytes());
    bytes.extend_from_slice(runtime.signal.temporal_state_digest.as_array());
    bytes.extend_from_slice(&runtime.signal.activation_sparsity_ppm.to_be_bytes());
    bytes.push(u8::from(runtime.signal.abstain));
    Digest32::of_bytes(&bytes)
}

fn push_resource_receipt(bytes: &mut Vec<u8>, receipt: &crate::NeuronResourceReceiptV1) {
    bytes.extend_from_slice(&receipt.execution_micros.to_be_bytes());
    bytes.extend_from_slice(&receipt.transient_allocation_bytes.to_be_bytes());
    bytes.extend_from_slice(&receipt.checkpoint_bytes.to_be_bytes());
    bytes.extend_from_slice(&receipt.journal_bytes_written.to_be_bytes());
    bytes.extend_from_slice(&receipt.write_amplification_ppm.to_be_bytes());
    bytes.extend_from_slice(&receipt.saturation_count.to_be_bytes());
    bytes.extend_from_slice(&receipt.queue_age_micros.to_be_bytes());
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    let raw = value.as_str().as_bytes();
    bytes.extend_from_slice(&(raw.len() as u64).to_be_bytes());
    bytes.extend_from_slice(raw);
}

#[cfg(test)]
#[path = "cell_evidence_tests.rs"]
mod tests;
