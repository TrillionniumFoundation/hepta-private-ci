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
///
/// The struct is non-exhaustive so external crates can inspect but cannot forge
/// solver receipts with a struct literal.
#[non_exhaustive]
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NduSolverIterationReceipt {
    pub context_digest: Digest32,
    pub iteration: u32,
    pub predecessor_revision: Revision,
    pub next_revision: Revision,
    pub residual_raw: i64,
    pub projection_count: u32,
    pub state_digest: Digest32,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum SolveDisposition {
    Converged,
    UnavailableIterationBoundReached,
}

/// Local solver termination evidence. It deliberately does not use the name
/// `NduConvergenceCertificateV1`, which is owned by `learning.eval` and also
/// requires independent stability, conservation and evaluator evidence.
#[non_exhaustive]
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

/// A bounded solve never exposes an unconverged candidate state as publishable.
///
/// `Unavailable` retains numerical evidence but intentionally omits the terminal
/// candidate state. This prevents callers from accidentally treating iteration
/// exhaustion as a valid preference revision.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum PreferenceSolveResult {
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

impl PreferenceSolveResult {
    #[must_use]
    pub fn termination(&self) -> &NduSolverTerminationReceipt {
        match self {
            Self::Converged { termination, .. } | Self::Unavailable { termination, .. } => {
                termination
            }
        }
    }

    #[must_use]
    pub fn receipts(&self) -> &[NduSolverIterationReceipt] {
        match self {
            Self::Converged { receipts, .. } | Self::Unavailable { receipts, .. } => receipts,
        }
    }

    #[must_use]
    pub fn converged_state(&self) -> Option<&PreferenceState> {
        match self {
            Self::Converged { state, .. } => Some(state),
            Self::Unavailable { .. } => None,
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct UpdateGeneration {
    pub generation: Generation,
    pub subject_id: StableId,
    pub subject_class: SubjectClass,
    pub parent_subject_id: Option<StableId>,
    pub parent_subject_class: Option<SubjectClass>,
    pub artifact_id: StableId,
}

/// Rejects only actual direct parent/child updates in one generation.
///
/// Each update names its subject and direct parent. This avoids rejecting
/// unrelated subjects merely because they occupy different hierarchy levels.
pub fn validate_staged_updates(updates: &[UpdateGeneration]) -> Result<(), NduError> {
    let mut by_generation: BTreeMap<u64, Vec<&UpdateGeneration>> = BTreeMap::new();
    let mut selected_artifacts: BTreeMap<(u64, StableId), StableId> = BTreeMap::new();

    for update in updates {
        validate_hierarchy_shape(update)?;
        let key = (update.generation.get(), update.subject_id.clone());
        if let Some(existing) = selected_artifacts.insert(key, update.artifact_id.clone())
            && existing != update.artifact_id
        {
            return Err(NduError::ConflictingHierarchyArtifact {
                subject: update.subject_id.to_string(),
            });
        }
        by_generation
            .entry(update.generation.get())
            .or_default()
            .push(update);
    }

    for (generation, values) in by_generation {
        for (index, left) in values.iter().enumerate() {
            for right in values.iter().skip(index + 1) {
                if is_direct_parent_child(left, right) || is_direct_parent_child(right, left) {
                    return Err(NduError::SimultaneousHierarchyUpdate(generation));
                }
            }
        }
    }
    Ok(())
}

fn validate_hierarchy_shape(update: &UpdateGeneration) -> Result<(), NduError> {
    let expected_parent = expected_parent_class(update.subject_class);
    if update.parent_subject_id.as_ref() == Some(&update.subject_id) {
        return Err(NduError::InvalidHierarchyParent {
            subject: update.subject_id.to_string(),
        });
    }
    match (
        expected_parent,
        update.parent_subject_id.as_ref(),
        update.parent_subject_class,
    ) {
        (None, None, None) => Ok(()),
        (Some(expected), Some(_), Some(actual)) if actual == expected => Ok(()),
        _ => Err(NduError::InvalidHierarchyParent {
            subject: update.subject_id.to_string(),
        }),
    }
}

fn expected_parent_class(subject_class: SubjectClass) -> Option<SubjectClass> {
    match subject_class {
        SubjectClass::System => None,
        SubjectClass::Domain => Some(SubjectClass::System),
        SubjectClass::Agent => Some(SubjectClass::Domain),
        SubjectClass::Episode => Some(SubjectClass::Agent),
    }
}

fn is_direct_parent_child(parent: &UpdateGeneration, child: &UpdateGeneration) -> bool {
    child.parent_subject_id.as_ref() == Some(&parent.subject_id)
        && child.parent_subject_class == Some(parent.subject_class)
        && expected_parent_class(child.subject_class) == Some(parent.subject_class)
}

/// Iterates a bounded damped preference update toward a deterministic target.
///
/// This compatibility entry is owner-local and emits an unbound zero context
/// digest. Its receipts cannot be published through
/// `bind_solver_iteration_receipt_v1`. Protocol-producing callers must use
/// `solve_preference_target_with_context_digest`.
pub fn solve_preference_target(
    initial: PreferenceState,
    target: Vec<AxisValue>,
    eta: FixedQ32,
) -> Result<PreferenceSolveResult, NduError> {
    solve_preference_target_internal(initial, target, eta, Digest32::ZERO)
}

/// Runs the deterministic preference solver with a precomputed canonical
/// iteration-context digest. A nonzero digest is mandatory for protocol-bound
/// evidence and is copied into every local receipt.
pub fn solve_preference_target_with_context_digest(
    initial: PreferenceState,
    target: Vec<AxisValue>,
    eta: FixedQ32,
    context_digest: Digest32,
) -> Result<PreferenceSolveResult, NduError> {
    if context_digest.is_zero() {
        return Err(NduError::EmptyProtocolDigest("solver_context"));
    }
    solve_preference_target_internal(initial, target, eta, context_digest)
}

fn solve_preference_target_internal(
    initial: PreferenceState,
    mut target: Vec<AxisValue>,
    eta: FixedQ32,
    context_digest: Digest32,
) -> Result<PreferenceSolveResult, NduError> {
    if !(ETA_MIN_RAW..=ETA_MAX_RAW).contains(&eta.raw()) {
        return Err(NduError::InvalidEta);
    }
    normalize_values(&mut target)?;
    validate_preference_values(&target)?;
    let mut state = initial;
    normalize_values(&mut state.values)?;
    validate_preference_values(&state.values)?;
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
        return Ok(PreferenceSolveResult::Converged {
            state,
            termination,
            receipts: Vec::new(),
        });
    }

    let mut receipts = Vec::new();
    let mut total_projection_count = 0_u32;
    let mut maximum_residual_raw = 0_i64;

    for iteration in 1..=MAX_ITERATIONS {
        let (next, receipt) = update_once(&state, &target, eta, iteration, context_digest)?;
        let terminal_residual_raw = receipt.residual_raw;
        maximum_residual_raw = maximum_residual_raw.max(terminal_residual_raw);
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
                maximum_residual_raw,
                projection_count: total_projection_count,
                predecessor_digest,
                terminal_state_digest: state.state_digest,
            };
            return Ok(PreferenceSolveResult::Converged {
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
        disposition: SolveDisposition::UnavailableIterationBoundReached,
        iterations: MAX_ITERATIONS,
        terminal_residual_raw,
        maximum_residual_raw,
        projection_count: total_projection_count,
        predecessor_digest,
        terminal_state_digest: state.state_digest,
    };
    Ok(PreferenceSolveResult::Unavailable {
        termination,
        receipts,
    })
}

fn update_once(
    state: &PreferenceState,
    target: &[AxisValue],
    eta: FixedQ32,
    iteration: u32,
    context_digest: Digest32,
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
        validate_preference_values(&values)?;
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
    values.sort();
    for window in values.windows(2) {
        if window[0].axis == window[1].axis {
            return Err(NduError::DuplicateAxis(window[0].axis.to_string()));
        }
    }
    Ok(())
}

fn validate_preference_values(values: &[AxisValue]) -> Result<(), NduError> {
    if values.is_empty() || values.len() > MAX_PREFERENCE_DIMENSIONS {
        return Err(NduError::PreferenceDimensionLimitExceeded);
    }
    let lower = FixedQ32::from_raw(-FixedQ32::ONE.raw());
    for value in values {
        if value.value < lower || value.value > FixedQ32::ONE {
            return Err(NduError::PreferenceValueOutOfRange(
                value.axis.to_string(),
            ));
        }
    }
    Ok(())
}

fn maximum_residual_raw(current: &[AxisValue], target: &[AxisValue]) -> Result<i64, NduError> {
    let mut maximum = 0_i64;
    for (current, desired) in current.iter().zip(target) {
        let residual = desired
            .value
            .checked_sub(current.value)
            .map_err(|_| NduError::Arithmetic)?
            .raw()
            .checked_abs()
            .ok_or(NduError::Arithmetic)?;
        maximum = maximum.max(residual);
    }
    Ok(maximum)
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
