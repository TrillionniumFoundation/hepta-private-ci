//! Typed finite-cycle outcomes and retained evidence; no execution authority.

use std::error::Error;
use std::fmt;

use codex_hepta_intelligence_eval::ProductEvaluationError;
use codex_hepta_learning_ledger::SignedEvidenceError;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::CandidateEvaluationAdmissionV1;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum LearningCycleDispositionV1 {
    Adoptable,
    NoUpdate,
    Inconclusive,
    Failed,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum LearningStopV1 {
    FiniteSearchComplete,
    NoQualifiedData,
    BudgetStopped,
    EvidenceIncomplete,
    ExecutionFailed,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum LearningAttemptPhaseV1 {
    Training,
    Search,
    Evaluation,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum LearningAttemptStatusV1 {
    Succeeded,
    Failed,
    Stopped,
    Unresolved,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct LearningDecisionPlanV1 {
    pub cycle_id: StableId,
    pub incumbent_id: StableId,
    pub incumbent_model_digest: Digest32,
    pub protocol_digest: Digest32,
    pub objective_digest: Digest32,
    pub dataset_digest: Digest32,
    pub search_space_digest: Digest32,
    /// Pinned normalization and allocation of physical/research costs.
    pub cost_profile_digest: Digest32,
    pub maximum_candidates: u32,
    pub maximum_attempts: u32,
    pub maximum_cost_units: u64,
    pub next_attempt_reservation_units: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct LearningCandidateResultV1 {
    pub candidate_id: StableId,
    pub model_digest: Digest32,
    /// Missing evaluation is evidence insufficiency, except an explicit budget
    /// stop. Any present evaluation is revalidated, including rejected ones.
    pub evaluation: Option<CandidateEvaluationAdmissionV1>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct LearningAttemptV1 {
    /// Canonical monotonic owner-journal ID; its original native receipt remains
    /// pinned below. Lexical order must preserve the retry predecessor order.
    pub attempt_id: StableId,
    /// Explicit native retry lineage; an unrelated earlier success cannot erase
    /// a later failure. Unresolved attempts cannot be retried through this path.
    pub retry_of: Option<StableId>,
    /// None identifies shared work and is charged exactly once.
    pub candidate_id: Option<StableId>,
    pub phase: LearningAttemptPhaseV1,
    pub status: LearningAttemptStatusV1,
    /// Disjoint encoder/shared/decoder/critic/planning/codec/failure/retry/sync
    /// costs in the pinned profile's unit. None is unknown, never measured zero.
    pub cost_units: [Option<u64>; 9],
    pub owner_receipt_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct LearningDecisionInputV1 {
    pub plan: LearningDecisionPlanV1,
    pub stop: LearningStopV1,
    pub terminal_evidence_digest: Digest32,
    pub data_eligibility_evidence_digest: Digest32,
    /// Strictly ordered complete inventories, including failures and retries.
    pub candidates: Vec<LearningCandidateResultV1>,
    pub attempts: Vec<LearningAttemptV1>,
}

/// Supplied from host-owned retained plan and drained native inventories, never
/// accepted as authority merely because a submitting actor computed these hashes.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct LearningDecisionPinsV1 {
    pub plan_digest: Digest32,
    pub candidate_inventory_digest: Digest32,
    pub attempt_inventory_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct LearningDecisionAttestationsV1 {
    pub generator: SignedLearningEvidenceV1,
    pub observer: SignedLearningEvidenceV1,
    pub evaluator: SignedLearningEvidenceV1,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct LearningDecisionSummaryV1 {
    pub decision: LearningCycleDispositionV1,
    pub no_update_reason: Option<LearningStopV1>,
    pub eligible_candidate_ids: Vec<StableId>,
    pub retained_incumbent_id: StableId,
    pub retained_incumbent_model_digest: Digest32,
    pub known_cost_units: u128,
    pub unknown_cost_fields: usize,
    pub failed_attempts: usize,
    pub unresolved_attempts: usize,
    pub pins: LearningDecisionPinsV1,
    pub receipt_digest: Digest32,
    pub authority: AuthorityPosture,
}

/// Only authenticated completion constructs this receipt. Reading its incumbent
/// is not evidence that a later task used it, nor a final-use authorization.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct LearningDecisionReceiptV1 {
    pub(super) summary: LearningDecisionSummaryV1,
    pub(super) input: LearningDecisionInputV1,
    pub(super) attestations: LearningDecisionAttestationsV1,
}

impl LearningDecisionReceiptV1 {
    pub fn summary(&self) -> &LearningDecisionSummaryV1 {
        &self.summary
    }

    pub fn evidence(&self) -> (&LearningDecisionInputV1, &LearningDecisionAttestationsV1) {
        (&self.input, &self.attestations)
    }
}

#[derive(Debug)]
pub enum LearningDecisionErrorV1 {
    Binding(&'static str),
    Authentication(SignedEvidenceError),
    Evaluation(ProductEvaluationError),
}

impl fmt::Display for LearningDecisionErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}
impl Error for LearningDecisionErrorV1 {}
