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
const PREFERENCE_STATE_DIGEST_DOMAIN: &[u8] = b"hepta.ndu.preference-state.v1";
const ITERATION_CONTEXT_DIGEST_DOMAIN: &[u8] = b"hepta.ndu.iteration-context.v1";
const SUBJECT_HIERARCHY_DIGEST_DOMAIN: &[u8] = b"hepta.ndu.subject-hierarchy.v1";

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NduIterationContextV1 {
    pub subject_id: StableId,
    pub subject_class: SubjectClass,
    pub objective_digest: Digest32,
    pub generation: Generation,
    pub event_digest: Digest32,
    pub coefficient_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PreferenceState {
    pub subject_id: StableId,
    pub subject_class: SubjectClass,
    pub revision: Revision,
    pub predecessor_digest: Digest32,
    pub values: Vec<AxisValue>,
    pub state_digest: Digest32,
}

/// Local deterministic solver step. Construction is private to the preference
/// solver so a caller cannot fabricate or re-contextualize provenance fields.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NduSolverIterationReceipt {
    context_digest: Digest32,
    iteration: u32,
    predecessor_revision: Revision,
    next_revision: Revision,
    residual_raw: i64,
    projection_count: u32,
    state_digest: Digest32,
}

impl NduSolverIterationReceipt {
    #[must_use]
    pub const fn context_digest(&self) -> Digest32 {
        self.context_digest
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
    pub context_digest: Digest32,
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
    pub artifact_id: StableId,
}

#[derive(Clone, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub struct SubjectHierarchyEdgeV1 {
    pub parent_subject_id: StableId,
    pub parent_subject_class: SubjectClass,
    pub child_subject_id: StableId,
    pub child_subject_class: SubjectClass,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SubjectHierarchyV1 {
    pub hierarchy_digest: Digest32,
    pub edges: Vec<SubjectHierarchyEdgeV1>,
}

/// Canonically binds the concrete subject graph used for staged-update checks.
pub fn canonical_subject_hierarchy_digest(
    edges: &[SubjectHierarchyEdgeV1],
) -> Result<Digest32, NduError> {
    let mut normalized = edges.to_vec();
    normalized.sort();
    let mut parents = BTreeMap::<StableId, StableId>::new();
    let mut classes = BTreeMap::<StableId, SubjectClass>::new();
    let mut seen_edges = BTreeSet::new();
    let mut bytes = Vec::new();
    bytes.extend_from_slice(SUBJECT_HIERARCHY_DIGEST_DOMAIN);
    bytes.extend_from_slice(&usize_to_u32(normalized.len()).to_be_bytes());
    for edge in &normalized {
        validate_hierarchy_edge(edge)?;
        if !seen_edges.insert(edge.clone()) {
            return Err(NduError::InvalidHierarchyRelation(
                "duplicate hierarchy edge".to_string(),
            ));
        }
        bind_subject_class(
            &mut classes,
            &edge.parent_subject_id,
            edge.parent_subject_class,
        )?;
        bind_subject_class(
            &mut classes,
            &edge.child_subject_id,
            edge.child_subject_class,
        )?;
        if let Some(existing) = parents.insert(
            edge.child_subject_id.clone(),
            edge.parent_subject_id.clone(),
        ) {
            if existing != edge.parent_subject_id {
                return Err(NduError::InvalidHierarchyRelation(
                    edge.child_subject_id.to_string(),
                ));
            }
        }
        push_id(&mut bytes, &edge.parent_subject_id);
        bytes.push(edge.parent_subject_class.tag());
        push_id(&mut bytes, &edge.child_subject_id);
        bytes.push(edge.child_subject_class.tag());
    }
    Ok(Digest32::of_bytes(&bytes))
}

/// Rejects only concrete parent/child updates that share one generation.
/// Unrelated subjects may advance in the same generation even when their
/// `SubjectClass` values differ.
pub fn validate_staged_updates(
    updates: &[UpdateGeneration],
    hierarchy: &SubjectHierarchyV1,
) -> Result<(), NduError> {
    if hierarchy.hierarchy_digest.is_zero() {
        return Err(NduError::EmptyProtocolDigest("subject_hierarchy"));
    }
    if canonical_subject_hierarchy_digest(&hierarchy.edges)? != hierarchy.hierarchy_digest {
        return Err(NduError::InvalidHierarchyRelation(
            "hierarchy digest mismatch".to_string(),
        ));
    }

    let mut parents = BTreeMap::<StableId, (&StableId, SubjectClass, SubjectClass)>::new();
    let mut declared_classes = BTreeMap::<StableId, SubjectClass>::new();
    for edge in &hierarchy.edges {
        bind_subject_class(
            &mut declared_classes,
            &edge.parent_subject_id,
            edge.parent_subject_class,
        )?;
        bind_subject_class(
            &mut declared_classes,
            &edge.child_subject_id,
            edge.child_subject_class,
        )?;
        parents.insert(
            edge.child_subject_id.clone(),
            (
                &edge.parent_subject_id,
                edge.parent_subject_class,
                edge.child_subject_class,
            ),
        );
    }

    let mut staged = BTreeMap::<(u64, StableId), &UpdateGeneration>::new();
    let mut artifact_subjects = BTreeMap::<StableId, StableId>::new();
    for update in updates {
        let key = (update.generation.get(), update.subject_id.clone());
        if staged.insert(key, update).is_some() {
            return Err(NduError::InvalidHierarchyRelation(format!(
                "duplicate staged subject {}",
                update.subject_id
            )));
        }
        if let Some(expected_class) = declared_classes.get(&update.subject_id) {
            if *expected_class != update.subject_class {
                return Err(NduError::InvalidHierarchyRelation(
                    update.subject_id.to_string(),
                ));
            }
        }
        if let Some(existing_subject) =
            artifact_subjects.insert(update.artifact_id.clone(), update.subject_id.clone())
        {
            if existing_subject != update.subject_id {
                return Err(NduError::InvalidHierarchyRelation(format!(
                    "artifact {} is staged for multiple subjects",
                    update.artifact_id
                )));
            }
        }
    }

    for update in updates {
        let Some((parent_id, _, _)) = parents.get(&update.subject_id) else {
            continue;
        };
        if staged.contains_key(&(update.generation.get(), (*parent_id).clone())) {
            return Err(NduError::SimultaneousHierarchyUpdate(
                update.generation.get(),
            ));
        }
    }
    Ok(())
}

/// Returns the canonical provenance digest that a local solver receipt must
/// carry before it can be published through the protocol adapter.
pub fn canonical_iteration_context_digest(
    context: &NduIterationContextV1,
) -> Result<Digest32, NduError> {
    require_digest(context.objective_digest, "objective")?;
    require_digest(context.event_digest, "event")?;
    require_digest(context.coefficient_digest, "coefficient")?;
    let mut bytes = Vec::new();
    bytes.extend_from_slice(ITERATION_CONTEXT_DIGEST_DOMAIN);
    push_id(&mut bytes, &context.subject_id);
    bytes.push(context.subject_class.tag());
    bytes.extend_from_slice(context.objective_digest.as_array());
    bytes.extend_from_slice(&context.generation.get().to_be_bytes());
    bytes.extend_from_slice(context.event_digest.as_array());
    bytes.extend_from_slice(context.coefficient_digest.as_array());
    Ok(Digest32::of_bytes(&bytes))
}

/// Iterates a bounded damped preference update toward a deterministic target.
/// The previous state remains immutable and every emitted step advances a new
/// revision. An already-converged state returns zero steps and no new revision.
/// Exhaustion is unavailable rather than a successful terminal state.
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
    validate_preference_values(&target)?;
    normalize_values(&mut target)?;
    let mut state = initial;
    validate_preference_values(&state.values)?;
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
    if context.subject_id != state.subject_id || context.subject_class != state.subject_class {
        return Err(NduError::ProtocolContextMismatch);
    }
    let context_digest = canonical_iteration_context_digest(context)?;
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
        return Ok((state, termination, Vec::new()));
    }

    let mut receipts = Vec::new();
    let mut total_projection_count = 0_u32;
    let mut maximum_residual_raw = initial_residual_raw;

    for iteration in 1..=MAX_ITERATIONS {
        let (next, receipt) = update_once(&state, &target, eta, iteration, context_digest)?;
        let terminal_residual_raw = receipt.residual_raw();
        maximum_residual_raw = maximum_residual_raw.max(terminal_residual_raw);
        total_projection_count = total_projection_count
            .checked_add(receipt.projection_count())
            .ok_or(NduError::Arithmetic)?;
        let converged = terminal_residual_raw <= RESIDUAL_TOLERANCE_RAW;
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
            return Ok((state, termination, receipts));
        }
    }

    Err(NduError::SolverUnavailable)
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
        validate_preference_values(&values)?;
        normalize_values(&mut values)?;
        let revision = Revision::new(1).map_err(|_| NduError::Arithmetic)?;
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

fn validate_preference_values(values: &[AxisValue]) -> Result<(), NduError> {
    if values.len() > MAX_PREFERENCE_DIMENSIONS {
        return Err(NduError::PreferenceDimensionLimitExceeded);
    }
    let minimum = FixedQ32::from_raw(-FixedQ32::ONE.raw());
    for value in values {
        if value.value < minimum || value.value > FixedQ32::ONE {
            return Err(NduError::PreferenceValueOutOfRange(value.axis.to_string()));
        }
    }
    Ok(())
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

fn bind_subject_class(
    classes: &mut BTreeMap<StableId, SubjectClass>,
    subject_id: &StableId,
    subject_class: SubjectClass,
) -> Result<(), NduError> {
    if let Some(existing) = classes.insert(subject_id.clone(), subject_class) {
        if existing != subject_class {
            return Err(NduError::InvalidHierarchyRelation(subject_id.to_string()));
        }
    }
    Ok(())
}

fn validate_hierarchy_edge(edge: &SubjectHierarchyEdgeV1) -> Result<(), NduError> {
    if edge.parent_subject_id == edge.child_subject_id
        || expected_parent_class(edge.child_subject_class) != Some(edge.parent_subject_class)
    {
        return Err(NduError::InvalidHierarchyRelation(
            edge.child_subject_id.to_string(),
        ));
    }
    Ok(())
}

const fn expected_parent_class(value: SubjectClass) -> Option<SubjectClass> {
    match value {
        SubjectClass::System => None,
        SubjectClass::Domain => Some(SubjectClass::System),
        SubjectClass::Agent => Some(SubjectClass::Domain),
        SubjectClass::Episode => Some(SubjectClass::Agent),
    }
}

fn digest_state(
    subject_id: &StableId,
    subject_class: SubjectClass,
    revision: Revision,
    predecessor_digest: Digest32,
    values: &[AxisValue],
) -> Digest32 {
    let mut bytes = Vec::new();
    bytes.extend_from_slice(PREFERENCE_STATE_DIGEST_DOMAIN);
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

fn require_digest(value: Digest32, field: &'static str) -> Result<(), NduError> {
    if value.is_zero() {
        return Err(NduError::EmptyProtocolDigest(field));
    }
    Ok(())
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
