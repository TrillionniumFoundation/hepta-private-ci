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

/// Durable terminality for authenticated V2 outcomes. Pending and censored
/// observations are explicit states and are never collapsed into zero reward.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum AuthenticatedOutcomeTerminality {
    Pending,
    Censored,
    Terminal,
}

impl AuthenticatedOutcomeTerminality {
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

/// Production decision fact with authenticated generator identity and a
/// generator-relative candidate-completeness receipt bound into the durable row.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AuthenticatedDecisionRecordV2 {
    pub record_id: StableId,
    pub episode_id: StableId,
    pub run_snapshot_digest: Digest32,
    pub objective_digest: Digest32,
    pub policy_digest: Digest32,
    pub generator_id: StableId,
    pub generator_controller_id: StableId,
    pub generator_credential_chain_digest: Digest32,
    pub generator_signing_key_digest: Digest32,
    pub generator_scope_digest: Digest32,
    pub generator_authority_epoch: u64,
    pub candidate_ids: Vec<StableId>,
    pub selected_candidate_id: StableId,
    pub selected_propensity: ProbabilityQ32,
    pub candidate_completeness_digest: Digest32,
    pub support_digest: Digest32,
    pub authentication_digest: Digest32,
}

/// Legacy V1 outcome record retained for backward readability. Product writers
/// use `AuthenticatedOutcomeRecordV2` so authentication, delayed-outcome state
/// and correction lineage are durable rather than caller-local assertions.
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

/// Authenticated outcome fact persisted as one immutable ledger record.
/// `correction_predecessor` forms a single-head lineage per episode; the ledger
/// validates existence, same-episode ancestry and head continuity before append.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AuthenticatedOutcomeRecordV2 {
    pub record_id: StableId,
    pub outcome_id: StableId,
    pub episode_id: StableId,
    pub observer_id: StableId,
    pub observer_controller_id: StableId,
    pub observer_credential_chain_digest: Digest32,
    pub observer_signing_key_digest: Digest32,
    pub observer_scope_digest: Digest32,
    pub observer_authority_epoch: u64,
    pub observed_at: Option<u64>,
    pub value: Option<FixedQ32>,
    pub unit_profile_digest: Digest32,
    pub support_digest: Digest32,
    pub latest_observable_at: u64,
    pub expected_delay_profile_digest: Digest32,
    pub terminality: AuthenticatedOutcomeTerminality,
    pub censoring_reason: Option<StableId>,
    pub correction_predecessor: Option<StableId>,
    pub finalized_at: Option<u64>,
    /// Digest of the verified signed evidence admitted by the production writer.
    pub authentication_digest: Digest32,
}

/// Legacy V1 per-target credit retained for backward readability. Product
/// writers use `CreditAllocationBatchRecordV2` so conservation is enforced
/// before a single durable append.
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
pub struct CreditAllocationRecordV2 {
    pub target_artifact_id: StableId,
    pub credit: FixedQ32,
}

/// Atomic durable credit publication unit. All allocations and the residual are
/// committed in one ledger frame, so readers never observe a partially written
/// conserved batch.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CreditAllocationBatchRecordV2 {
    pub record_id: StableId,
    pub batch_id: StableId,
    pub episode_id: StableId,
    pub outcome_id: StableId,
    pub allocator_id: StableId,
    pub allocator_controller_id: StableId,
    pub allocator_credential_chain_digest: Digest32,
    pub allocator_signing_key_digest: Digest32,
    pub allocator_scope_digest: Digest32,
    pub allocator_authority_epoch: u64,
    pub terminal_outcome: FixedQ32,
    pub allocations: Vec<CreditAllocationRecordV2>,
    pub conservation_residual: FixedQ32,
    pub support_digest: Digest32,
    pub authentication_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct Revocation {
    pub record_id: StableId,
    pub target_record_id: StableId,
    pub authority_id: StableId,
    pub reason_digest: Digest32,
}

/// Explicit source -> frozen dataset -> artifact invalidation lineage. Appending
/// this event also logically revokes the source record in the active projection;
/// the immutable audit bytes remain present.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct UnlearningLineageEventV1 {
    pub record_id: StableId,
    pub lineage_id: StableId,
    pub source_record_id: StableId,
    pub dataset_snapshot_id: StableId,
    pub artifact_id: StableId,
    pub authority_id: StableId,
    pub reason_digest: Digest32,
    pub authentication_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum LedgerEvent {
    Decision(EpisodeDecision),
    Outcome(OutcomeObservation),
    Credit(CreditAssignment),
    Revocation(Revocation),
    AuthenticatedDecisionV2(AuthenticatedDecisionRecordV2),
    AuthenticatedOutcomeV2(AuthenticatedOutcomeRecordV2),
    CreditBatchV2(CreditAllocationBatchRecordV2),
    UnlearningLineageV1(UnlearningLineageEventV1),
}

impl LedgerEvent {
    pub(crate) fn record_id(&self) -> &StableId {
        match self {
            Self::Decision(value) => &value.record_id,
            Self::Outcome(value) => &value.record_id,
            Self::Credit(value) => &value.record_id,
            Self::Revocation(value) => &value.record_id,
            Self::AuthenticatedDecisionV2(value) => &value.record_id,
            Self::AuthenticatedOutcomeV2(value) => &value.record_id,
            Self::CreditBatchV2(value) => &value.record_id,
            Self::UnlearningLineageV1(value) => &value.record_id,
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
