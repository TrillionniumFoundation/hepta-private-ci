//! Authority-free state projection for a DecisionCell split.
//!
//! This module only projects an already committed neuron checkpoint into
//! child state snapshots. It does not publish a journal record, change a
//! selected artifact, update a route, or issue any runtime authority. The
//! caller remains responsible for validating the parent config, writer
//! handoff, child artifacts and the final CAS publication.

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::CellSplitV1;
use codex_hepta_types::CellStateTransformKindV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

pub const MAX_CELL_SPLIT_CHILDREN_V1: usize = 64;

/// A deterministic partition of a parent cell's state vectors.
///
/// Temporal and activation dimensions are separate because the population
/// kernel has different widths for those vectors. The same child count is
/// used for both dimensions, while each dimension may have a different
/// partition. Every index must occur exactly once in its dimension.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellStateSplitPlanV1 {
    pub parent_cell_id: StableId,
    pub child_cell_ids: Vec<StableId>,
    pub child_scopes: Vec<Digest32>,
    pub parent_generation: Generation,
    pub candidate_generation: Generation,
    pub temporal_partitions: Vec<Vec<usize>>,
    pub activation_partitions: Vec<Vec<usize>>,
}

/// State projected for one child. This is a migration payload, not a
/// checkpoint and cannot be published by this module.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellStateSplitChildV1 {
    pub parent_cell_id: StableId,
    pub child_cell_id: StableId,
    pub child_scope: Digest32,
    pub parent_generation: Generation,
    pub candidate_generation: Generation,
    pub parent_checkpoint_digest: Digest32,
    pub parent_config_digest: Digest32,
    pub parent_scope: Digest32,
    pub objective_digest: Digest32,
    pub body_digest: Digest32,
    pub sequence: u64,
    pub temporal_q24: Vec<i64>,
    pub activation_q24: Vec<i64>,
    pub activity_q24: Vec<i64>,
    pub threshold_q24: Vec<i64>,
    pub eligibility_q24: Vec<i64>,
    pub state_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum CellStateSplitError {
    InvalidPlan(&'static str),
    InvalidParentDigest,
    InvalidParentContext(&'static str),
    ParentGenerationMismatch,
    CandidateGenerationMismatch,
    ChildIndexOutOfRange {
        dimension: &'static str,
        index: usize,
    },
    DimensionMismatch {
        dimension: &'static str,
        expected: usize,
        actual: usize,
    },
    InvalidCheckpoint,
    MappingDigestMismatch(&'static str),
}

impl fmt::Display for CellStateSplitError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for CellStateSplitError {}

impl CellStateSplitPlanV1 {
    pub fn new(
        parent_cell_id: StableId,
        child_cell_ids: Vec<StableId>,
        child_scopes: Vec<Digest32>,
        parent_generation: Generation,
        candidate_generation: Generation,
        temporal_partitions: Vec<Vec<usize>>,
        activation_partitions: Vec<Vec<usize>>,
    ) -> Result<Self, CellStateSplitError> {
        let plan = Self {
            parent_cell_id,
            child_cell_ids,
            child_scopes,
            parent_generation,
            candidate_generation,
            temporal_partitions,
            activation_partitions,
        };
        plan.validate_shape()?;
        Ok(plan)
    }

    /// Convenience constructor for kernels whose recurrent and activation
    /// vectors have the same width.
    pub fn shared_partition(
        parent_cell_id: StableId,
        child_cell_ids: Vec<StableId>,
        child_scopes: Vec<Digest32>,
        parent_generation: Generation,
        candidate_generation: Generation,
        partitions: Vec<Vec<usize>>,
    ) -> Result<Self, CellStateSplitError> {
        Self::new(
            parent_cell_id,
            child_cell_ids,
            child_scopes,
            parent_generation,
            candidate_generation,
            partitions.clone(),
            partitions,
        )
    }

    /// Binds the executable Q24 partition to the semantic CellSplit contract.
    /// The neuron kernel supports explicit partition transforms for recurrent
    /// and eligibility vectors and requires optimizer state to be reset by its
    /// external artifact owner; it never infers those policies from a digest.
    pub fn from_contract(
        contract: &CellSplitV1,
        temporal_partitions: Vec<Vec<usize>>,
        activation_partitions: Vec<Vec<usize>>,
    ) -> Result<Self, CellStateSplitError> {
        contract
            .validate()
            .map_err(|_| CellStateSplitError::InvalidPlan("invalid cell split contract"))?;
        if contract.state.recurrent.kind != CellStateTransformKindV1::Partition {
            return Err(CellStateSplitError::InvalidPlan(
                "recurrent transform is not partition",
            ));
        }
        if contract.state.eligibility.kind != CellStateTransformKindV1::Partition {
            return Err(CellStateSplitError::InvalidPlan(
                "eligibility transform is not partition",
            ));
        }
        if contract.state.optimizer.kind != CellStateTransformKindV1::Reset {
            return Err(CellStateSplitError::InvalidPlan(
                "optimizer transform is not reset",
            ));
        }
        if canonical_partition_digest_v1(b"temporal", &temporal_partitions)
            != contract.state.recurrent.mapping_digest
        {
            return Err(CellStateSplitError::MappingDigestMismatch("temporal"));
        }
        if canonical_partition_digest_v1(b"activation", &activation_partitions)
            != contract.state.eligibility.mapping_digest
        {
            return Err(CellStateSplitError::MappingDigestMismatch("activation"));
        }
        Self::new(
            contract.parent_cell_id.clone(),
            contract
                .children
                .iter()
                .map(|child| child.child_cell_id.clone())
                .collect(),
            contract
                .children
                .iter()
                .map(|child| child.child_scope_digest)
                .collect(),
            contract.predecessor_generation,
            contract.successor_generation,
            temporal_partitions,
            activation_partitions,
        )
    }

    pub fn child_count(&self) -> usize {
        self.child_cell_ids.len()
    }

    pub(crate) fn validate_shape(&self) -> Result<(), CellStateSplitError> {
        if self.parent_cell_id.as_str().is_empty() {
            return Err(CellStateSplitError::InvalidPlan("empty parent cell id"));
        }
        let count = self.child_cell_ids.len();
        if !(2..=MAX_CELL_SPLIT_CHILDREN_V1).contains(&count)
            || self.child_scopes.len() != count
            || self.temporal_partitions.len() != count
            || self.activation_partitions.len() != count
        {
            return Err(CellStateSplitError::InvalidPlan(
                "child arity or partition count",
            ));
        }
        if self.parent_generation.next().ok() != Some(self.candidate_generation) {
            return Err(CellStateSplitError::CandidateGenerationMismatch);
        }
        let mut ids = std::collections::BTreeSet::new();
        for id in &self.child_cell_ids {
            if id == &self.parent_cell_id || !ids.insert(id) {
                return Err(CellStateSplitError::InvalidPlan(
                    "duplicate or parent child id",
                ));
            }
        }
        let mut scopes = std::collections::BTreeSet::new();
        for scope in &self.child_scopes {
            if scope.is_zero() || !scopes.insert(scope) {
                return Err(CellStateSplitError::InvalidPlan(
                    "duplicate or empty child scope",
                ));
            }
        }
        Ok(())
    }

    pub(crate) fn validate_dimensions(
        &self,
        temporal_width: usize,
        activation_width: usize,
    ) -> Result<(), CellStateSplitError> {
        self.validate_shape()?;
        validate_partition("temporal", &self.temporal_partitions, temporal_width)?;
        validate_partition("activation", &self.activation_partitions, activation_width)?;
        Ok(())
    }
}

#[allow(clippy::too_many_arguments)]
pub(crate) fn build_child_state_v1(
    plan: &CellStateSplitPlanV1,
    child_index: usize,
    parent_checkpoint_digest: Digest32,
    parent_config_digest: Digest32,
    parent_scope: Digest32,
    objective_digest: Digest32,
    body_digest: Digest32,
    sequence: u64,
    temporal: &[i64],
    activation: &[i64],
    activity: &[i64],
    threshold: &[i64],
    eligibility: &[i64],
) -> Result<CellStateSplitChildV1, CellStateSplitError> {
    if parent_checkpoint_digest.is_zero() || parent_config_digest.is_zero() {
        return Err(CellStateSplitError::InvalidParentDigest);
    }
    for (name, digest) in [
        ("parent scope", parent_scope),
        ("objective", objective_digest),
        ("body", body_digest),
    ] {
        if digest.is_zero() {
            return Err(CellStateSplitError::InvalidParentContext(name));
        }
    }
    plan.validate_dimensions(temporal.len(), activation.len())?;
    if child_index >= plan.child_count() {
        return Err(CellStateSplitError::InvalidPlan("child index"));
    }
    if activity.len() != activation.len()
        || threshold.len() != activation.len()
        || eligibility.len() != activation.len()
    {
        return Err(CellStateSplitError::DimensionMismatch {
            dimension: "activation-state",
            expected: activation.len(),
            actual: activity.len().max(threshold.len()).max(eligibility.len()),
        });
    }

    let temporal_q24 = project("temporal", &plan.temporal_partitions[child_index], temporal)?;
    let activation_q24 = project(
        "activation",
        &plan.activation_partitions[child_index],
        activation,
    )?;
    let activity_q24 = project(
        "activity",
        &plan.activation_partitions[child_index],
        activity,
    )?;
    let threshold_q24 = project(
        "threshold",
        &plan.activation_partitions[child_index],
        threshold,
    )?;
    let eligibility_q24 = project(
        "eligibility",
        &plan.activation_partitions[child_index],
        eligibility,
    )?;
    let mut child = CellStateSplitChildV1 {
        parent_cell_id: plan.parent_cell_id.clone(),
        child_cell_id: plan.child_cell_ids[child_index].clone(),
        child_scope: plan.child_scopes[child_index],
        parent_generation: plan.parent_generation,
        candidate_generation: plan.candidate_generation,
        parent_checkpoint_digest,
        parent_config_digest,
        parent_scope,
        objective_digest,
        body_digest,
        sequence,
        temporal_q24,
        activation_q24,
        activity_q24,
        threshold_q24,
        eligibility_q24,
        state_digest: Digest32::ZERO,
    };
    child.state_digest = child_digest_v1(&child);
    Ok(child)
}

fn validate_partition(
    dimension: &'static str,
    partitions: &[Vec<usize>],
    width: usize,
) -> Result<(), CellStateSplitError> {
    if width == 0 || partitions.iter().any(Vec::is_empty) {
        return Err(CellStateSplitError::InvalidPlan("empty state dimension"));
    }
    let mut seen = vec![false; width];
    for partition in partitions {
        for &index in partition {
            if index >= width {
                return Err(CellStateSplitError::ChildIndexOutOfRange { dimension, index });
            }
            if std::mem::replace(&mut seen[index], true) {
                return Err(CellStateSplitError::InvalidPlan("overlapping partition"));
            }
        }
    }
    if seen.iter().any(|present| !present) {
        return Err(CellStateSplitError::InvalidPlan("incomplete partition"));
    }
    Ok(())
}

/// Canonical digest for a Q24 state-index partition used by the semantic
/// `CellSplitV1.state` mapping reference.
pub fn canonical_partition_digest_v1(domain: &[u8], partitions: &[Vec<usize>]) -> Digest32 {
    let mut bytes = b"hepta.neuron.cell-state-partition.q24.v1".to_vec();
    bytes.extend_from_slice(&(domain.len() as u64).to_be_bytes());
    bytes.extend_from_slice(domain);
    bytes.extend_from_slice(&(partitions.len() as u64).to_be_bytes());
    for partition in partitions {
        bytes.extend_from_slice(&(partition.len() as u64).to_be_bytes());
        for index in partition {
            bytes.extend_from_slice(&(*index as u64).to_be_bytes());
        }
    }
    Digest32::of_bytes(&bytes)
}

fn project(
    dimension: &'static str,
    indices: &[usize],
    values: &[i64],
) -> Result<Vec<i64>, CellStateSplitError> {
    indices
        .iter()
        .map(|&index| {
            values
                .get(index)
                .copied()
                .ok_or(CellStateSplitError::ChildIndexOutOfRange { dimension, index })
        })
        .collect()
}

fn child_digest_v1(child: &CellStateSplitChildV1) -> Digest32 {
    let mut bytes = b"hepta.neuron.cell-state-split-child.q24.v1".to_vec();
    bytes.extend_from_slice(child.parent_cell_id.as_str().as_bytes());
    bytes.push(0);
    bytes.extend_from_slice(child.child_cell_id.as_str().as_bytes());
    bytes.push(0);
    bytes.extend_from_slice(child.child_scope.as_array());
    for generation in [child.parent_generation, child.candidate_generation] {
        bytes.extend_from_slice(&generation.get().to_be_bytes());
    }
    for digest in [
        child.parent_checkpoint_digest,
        child.parent_config_digest,
        child.parent_scope,
        child.objective_digest,
        child.body_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    bytes.extend_from_slice(&child.sequence.to_be_bytes());
    for values in [
        &child.temporal_q24,
        &child.activation_q24,
        &child.activity_q24,
        &child.threshold_q24,
        &child.eligibility_q24,
    ] {
        bytes.extend_from_slice(&(values.len() as u64).to_be_bytes());
        for value in values {
            bytes.extend_from_slice(&value.to_be_bytes());
        }
    }
    Digest32::of_bytes(&bytes)
}

impl CellStateSplitChildV1 {
    pub fn digest(&self) -> Digest32 {
        self.state_digest
    }

    pub fn verify_digest(&self) -> bool {
        child_digest_v1(self) == self.state_digest
    }
}
