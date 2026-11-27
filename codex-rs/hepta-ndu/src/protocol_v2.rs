//! Source-bound iteration evidence with an explicitly separate V2 contract.
//!
//! V1 remains the context-free solver and its existing publication adapter.
//! V2 records the context and numerical inputs supplied to an actual local
//! solver invocation. It does not authenticate the caller's claimed context,
//! grant authority, or establish independent convergence. A V1 receipt cannot
//! be promoted to V2 without performing a new source-bound solve.

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::Generation;
use codex_hepta_types::Revision;
use codex_hepta_types::StableId;

use crate::AxisValue;
use crate::NduError;
use crate::NduIterationContextV1;
use crate::NduSolverIterationReceipt;
use crate::NduSolverTerminationReceipt;
use crate::PreferenceState;
use crate::SubjectClass;
use crate::solve_preference_target;

// Bound the extra canonicalization allocation before the unchanged kernel
// validates every dimension, value, state digest and numerical parameter.
const MAX_SOURCE_BOUND_DIMENSIONS_V2: usize = 64;

/// A local step whose source was fixed before its solver invocation.
///
/// Construction is private and there is no conversion from a legacy step or
/// receipt. The exposed legacy step is an advisory view, not a way to attach
/// source evidence to an existing execution.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NduSourceBoundSolverIterationReceiptV2 {
    step: NduSolverIterationReceipt,
    source_context_digest: Digest32,
    solve_input_digest: Digest32,
}

impl NduSourceBoundSolverIterationReceiptV2 {
    #[must_use]
    pub const fn solver_step(&self) -> &NduSolverIterationReceipt {
        &self.step
    }

    #[must_use]
    pub const fn source_context_digest(&self) -> Digest32 {
        self.source_context_digest
    }

    #[must_use]
    pub const fn solve_input_digest(&self) -> Digest32 {
        self.solve_input_digest
    }

    fn validate_context(&self, context: &NduIterationContextV1) -> Result<(), NduError> {
        let expected_context = context_digest(context)?;
        self.step.validate()?;
        if self.step.subject_id() != &context.subject_id
            || self.step.subject_class() != context.subject_class
        {
            return Err(NduError::ProtocolSubjectMismatch);
        }
        if self.source_context_digest != expected_context {
            return Err(NduError::InvalidSolverReceipt("solve context mismatch"));
        }
        require_digest(self.solve_input_digest, "solve input")
    }
}

/// Iteration evidence using the V2 digest domain and an actual source-bound step.
///
/// Fields are private. This type has no V1 migration or deserialization path:
/// checking an old digest alone cannot recover an invocation's missing inputs.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NduIterationReceiptV2 {
    context: NduIterationContextV1,
    source: NduSourceBoundSolverIterationReceiptV2,
    receipt_digest: Digest32,
}

impl NduIterationReceiptV2 {
    #[must_use]
    pub fn subject_id(&self) -> &StableId {
        &self.context.subject_id
    }

    #[must_use]
    pub const fn subject_class(&self) -> SubjectClass {
        self.context.subject_class
    }

    #[must_use]
    pub const fn objective_digest(&self) -> Digest32 {
        self.context.objective_digest
    }

    #[must_use]
    pub const fn generation(&self) -> Generation {
        self.context.generation
    }

    #[must_use]
    pub const fn event_digest(&self) -> Digest32 {
        self.context.event_digest
    }

    #[must_use]
    pub const fn coefficient_digest(&self) -> Digest32 {
        self.context.coefficient_digest
    }

    #[must_use]
    pub const fn iteration(&self) -> u32 {
        self.source.step.iteration()
    }

    #[must_use]
    pub const fn predecessor_revision(&self) -> Revision {
        self.source.step.predecessor_revision()
    }

    #[must_use]
    pub const fn next_revision(&self) -> Revision {
        self.source.step.next_revision()
    }

    #[must_use]
    pub const fn residual_raw(&self) -> i64 {
        self.source.step.residual_raw()
    }

    #[must_use]
    pub const fn projection_count(&self) -> u32 {
        self.source.step.projection_count()
    }

    #[must_use]
    pub const fn state_digest(&self) -> Digest32 {
        self.source.step.state_digest()
    }

    #[must_use]
    pub const fn solve_input_digest(&self) -> Digest32 {
        self.source.solve_input_digest
    }

    #[must_use]
    pub const fn receipt_digest(&self) -> Digest32 {
        self.receipt_digest
    }

    #[must_use]
    pub const fn authority(&self) -> AuthorityPosture {
        AuthorityPosture::DENY_ALL
    }

    pub fn validate(&self) -> Result<(), NduError> {
        self.source.validate_context(&self.context)?;
        if self.receipt_digest != digest_receipt(&self.context, &self.source) {
            return Err(NduError::InvalidSolverReceipt("V2 receipt digest"));
        }
        Ok(())
    }
}

/// Freeze context and canonical input identity before running the unchanged
/// deterministic kernel. Errors and zero-step convergence emit no V2 steps.
pub fn solve_preference_target_with_context_v2(
    initial: PreferenceState,
    target: Vec<AxisValue>,
    eta: FixedQ32,
    context: &NduIterationContextV1,
) -> Result<
    (
        PreferenceState,
        NduSolverTerminationReceipt,
        Vec<NduSourceBoundSolverIterationReceiptV2>,
    ),
    NduError,
> {
    let source_context_digest = context_digest(context)?;
    if initial.subject_id != context.subject_id || initial.subject_class != context.subject_class {
        return Err(NduError::ProtocolSubjectMismatch);
    }
    if target.is_empty() || target.len() > MAX_SOURCE_BOUND_DIMENSIONS_V2 {
        return Err(NduError::PreferenceDimensionLimitExceeded);
    }
    let mut canonical_target = target.clone();
    canonical_target.sort();
    let target_count = u32::try_from(canonical_target.len())
        .map_err(|_| NduError::PreferenceDimensionLimitExceeded)?;
    let mut input = b"hepta.ndu.preference-solve-input.v1\0".to_vec();
    input.extend_from_slice(source_context_digest.as_array());
    input.extend_from_slice(initial.state_digest.as_array());
    input.extend_from_slice(&eta.raw().to_be_bytes());
    input.extend_from_slice(&target_count.to_be_bytes());
    for value in &canonical_target {
        push_id(&mut input, &value.axis);
        input.extend_from_slice(&value.value.raw().to_be_bytes());
    }
    let solve_input_digest = Digest32::of_bytes(&input);
    let (state, termination, steps) = solve_preference_target(initial, target, eta)?;
    let bound = steps
        .into_iter()
        .map(|step| NduSourceBoundSolverIterationReceiptV2 {
            step,
            source_context_digest,
            solve_input_digest,
        })
        .collect();
    Ok((state, termination, bound))
}

/// Publish only a step produced by the V2 invocation path, under its original
/// context. Neither a V1 receipt nor a context-free solver step is accepted.
pub fn bind_solver_iteration_receipt_v2(
    context: &NduIterationContextV1,
    receipt: &NduSourceBoundSolverIterationReceiptV2,
) -> Result<NduIterationReceiptV2, NduError> {
    receipt.validate_context(context)?;
    Ok(NduIterationReceiptV2 {
        context: context.clone(),
        source: receipt.clone(),
        receipt_digest: digest_receipt(context, receipt),
    })
}

fn require_digest(value: Digest32, field: &'static str) -> Result<(), NduError> {
    if value.is_zero() {
        return Err(NduError::EmptyProtocolDigest(field));
    }
    Ok(())
}

fn context_digest(context: &NduIterationContextV1) -> Result<Digest32, NduError> {
    require_digest(context.objective_digest, "objective")?;
    require_digest(context.event_digest, "event")?;
    require_digest(context.coefficient_digest, "coefficient")?;
    let mut bytes = b"hepta.ndu.solver-context.v1\0".to_vec();
    push_id(&mut bytes, &context.subject_id);
    bytes.push(context.subject_class.tag());
    bytes.extend_from_slice(context.objective_digest.as_array());
    bytes.extend_from_slice(&context.generation.get().to_be_bytes());
    bytes.extend_from_slice(context.event_digest.as_array());
    bytes.extend_from_slice(context.coefficient_digest.as_array());
    Ok(Digest32::of_bytes(&bytes))
}

fn digest_receipt(
    context: &NduIterationContextV1,
    receipt: &NduSourceBoundSolverIterationReceiptV2,
) -> Digest32 {
    let step = &receipt.step;
    let mut bytes = b"hepta.ndu.iteration-receipt.v2\0".to_vec();
    push_id(&mut bytes, &context.subject_id);
    bytes.push(context.subject_class.tag());
    bytes.extend_from_slice(context.objective_digest.as_array());
    bytes.extend_from_slice(&context.generation.get().to_be_bytes());
    bytes.extend_from_slice(context.event_digest.as_array());
    bytes.extend_from_slice(context.coefficient_digest.as_array());
    bytes.extend_from_slice(&step.iteration().to_be_bytes());
    bytes.extend_from_slice(&step.predecessor_revision().get().to_be_bytes());
    bytes.extend_from_slice(&step.next_revision().get().to_be_bytes());
    bytes.extend_from_slice(&step.residual_raw().to_be_bytes());
    bytes.extend_from_slice(&step.projection_count().to_be_bytes());
    bytes.extend_from_slice(step.state_digest().as_array());
    bytes.extend_from_slice(receipt.solve_input_digest.as_array());
    Digest32::of_bytes(&bytes)
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    let raw = value.as_str().as_bytes();
    let length = u32::try_from(raw.len()).unwrap_or(u32::MAX);
    bytes.extend_from_slice(&length.to_be_bytes());
    bytes.extend_from_slice(raw);
}

#[cfg(test)]
#[path = "protocol_v2_tests.rs"]
mod tests;
