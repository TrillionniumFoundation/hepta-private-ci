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

/// Local deterministic solver step. Fields are crate-visible so an external
/// caller cannot fabricate or rewrite evidence before protocol publication.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NduSolverIterationReceipt {
    pub(crate) iteration: u32,
    pub(crate) predecessor_revision: Revision,
    pub(crate) next_revision: Revision,
    pub(crate) residual_raw: i64,
    pub(crate) projection_count: u32,
    pub(crate) state_digest: Digest32,
    pub(crate) solver_predecessor_digest: Digest32,
    pub(crate) context_digest: Option<Digest32>,
    pub(crate) local_receipt_digest: Digest32,
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
    pub const fn solver_predecessor_digest(&self) -> Digest32 {
        self.solver_predecessor_digest
    }

    #[must_use]
    pub const fn context_digest(&self) -> Option<Digest32> {
        self.context_digest
    }

    #[must_use]
    pub const fn local_receipt_digest(&self) -> Digest32 {
        self.local_receipt_digest
    }

    pub(crate) fn validate_integrity(&self) -> Result<(), NduError> {
        let expected = digest_solver_receipt(
            self.context_digest,
            self.solver_predecessor_digest,
            self.iteration,
            self.predecessor_revision,
            self.next_revision,
            self.residual_raw,
            self.projection_count,
            self.state_digest,
        );
        if expected != self.local_receipt_digest {
            return Err(NduError::SolverReceiptIntegrityMismatch);
        }
        Ok(())
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum SolveDisposition {
    Converged,
    /// Retained for compatibility with previously stored owner-local evidence.
    /// The public solver now fails closed rather than returning this as success.
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
pub struct UpdateGeneration {
    pub generation: Generation,
    pub subject_id: StableId,
    pub subject_class: SubjectClass,
    pub parent_subject_id: Option<StableId>,
    pub parent_subject_class: Option<SubjectClass>,
    pub artifact_id: StableId,
}

/// Validates explicit hierarchy links and rejects a parent and its direct child
/// selecting new artifacts in the same generation. Unrelated subjects may
/// update in the same generation.
pub fn validate_staged_updates(updates: &[UpdateGeneration]) -> Result<(), NduError> {
    let mut by_subject: BTreeMap<(u64, StableId), &UpdateGeneration> = BTreeMap::new();
    let mut by_artifact: BTreeMap<(u64, StableId), StableId> = BTreeMap::new();

    for update in updates {
        validate_parent_shape(update)?;
        let subject_key = (update.generation.get(), update.subject_id.clone());
        if by_subject.insert(subject_key, update).is_some() {
            return Err(NduError::DuplicateHierarchyUpdate(
                update.subject_id.to_string(),
            ));
        }
        let artifact_key = (update.generation.get(), update.artifact_id.clone());
        if let Some(existing_subject) = by_artifact.insert(artifact_key, update.subject_id.clone())
            && existing_subject != update.subject_id
        {
            return Err(NduError::DuplicateHierarchyArtifact(
                update.artifact_id.to_string(),
            ));
        }
    }

    for update in updates {
        let (Some(parent_id), Some(parent_class)) =
            (&update.parent_subject_id, update.parent_subject_class)
        else {
            continue;
        };
        if let Some(parent) = by_subject.get(&(update.generation.get(), parent_id.clone())) {
            if parent.subject_class != parent_class {
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

fn validate_parent_shape(update: &UpdateGeneration) -> Result<(), NduError> {
    let expected = match update.subject_class {
        SubjectClass::System => None,
        SubjectClass::Domain => Some(SubjectClass::System),
        SubjectClass::Agent => Some(SubjectClass::Domain),
        SubjectClass::Episode => Some(SubjectClass::Agent),
    };
    match (expected, &update.parent_subject_id, update.parent_subject_class) {
        (None, None, None) => Ok(()),
        (Some(expected_class), Some(parent_id), Some(parent_class))
            if expected_class == parent_class && parent_id != &update.subject_id =>
        {
            Ok(())
        }
        _ => Err(NduError::InvalidHierarchyLink(
            update.subject_id.to_string(),
        )),
    }
}

/// Iterates a bounded damped preference update toward a deterministic target.
/// This local entry point intentionally produces receipts without runtime
/// context; such receipts cannot be published through the canonical protocol.
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
    solve_preference_target_inner(initial, target, eta, None)
}

pub(crate) fn solve_preference_target_with_context_digest(
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
        return Err(NduError::SolverContextRequired);
    }
    solve_preference_target_inner(initial, target, eta, Some(context_digest))
}

fn solve_preference_target_inner(
    initial: PreferenceState,
    mut target: Vec<AxisValue>,
    eta: FixedQ32,
    context_digest: Option<Digest32>,
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
    normalize_and_validate_values(&mut target)?;
    let mut state = initial;
    normalize_and_validate_values(&mut state.values)?;
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
        let (next, receipt) = update_once(
            &state,
            &target,
            eta,
            iteration,
            predecessor_digest,
            context_digest,
        )?;
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

    Err(NduError::PreferenceSolverUnavailable)
}

fn update_once(
    state: &PreferenceState,
    target: &[AxisValue],
    eta: FixedQ32,
    iteration: u32,
    solver_predecessor_digest: Digest32,
    context_digest: Option<Digest32>,
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
    let local_receipt_digest = digest_solver_receipt(
        context_digest,
        solver_predecessor_digest,
        iteration,
        state.revision,
        next_revision,
        residual_raw,
        projection_count,
        state_digest,
    );
    let receipt = NduSolverIterationReceipt {
        iteration,
        predecessor_revision: state.revision,
        next_revision,
        residual_raw,
        projection_count,
        state_digest,
        solver_predecessor_digest,
        context_digest,
        local_receipt_digest,
    };
    Ok((next, receipt))
}

impl PreferenceState {
    pub fn genesis(
        subject_id: StableId,
        subject_class: SubjectClass,
        mut values: Vec<AxisValue>,
    ) -> Result<Self, NduError> {
        normalize_and_validate_values(&mut values)?;
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

fn normalize_and_validate_values(values: &mut [AxisValue]) -> Result<(), NduError> {
    if values.is_empty() || values.len() > MAX_PREFERENCE_DIMENSIONS {
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

fn maximum_residual_raw(current: &[AxisValue], target: &[AxisValue]) -> Result<i64, NduError> {
    let mut result = 0_i64;
    for (left, right) in current.iter().zip(target) {
        let residual = right
            .value
            .checked_sub(left.value)
            .map_err(|_| NduError::Arithmetic)?
            .raw()
            .checked_abs()
            .ok_or(NduError::Arithmetic)?;
        result = result.max(residual);
    }
    Ok(result)
}

fn digest_state(
    subject_id: &StableId,
    subject_class: SubjectClass,
    revision: Revision,
    predecessor_digest: Digest32,
    values: &[AxisValue],
) -> Digest32 {
    let mut bytes = b"hepta.ndu.preference-state.v2".to_vec();
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

fn digest_solver_receipt(
    context_digest: Option<Digest32>,
    solver_predecessor_digest: Digest32,
    iteration: u32,
    predecessor_revision: Revision,
    next_revision: Revision,
    residual_raw: i64,
    projection_count: u32,
    state_digest: Digest32,
) -> Digest32 {
    let mut bytes = b"hepta.ndu.local-solver-receipt.v2".to_vec();
    match context_digest {
        Some(digest) => {
            bytes.push(1);
            bytes.extend_from_slice(digest.as_array());
        }
        None => bytes.push(0),
    }
    bytes.extend_from_slice(solver_predecessor_digest.as_array());
    bytes.extend_from_slice(&iteration.to_be_bytes());
    bytes.extend_from_slice(&predecessor_revision.get().to_be_bytes());
    bytes.extend_from_slice(&next_revision.get().to_be_bytes());
    bytes.extend_from_slice(&residual_raw.to_be_bytes());
    bytes.extend_from_slice(&projection_count.to_be_bytes());
    bytes.extend_from_slice(state_digest.as_array());
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
