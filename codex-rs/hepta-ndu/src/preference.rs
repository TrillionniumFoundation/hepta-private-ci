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

#[derive(Clone, Debug, Eq, PartialEq)]
struct ReceiptSeal;

/// Local deterministic solver step. The private seal prevents external callers
/// from fabricating a receipt with arbitrary provenance fields.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NduSolverIterationReceipt {
    pub context_digest: Digest32,
    pub iteration: u32,
    pub predecessor_revision: Revision,
    pub next_revision: Revision,
    pub residual_raw: i64,
    pub projection_count: u32,
    pub state_digest: Digest32,
    _seal: ReceiptSeal,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum SolveDisposition {
    Converged,
    IterationBoundReached,
}

/// Local solver termination evidence. It is not an independent convergence
/// certificate. The private seal prevents external construction.
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
    _seal: ReceiptSeal,
}

/// Exhaustion is structurally distinct from convergence. The candidate state
/// reached at the iteration bound is evidence only and is intentionally not
/// returned as a selectable `PreferenceState`.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum PreferenceSolveOutcome {
    Converged {
        state: PreferenceState,
        termination: NduSolverTerminationReceipt,
        iteration_receipts: Vec<NduSolverIterationReceipt>,
    },
    Unavailable {
        predecessor: PreferenceState,
        termination: NduSolverTerminationReceipt,
        iteration_receipts: Vec<NduSolverIterationReceipt>,
    },
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

/// Rejects an actual parent and child update in one generation while permitting
/// unrelated subjects at different hierarchy levels to advance concurrently.
pub fn validate_staged_updates(updates: &[UpdateGeneration]) -> Result<(), NduError> {
    let mut subjects: BTreeMap<(u64, StableId), SubjectClass> = BTreeMap::new();

    for update in updates {
        validate_parent_reference(update)?;
        let key = (update.generation.get(), update.subject_id.clone());
        if subjects.insert(key, update.subject_class).is_some() {
            return Err(NduError::DuplicateHierarchySubject {
                generation: update.generation.get(),
                subject: update.subject_id.to_string(),
            });
        }
    }

    for update in updates {
        let Some(parent_id) = &update.parent_subject_id else {
            continue;
        };
        let Some(expected_parent_class) = expected_parent_class(update.subject_class) else {
            return Err(NduError::InvalidHierarchyParent(
                update.subject_id.to_string(),
            ));
        };
        if let Some(actual_parent_class) =
            subjects.get(&(update.generation.get(), parent_id.clone()))
        {
            if *actual_parent_class != expected_parent_class {
                return Err(NduError::InvalidHierarchyParent(
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

fn expected_parent_class(subject_class: SubjectClass) -> Option<SubjectClass> {
    match subject_class {
        SubjectClass::System => None,
        SubjectClass::Domain => Some(SubjectClass::System),
        SubjectClass::Agent => Some(SubjectClass::Domain),
        SubjectClass::Episode => Some(SubjectClass::Agent),
    }
}

fn validate_parent_reference(update: &UpdateGeneration) -> Result<(), NduError> {
    let expected = expected_parent_class(update.subject_class);
    match (
        expected,
        update.parent_subject_id.as_ref(),
        update.parent_subject_class,
    ) {
        (None, None, None) => Ok(()),
        (Some(expected_class), Some(parent_id), Some(actual_class))
            if actual_class == expected_class && parent_id != &update.subject_id =>
        {
            Ok(())
        }
        _ => Err(NduError::InvalidHierarchyParent(
            update.subject_id.to_string(),
        )),
    }
}

/// Iterates a bounded damped preference update toward a deterministic target.
/// A canonical, nonzero solver-context digest is required before any step can be
/// emitted. Already-converged input is a true no-op and does not advance revision.
pub fn solve_preference_target(
    initial: PreferenceState,
    mut target: Vec<AxisValue>,
    eta: FixedQ32,
    context_digest: Digest32,
) -> Result<PreferenceSolveOutcome, NduError> {
    if context_digest.is_zero() {
        return Err(NduError::EmptyProtocolDigest("solver_context"));
    }
    if !(ETA_MIN_RAW..=ETA_MAX_RAW).contains(&eta.raw()) {
        return Err(NduError::InvalidEta);
    }
    normalize_values(&mut target)?;
    let predecessor_state = initial.clone();
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
    let initial_residual_raw = residual_between(&state.values, &target)?;
    if initial_residual_raw <= RESIDUAL_TOLERANCE_RAW {
        return Ok(PreferenceSolveOutcome::Converged {
            termination: NduSolverTerminationReceipt {
                context_digest,
                disposition: SolveDisposition::Converged,
                iterations: 0,
                terminal_residual_raw: initial_residual_raw,
                maximum_residual_raw: initial_residual_raw,
                projection_count: 0,
                predecessor_digest,
                terminal_state_digest: state.state_digest,
                _seal: ReceiptSeal,
            },
            state,
            iteration_receipts: Vec::new(),
        });
    }

    let mut receipts = Vec::new();
    let mut total_projection_count = 0_u32;
    let mut maximum_residual_raw = 0_i64;

    for iteration in 1..=MAX_ITERATIONS {
        let (next, receipt) = update_once(&state, &target, eta, context_digest, iteration)?;
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
                _seal: ReceiptSeal,
            };
            return Ok(PreferenceSolveOutcome::Converged {
                state,
                termination,
                iteration_receipts: receipts,
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
        maximum_residual_raw,
        projection_count: total_projection_count,
        predecessor_digest,
        terminal_state_digest: state.state_digest,
        _seal: ReceiptSeal,
    };
    Ok(PreferenceSolveOutcome::Unavailable {
        predecessor: predecessor_state,
        termination,
        iteration_receipts: receipts,
    })
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
            .clamp(preference_minimum(), FixedQ32::ONE)
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
        _seal: ReceiptSeal,
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
    if values.is_empty() {
        return Err(NduError::EmptyPreferenceState);
    }
    if values.len() > MAX_PREFERENCE_DIMENSIONS {
        return Err(NduError::PreferenceDimensionLimitExceeded);
    }
    values.sort();
    for value in values.iter() {
        if value.value < preference_minimum() || value.value > FixedQ32::ONE {
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

fn residual_between(current: &[AxisValue], target: &[AxisValue]) -> Result<i64, NduError> {
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

fn preference_minimum() -> FixedQ32 {
    FixedQ32::from_raw(-FixedQ32::ONE.raw())
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
