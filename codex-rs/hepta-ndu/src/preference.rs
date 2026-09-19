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
use crate::protocol::NduIterationContextV1;
use crate::protocol::canonical_iteration_context_digest;

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

/// Local deterministic solver step. The private context digest prevents an
/// external caller from fabricating a struct literal and binds every emitted
/// step to the frozen iteration context used when the solver ran.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NduSolverIterationReceipt {
    pub iteration: u32,
    pub predecessor_revision: Revision,
    pub next_revision: Revision,
    pub residual_raw: i64,
    pub projection_count: u32,
    pub state_digest: Digest32,
    context_digest: Digest32,
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

/// One proposed hierarchy-level artifact update. The subject relationship is
/// explicit so unrelated subjects may advance in one generation while an
/// actual parent/child pair remains staged across generations.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct UpdateGeneration {
    pub generation: Generation,
    pub subject_id: StableId,
    pub subject_class: SubjectClass,
    pub parent_subject_id: Option<StableId>,
    pub parent_subject_class: Option<SubjectClass>,
    pub artifact_id: StableId,
}

/// Rejects only actual parent/child hierarchy updates in one generation and
/// validates the declared system -> domain -> agent -> episode relationship.
pub fn validate_staged_updates(updates: &[UpdateGeneration]) -> Result<(), NduError> {
    let mut generations: BTreeMap<u64, Vec<&UpdateGeneration>> = BTreeMap::new();
    for update in updates {
        generations
            .entry(update.generation.get())
            .or_default()
            .push(update);
    }

    for (generation, generation_updates) in generations {
        let mut subjects = BTreeSet::new();
        let mut artifacts = BTreeSet::new();
        for update in &generation_updates {
            if !subjects.insert(update.subject_id.clone()) {
                return Err(NduError::DuplicateSubjectUpdate(
                    update.subject_id.to_string(),
                ));
            }
            if !artifacts.insert(update.artifact_id.clone()) {
                return Err(NduError::DuplicateArtifactUpdate(
                    update.artifact_id.to_string(),
                ));
            }
            validate_hierarchy_relation(update)?;
        }

        for child in &generation_updates {
            let Some(parent_id) = child.parent_subject_id.as_ref() else {
                continue;
            };
            if generation_updates
                .iter()
                .any(|candidate| &candidate.subject_id == parent_id)
            {
                return Err(NduError::SimultaneousHierarchyUpdate(generation));
            }
        }
    }
    Ok(())
}

fn validate_hierarchy_relation(update: &UpdateGeneration) -> Result<(), NduError> {
    let expected_parent_class = match update.subject_class {
        SubjectClass::System => None,
        SubjectClass::Domain => Some(SubjectClass::System),
        SubjectClass::Agent => Some(SubjectClass::Domain),
        SubjectClass::Episode => Some(SubjectClass::Agent),
    };
    let parent_id = update.parent_subject_id.as_ref();
    let declared_parent_class = update.parent_subject_class;
    let valid = match expected_parent_class {
        None => parent_id.is_none() && declared_parent_class.is_none(),
        Some(expected) => {
            parent_id.is_some()
                && declared_parent_class == Some(expected)
                && parent_id != Some(&update.subject_id)
        }
    };
    if valid {
        return Ok(());
    }
    Err(NduError::InvalidHierarchyRelation {
        subject: update.subject_id.to_string(),
        parent: parent_id.map_or_else(|| "<missing>".to_string(), ToString::to_string),
    })
}

/// Iterates a bounded damped preference update toward a deterministic target.
///
/// The solver validates the complete iteration context before creating any
/// receipt, binds its digest into every local step, preserves an already
/// converged state without manufacturing a revision, and fails unavailable
/// when the 64-iteration bound is exhausted.
pub fn solve_preference_target(
    initial: PreferenceState,
    mut target: Vec<AxisValue>,
    eta: FixedQ32,
    context: &NduIterationContextV1,
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
    validate_preference_values(&mut target)?;
    let mut state = initial;
    validate_preference_values(&mut state.values)?;
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
    if state.subject_id != context.subject_id || state.subject_class != context.subject_class {
        return Err(NduError::SolverContextMismatch);
    }
    let context_digest = canonical_iteration_context_digest(context)?;
    let predecessor_digest = state.state_digest;
    let initial_residual_raw = residual_between(&state.values, &target)?;
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

    Err(NduError::IterationBoundReached)
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
        validate_preference_values(&mut values)?;
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

fn validate_preference_values(values: &mut [AxisValue]) -> Result<(), NduError> {
    if !(1..=MAX_PREFERENCE_DIMENSIONS).contains(&values.len()) {
        return Err(NduError::PreferenceDimensionLimitExceeded);
    }
    values.sort();
    let minimum = FixedQ32::from_raw(-FixedQ32::ONE.raw());
    for value in values.iter() {
        if value.value < minimum || value.value > FixedQ32::ONE {
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
    for (left, right) in current.iter().zip(target) {
        let residual = right
            .value
            .checked_sub(left.value)
            .map_err(|_| NduError::Arithmetic)?
            .raw()
            .checked_abs()
            .ok_or(NduError::Arithmetic)?;
        residual_raw = residual_raw.max(residual);
    }
    Ok(residual_raw)
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
