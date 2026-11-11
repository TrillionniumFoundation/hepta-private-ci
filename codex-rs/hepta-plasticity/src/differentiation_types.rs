//! Frozen research policy for demand-driven specialization.
//!
//! Inputs are owner-supplied observations, not authenticated capabilities. A
//! digest binds content; neither a digest nor different role labels establishes
//! independent evaluation. Existing product evaluation and lifecycle owners
//! retain authentication, final holdout consumption and adoption.

use std::collections::BTreeMap;
use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

pub(super) const PPM: u64 = 1_000_000;
pub(super) const MAX_TASKS: usize = 4_096;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
#[repr(u8)]
pub enum DifferentiationDiagnosisV1 {
    NegativeTransfer = 0,
    CapacityShortfall = 1,
    RoutingConfusion = 2,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
#[repr(u8)]
pub enum DifferentiationTriggerV1 {
    PersistentTaskPartition = 0,
    PersistentError = 1,
}

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd)]
#[repr(u8)]
pub enum DifferentiationArmV1 {
    UnchangedParent = 0,
    ContinueParent = 1,
    ExpandedSingleModel = 2,
    FixedExperts = 3,
    RandomGrouping = 4,
    Candidate = 5,
}

pub(super) const ARMS: [DifferentiationArmV1; 6] = [
    DifferentiationArmV1::UnchangedParent,
    DifferentiationArmV1::ContinueParent,
    DifferentiationArmV1::ExpandedSingleModel,
    DifferentiationArmV1::FixedExperts,
    DifferentiationArmV1::RandomGrouping,
    DifferentiationArmV1::Candidate,
];

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DifferentiationParentV1 {
    pub artifact_digest: Digest32,
    pub topology_digest: Digest32,
    pub capability_digest: Digest32,
    pub state_schema_digest: Digest32,
    pub checkpoint_digest: Digest32,
    pub generation: Generation,
    pub namespace: StableId,
}

/// Host-provided identity observations. Collision checks do not verify signatures.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DifferentiationActorV1 {
    pub principal: StableId,
    pub signing_key_digest: Digest32,
    /// Credential identity/chain binding, not a shared trust anchor or CA root.
    pub credential_chain_digest: Digest32,
    pub controller_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DifferentiationActorsV1 {
    pub generator: DifferentiationActorV1,
    pub evaluator: DifferentiationActorV1,
    pub outcome_observer: DifferentiationActorV1,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DifferentiationDemandPolicyV1 {
    /// Half-open windows are exactly adjacent and begin after plan freeze.
    pub starts_at_ms: u64,
    pub window_width_ms: u64,
    pub required_windows: u16,
    pub minimum_tasks_per_window: u16,
    /// Positive for PersistentError; exactly zero for PersistentTaskPartition.
    pub minimum_error_ppm: u32,
    pub minimum_diagnosis_ppm: u32,
    pub diagnosis: DifferentiationDiagnosisV1,
    pub trigger: DifferentiationTriggerV1,
    pub measurement_protocol_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DifferentiationStudyPolicyV1 {
    pub opens_at_ms: u64,
    pub deadline_at_ms: u64,
    /// Common metering units and scope of all six cost categories.
    pub cost_profile_digest: Digest32,
    pub outcome_protocol_digest: Digest32,
    pub maximum_cost_per_arm: u64,
    pub maximum_total_study_cost: u64,
    /// Net score is summed new-task score minus this coefficient times cost.
    pub cost_penalty_ppm_per_unit: u32,
    pub minimum_net_gain_ppm_per_task: u32,
    pub maximum_retention_regression_ppm: u32,
    pub maximum_migration_regression_ppm: u32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DifferentiationRetentionPanelV1 {
    pub slice_id: StableId,
    pub task_ids: Vec<StableId>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DifferentiationPlanRequestV1 {
    pub study_id: StableId,
    pub module_id: StableId,
    pub partition_id: StableId,
    pub parent: DifferentiationParentV1,
    pub candidate_namespace: StableId,
    pub frozen_at_ms: u64,
    pub demand: DifferentiationDemandPolicyV1,
    pub study: DifferentiationStudyPolicyV1,
    /// All six protocols, including the unchanged-parent baseline.
    pub arm_protocols: BTreeMap<DifferentiationArmV1, Digest32>,
    pub new_task_ids: Vec<StableId>,
    pub retention_panels: Vec<DifferentiationRetentionPanelV1>,
    pub actors: DifferentiationActorsV1,
    pub compatibility_plan_digest: Digest32,
    pub migration_plan_digest: Digest32,
    pub rollback_plan_digest: Digest32,
}

/// Immutable in-memory preregistration. The host must establish actual chronology
/// and durable custody; a caller-supplied timestamp is not proof.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DifferentiationPlanV1 {
    pub(super) request: DifferentiationPlanRequestV1,
    pub(super) plan_digest: Digest32,
    pub(super) demand_ends_at_ms: u64,
}

impl DifferentiationPlanV1 {
    pub const fn digest(&self) -> Digest32 {
        self.plan_digest
    }

    pub const fn demand_ends_at_ms(&self) -> u64 {
        self.demand_ends_at_ms
    }

    /// Read-only access does not permit changing the frozen policy.
    pub fn specification(&self) -> &DifferentiationPlanRequestV1 {
        &self.request
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
#[repr(u8)]
pub enum DifferentiationHoldReasonV1 {
    InsufficientPersistentDemand = 0,
    PendingOutcomes = 1,
    BudgetExceeded = 2,
    RetentionRegression = 3,
    NoMeasuredNetGain = 4,
    MigrationUnverified = 5,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum DifferentiationConclusionV1 {
    Hold(DifferentiationHoldReasonV1),
    RecommendForOwnerReview,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum DifferentiationErrorV1 {
    InvalidPlan,
    Bounds,
    EmptyEvidence,
    SourceCollision,
    PlanBinding,
    ParentBinding,
    WindowSequence,
    DuplicateIdentity,
    DataLeakage,
    CandidateCompatibility,
    Chronology,
    MissingComparator,
    Observation,
    TopologyBinding,
    TopologyProposal(crate::TopologyProposalErrorV2),
    Arithmetic,
}

impl fmt::Display for DifferentiationErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for DifferentiationErrorV1 {}

pub(super) fn validate_actors(
    actors: &DifferentiationActorsV1,
) -> Result<(), DifferentiationErrorV1> {
    for actor in [
        &actors.generator,
        &actors.evaluator,
        &actors.outcome_observer,
    ] {
        require_digest(actor.signing_key_digest)?;
        require_digest(actor.credential_chain_digest)?;
        require_digest(actor.controller_digest)?;
    }
    for (left, right) in [
        (&actors.generator, &actors.evaluator),
        (&actors.generator, &actors.outcome_observer),
        (&actors.evaluator, &actors.outcome_observer),
    ] {
        if left.principal == right.principal
            || left.signing_key_digest == right.signing_key_digest
            || left.credential_chain_digest == right.credential_chain_digest
            || left.controller_digest == right.controller_digest
        {
            return Err(DifferentiationErrorV1::SourceCollision);
        }
    }
    Ok(())
}

pub(super) fn require_digest(digest: Digest32) -> Result<(), DifferentiationErrorV1> {
    if digest.is_zero() {
        Err(DifferentiationErrorV1::EmptyEvidence)
    } else {
        Ok(())
    }
}

/// Fixed-order, length-delimited encoding, without Debug or platform-width values.
pub(super) struct DigestTranscript(Vec<u8>);

impl DigestTranscript {
    pub(super) fn new(domain: &[u8]) -> Self {
        Self(domain.to_vec())
    }

    pub(super) fn number(&mut self, number: u64) {
        self.0.extend_from_slice(&number.to_be_bytes());
    }

    pub(super) fn id(&mut self, id: &StableId) {
        self.number(id.as_str().len() as u64);
        self.0.extend_from_slice(id.as_str().as_bytes());
    }

    pub(super) fn digest(&mut self, digest: Digest32) {
        self.0.extend_from_slice(digest.as_array());
    }

    pub(super) fn finish(self) -> Digest32 {
        Digest32::of_bytes(&self.0)
    }
}
