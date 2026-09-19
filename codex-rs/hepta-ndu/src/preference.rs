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

/// Local deterministic solver step. Construction is restricted to this module
/// so a caller cannot fabricate a receipt and later attach arbitrary protocol
/// context. Protocol publication additionally requires a matching nonzero
/// context digest.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NduSolverIterationReceipt {
    iteration: u32,
    predecessor_revision: Revision,
    next_revision: Revision,
    residual_raw: i64,
    projection_count: u32,
    state_digest: Digest32,
    context_digest: Digest32,
}

impl NduSolverIterationReceipt {
    #[must_use]
    pub const fn iteration(&self) -> u32 {
        self.iteration
    }

    #[must_use]
    pub const fn predecessor_revision(&self) -> Revision {
        self.predecessor_revision
    }

    #[must_use]
    pub const fn next_revision(&self) -> Revision {
        self.next_revision
    }

    #[must_use]
    pub const fn residual_raw(&self) -> i64 {
        self.residual_raw
    }

    #[must_use]
    pub const fn projection_count(&self) -> u32 {
        self.projection_count
    }

    #[must_use]
    pub const fn state_digest(&self) -> Digest32 {
        self.state_digest
    }

    #[must_use]
    pub const fn context_digest(&self) -> Digest32 {
        self.context_digest
    }
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
    pub disposition: SolveDisposition,
    pub iterations: u32,
    pub terminal_residual_raw: i64,
    pub maximum_residual_raw: i64,
    pub projection_count: u32,
    pub predecessor_digest: Digest32,
    pub terminal_state_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct HierarchyParentV1 {
    pub subject_id: StableId,
    pub subject_class: SubjectClass,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct UpdateGeneration {
    pub generation: Generation,
    pub subject_id: StableId,
    pub subject_class: SubjectClass,
    pub parent: Option<HierarchyParentV1>,
    pub artifact_id: StableId,
}

/// Validates explicit hierarchy lineage and rejects a direct parent and child
/// update in the same generation. Unrelated subjects at different hierarchy
/// levels are not rejected merely because their enum classes differ.
pub fn validate_staged_updates(updates: &[UpdateGeneration]) -> Result<(), NduError> {
    let mut by_generation_subject = BTreeMap::new();
    for update in updates {
        validate_parent_shape(update)?;
        let key = (update.generation.get(), update.subject_id.clone());
        if by_generation_subject
            .insert(key, update.subject_class)
            .is_some()
        {
            return Err(NduError::DuplicateHierarchySubjectUpdate(
                update.subject_id.to_string(),
            ));
        }
    }

    for update in updates {
        let Some(parent) = &update.parent else {
            continue;
        };
        let key = (update.generation.get(), parent.subject_id.clone());
        if let Some(observed_parent_class) = by_generation_subject.get(&key) {
            if *observed_parent_class != parent.subject_class {
                return Err(NduError::InvalidHierarchyLink(
                    update.subject_id.to_string(),
                ));
            }
            return Err(NduError::SimultaneousHierarchyUpdate(
                update.generation.get(),
            ));
        }
    }
    Ok(())
}

/// Iterates a bounded damped preference update toward a deterministic target.
///
/// This local entry point deliberately emits receipts with no protocol context.
/// Such receipts are valid local numerical evidence but cannot be published as
/// `NduIterationReceiptV1`. Use `solve_preference_target_with_context` when
/// protocol publication is required.
pub fn solve_preference_target(
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
    solve_preference_target_internal(initial, target, eta, Digest32::ZERO)
}

/// Runs the deterministic preference solver with an immutable protocol-context
/// digest. The digest must be the canonical digest of the exact
/// `NduIterationContextV1` later supplied to the protocol adapter.
pub fn solve_preference_target_with_context(
    initial: PreferenceState,
    target: Vec<AxisValue>,
    eta: FixedQ32,
    context_digest: Digest32,
) -> Result<
    (
        PreferenceState,
        NduSolverTerminationReceipt,
        Vec<NduSolverIterationReceipt>,
    ),
    NduError,
> {
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
) -> Result<
    (
        PreferenceState,
        NduSolverTerminationReceipt,
        Vec<NduSolverIterationReceipt>,
    ),
    NduError,
> {
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
    let initial_residual_raw = residual_raw(&state.values, &target)?;
    if initial_residual_raw <= RESIDUAL_TOLERANCE_RAW {
        let termination = NduSolverTerminationReceipt {
            disposition: SolveDisposition::Converged,
            iterations: 0,
            terminal_residual_raw: initial_residual_raw,
            maximum_residual_raw: initial_residual_raw,
            projection_count: 0,
            predecessor_digest,
            terminal_state_digest: state.state_digest,
        };
        return Ok((state, termination, Vec::new()));
    }

    let mut receipts = Vec::new();
    let mut total_projection_count = 0_u32;
    let mut maximum_residual_raw = initial_residual_raw;

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
                disposition: SolveDisposition::Converged,
                iterations: iteration,
                terminal_residual_raw,
                maximum_residual_raw,
                projection_count: total_projection_count,
                predecessor_digest,
                terminal_state_digest: state.state_digest,
            };
            return Ok((state, termination, receipts));
        }
    }

    let terminal_residual_raw = receipts
        .last()
        .map_or(i64::MAX, NduSolverIterationReceipt::residual_raw);
    Err(NduError::ConvergenceUnavailable(terminal_residual_raw))
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
        iteration,
        predecessor_revision: state.revision,
        next_revision,
        residual_raw,
        projection_count,
        state_digest,
        context_digest,
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

fn validate_parent_shape(update: &UpdateGeneration) -> Result<(), NduError> {
    let expected = match update.subject_class {
        SubjectClass::System => None,
        SubjectClass::Domain => Some(SubjectClass::System),
        SubjectClass::Agent => Some(SubjectClass::Domain),
        SubjectClass::Episode => Some(SubjectClass::Agent),
    };
    match (expected, &update.parent) {
        (None, None) => Ok(()),
        (Some(expected_class), Some(parent)) if parent.subject_class == expected_class => Ok(()),
        _ => Err(NduError::InvalidHierarchyLink(
            update.subject_id.to_string(),
        )),
    }
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

fn residual_raw(current: &[AxisValue], target: &[AxisValue]) -> Result<i64, NduError> {
    let mut residual = 0_i64;
    for (current, desired) in current.iter().zip(target) {
        let component = desired
            .value
            .checked_sub(current.value)
            .map_err(|_| NduError::Arithmetic)?
            .raw()
            .checked_abs()
            .ok_or(NduError::Arithmetic)?;
        residual = residual.max(component);
    }
    Ok(residual)
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
