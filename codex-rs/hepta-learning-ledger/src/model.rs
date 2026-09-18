use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::LogicalSequence;
use codex_hepta_types::ProbabilityQ32;
use codex_hepta_types::StableId;

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

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum DurableOutcomeTerminalityV2 {
    Pending,
    Censored,
    Terminal,
}

impl DurableOutcomeTerminalityV2 {
    pub(crate) const fn tag(self) -> u8 {
        match self {
            Self::Pending => 0,
            Self::Censored => 1,
            Self::Terminal => 2,
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

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AuthenticatedDecisionV2 {
    pub decision: EpisodeDecision,
    pub generator_credential_chain_digest: Digest32,
    pub generator_signing_key_digest: Digest32,
    pub generator_controller_id: StableId,
    pub generator_scope_digest: Digest32,
    pub generator_authority_epoch: u64,
    pub candidate_set_digest: Digest32,
    pub candidate_count: u32,
    pub omitted_count_bound: u32,
    pub candidate_receipt_digest: Digest32,
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

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AuthenticatedOutcomeV2 {
    pub record_id: StableId,
    pub outcome_id: StableId,
    pub episode_id: StableId,
    pub observer_id: StableId,
    pub observer_credential_chain_digest: Digest32,
    pub observer_signing_key_digest: Digest32,
    pub observer_controller_id: StableId,
    pub observer_scope_digest: Digest32,
    pub observer_authority_epoch: u64,
    pub observed_at: Option<u64>,
    pub value: Option<FixedQ32>,
    pub unit_profile_digest: Digest32,
    pub support_digest: Digest32,
    pub latest_observable_at: u64,
    pub expected_delay_profile_digest: Digest32,
    pub terminality: DurableOutcomeTerminalityV2,
    pub censoring_reason: Option<StableId>,
    pub correction_predecessor: Option<StableId>,
    pub finalized_at: Option<u64>,
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

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DurableCreditAllocationV1 {
    pub target_id: StableId,
    pub credit: FixedQ32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CreditAllocationBatchV2 {
    pub record_id: StableId,
    pub batch_id: StableId,
    pub episode_id: StableId,
    pub outcome_id: StableId,
    pub allocator_id: StableId,
    pub allocator_credential_chain_digest: Digest32,
    pub allocator_signing_key_digest: Digest32,
    pub allocator_controller_id: StableId,
    pub allocator_scope_digest: Digest32,
    pub allocator_authority_epoch: u64,
    pub terminal_outcome: FixedQ32,
    pub allocations: Vec<DurableCreditAllocationV1>,
    pub conservation_residual: FixedQ32,
    pub parent_credit_id: Option<StableId>,
    pub rule_digest: Digest32,
    pub support_digest: Digest32,
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
pub struct UnlearningLineageEventV1 {
    pub record_id: StableId,
    pub lineage_id: StableId,
    pub scope_digest: Digest32,
    pub authority_id: StableId,
    pub authority_credential_chain_digest: Digest32,
    pub authority_signing_key_digest: Digest32,
    pub authority_controller_id: StableId,
    pub authority_epoch: u64,
    pub reason_digest: Digest32,
    pub source_record_ids: Vec<StableId>,
    pub dataset_ids: Vec<StableId>,
    pub artifact_ids: Vec<StableId>,
    pub predecessor_lineage_id: Option<StableId>,
    pub evidence_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum LedgerEvent {
    Decision(EpisodeDecision),
    Outcome(OutcomeObservation),
    Credit(CreditAssignment),
    Revocation(Revocation),
    DecisionV2(AuthenticatedDecisionV2),
    OutcomeV2(AuthenticatedOutcomeV2),
    CreditBatchV2(CreditAllocationBatchV2),
    UnlearningV1(UnlearningLineageEventV1),
}

impl LedgerEvent {
    pub(crate) fn record_id(&self) -> &StableId {
        match self {
            Self::Decision(value) => &value.record_id,
            Self::Outcome(value) => &value.record_id,
            Self::Credit(value) => &value.record_id,
            Self::Revocation(value) => &value.record_id,
            Self::DecisionV2(value) => &value.decision.record_id,
            Self::OutcomeV2(value) => &value.record_id,
            Self::CreditBatchV2(value) => &value.record_id,
            Self::UnlearningV1(value) => &value.record_id,
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
