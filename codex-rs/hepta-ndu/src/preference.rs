use std::collections::BTreeMap;
use std::collections::BTreeSet;

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
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NduSolverIterationReceipt {
    pub iteration: u32,
    pub predecessor_revision: Revision,
    pub next_revision: Revision,
    pub residual_raw: i64,
    pub projection_count: u32,
    pub state_digest: Digest32,
    pub(crate) context_digest: Digest32,
}

impl NduSolverIterationReceipt {
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
    pub(crate) context_digest: Digest32,
}

impl NduSolverTerminationReceipt {
    #[must_use]
    pub const fn context_digest(&self) -> Digest32 {
        self.context_digest
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct UpdateGeneration {
    pub generation: Generation,
    pub subject_id: StableId,
    pub subject_class: SubjectClass,
    pub parent_subject_id: Option<StableId>,
    pub artifact_id: StableId,
}

/// Rejects only actual direct parent/child updates in one generation. Unrelated
/// subjects may advance concurrently even when their subject classes differ.
pub fn validate_staged_updates(updates: &[UpdateGeneration]) -> Result<(), NduError> {
    let mut generations: BTreeMap<u64, BTreeMap<StableId, &UpdateGeneration>> = BTreeMap::new();
    for update in updates {
        if update.parent_subject_id.as_ref() == Some(&update.subject_id) {
            return Err(NduError::HierarchySelfParent(update.subject_id.to_string()));
        }
        let subjects = generations.entry(update.generation.get()).or_default();
        if subjects.insert(update.subject_id.clone(), update).is_some() {
            return Err(NduError::DuplicateHierarchySubject(
                update.subject_id.to_string(),
            ));
        }
    }

    for (generation, subjects) in generations {
        for child in subjects.values() {
            let Some(parent_id) = child.parent_subject_id.as_ref() else {
                continue;
            };
            let Some(parent) = subjects.get(parent_id) else {
                continue;
            };
            if !is_direct_parent(parent.subject_class, child.subject_class) {
                return Err(NduError::InvalidHierarchyParent {
                    parent: parent.subject_id.to_string(),
                    child: child.subject_id.to_string(),
                });
            }
            return Err(NduError::SimultaneousHierarchyUpdate(generation));
        }
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

/// Compatibility/local-diagnostic entry point. Receipts from this function are
/// intentionally unbound (context digest is zero) and cannot be published by
/// the canonical protocol adapter. New protocol-capable callers use the
/// context-bound solver.
#[deprecated(
    note = "use solve_preference_target_with_context for publishable, fail-closed solver evidence"
)]
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

/// Runs the bounded preference solver with a precomputed canonical context
/// digest. Exhausting the 64-iteration budget is unavailable rather than a
/// successful state transition.
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
    let outcome = solve_preference_target_internal(initial, target, eta, context_digest)?;
    if outcome.1.disposition == SolveDisposition::IterationBoundReached {
        return Err(NduError::IterationBoundReached);
    }
    Ok(outcome)
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
    normalize_preference_values(&mut target)?;
    let mut state = initial;
    normalize_preference_values(&mut state.values)?;
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
    let initial_residual_raw = maximum_residual(&state.values, &target)?;
    if initial_residual_raw <= RESIDUAL_TOLERANCE_RAW {
        let termination = NduSolverTerminationReceipt {
            disposition: SolveDisposition::Converged,
            iterations: 0,
            terminal_residual_raw: initial_residual_raw,
            maximum_residual_raw: initial_residual_raw,
            projection_count: 0,
            predecessor_digest,
            terminal_state_digest: state.state_digest,
            context_digest,
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
                context_digest,
            };
            return Ok((state, termination, receipts));
        }
    }

    let terminal_residual_raw = receipts
        .last()
        .map_or(initial_residual_raw, |receipt| receipt.residual_raw);
    let termination = NduSolverTerminationReceipt {
        disposition: SolveDisposition::IterationBoundReached,
        iterations: MAX_ITERATIONS,
        terminal_residual_raw,
        maximum_residual_raw,
        projection_count: total_projection_count,
        predecessor_digest,
        terminal_state_digest: state.state_digest,
        context_digest,
    };
    Ok((state, termination, receipts))
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
        normalize_preference_values(&mut values)?;
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

fn normalize_preference_values(values: &mut [AxisValue]) -> Result<(), NduError> {
    if values.is_empty() || values.len() > MAX_PREFERENCE_DIMENSIONS {
        return Err(NduError::PreferenceDimensionLimitExceeded);
    }
    values.sort();
    for value in values.iter() {
        if value.value < FixedQ32::from_raw(-FixedQ32::ONE.raw())
            || value.value > FixedQ32::ONE
        {
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

fn maximum_residual(current: &[AxisValue], target: &[AxisValue]) -> Result<i64, NduError> {
    let mut maximum = 0_i64;
    for (current, target) in current.iter().zip(target) {
        let residual = target
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
