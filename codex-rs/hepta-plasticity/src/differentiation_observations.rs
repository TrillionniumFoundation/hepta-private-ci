//! Owner-supplied research observations. Integer ppm scores cannot represent
//! NaN, and costs cannot silently omit a category. Source identity, measurement
//! truth and physical isolation still require verification by their real owners.

use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use crate::differentiation_types::DifferentiationActorsV1;
use crate::differentiation_types::DifferentiationArmV1;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
#[repr(u8)]
pub enum DifferentiationTaskStatusV1 {
    Completed = 0,
    Failed = 1,
    Pending = 2,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DifferentiationTaskObservationV1 {
    pub task_id: StableId,
    pub status: DifferentiationTaskStatusV1,
    pub score_ppm: u32,
    pub evidence_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DifferentiationCostReadingV1 {
    pub units: u64,
    /// Required even for measured zero or a justified non-applicable category.
    /// Each arm/category uses its own source record; a shared report must expose
    /// distinct bound readings instead of repeating the report's bare digest.
    pub evidence_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DifferentiationCostsV1 {
    pub training: DifferentiationCostReadingV1,
    pub evaluation: DifferentiationCostReadingV1,
    pub inference: DifferentiationCostReadingV1,
    pub routing: DifferentiationCostReadingV1,
    pub storage: DifferentiationCostReadingV1,
    pub migration: DifferentiationCostReadingV1,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DifferentiationCandidateV1 {
    pub parent_artifact_digest: Digest32,
    pub parent_generation: Generation,
    pub artifact_digest: Digest32,
    pub topology_digest: Digest32,
    pub generation: Generation,
    pub capability_digest: Digest32,
    pub state_schema_digest: Digest32,
    pub namespace: StableId,
    pub training_started_at_ms: u64,
    pub training_finished_at_ms: u64,
    pub training_task_ids: Vec<StableId>,
    pub training_evidence_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DifferentiationArmObservationV1 {
    pub arm: DifferentiationArmV1,
    pub protocol_digest: Digest32,
    pub parent_artifact_digest: Digest32,
    pub artifact_digest: Digest32,
    /// Every registered new and old task appears, including failed requests.
    pub outcomes: Vec<DifferentiationTaskObservationV1>,
    pub costs: DifferentiationCostsV1,
    pub evidence_digest: Digest32,
}

/// Isolated migration rehearsal. Writer/effect counts describe that rehearsal,
/// not a request to stop the serving parent or mutate the live topology.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DifferentiationMigrationObservationV1 {
    pub candidate_artifact_digest: Digest32,
    pub migration_plan_digest: Digest32,
    pub rollback_plan_digest: Digest32,
    pub predecessor_checkpoint_digest: Digest32,
    pub restored_checkpoint_digest: Digest32,
    pub remaining_predecessor_writers: u32,
    pub unresolved_effects: u32,
    pub replayed_external_effects: u32,
    pub outcomes: Vec<DifferentiationTaskObservationV1>,
    pub evidence_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DifferentiationStudyObservationV1 {
    pub plan_digest: Digest32,
    pub demand_digest: Digest32,
    pub cost_profile_digest: Digest32,
    pub outcome_protocol_digest: Digest32,
    pub actors: DifferentiationActorsV1,
    pub candidate: DifferentiationCandidateV1,
    pub started_at_ms: u64,
    pub finished_at_ms: u64,
    pub arms: Vec<DifferentiationArmObservationV1>,
    pub migration: DifferentiationMigrationObservationV1,
}
