use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::Revision;
use codex_hepta_types::StableId;

use crate::NduError;
use crate::NduSolverIterationReceipt;
use crate::SubjectClass;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NduIterationContextV1 {
    pub subject_id: StableId,
    pub subject_class: SubjectClass,
    pub objective_digest: Digest32,
    pub generation: Generation,
    pub event_digest: Digest32,
    pub coefficient_digest: Digest32,
}

/// Owner-local native representation of the canonical readiness protocol. It
/// cannot be constructed from a local solver step without the complete frozen
/// context and always carries a deny-all authority posture.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NduIterationReceiptV1 {
    pub subject_id: StableId,
    pub subject_class: SubjectClass,
    pub objective_digest: Digest32,
    pub generation: Generation,
    pub event_digest: Digest32,
    pub coefficient_digest: Digest32,
    pub iteration: u32,
    pub predecessor_revision: Revision,
    pub next_revision: Revision,
    pub residual_raw: i64,
    pub projection_count: u32,
    pub state_digest: Digest32,
    pub receipt_digest: Digest32,
    pub authority: AuthorityPosture,
}

pub fn bind_solver_iteration_receipt_v1(
    context: &NduIterationContextV1,
    receipt: &NduSolverIterationReceipt,
) -> Result<NduIterationReceiptV1, NduError> {
    require_digest(context.objective_digest, "objective")?;
    require_digest(context.event_digest, "event")?;
    require_digest(context.coefficient_digest, "coefficient")?;
    require_digest(receipt.state_digest, "state")?;

    let receipt_digest = digest_receipt(context, receipt);
    Ok(NduIterationReceiptV1 {
        subject_id: context.subject_id.clone(),
        subject_class: context.subject_class,
        objective_digest: context.objective_digest,
        generation: context.generation,
        event_digest: context.event_digest,
        coefficient_digest: context.coefficient_digest,
        iteration: receipt.iteration,
        predecessor_revision: receipt.predecessor_revision,
        next_revision: receipt.next_revision,
        residual_raw: receipt.residual_raw,
        projection_count: receipt.projection_count,
        state_digest: receipt.state_digest,
        receipt_digest,
        authority: AuthorityPosture::DENY_ALL,
    })
}

fn require_digest(value: Digest32, field: &'static str) -> Result<(), NduError> {
    if value.is_zero() {
        return Err(NduError::EmptyProtocolDigest(field));
    }
    Ok(())
}

fn digest_receipt(
    context: &NduIterationContextV1,
    receipt: &NduSolverIterationReceipt,
) -> Digest32 {
    let mut bytes = Vec::new();
    bytes.extend_from_slice(b"hepta.ndu.iteration-receipt.v1");
    push_id(&mut bytes, &context.subject_id);
    bytes.push(context.subject_class.tag());
    bytes.extend_from_slice(context.objective_digest.as_array());
    bytes.extend_from_slice(&context.generation.get().to_be_bytes());
    bytes.extend_from_slice(context.event_digest.as_array());
    bytes.extend_from_slice(context.coefficient_digest.as_array());
    bytes.extend_from_slice(&receipt.iteration.to_be_bytes());
    bytes.extend_from_slice(&receipt.predecessor_revision.get().to_be_bytes());
    bytes.extend_from_slice(&receipt.next_revision.get().to_be_bytes());
    bytes.extend_from_slice(&receipt.residual_raw.to_be_bytes());
    bytes.extend_from_slice(&receipt.projection_count.to_be_bytes());
    bytes.extend_from_slice(receipt.state_digest.as_array());
    Digest32::of_bytes(&bytes)
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    let raw = value.as_str().as_bytes();
    let length = u32::try_from(raw.len()).unwrap_or(u32::MAX);
    bytes.extend_from_slice(&length.to_be_bytes());
    bytes.extend_from_slice(raw);
}

#[cfg(test)]
#[path = "protocol_tests.rs"]
mod tests;
