use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::LogicalSequence;
use codex_hepta_types::ProbabilityQ32;
use codex_hepta_types::StableId;

use crate::causal_v2::AuthenticatedOutcomeV1;
use crate::causal_v2::AuthenticatedPrincipalV1;
use crate::causal_v2::CandidateSetCompletenessReceiptV1;
use crate::causal_v2::CreditAllocationBatchV1;

/// Independent assertion that the logged candidate set is complete for the
/// evaluated decision boundary.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum CandidateSetCompleteness {
    Complete,
    Incomplete,
}

impl CandidateSetCompleteness {
    pub(crate) const fn tag(self) -> u8 {
        match self {
            Self::Complete => 0,
            Self::Incomplete => 1,
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum OutcomeFinality {
    Intermediate,
    Terminal,
}

impl OutcomeFinality {
    pub(crate) const fn tag(self) -> u8 {
        match self {
            Self::Intermediate => 0,
            Self::Terminal => 1,
        }
    }
}

/// Complete decision facts required for causal and counterfactual evaluation.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct EpisodeDecision {
    pub record_id: StableId,
    pub episode_id: StableId,
    pub objective_digest: Digest32,
    pub policy_id: StableId,
    pub candidate_ids: Vec<StableId>,
    pub selected_candidate_id: StableId,
    pub selected_propensity: ProbabilityQ32,
    pub completeness: CandidateSetCompleteness,
    pub support_digest: Digest32,
}

/// Authenticated V2 decision retained in the same append-only durable chain as
/// the stable V1 event. The signed evidence digest binds the exact admission
/// receipt without granting runtime authority.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AuthenticatedDecisionRecordV2 {
    pub record_id: StableId,
    pub episode_id: StableId,
    pub objective_digest: Digest32,
    pub policy_id: StableId,
    pub generator: AuthenticatedPrincipalV1,
    pub completeness: CandidateSetCompletenessReceiptV1,
    pub candidate_ids: Vec<StableId>,
    pub selected_candidate_id: StableId,
    pub selected_propensity: ProbabilityQ32,
    pub evidence_digest: Digest32,
}

/// Outcome observed by an identity independent from the evaluated policy.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct OutcomeObservation {
    pub record_id: StableId,
    pub outcome_id: StableId,
    pub episode_id: StableId,
    pub observer_id: StableId,
    pub value: FixedQ32,
    pub finality: OutcomeFinality,
    pub support_digest: Digest32,
}

/// Full delayed/censored/corrected V2 outcome plus the digest of the admitted
/// signed evidence. This removes the need to collapse missing outcomes to zero.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AuthenticatedOutcomeRecordV2 {
    pub outcome: AuthenticatedOutcomeV1,
    pub evidence_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CreditAssignment {
    pub record_id: StableId,
    pub credit_id: StableId,
    pub episode_id: StableId,
    pub outcome_id: StableId,
    pub target_artifact_id: StableId,
    pub allocator_id: StableId,
    pub credit: FixedQ32,
    pub support_digest: Digest32,
}

/// One atomic durable publication unit for conserved V2 credit. The embedded
/// batch is replay-validated; no partially acknowledged allocation set exists.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ConservedCreditBatchRecordV2 {
    pub record_id: StableId,
    pub batch: CreditAllocationBatchV1,
    pub batch_digest: Digest32,
    pub evidence_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct Revocation {
    pub record_id: StableId,
    pub target_record_id: StableId,
    pub authority_id: StableId,
    pub reason_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum LedgerEvent {
    Decision(EpisodeDecision),
    Outcome(OutcomeObservation),
    Credit(CreditAssignment),
    Revocation(Revocation),
    AuthenticatedDecision(AuthenticatedDecisionRecordV2),
    AuthenticatedOutcome(AuthenticatedOutcomeRecordV2),
    ConservedCreditBatch(ConservedCreditBatchRecordV2),
}

impl LedgerEvent {
    pub(crate) fn record_id(&self) -> &StableId {
        match self {
            Self::Decision(value) => &value.record_id,
            Self::Outcome(value) => &value.record_id,
            Self::Credit(value) => &value.record_id,
            Self::Revocation(value) => &value.record_id,
            Self::AuthenticatedDecision(value) => &value.record_id,
            Self::AuthenticatedOutcome(value) => &value.outcome.record_id,
            Self::ConservedCreditBatch(value) => &value.record_id,
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct LedgerRecord {
    pub sequence: LogicalSequence,
    pub predecessor_chain_digest: Digest32,
    pub event_digest: Digest32,
    pub chain_digest: Digest32,
    pub event: LedgerEvent,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum AppendDisposition {
    Appended,
    IdempotentReplay,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AppendReceipt {
    pub disposition: AppendDisposition,
    pub sequence: LogicalSequence,
    pub event_digest: Digest32,
    pub chain_digest: Digest32,
}

/// Cloneable, immutable persistence payload. Restoring it always replays every
/// invariant and verifies every chain link.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct LedgerSnapshot {
    pub(crate) records: Vec<LedgerRecord>,
    pub head_digest: Digest32,
}

impl LedgerSnapshot {
    #[must_use]
    pub fn records(&self) -> &[LedgerRecord] {
        &self.records
    }
}
