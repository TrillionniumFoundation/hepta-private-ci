//! Unverified operator input for the existing fenced product evaluation owner.
//! These types carry materials and statements, never opaque qualification seals.
use std::path::PathBuf;

use codex_hepta_contracts::AgentId;
use codex_hepta_fleet::ReleaseId;
use serde::Deserialize;

use crate::CognitiveModelReadback;
use crate::cognitive_process_evaluation::*;
use crate::cognitive_process_evidence::*;
use crate::cognitive_process_product::*;
use crate::cognitive_process_product_wire::*;
use crate::cognitive_process_wire::{Digest, Id};

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct CognitiveQualificationInputV1 {
    pub(super) agent_id: AgentId,
    pub(super) operation_id: Id,
    pub(super) host: PinnedProductFileV1,
    pub(super) frozen_plan: CrossFoldPlanV1Raw,
    pub(super) metric_roles: Vec<MetricRoleContractV2Raw>,
    pub(super) metric_sources: Vec<ProductMetricSourceContractV1Raw>,
    pub(super) candidate_plan: TemporalEvaluationPlanRaw,
    pub(super) baseline_plan: TemporalEvaluationPlanRaw,
    pub(super) holdout_material: PinnedProductFileV1,
    pub(super) generator_plan: Option<SignedLearningEvidenceV1Raw>,
    pub(super) stage: CognitiveQualificationStageV1,
}

#[derive(Debug, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub(super) enum CognitiveQualificationStageV1 {
    PlanStatement,
    Reserve,
    ObserverStatement { collection: PinnedProductFileV1, reservation: CognitiveHoldoutReservationV1 },
    EvaluatorStatement {
        collection: PinnedProductFileV1,
        reservation: CognitiveHoldoutReservationV1,
        observer: SignedLearningEvidenceV1Raw,
    },
    Finalize {
        collection: PinnedProductFileV1,
        reservation: CognitiveHoldoutReservationV1,
        observer: SignedLearningEvidenceV1Raw,
        evaluator: SignedLearningEvidenceV1Raw,
        qualification_evidence_path: PathBuf,
    },
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct CognitiveHoldoutReservationV1 {
    pub sequence: u64,
    pub record_digest: Digest,
    pub use_digest: Digest,
}

/// Operator-pinned configuration outside every Agent-owned path. The command
/// line pins the entire request and this file's bytes; a daemon effect request
/// cannot select or replace this verifier, fence, or independent anchor.
#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct CognitiveQualificationHostV1 {
    pub schema_version: u32,
    pub agent_id: AgentId,
    pub source_release: ReleaseId,
    pub expected_predecessor: CognitiveModelReadback,
    pub policy: SelfEvolutionSelectionPolicyV1Raw,
    pub trust: LearningEvidenceTrustV1Raw,
    pub holdout: FencedHoldoutDescriptorV1,
    pub estimand_digest: Digest,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct CognitiveCollectedQualificationV1 {
    pub inputs: TemporalComparisonInputsV1Raw,
    pub context: ProductQualificationContextV1Raw,
    pub windows: Vec<ObservedFutureWindowV1Raw>,
}
