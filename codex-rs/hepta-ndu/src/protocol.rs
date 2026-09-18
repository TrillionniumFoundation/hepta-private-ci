use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::Generation;
use codex_hepta_types::Revision;
use codex_hepta_types::StableId;

use crate::AxisValue;
use crate::NduError;
use crate::NduSolverIterationReceipt;
use crate::NduSolverTerminationReceipt;
use crate::PreferenceState;
use crate::SubjectClass;
use crate::preference::solve_preference_target_with_context_digest;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NduIterationContextV1 {
    pub subject_id: StableId,
    pub subject_class: SubjectClass,
    pub objective_digest: Digest32,
    pub generation: Generation,
    pub event_digest: Digest32,
    pub coefficient_digest: Digest32,
}

/// Returns the canonical context digest before binding an exact predecessor.
pub fn canonical_iteration_context_digest_v1(
    context: &NduIterationContextV1,
) -> Result<Digest32, NduError> {
    require_digest(context.objective_digest, "objective")?;
    require_digest(context.event_digest, "event")?;
    require_digest(context.coefficient_digest, "coefficient")?;

    let mut bytes = b"hepta.ndu.iteration-context.v1".to_vec();
    push_id(&mut bytes, &context.subject_id);
    bytes.push(context.subject_class.tag());
    bytes.extend_from_slice(context.objective_digest.as_array());
    bytes.extend_from_slice(&context.generation.get().to_be_bytes());
    bytes.extend_from_slice(context.event_digest.as_array());
    bytes.extend_from_slice(context.coefficient_digest.as_array());
    Ok(Digest32::of_bytes(&bytes))
}

fn bind_context_to_predecessor(
    context_digest: Digest32,
    predecessor_state_digest: Digest32,
) -> Result<Digest32, NduError> {
    require_digest(predecessor_state_digest, "predecessor state")?;
    let mut bytes = b"hepta.ndu.iteration-context-predecessor.v1".to_vec();
    bytes.extend_from_slice(context_digest.as_array());
    bytes.extend_from_slice(predecessor_state_digest.as_array());
    Ok(Digest32::of_bytes(&bytes))
}

/// Canonical protocol-producing solver path. The local solver remains usable
/// without runtime context, but only receipts created through this path bind
/// the frozen context and exact predecessor state.
pub fn solve_preference_target_for_context(
    context: &NduIterationContextV1,
    initial: PreferenceState,
    target: Vec<AxisValue>,
    eta: FixedQ32,
) -> Result<
    (
        PreferenceState,
        NduSolverTerminationReceipt,
        Vec<NduSolverIterationReceipt>,
    ),
    NduError,
> {
    if initial.subject_id != context.subject_id || initial.subject_class != context.subject_class {
        return Err(NduError::SolverContextMismatch);
    }
    let context_digest = canonical_iteration_context_digest_v1(context)?;
    let bound_context_digest = bind_context_to_predecessor(context_digest, initial.state_digest)?;
    solve_preference_target_with_context_digest(initial, target, eta, bound_context_digest)
}

/// Owner-local native representation of the canonical readiness protocol. It
/// cannot be constructed from an unbound local solver step and always carries
/// a deny-all authority posture.
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
    let context_digest = canonical_iteration_context_digest_v1(context)?;
    require_digest(receipt.state_digest(), "state")?;
    receipt.validate_integrity()?;

    let expected_bound_context =
        bind_context_to_predecessor(context_digest, receipt.solver_predecessor_digest())?;
    match receipt.context_digest() {
        None => return Err(NduError::SolverContextRequired),
        Some(bound) if bound != expected_bound_context => {
            return Err(NduError::SolverContextMismatch);
        }
        Some(_) => {}
    }

    let receipt_digest = digest_receipt(expected_bound_context, context, receipt);
    Ok(NduIterationReceiptV1 {
        subject_id: context.subject_id.clone(),
        subject_class: context.subject_class,
        objective_digest: context.objective_digest,
        generation: context.generation,
        event_digest: context.event_digest,
        coefficient_digest: context.coefficient_digest,
        iteration: receipt.iteration(),
        predecessor_revision: receipt.predecessor_revision(),
        next_revision: receipt.next_revision(),
        residual_raw: receipt.residual_raw(),
        projection_count: receipt.projection_count(),
        state_digest: receipt.state_digest(),
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
    bound_context_digest: Digest32,
    context: &NduIterationContextV1,
    receipt: &NduSolverIterationReceipt,
) -> Digest32 {
    let mut bytes = Vec::new();
    bytes.extend_from_slice(b"hepta.ndu.iteration-receipt.v2");
    bytes.extend_from_slice(bound_context_digest.as_array());
    push_id(&mut bytes, &context.subject_id);
    bytes.push(context.subject_class.tag());
    bytes.extend_from_slice(context.objective_digest.as_array());
    bytes.extend_from_slice(&context.generation.get().to_be_bytes());
    bytes.extend_from_slice(context.event_digest.as_array());
    bytes.extend_from_slice(context.coefficient_digest.as_array());
    bytes.extend_from_slice(receipt.solver_predecessor_digest().as_array());
    bytes.extend_from_slice(&receipt.iteration().to_be_bytes());
    bytes.extend_from_slice(&receipt.predecessor_revision().get().to_be_bytes());
    bytes.extend_from_slice(&receipt.next_revision().get().to_be_bytes());
    bytes.extend_from_slice(&receipt.residual_raw().to_be_bytes());
    bytes.extend_from_slice(&receipt.projection_count().to_be_bytes());
    bytes.extend_from_slice(receipt.state_digest().as_array());
    bytes.extend_from_slice(receipt.local_receipt_digest().as_array());
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
