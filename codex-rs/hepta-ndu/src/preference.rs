use std::collections::BTreeMap;

use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::Generation;
use codex_hepta_types::Revision;
use codex_hepta_types::StableId;

use crate::AxisValue;
use crate::NduError;
use crate::SubjectClass;
use crate::mul_q32_ties_even;
use crate::protocol::NduIterationContextV1;
use crate::protocol::ndu_iteration_context_digest_v1;

const ETA_MIN_RAW: i64 = 1_i64 << 28;
const ETA_MAX_RAW: i64 = 1_i64 << 30;
const RESIDUAL_TOLERANCE_RAW: i64 = 1_i64 << 12;
const MAX_ITERATIONS: u32 = 64;
const MAX_PREFERENCE_DIMENSIONS: usize = 64;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PreferenceState {
    pub subject_id: StableId,
    pub subject_class: SubjectClass,
    pub revision: Revision,
    pub predecessor_digest: Digest32,
    pub values: Vec<AxisValue>,
    pub state_digest: Digest32,
}

/// Local deterministic solver step. This is not the canonical
/// `NduIterationReceiptV1` until bound through the protocol adapter with the
/// frozen objective, subject, event, coefficient and generation context.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NduSolverIterationReceipt {
    pub(crate) context_digest: Digest32,
    pub(crate) iteration: u32,
    pub(crate) predecessor_revision: Revision,
    pub(crate) next_revision: Revision,
    pub(crate) residual_raw: i64,
    pub(crate) projection_count: u32,
    pub(crate) state_digest: Digest32,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum SolveDisposition {
    Converged,
    IterationBoundReached,
}

/// Local solver termination evidence. It deliberately does not use the name
/// `NduConvergenceCertificateV1`, which is owned by `learning.eval` and also
/// requires independent stability, conservation and evaluator evidence.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NduSolverTerminationReceipt {
    pub context_digest: Digest32,
    pub disposition: SolveDisposition,
    pub iterations: u32,
    pub terminal_residual_raw: i64,
    pub maximum_residual_raw: i64,
    pub projection_count: u32,
    pub predecessor_digest: Digest32,
    pub terminal_state_digest: Digest32,
}

/// A bounded preference solve either yields an admitted converged state or
/// explicit unavailable evidence. Iteration exhaustion never returns a state
/// that a caller can accidentally persist as converged.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum PreferenceSolveOutcome {
    Converged {
        state: PreferenceState,
        termination: NduSolverTerminationReceipt,
        receipts: Vec<NduSolverIterationReceipt>,
    },
    Unavailable {
        termination: NduSolverTerminationReceipt,
        receipts: Vec<NduSolverIterationReceipt>,
    },
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct UpdateGeneration {
    pub generation: Generation,
    pub subject_class: SubjectClass,
    pub artifact_id: StableId,
    /// Canonical parent identity from the admitted subject hierarchy. None
    /// is valid for a root or when the parent is outside this staged batch.
    pub parent_artifact_id: Option<StableId>,
}

/// Rejects only actual parent/child updates in one generation. Different
/// hierarchy classes are allowed to share a generation when their admitted
/// lineage identities are unrelated.
pub fn validate_staged_updates(updates: &[UpdateGeneration]) -> Result<(), NduError> {
    let mut by_generation: BTreeMap<
        u64,
        BTreeMap<StableId, (SubjectClass, Option<StableId>)>,
    > = BTreeMap::new();

    for update in updates {
        let generation = update.generation.get();
        let inserted = by_generation.entry(generation).or_default().insert(
            update.artifact_id.clone(),
            (update.subject_class, update.parent_artifact_id.clone()),
        );
        if inserted.is_some() {
            return Err(NduError::DuplicateHierarchyArtifact(
                update.artifact_id.to_string(),
            ));
        }
    }

    for update in updates {
        let Some(parent_id) = &update.parent_artifact_id else {
            continue;
        };
        let Some(nodes) = by_generation.get(&update.generation.get()) else {
            continue;
        };
        let Some((parent_class, _)) = nodes.get(parent_id) else {
            continue;
        };
        if !is_direct_parent(*parent_class, update.subject_class) {
            return Err(NduError::InvalidHierarchyRelation {
                child: update.artifact_id.to_string(),
                parent: parent_id.to_string(),
            });
        }
        return Err(NduError::SimultaneousHierarchyUpdate(
            update.generation.get(),
        ));
    }
    Ok(())
}

const fn is_direct_parent(parent: SubjectClass, child: SubjectClass) -> bool {
    matches!(
        (parent, child),
        (SubjectClass::System, SubjectClass::Domain)
            | (SubjectClass::Domain, SubjectClass::Agent)
            | (SubjectClass::Agent, SubjectClass::Episode)
    )
}

/// Iterates a bounded damped preference update toward a deterministic target.
/// The previous state remains immutable and every step emits a new revision.
pub fn solve_preference_target(
    initial: PreferenceState,
    mut target: Vec<AxisValue>,
    eta: FixedQ32,
    context: &NduIterationContextV1,
) -> Result<PreferenceSolveOutcome, NduError> {
    if initial.subject_id != context.subject_id || initial.subject_class != context.subject_class {
        return Err(NduError::ProtocolContextMismatch);
    }
    let context_digest = ndu_iteration_context_digest_v1(context)?;
    if !(ETA_MIN_RAW..=ETA_MAX_RAW).contains(&eta.raw()) {
        return Err(NduError::InvalidEta);
    }
    normalize_values(&mut target)?;
    let mut state = initial;
    normalize_values(&mut state.values)?;
    if state
        .values
        .iter()
        .map(|value| &value.axis)
        .ne(target.iter().map(|value| &value.axis))
    {
        return Err(NduError::DimensionMismatch);
    }
    let expected_state_digest = digest_state(
        &state.subject_id,
        state.subject_class,
        state.revision,
        state.predecessor_digest,
        &state.values,
    );
    if expected_state_digest != state.state_digest {
        return Err(NduError::StateDigestMismatch);
    }

    let predecessor_digest = state.state_digest;
    let initial_residual_raw = maximum_residual_raw(&state.values, &target)?;
    if initial_residual_raw <= RESIDUAL_TOLERANCE_RAW {
        let termination = NduSolverTerminationReceipt {
            context_digest,
            disposition: SolveDisposition::Converged,
            iterations: 0,
            terminal_residual_raw: initial_residual_raw,
            maximum_residual_raw: initial_residual_raw,
            projection_count: 0,
            predecessor_digest,
            terminal_state_digest: state.state_digest,
        };
        return Ok(PreferenceSolveOutcome::Converged {
            state,
            termination,
            receipts: Vec::new(),
        });
    }

    let mut receipts = Vec::new();
    let mut total_projection_count = 0_u32;
    let mut maximum_residual_seen = 0_i64;

    for iteration in 1..=MAX_ITERATIONS {
        let (next, receipt) = update_once(&state, &target, eta, context_digest, iteration)?;
        let terminal_residual_raw = receipt.residual_raw;
        maximum_residual_seen = maximum_residual_seen.max(terminal_residual_raw);
        total_projection_count = total_projection_count
            .checked_add(receipt.projection_count)
            .ok_or(NduError::Arithmetic)?;
        let converged = receipt.residual_raw <= RESIDUAL_TOLERANCE_RAW;
        state = next;
        receipts.push(receipt);
        if converged {
            let termination = NduSolverTerminationReceipt {
                context_digest,
                disposition: SolveDisposition::Converged,
                iterations: iteration,
                terminal_residual_raw,
                maximum_residual_raw: maximum_residual_seen,
                projection_count: total_projection_count,
                predecessor_digest,
                terminal_state_digest: state.state_digest,
            };
            return Ok(PreferenceSolveOutcome::Converged {
                state,
                termination,
                receipts,
            });
        }
    }

    let terminal_residual_raw = receipts
        .last()
        .map_or(i64::MAX, |receipt| receipt.residual_raw);
    let termination = NduSolverTerminationReceipt {
        context_digest,
        disposition: SolveDisposition::IterationBoundReached,
        iterations: MAX_ITERATIONS,
        terminal_residual_raw,
        maximum_residual_raw: maximum_residual_seen,
        projection_count: total_projection_count,
        predecessor_digest,
        terminal_state_digest: state.state_digest,
    };
    Ok(PreferenceSolveOutcome::Unavailable {
        termination,
        receipts,
    })
}

fn maximum_residual_raw(current: &[AxisValue], target: &[AxisValue]) -> Result<i64, NduError> {
    let mut residual_raw = 0_i64;
    for (current, desired) in current.iter().zip(target) {
        let residual = desired
            .value
            .checked_sub(current.value)
            .map_err(|_| NduError::Arithmetic)?
            .raw()
            .checked_abs()
            .ok_or(NduError::Arithmetic)?;
        residual_raw = residual_raw.max(residual);
    }
    Ok(residual_raw)
}

fn update_once(
    state: &PreferenceState,
    target: &[AxisValue],
    eta: FixedQ32,
    context_digest: Digest32,
    iteration: u32,
) -> Result<(PreferenceState, NduSolverIterationReceipt), NduError> {
    let mut next_values = Vec::with_capacity(state.values.len());
    let mut residual_raw = 0_i64;
    let mut projection_count = 0_u32;
    for (current, desired) in state.values.iter().zip(target) {
        let delta = desired
            .value
            .checked_sub(current.value)
            .map_err(|_| NduError::Arithmetic)?;
        let step = mul_q32_ties_even(delta, eta)?;
        let raw_next = current
            .value
            .checked_add(step)
            .map_err(|_| NduError::Arithmetic)?;
        let projected = raw_next
            .clamp(FixedQ32::from_raw(-FixedQ32::ONE.raw()), FixedQ32::ONE)
            .map_err(|_| NduError::Arithmetic)?;
        if projected != raw_next {
            projection_count = projection_count
                .checked_add(1)
                .ok_or(NduError::Arithmetic)?;
        }
        let residual = desired
            .value
            .checked_sub(projected)
            .map_err(|_| NduError::Arithmetic)?
            .raw()
            .checked_abs()
            .ok_or(NduError::Arithmetic)?;
        residual_raw = residual_raw.max(residual);
        next_values.push(AxisValue {
            axis: current.axis.clone(),
            value: projected,
        });
    }
    let next_revision = state.revision.next().map_err(|_| NduError::Arithmetic)?;
    let state_digest = digest_state(
        &state.subject_id,
        state.subject_class,
        next_revision,
        state.state_digest,
        &next_values,
    );
    let next = PreferenceState {
        subject_id: state.subject_id.clone(),
        subject_class: state.subject_class,
        revision: next_revision,
        predecessor_digest: state.state_digest,
        values: next_values,
        state_digest,
    };
    let receipt = NduSolverIterationReceipt {
        context_digest,
        iteration,
        predecessor_revision: state.revision,
        next_revision,
        residual_raw,
        projection_count,
        state_digest,
    };
    Ok((next, receipt))
}

impl PreferenceState {
    pub fn genesis(
        subject_id: StableId,
        subject_class: SubjectClass,
        mut values: Vec<AxisValue>,
    ) -> Result<Self, NduError> {
        normalize_values(&mut values)?;
        let revision = Revision::new(/*value*/ 1).map_err(|_| NduError::Arithmetic)?;
        let state_digest = digest_state(
            &subject_id,
            subject_class,
            revision,
            Digest32::ZERO,
            &values,
        );
        Ok(Self {
            subject_id,
            subject_class,
            revision,
            predecessor_digest: Digest32::ZERO,
            values,
            state_digest,
        })
    }
}

fn normalize_values(values: &mut [AxisValue]) -> Result<(), NduError> {
    if values.len() > MAX_PREFERENCE_DIMENSIONS {
        return Err(NduError::DimensionLimitExceeded);
    }
    values.sort();
    for value in values.iter() {
        if !(-FixedQ32::ONE.raw()..=FixedQ32::ONE.raw()).contains(&value.value.raw()) {
            return Err(NduError::PreferenceValueOutOfRange(
                value.axis.to_string(),
            ));
        }
    }
    for window in values.windows(2) {
        if window[0].axis == window[1].axis {
            return Err(NduError::DuplicateAxis(window[0].axis.to_string()));
        }
    }
    Ok(())
}

fn digest_state(
    subject_id: &StableId,
    subject_class: SubjectClass,
    revision: Revision,
    predecessor_digest: Digest32,
    values: &[AxisValue],
) -> Digest32 {
    let mut bytes = Vec::new();
    push_id(&mut bytes, subject_id);
    bytes.push(subject_class.tag());
    bytes.extend_from_slice(&revision.get().to_be_bytes());
    bytes.extend_from_slice(predecessor_digest.as_array());
    for value in values {
        push_id(&mut bytes, &value.axis);
        bytes.extend_from_slice(&value.value.raw().to_be_bytes());
    }
    Digest32::of_bytes(&bytes)
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    let raw = value.as_str().as_bytes();
    bytes.extend_from_slice(&usize_to_u32(raw.len()).to_be_bytes());
    bytes.extend_from_slice(raw);
}

fn usize_to_u32(value: usize) -> u32 {
    u32::try_from(value).unwrap_or(u32::MAX)
}

#[cfg(test)]
#[path = "preference_tests.rs"]
mod tests;
