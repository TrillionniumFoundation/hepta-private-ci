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
/// Fields are intentionally private so callers cannot fabricate canonical-
/// looking state-machine evidence without going through the solver.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NduSolverIterationReceipt {
    subject_id: StableId,
    subject_class: SubjectClass,
    iteration: u32,
    predecessor_revision: Revision,
    next_revision: Revision,
    residual_raw: i64,
    projection_count: u32,
    state_digest: Digest32,
}

impl NduSolverIterationReceipt {
    #[must_use]
    pub fn subject_id(&self) -> &StableId {
        &self.subject_id
    }

    #[must_use]
    pub const fn subject_class(&self) -> SubjectClass {
        self.subject_class
    }

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

    pub(crate) fn validate(&self) -> Result<(), NduError> {
        if !(1..=MAX_ITERATIONS).contains(&self.iteration) {
            return Err(NduError::InvalidSolverReceipt("iteration"));
        }
        let expected_next = self
            .predecessor_revision
            .next()
            .map_err(|_| NduError::InvalidSolverReceipt("predecessor revision"))?;
        if self.next_revision != expected_next {
            return Err(NduError::InvalidSolverReceipt("revision adjacency"));
        }
        if self.residual_raw < 0 {
            return Err(NduError::InvalidSolverReceipt("negative residual"));
        }
        if self.state_digest.is_zero() {
            return Err(NduError::InvalidSolverReceipt("state digest"));
        }
        Ok(())
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum SolveDisposition {
    Converged,
}

/// Local solver termination evidence. It deliberately does not use the name
/// `NduConvergenceCertificateV1`, which is owned by `learning.eval` and also
/// requires independent stability, conservation and evaluator evidence.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NduSolverTerminationReceipt {
    pub disposition: SolveDisposition,
    pub iterations: u32,
    pub terminal_residual_raw: i64,
    /// Maximum over the initial state and every post-update step.
    pub maximum_residual_raw: i64,
    pub projection_count: u32,
    pub predecessor_digest: Digest32,
    pub terminal_state_digest: Digest32,
}

/// One staged subject/artifact update. `parent_subject_id` is the concrete
/// immediate parent relation used to determine whether two updates conflict;
/// unrelated subjects can safely appear in the same validation batch.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct UpdateGeneration {
    pub generation: Generation,
    pub subject_id: StableId,
    pub parent_subject_id: Option<StableId>,
    pub subject_class: SubjectClass,
    pub artifact_id: StableId,
}

/// Rejects only explicit parent/child updates in one generation. Exact
/// duplicate updates are idempotent; selecting two different artifacts for the
/// same subject/generation is a conflict. Sibling and unrelated hierarchies are
/// not rejected merely because their subject classes differ.
pub fn validate_staged_updates(updates: &[UpdateGeneration]) -> Result<(), NduError> {
    let mut staged: BTreeMap<(u64, StableId), &UpdateGeneration> = BTreeMap::new();

    for update in updates {
        validate_parent_presence(update)?;
        let key = (update.generation.get(), update.subject_id.clone());
        if let Some(existing) = staged.get(&key) {
            if existing.subject_class != update.subject_class
                || existing.parent_subject_id != update.parent_subject_id
                || existing.artifact_id != update.artifact_id
            {
                return Err(NduError::ConflictingStagedArtifact {
                    generation: update.generation.get(),
                    subject: update.subject_id.to_string(),
                });
            }
            continue;
        }
        staged.insert(key, update);
    }

    for update in updates {
        let Some(parent_subject_id) = &update.parent_subject_id else {
            continue;
        };
        let parent_key = (update.generation.get(), parent_subject_id.clone());
        let Some(parent) = staged.get(&parent_key) else {
            continue;
        };
        let expected_parent = expected_parent_class(update.subject_class).ok_or_else(|| {
            NduError::InvalidHierarchyRelation {
                generation: update.generation.get(),
                child: update.subject_id.to_string(),
                parent: parent_subject_id.to_string(),
            }
        })?;
        if parent.subject_class != expected_parent {
            return Err(NduError::InvalidHierarchyRelation {
                generation: update.generation.get(),
                child: update.subject_id.to_string(),
                parent: parent_subject_id.to_string(),
            });
        }
        return Err(NduError::SimultaneousHierarchyUpdate(
            update.generation.get(),
        ));
    }
    Ok(())
}

fn validate_parent_presence(update: &UpdateGeneration) -> Result<(), NduError> {
    let valid = match update.subject_class {
        SubjectClass::System => update.parent_subject_id.is_none(),
        SubjectClass::Domain | SubjectClass::Agent | SubjectClass::Episode => {
            update.parent_subject_id.is_some()
        }
    };
    if !valid || update.parent_subject_id.as_ref() == Some(&update.subject_id) {
        return Err(NduError::InvalidHierarchyRelation {
            generation: update.generation.get(),
            child: update.subject_id.to_string(),
            parent: update
                .parent_subject_id
                .as_ref()
                .map_or_else(|| "<none>".to_string(), ToString::to_string),
        });
    }
    Ok(())
}

const fn expected_parent_class(child: SubjectClass) -> Option<SubjectClass> {
    match child {
        SubjectClass::System => None,
        SubjectClass::Domain => Some(SubjectClass::System),
        SubjectClass::Agent => Some(SubjectClass::Domain),
        SubjectClass::Episode => Some(SubjectClass::Agent),
    }
}

/// Iterates a bounded damped preference update toward a deterministic target.
/// The previous state remains immutable and every step emits a new revision.
/// Failure to converge within the registered 64-step bound is unavailable and
/// therefore returns `NduError::IterationExhausted`, never a successful terminal
/// state.
pub fn solve_preference_target(
    initial: PreferenceState,
    mut target: Vec<AxisValue>,
    eta: FixedQ32,
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
        };
        return Ok((state, termination, Vec::new()));
    }

    let mut receipts = Vec::new();
    let mut total_projection_count = 0_u32;
    let mut maximum_residual_raw = initial_residual_raw;

    for iteration in 1..=MAX_ITERATIONS {
        let (next, receipt) = update_once(&state, &target, eta, iteration)?;
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
        .map_or(i64::MAX, |receipt| receipt.residual_raw);
    Err(NduError::IterationExhausted {
        iterations: MAX_ITERATIONS,
        terminal_residual_raw,
    })
}

fn update_once(
    state: &PreferenceState,
    target: &[AxisValue],
    eta: FixedQ32,
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
        subject_id: state.subject_id.clone(),
        subject_class: state.subject_class,
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
    let lower = FixedQ32::from_raw(-FixedQ32::ONE.raw());
    for value in values.iter() {
        if value.value < lower || value.value > FixedQ32::ONE {
            return Err(NduError::PreferenceValueOutOfRange(value.axis.to_string()));
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
