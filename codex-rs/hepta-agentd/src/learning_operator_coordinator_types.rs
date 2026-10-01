//! Receipts and owner-port contracts for shadow-only coordination.

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum LearningOperatorShadowStageV1 {
    FreezeTraining,
    Derive,
    Fit,
    FreezeEvaluation,
    Evaluate,
    Select,
    Persist,
    FreshProcessLoad,
    Shadow,
    Revalidate,
    Rollback,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum LearningOperatorShadowRollbackTriggerV1 {
    ShadowCompleted,
    ShadowRejected,
    CandidateRevoked,
    CurrentnessMismatch,
    FreshProcessLoadMismatch,
    PersistDeadlineExceeded,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum LearningOperatorCurrentnessStateV1 {
    Current,
    Revoked,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum LearningOperatorSelectionReasonCodeV1 {
    IndependentFutureWindowSuperiority,
    SafetyEquivalentLowerResourceCost,
    IndependentlyVerifiedRollback,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AuditableLearningOperatorSelectionReasonV1 {
    pub code: LearningOperatorSelectionReasonCodeV1,
    pub policy_digest: Digest32,
    pub evidence_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct LearningOperatorShadowRequestV1 {
    pub run_id: StableId,
    pub owner_id: StableId,
    pub producer_id: StableId,
    pub objective_digest: Digest32,
    pub training_source_digest: Digest32,
    pub evaluation_source_digest: Digest32,
    pub predecessor_artifact_digest: Digest32,
    pub predecessor_generation: Generation,
    pub expected_authority_epoch: u64,
    pub expected_stop_epoch: u64,
    /// Trusted host time at coordinator admission.
    pub now_unix_micros: u64,
    /// Absolute host deadline shared by every stage receipt.
    pub deadline_unix_micros: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct FrozenOperatorDatasetV1 {
    pub receipt_id: StableId,
    pub owner_id: StableId,
    pub authority_epoch: u64,
    pub stop_epoch: u64,
    pub source_digest: Digest32,
    pub ledger_head_digest: Digest32,
    pub dataset_digest: Digest32,
    pub row_commitment_digest: Digest32,
    pub frozen_at: u64,
    pub expires_at: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DerivedOperatorTrainingInputV1 {
    pub training_receipt_id: StableId,
    pub dataset_digest: Digest32,
    pub row_commitment_digest: Digest32,
    pub input_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct FittedOperatorCandidateV1 {
    pub artifact_id: StableId,
    pub producer_id: StableId,
    pub generation: Generation,
    pub objective_digest: Digest32,
    pub training_receipt_id: StableId,
    pub dataset_digest: Digest32,
    pub row_commitment_digest: Digest32,
    pub artifact_digest: Digest32,
    pub payload_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct IndependentOperatorEvaluationV1 {
    pub evaluation_id: StableId,
    pub evaluator_id: StableId,
    pub dataset_receipt_id: StableId,
    pub dataset_digest: Digest32,
    pub candidate_artifact_digest: Digest32,
    pub evidence_digest: Digest32,
    pub trust_digest: Digest32,
    pub authority_epoch: u64,
    pub stop_epoch: u64,
    pub observed_at: u64,
    pub expires_at: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SelectedOperatorCandidateV1 {
    pub selection_id: StableId,
    pub selector_id: StableId,
    pub candidate_artifact_digest: Digest32,
    pub evaluation_evidence_digest: Digest32,
    pub selection_digest: Digest32,
    pub reason: AuditableLearningOperatorSelectionReasonV1,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PersistedOperatorCandidateV1 {
    pub artifact_digest: Digest32,
    pub payload_digest: Digest32,
    pub selection_digest: Digest32,
    pub storage_receipt_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct FreshProcessLoadedOperatorV1 {
    pub process_id: StableId,
    pub boot_nonce_digest: Digest32,
    pub artifact_digest: Digest32,
    pub payload_digest: Digest32,
    pub selection_digest: Digest32,
    pub storage_receipt_digest: Digest32,
    pub loaded_digest: Digest32,
    pub loaded_at: u64,
    pub expires_at: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct OperatorShadowReceiptV1 {
    pub process_id: StableId,
    pub loaded_digest: Digest32,
    pub artifact_digest: Digest32,
    pub selection_digest: Digest32,
    pub shadow_digest: Digest32,
    pub passed: bool,
    pub observation_count: u32,
    pub observed_at: u64,
    pub expires_at: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct OperatorCurrentnessReceiptV1 {
    pub artifact_digest: Digest32,
    pub selection_digest: Digest32,
    pub ledger_head_digest: Digest32,
    pub registry_head_digest: Digest32,
    pub authority_epoch: u64,
    pub stop_epoch: u64,
    pub state: LearningOperatorCurrentnessStateV1,
    pub observed_at: u64,
    pub expires_at: u64,
    pub currentness_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RolledBackOperatorCandidateV1 {
    pub failed_artifact_digest: Digest32,
    pub failed_selection_digest: Digest32,
    pub restored_artifact_digest: Digest32,
    pub restored_generation: Generation,
    pub rollback_digest: Digest32,
    pub owner_id: StableId,
    pub authority_epoch: u64,
    pub stop_epoch: u64,
    pub trigger: LearningOperatorShadowRollbackTriggerV1,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum LearningOperatorShadowTerminalV1 {
    QualifiedAndRolledBack(RolledBackOperatorCandidateV1),
    RevokedAndRolledBack(RolledBackOperatorCandidateV1),
    RejectedAndRolledBack(RolledBackOperatorCandidateV1),
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct LearningOperatorShadowOutcomeV1 {
    pub run_id: StableId,
    pub candidate_artifact_digest: Digest32,
    pub selection_digest: Digest32,
    pub shadow_digest: Option<Digest32>,
    pub currentness_digest: Option<Digest32>,
    pub terminal: LearningOperatorShadowTerminalV1,
    pub audit_digest: Digest32,
}

/// Owner adapters for one bounded shadow run.
///
/// Every effect must be durably idempotent under `(run_id, stage)` and reject a
/// conflicting request identity. This stateless coordinator never retries an
/// effect: owners must reconcile persistence and cleanup outcomes before a run
/// can be retried. Receipt event times are untrusted until checked against the
/// separately sampled trusted host clock. Synchronous calls cannot be preempted;
/// owners must enforce the absolute deadline while doing work.
pub trait LearningOperatorShadowPortsV1 {
    /// Sample trusted host time independently of any stage receipt. Adapters must
    /// not return the request admission time or a receipt-provided timestamp.
    fn now_unix_micros(&mut self) -> u64;

    fn freeze_training(
        &mut self,
        request: &LearningOperatorShadowRequestV1,
    ) -> Result<FrozenOperatorDatasetV1, String>;

    fn derive(
        &mut self,
        request: &LearningOperatorShadowRequestV1,
        training: &FrozenOperatorDatasetV1,
    ) -> Result<DerivedOperatorTrainingInputV1, String>;

    fn fit(
        &mut self,
        request: &LearningOperatorShadowRequestV1,
        input: &DerivedOperatorTrainingInputV1,
    ) -> Result<FittedOperatorCandidateV1, String>;

    fn freeze_evaluation(
        &mut self,
        request: &LearningOperatorShadowRequestV1,
        candidate: &FittedOperatorCandidateV1,
    ) -> Result<FrozenOperatorDatasetV1, String>;

    fn evaluate(
        &mut self,
        request: &LearningOperatorShadowRequestV1,
        candidate: &FittedOperatorCandidateV1,
        evaluation_dataset: &FrozenOperatorDatasetV1,
    ) -> Result<IndependentOperatorEvaluationV1, String>;

    fn select(
        &mut self,
        request: &LearningOperatorShadowRequestV1,
        candidate: &FittedOperatorCandidateV1,
        evaluation: &IndependentOperatorEvaluationV1,
    ) -> Result<SelectedOperatorCandidateV1, String>;

    fn persist(
        &mut self,
        request: &LearningOperatorShadowRequestV1,
        candidate: &FittedOperatorCandidateV1,
        selection: &SelectedOperatorCandidateV1,
    ) -> Result<PersistedOperatorCandidateV1, String>;

    fn fresh_process_load(
        &mut self,
        request: &LearningOperatorShadowRequestV1,
        persisted: &PersistedOperatorCandidateV1,
    ) -> Result<FreshProcessLoadedOperatorV1, String>;

    fn shadow(
        &mut self,
        request: &LearningOperatorShadowRequestV1,
        loaded: &FreshProcessLoadedOperatorV1,
    ) -> Result<OperatorShadowReceiptV1, String>;

    fn revalidate(
        &mut self,
        request: &LearningOperatorShadowRequestV1,
        candidate: &FittedOperatorCandidateV1,
        selection: &SelectedOperatorCandidateV1,
        shadow: &OperatorShadowReceiptV1,
    ) -> Result<OperatorCurrentnessReceiptV1, String>;

    fn rollback(
        &mut self,
        request: &LearningOperatorShadowRequestV1,
        candidate: &FittedOperatorCandidateV1,
        selection: &SelectedOperatorCandidateV1,
        persisted: &PersistedOperatorCandidateV1,
        trigger: LearningOperatorShadowRollbackTriggerV1,
    ) -> Result<RolledBackOperatorCandidateV1, String>;
}

/// Stable identity and owner-reported evidence retained for persistence recovery.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct LearningOperatorPersistenceRecoveryV1 {
    pub run_id: StableId,
    pub candidate_artifact_digest: Digest32,
    pub selection_digest: Digest32,
    pub reported: Option<PersistedOperatorCandidateV1>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum LearningOperatorShadowErrorV1 {
    InvalidRequest(&'static str),
    Port {
        stage: LearningOperatorShadowStageV1,
        message: String,
    },
    Invariant {
        stage: LearningOperatorShadowStageV1,
        message: &'static str,
    },
    /// The owner may have written a candidate, but no verified storage binding is
    /// available for safe loading or cleanup. Reconcile by this stable run and
    /// candidate identity; blindly restarting the coordinator is unsafe.
    PersistenceOutcomeUnknown {
        recovery: Box<LearningOperatorPersistenceRecoveryV1>,
        message: String,
    },
    /// Cleanup is not verified. The retained verified storage receipt identifies
    /// the selected object for owner reconciliation before any run is retried.
    RollbackFailed {
        trigger: LearningOperatorShadowRollbackTriggerV1,
        recovery: Box<LearningOperatorPersistenceRecoveryV1>,
        message: String,
    },
}

impl fmt::Display for LearningOperatorShadowErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::InvalidRequest(message) => {
                write!(formatter, "invalid shadow coordinator request: {message}")
            }
            Self::Port { stage, message } => {
                write!(
                    formatter,
                    "learning.operator shadow port failure at {stage:?}: {message}"
                )
            }
            Self::Invariant { stage, message } => {
                write!(
                    formatter,
                    "learning.operator shadow invariant at {stage:?}: {message}"
                )
            }
            Self::PersistenceOutcomeUnknown { recovery, message } => {
                write!(
                    formatter,
                    "learning.operator persistence outcome unknown for {}: {message}",
                    recovery.run_id
                )
            }
            Self::RollbackFailed {
                trigger, message, ..
            } => {
                write!(
                    formatter,
                    "learning.operator rollback failed after {trigger:?}: {message}"
                )
            }
        }
    }
}

impl StdError for LearningOperatorShadowErrorV1 {}
