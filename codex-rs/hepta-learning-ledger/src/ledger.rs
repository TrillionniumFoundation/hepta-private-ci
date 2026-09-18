use std::collections::BTreeMap;
use std::collections::BTreeSet;

use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::LogicalSequence;
use codex_hepta_types::StableId;

use crate::AppendDisposition;
use crate::AppendReceipt;
use crate::AuthenticatedDecisionRecordV2;
use crate::AuthenticatedOutcomeRecordV2;
use crate::AuthenticatedOutcomeTerminality;
use crate::CandidateSetCompleteness;
use crate::CreditAllocationBatchRecordV2;
use crate::CreditAssignment;
use crate::EpisodeDecision;
use crate::LedgerError;
use crate::LedgerEvent;
use crate::LedgerRecord;
use crate::LedgerSnapshot;
use crate::OutcomeFinality;
use crate::OutcomeObservation;
use crate::Revocation;
use crate::UnlearningLineageEventV1;

const MAX_RECORDS: usize = 1_000_000;
const MAX_CANDIDATES: usize = 128;
const MAX_CREDIT_ALLOCATIONS: usize = 256;
const EVENT_DIGEST_DOMAIN: &[u8] = b"hepta.learning-ledger.event.v1";
const CHAIN_DIGEST_DOMAIN: &[u8] = b"hepta.learning-ledger.chain.v1";

#[derive(Clone, Debug)]
struct DecisionIndex {
    record_id: StableId,
    policy_id: StableId,
    controller_id: Option<StableId>,
}

#[derive(Clone, Debug)]
struct OutcomeIndex {
    record_id: StableId,
    episode_id: StableId,
    observer_id: StableId,
    controller_id: Option<StableId>,
    terminal: bool,
    value: Option<FixedQ32>,
    lineage_managed: bool,
}

/// Validated immutable event prepared for a single-writer commit.
pub(crate) struct PreparedAppend {
    pub(crate) record: LedgerRecord,
    pub(crate) disposition: AppendDisposition,
}

/// Deterministic append-only ledger core. Legacy V1 facts remain readable, while
/// product-facing V2 facts add authenticated outcome lineage and atomic credit.
#[derive(Clone, Debug, Default)]
pub struct LearningLedger {
    records: Vec<LedgerRecord>,
    record_digests: BTreeMap<StableId, Digest32>,
    record_kinds: BTreeMap<StableId, u8>,
    decisions: BTreeMap<StableId, DecisionIndex>,
    outcomes: BTreeMap<StableId, OutcomeIndex>,
    outcome_lineage_heads: BTreeMap<StableId, StableId>,
    credit_ids: BTreeSet<StableId>,
    credit_keys: BTreeSet<(StableId, StableId, StableId)>,
    credit_batch_ids: BTreeSet<StableId>,
    credited_outcomes: BTreeSet<StableId>,
    revoked: BTreeSet<StableId>,
    unlearning_lineage_ids: BTreeSet<StableId>,
    unlearning_keys: BTreeSet<(StableId, StableId, StableId)>,
}

impl LearningLedger {
    #[must_use]
    pub fn new() -> Self {
        Self::default()
    }

    pub fn append(&mut self, event: LedgerEvent) -> Result<AppendReceipt, LedgerError> {
        let prepared = self.prepare(event)?;
        self.apply(prepared)
    }

    pub(crate) fn prepare(&self, mut event: LedgerEvent) -> Result<PreparedAppend, LedgerError> {
        normalize_event(&mut event)?;
        let record_id = event.record_id().clone();
        let event_digest = digest_event(&event);

        if let Some(existing_digest) = self.record_digests.get(&record_id) {
            if *existing_digest != event_digest {
                return Err(LedgerError::IdentityConflict(record_id.to_string()));
            }
            let record = self
                .records
                .iter()
                .find(|record| record.event.record_id() == &record_id)
                .ok_or(LedgerError::InternalInvariant)?;
            return Ok(PreparedAppend {
                record: record.clone(),
                disposition: AppendDisposition::IdempotentReplay,
            });
        }

        if self.records.len() >= MAX_RECORDS {
            return Err(LedgerError::RecordLimitExceeded);
        }
        self.validate_event(&event)?;
        let sequence_value = u64::try_from(self.records.len())
            .map_err(|_| LedgerError::SequenceOverflow)?
            .checked_add(1)
            .ok_or(LedgerError::SequenceOverflow)?;
        let sequence =
            LogicalSequence::new(sequence_value).map_err(|_| LedgerError::SequenceOverflow)?;
        let predecessor_chain_digest = self
            .records
            .last()
            .map_or(Digest32::ZERO, |record| record.chain_digest);
        let chain_digest = digest_chain(predecessor_chain_digest, sequence, event_digest);
        let record = LedgerRecord {
            sequence,
            predecessor_chain_digest,
            event_digest,
            chain_digest,
            event,
        };
        Ok(PreparedAppend {
            record,
            disposition: AppendDisposition::Appended,
        })
    }

    pub(crate) fn apply(&mut self, prepared: PreparedAppend) -> Result<AppendReceipt, LedgerError> {
        let PreparedAppend {
            record,
            disposition,
        } = prepared;
        let result = receipt(&record, disposition);
        if disposition == AppendDisposition::Appended {
            let head = self
                .records
                .last()
                .map_or(Digest32::ZERO, |row| row.chain_digest);
            if record.predecessor_chain_digest != head
                || record.sequence.get() != self.records.len() as u64 + 1
            {
                return Err(LedgerError::InternalInvariant);
            }
            self.index_record(&record);
            self.records.push(record);
        }
        Ok(result)
    }

    #[must_use]
    pub fn records(&self) -> &[LedgerRecord] {
        &self.records
    }

    /// Returns facts that remain causally effective after corrections,
    /// revocations and explicit unlearning lineage have been applied.
    #[must_use]
    pub fn active_records(&self) -> Vec<&LedgerRecord> {
        self.records
            .iter()
            .filter(|record| self.record_is_active(record))
            .collect()
    }

    #[must_use]
    pub fn snapshot(&self) -> LedgerSnapshot {
        LedgerSnapshot {
            records: self.records.clone(),
            head_digest: self
                .records
                .last()
                .map_or(Digest32::ZERO, |record| record.chain_digest),
        }
    }

    pub fn from_snapshot(snapshot: LedgerSnapshot) -> Result<Self, LedgerError> {
        let expected_head = snapshot.head_digest;
        let mut ledger = Self::new();
        for expected in snapshot.records {
            let receipt = ledger.append(expected.event.clone())?;
            let actual = ledger
                .records
                .last()
                .ok_or(LedgerError::InternalInvariant)?;
            if actual != &expected || receipt.disposition != AppendDisposition::Appended {
                return Err(LedgerError::SnapshotRecordMismatch(expected.sequence.get()));
            }
        }
        let actual_head = ledger
            .records
            .last()
            .map_or(Digest32::ZERO, |record| record.chain_digest);
        if actual_head != expected_head {
            return Err(LedgerError::SnapshotHeadMismatch);
        }
        Ok(ledger)
    }

    fn validate_event(&self, event: &LedgerEvent) -> Result<(), LedgerError> {
        validate_support_digests(event)?;
        match event {
            LedgerEvent::Decision(value) => self.validate_decision(value),
            LedgerEvent::Outcome(value) => self.validate_outcome(value),
            LedgerEvent::Credit(value) => self.validate_credit(value),
            LedgerEvent::Revocation(value) => self.validate_revocation(value),
            LedgerEvent::AuthenticatedDecisionV2(value) => {
                self.validate_authenticated_decision(value)
            }
            LedgerEvent::AuthenticatedOutcomeV2(value) => {
                self.validate_authenticated_outcome(value)
            }
            LedgerEvent::CreditBatchV2(value) => self.validate_credit_batch(value),
            LedgerEvent::UnlearningLineageV1(value) => self.validate_unlearning(value),
        }
    }

    fn validate_decision(&self, decision: &EpisodeDecision) -> Result<(), LedgerError> {
        if decision.completeness != CandidateSetCompleteness::Complete {
            return Err(LedgerError::IncompleteCandidateSet);
        }
        if decision.candidate_ids.is_empty() {
            return Err(LedgerError::EmptyCandidateSet);
        }
        if decision.candidate_ids.len() > MAX_CANDIDATES {
            return Err(LedgerError::CandidateLimitExceeded);
        }
        if !decision
            .candidate_ids
            .iter()
            .any(|candidate| candidate.as_str() == "abstain")
        {
            return Err(LedgerError::MissingAbstainCandidate);
        }
        if !decision
            .candidate_ids
            .contains(&decision.selected_candidate_id)
        {
            return Err(LedgerError::SelectedCandidateMissing(
                decision.selected_candidate_id.to_string(),
            ));
        }
        if decision.selected_propensity.raw() == 0 {
            return Err(LedgerError::ZeroSelectedPropensity);
        }
        if self.decisions.contains_key(&decision.episode_id) {
            return Err(LedgerError::EpisodeAlreadyExists(
                decision.episode_id.to_string(),
            ));
        }
        Ok(())
    }

    fn validate_authenticated_decision(
        &self,
        decision: &AuthenticatedDecisionRecordV2,
    ) -> Result<(), LedgerError> {
        if decision.generator_authority_epoch == 0 {
            return Err(LedgerError::InvalidAuthorityEpoch);
        }
        if decision.candidate_ids.is_empty() {
            return Err(LedgerError::EmptyCandidateSet);
        }
        if decision.candidate_ids.len() > MAX_CANDIDATES {
            return Err(LedgerError::CandidateLimitExceeded);
        }
        if !decision
            .candidate_ids
            .iter()
            .any(|candidate| candidate.as_str() == "abstain")
        {
            return Err(LedgerError::MissingAbstainCandidate);
        }
        if !decision
            .candidate_ids
            .contains(&decision.selected_candidate_id)
        {
            return Err(LedgerError::SelectedCandidateMissing(
                decision.selected_candidate_id.to_string(),
            ));
        }
        if decision.selected_propensity.raw() == 0 {
            return Err(LedgerError::ZeroSelectedPropensity);
        }
        if self.decisions.contains_key(&decision.episode_id) {
            return Err(LedgerError::EpisodeAlreadyExists(
                decision.episode_id.to_string(),
            ));
        }
        Ok(())
    }

    fn validate_outcome(&self, outcome: &OutcomeObservation) -> Result<(), LedgerError> {
        if self.outcomes.contains_key(&outcome.outcome_id) {
            return Err(LedgerError::OutcomeAlreadyExists(
                outcome.outcome_id.to_string(),
            ));
        }
        let decision = self.decision_for_episode(&outcome.episode_id)?;
        if decision.policy_id == outcome.observer_id {
            return Err(LedgerError::PolicySelfLabelsOutcome);
        }
        Ok(())
    }

    fn validate_authenticated_outcome(
        &self,
        outcome: &AuthenticatedOutcomeRecordV2,
    ) -> Result<(), LedgerError> {
        if self.outcomes.contains_key(&outcome.outcome_id) {
            return Err(LedgerError::OutcomeAlreadyExists(
                outcome.outcome_id.to_string(),
            ));
        }
        let decision = self.decision_for_episode(&outcome.episode_id)?;
        if decision.policy_id == outcome.observer_id {
            return Err(LedgerError::PolicySelfLabelsOutcome);
        }
        validate_authenticated_outcome_state(outcome)?;

        match &outcome.correction_predecessor {
            None => {
                if let Some(existing) = self
                    .outcomes
                    .iter()
                    .find(|(_, indexed)| indexed.episode_id == outcome.episode_id)
                    .map(|(id, _)| id)
                {
                    return Err(LedgerError::OutcomeLineageRootExists(existing.to_string()));
                }
            }
            Some(predecessor_id) => {
                let predecessor = self.outcomes.get(predecessor_id).ok_or_else(|| {
                    LedgerError::OutcomePredecessorNotFound(predecessor_id.to_string())
                })?;
                if predecessor.episode_id != outcome.episode_id {
                    return Err(LedgerError::OutcomePredecessorEpisodeMismatch);
                }
                if self.revoked.contains(&predecessor.record_id) {
                    return Err(LedgerError::OutcomeRevoked(predecessor_id.to_string()));
                }
                if self.outcome_lineage_heads.get(&outcome.episode_id) != Some(predecessor_id) {
                    return Err(LedgerError::OutcomePredecessorNotHead(
                        predecessor_id.to_string(),
                    ));
                }
            }
        }
        Ok(())
    }

    fn validate_credit(&self, credit: &CreditAssignment) -> Result<(), LedgerError> {
        if self.credit_ids.contains(&credit.credit_id) {
            return Err(LedgerError::CreditIdentityAlreadyExists(
                credit.credit_id.to_string(),
            ));
        }
        self.decision_for_episode(&credit.episode_id)?;
        let outcome = self.effective_outcome(&credit.outcome_id)?;
        if outcome.episode_id != credit.episode_id {
            return Err(LedgerError::OutcomeEpisodeMismatch);
        }
        if !outcome.terminal {
            return Err(LedgerError::OutcomeNotTerminal);
        }
        let key = (
            credit.episode_id.clone(),
            credit.outcome_id.clone(),
            credit.target_artifact_id.clone(),
        );
        if self.credit_keys.contains(&key) {
            return Err(LedgerError::CreditAlreadyAssigned);
        }
        Ok(())
    }

    fn validate_credit_batch(
        &self,
        batch: &CreditAllocationBatchRecordV2,
    ) -> Result<(), LedgerError> {
        if self.credit_batch_ids.contains(&batch.batch_id) {
            return Err(LedgerError::CreditBatchIdentityAlreadyExists(
                batch.batch_id.to_string(),
            ));
        }
        let decision = self.decision_for_episode(&batch.episode_id)?;
        let outcome = self.effective_outcome(&batch.outcome_id)?;
        if outcome.episode_id != batch.episode_id {
            return Err(LedgerError::OutcomeEpisodeMismatch);
        }
        if !outcome.terminal || outcome.value != Some(batch.terminal_outcome) {
            return Err(LedgerError::OutcomeNotTerminal);
        }
        if decision.policy_id == batch.allocator_id
            || outcome.observer_id == batch.allocator_id
            || decision.controller_id.as_ref() == Some(&batch.allocator_controller_id)
            || outcome.controller_id.as_ref() == Some(&batch.allocator_controller_id)
        {
            return Err(LedgerError::CreditAllocatorNotIndependent);
        }
        if self.credited_outcomes.contains(&batch.outcome_id) {
            return Err(LedgerError::CreditBatchAlreadyAssigned(
                batch.outcome_id.to_string(),
            ));
        }
        if batch.allocations.is_empty() {
            return Err(LedgerError::CreditBatchEmpty);
        }
        if batch.allocations.len() > MAX_CREDIT_ALLOCATIONS {
            return Err(LedgerError::CreditBatchLimitExceeded);
        }
        for adjacent in batch.allocations.windows(2) {
            if adjacent[0].target_artifact_id == adjacent[1].target_artifact_id {
                return Err(LedgerError::DuplicateCreditTarget(
                    adjacent[0].target_artifact_id.to_string(),
                ));
            }
        }
        let allocated = batch
            .allocations
            .iter()
            .try_fold(0_i128, |sum, allocation| {
                sum.checked_add(i128::from(allocation.credit.raw()))
                    .ok_or(LedgerError::Arithmetic)
            })?;
        let conserved = allocated
            .checked_add(i128::from(batch.conservation_residual.raw()))
            .ok_or(LedgerError::Arithmetic)?;
        if conserved != i128::from(batch.terminal_outcome.raw()) {
            return Err(LedgerError::CreditConservation);
        }
        Ok(())
    }

    fn validate_revocation(&self, revocation: &Revocation) -> Result<(), LedgerError> {
        let Some(kind) = self.record_kinds.get(&revocation.target_record_id) else {
            return Err(LedgerError::TargetNotFound(
                revocation.target_record_id.to_string(),
            ));
        };
        if matches!(
            *kind,
            value if value == event_kind_code(EventKind::Revocation)
                || value == event_kind_code(EventKind::UnlearningLineageV1)
        ) {
            return Err(LedgerError::RevocationOfRevocation);
        }
        if self.revoked.contains(&revocation.target_record_id) {
            return Err(LedgerError::TargetAlreadyRevoked(
                revocation.target_record_id.to_string(),
            ));
        }
        Ok(())
    }

    fn validate_unlearning(&self, value: &UnlearningLineageEventV1) -> Result<(), LedgerError> {
        if self.unlearning_lineage_ids.contains(&value.lineage_id) {
            return Err(LedgerError::UnlearningLineageIdentityAlreadyExists(
                value.lineage_id.to_string(),
            ));
        }
        let Some(kind) = self.record_kinds.get(&value.source_record_id) else {
            return Err(LedgerError::TargetNotFound(
                value.source_record_id.to_string(),
            ));
        };
        if *kind == event_kind_code(EventKind::Revocation)
            || *kind == event_kind_code(EventKind::UnlearningLineageV1)
        {
            return Err(LedgerError::UnlearningTargetInvalid);
        }
        if self.revoked.contains(&value.source_record_id) {
            return Err(LedgerError::TargetAlreadyRevoked(
                value.source_record_id.to_string(),
            ));
        }
        let key = (
            value.source_record_id.clone(),
            value.dataset_snapshot_id.clone(),
            value.artifact_id.clone(),
        );
        if self.unlearning_keys.contains(&key) {
            return Err(LedgerError::UnlearningLineageAlreadyExists);
        }
        Ok(())
    }

    fn decision_for_episode(&self, episode_id: &StableId) -> Result<&DecisionIndex, LedgerError> {
        let decision = self
            .decisions
            .get(episode_id)
            .ok_or_else(|| LedgerError::EpisodeNotFound(episode_id.to_string()))?;
        if self.revoked.contains(&decision.record_id) {
            return Err(LedgerError::EpisodeRevoked(episode_id.to_string()));
        }
        Ok(decision)
    }

    fn effective_outcome(&self, outcome_id: &StableId) -> Result<&OutcomeIndex, LedgerError> {
        let outcome = self
            .outcomes
            .get(outcome_id)
            .ok_or_else(|| LedgerError::OutcomeNotFound(outcome_id.to_string()))?;
        if self.revoked.contains(&outcome.record_id)
            || !self.outcome_is_current(outcome_id, outcome)
        {
            return Err(LedgerError::OutcomeRevoked(outcome_id.to_string()));
        }
        Ok(outcome)
    }

    fn outcome_is_current(&self, outcome_id: &StableId, outcome: &OutcomeIndex) -> bool {
        if outcome.lineage_managed {
            self.outcome_lineage_heads.get(&outcome.episode_id) == Some(outcome_id)
        } else {
            !self.outcome_lineage_heads.contains_key(&outcome.episode_id)
        }
    }

    fn index_record(&mut self, record: &LedgerRecord) {
        let record_id = record.event.record_id().clone();
        self.record_digests
            .insert(record_id.clone(), record.event_digest);
        self.record_kinds
            .insert(record_id, event_kind(&record.event));
        match &record.event {
            LedgerEvent::Decision(value) => {
                self.decisions.insert(
                    value.episode_id.clone(),
                    DecisionIndex {
                        record_id: value.record_id.clone(),
                        policy_id: value.policy_id.clone(),
                        controller_id: None,
                    },
                );
            }
            LedgerEvent::AuthenticatedDecisionV2(value) => {
                self.decisions.insert(
                    value.episode_id.clone(),
                    DecisionIndex {
                        record_id: value.record_id.clone(),
                        policy_id: value.generator_id.clone(),
                        controller_id: Some(value.generator_controller_id.clone()),
                    },
                );
            }
            LedgerEvent::Outcome(value) => {
                self.outcomes.insert(
                    value.outcome_id.clone(),
                    OutcomeIndex {
                        record_id: value.record_id.clone(),
                        episode_id: value.episode_id.clone(),
                        observer_id: value.observer_id.clone(),
                        controller_id: None,
                        terminal: value.finality == OutcomeFinality::Terminal,
                        value: Some(value.value),
                        lineage_managed: false,
                    },
                );
            }
            LedgerEvent::AuthenticatedOutcomeV2(value) => {
                self.outcomes.insert(
                    value.outcome_id.clone(),
                    OutcomeIndex {
                        record_id: value.record_id.clone(),
                        episode_id: value.episode_id.clone(),
                        observer_id: value.observer_id.clone(),
                        controller_id: Some(value.observer_controller_id.clone()),
                        terminal: value.terminality == AuthenticatedOutcomeTerminality::Terminal,
                        value: value.value,
                        lineage_managed: true,
                    },
                );
                self.outcome_lineage_heads
                    .insert(value.episode_id.clone(), value.outcome_id.clone());
            }
            LedgerEvent::Credit(value) => {
                self.credit_ids.insert(value.credit_id.clone());
                self.credit_keys.insert((
                    value.episode_id.clone(),
                    value.outcome_id.clone(),
                    value.target_artifact_id.clone(),
                ));
                self.credited_outcomes.insert(value.outcome_id.clone());
            }
            LedgerEvent::CreditBatchV2(value) => {
                self.credit_batch_ids.insert(value.batch_id.clone());
                self.credited_outcomes.insert(value.outcome_id.clone());
            }
            LedgerEvent::Revocation(value) => {
                self.revoked.insert(value.target_record_id.clone());
            }
            LedgerEvent::UnlearningLineageV1(value) => {
                self.unlearning_lineage_ids.insert(value.lineage_id.clone());
                self.unlearning_keys.insert((
                    value.source_record_id.clone(),
                    value.dataset_snapshot_id.clone(),
                    value.artifact_id.clone(),
                ));
                self.revoked.insert(value.source_record_id.clone());
            }
        }
    }

    fn record_is_active(&self, record: &LedgerRecord) -> bool {
        let record_id = record.event.record_id();
        if self.revoked.contains(record_id) {
            return false;
        }
        match &record.event {
            LedgerEvent::Decision(_) | LedgerEvent::AuthenticatedDecisionV2(_) => true,
            LedgerEvent::Outcome(outcome) => {
                let indexed = self.outcomes.get(&outcome.outcome_id);
                self.decisions
                    .get(&outcome.episode_id)
                    .is_some_and(|decision| !self.revoked.contains(&decision.record_id))
                    && indexed
                        .is_some_and(|value| self.outcome_is_current(&outcome.outcome_id, value))
            }
            LedgerEvent::AuthenticatedOutcomeV2(outcome) => {
                let indexed = self.outcomes.get(&outcome.outcome_id);
                self.decisions
                    .get(&outcome.episode_id)
                    .is_some_and(|decision| !self.revoked.contains(&decision.record_id))
                    && indexed
                        .is_some_and(|value| self.outcome_is_current(&outcome.outcome_id, value))
            }
            LedgerEvent::Credit(credit) => {
                let decision_active = self
                    .decisions
                    .get(&credit.episode_id)
                    .is_some_and(|decision| !self.revoked.contains(&decision.record_id));
                let outcome_active = self
                    .outcomes
                    .get(&credit.outcome_id)
                    .is_some_and(|outcome| {
                        !self.revoked.contains(&outcome.record_id)
                            && self.outcome_is_current(&credit.outcome_id, outcome)
                    });
                decision_active && outcome_active
            }
            LedgerEvent::CreditBatchV2(batch) => {
                let decision_active = self
                    .decisions
                    .get(&batch.episode_id)
                    .is_some_and(|decision| !self.revoked.contains(&decision.record_id));
                let outcome_active = self.outcomes.get(&batch.outcome_id).is_some_and(|outcome| {
                    !self.revoked.contains(&outcome.record_id)
                        && self.outcome_is_current(&batch.outcome_id, outcome)
                });
                decision_active && outcome_active
            }
            LedgerEvent::Revocation(_) | LedgerEvent::UnlearningLineageV1(_) => true,
        }
    }
}

fn validate_authenticated_outcome_state(
    outcome: &AuthenticatedOutcomeRecordV2,
) -> Result<(), LedgerError> {
    if outcome.observer_authority_epoch == 0 {
        return Err(LedgerError::InvalidAuthorityEpoch);
    }
    match outcome.terminality {
        AuthenticatedOutcomeTerminality::Pending => {
            if outcome.observed_at.is_some()
                || outcome.value.is_some()
                || outcome.finalized_at.is_some()
                || outcome.censoring_reason.is_some()
                || outcome.correction_predecessor.is_some()
            {
                return Err(LedgerError::OutcomeStateMismatch);
            }
        }
        AuthenticatedOutcomeTerminality::Censored => {
            let Some(finalized_at) = outcome.finalized_at else {
                return Err(LedgerError::OutcomeStateMismatch);
            };
            if outcome.observed_at.is_some()
                || outcome.value.is_some()
                || outcome.censoring_reason.is_none()
                || finalized_at < outcome.latest_observable_at
            {
                return Err(LedgerError::OutcomeStateMismatch);
            }
        }
        AuthenticatedOutcomeTerminality::Terminal => {
            let (Some(observed_at), Some(_), Some(finalized_at)) =
                (outcome.observed_at, outcome.value, outcome.finalized_at)
            else {
                return Err(LedgerError::OutcomeStateMismatch);
            };
            if outcome.censoring_reason.is_some()
                || observed_at > outcome.latest_observable_at
                || finalized_at < observed_at
            {
                return Err(LedgerError::OutcomeStateMismatch);
            }
        }
    }
    Ok(())
}

fn validate_support_digests(event: &LedgerEvent) -> Result<(), LedgerError> {
    match event {
        LedgerEvent::Decision(value) => {
            require_digest(value.objective_digest, "objective")?;
            require_digest(value.support_digest, "decision support")?;
        }
        LedgerEvent::AuthenticatedDecisionV2(value) => {
            if value.generator_authority_epoch == 0 {
                return Err(LedgerError::InvalidAuthorityEpoch);
            }
            for (digest, label) in [
                (value.run_snapshot_digest, "run snapshot"),
                (value.objective_digest, "objective"),
                (value.policy_digest, "policy"),
                (
                    value.generator_credential_chain_digest,
                    "generator credential chain",
                ),
                (value.generator_signing_key_digest, "generator signing key"),
                (value.generator_scope_digest, "generator scope"),
                (
                    value.candidate_completeness_digest,
                    "candidate completeness",
                ),
                (value.support_digest, "decision support"),
                (value.authentication_digest, "decision authentication"),
            ] {
                require_digest(digest, label)?;
            }
        }
        LedgerEvent::Outcome(value) => {
            require_digest(value.support_digest, "outcome support")?;
        }
        LedgerEvent::Credit(value) => {
            require_digest(value.support_digest, "credit support")?;
        }
        LedgerEvent::Revocation(value) => {
            require_digest(value.reason_digest, "revocation reason")?;
        }
        LedgerEvent::AuthenticatedOutcomeV2(value) => {
            for (digest, label) in [
                (
                    value.observer_credential_chain_digest,
                    "observer credential chain",
                ),
                (value.observer_signing_key_digest, "observer signing key"),
                (value.observer_scope_digest, "observer scope"),
                (value.unit_profile_digest, "outcome unit profile"),
                (value.support_digest, "outcome support"),
                (value.expected_delay_profile_digest, "outcome delay profile"),
                (value.authentication_digest, "outcome authentication"),
            ] {
                require_digest(digest, label)?;
            }
        }
        LedgerEvent::CreditBatchV2(value) => {
            if value.allocator_authority_epoch == 0 {
                return Err(LedgerError::InvalidAuthorityEpoch);
            }
            for (digest, label) in [
                (
                    value.allocator_credential_chain_digest,
                    "allocator credential chain",
                ),
                (value.allocator_signing_key_digest, "allocator signing key"),
                (value.allocator_scope_digest, "allocator scope"),
                (value.support_digest, "credit support"),
                (value.authentication_digest, "credit authentication"),
            ] {
                require_digest(digest, label)?;
            }
        }
        LedgerEvent::UnlearningLineageV1(value) => {
            require_digest(value.reason_digest, "unlearning reason")?;
            require_digest(value.authentication_digest, "unlearning authentication")?;
        }
    }
    Ok(())
}

fn require_digest(digest: Digest32, label: &'static str) -> Result<(), LedgerError> {
    if digest.is_zero() {
        return Err(LedgerError::EmptyDigest(label));
    }
    Ok(())
}

fn normalize_event(event: &mut LedgerEvent) -> Result<(), LedgerError> {
    match event {
        LedgerEvent::Decision(decision) => {
            if decision.candidate_ids.len() > MAX_CANDIDATES {
                return Err(LedgerError::CandidateLimitExceeded);
            }
            decision.candidate_ids.sort();
            for window in decision.candidate_ids.windows(2) {
                if window[0] == window[1] {
                    return Err(LedgerError::DuplicateCandidate(window[0].to_string()));
                }
            }
        }
        LedgerEvent::AuthenticatedDecisionV2(decision) => {
            if decision.candidate_ids.len() > MAX_CANDIDATES {
                return Err(LedgerError::CandidateLimitExceeded);
            }
            decision.candidate_ids.sort();
            for window in decision.candidate_ids.windows(2) {
                if window[0] == window[1] {
                    return Err(LedgerError::DuplicateCandidate(window[0].to_string()));
                }
            }
        }
        LedgerEvent::CreditBatchV2(batch) => {
            if batch.allocations.len() > MAX_CREDIT_ALLOCATIONS {
                return Err(LedgerError::CreditBatchLimitExceeded);
            }
            batch
                .allocations
                .sort_by_key(|allocation| allocation.target_artifact_id.clone());
        }
        LedgerEvent::Outcome(_)
        | LedgerEvent::Credit(_)
        | LedgerEvent::Revocation(_)
        | LedgerEvent::AuthenticatedOutcomeV2(_)
        | LedgerEvent::UnlearningLineageV1(_) => {}
    }
    Ok(())
}

fn receipt(record: &LedgerRecord, disposition: AppendDisposition) -> AppendReceipt {
    AppendReceipt {
        disposition,
        sequence: record.sequence,
        event_digest: record.event_digest,
        chain_digest: record.chain_digest,
    }
}

#[derive(Clone, Copy)]
enum EventKind {
    Decision,
    Outcome,
    Credit,
    Revocation,
    AuthenticatedOutcomeV2,
    CreditBatchV2,
    AuthenticatedDecisionV2,
    UnlearningLineageV1,
}

const fn event_kind_code(kind: EventKind) -> u8 {
    match kind {
        EventKind::Decision => 0,
        EventKind::Outcome => 1,
        EventKind::Credit => 2,
        EventKind::Revocation => 3,
        EventKind::AuthenticatedOutcomeV2 => 4,
        EventKind::CreditBatchV2 => 5,
        EventKind::UnlearningLineageV1 => 6,
        EventKind::AuthenticatedDecisionV2 => 7,
    }
}

fn event_kind(event: &LedgerEvent) -> u8 {
    let kind = match event {
        LedgerEvent::Decision(_) => EventKind::Decision,
        LedgerEvent::Outcome(_) => EventKind::Outcome,
        LedgerEvent::Credit(_) => EventKind::Credit,
        LedgerEvent::Revocation(_) => EventKind::Revocation,
        LedgerEvent::AuthenticatedDecisionV2(_) => EventKind::AuthenticatedDecisionV2,
        LedgerEvent::AuthenticatedOutcomeV2(_) => EventKind::AuthenticatedOutcomeV2,
        LedgerEvent::CreditBatchV2(_) => EventKind::CreditBatchV2,
        LedgerEvent::UnlearningLineageV1(_) => EventKind::UnlearningLineageV1,
    };
    event_kind_code(kind)
}

fn digest_event(event: &LedgerEvent) -> Digest32 {
    Digest32::of_bytes(&encode_event(event))
}

pub(crate) fn encode_event(event: &LedgerEvent) -> Vec<u8> {
    let mut bytes = Vec::new();
    bytes.extend_from_slice(EVENT_DIGEST_DOMAIN);
    bytes.push(event_kind(event));
    match event {
        LedgerEvent::Decision(value) => push_decision(&mut bytes, value),
        LedgerEvent::Outcome(value) => push_outcome(&mut bytes, value),
        LedgerEvent::Credit(value) => push_credit(&mut bytes, value),
        LedgerEvent::Revocation(value) => push_revocation(&mut bytes, value),
        LedgerEvent::AuthenticatedDecisionV2(value) => {
            push_authenticated_decision(&mut bytes, value)
        }
        LedgerEvent::AuthenticatedOutcomeV2(value) => push_authenticated_outcome(&mut bytes, value),
        LedgerEvent::CreditBatchV2(value) => push_credit_batch(&mut bytes, value),
        LedgerEvent::UnlearningLineageV1(value) => push_unlearning(&mut bytes, value),
    }
    bytes
}

fn digest_chain(
    predecessor: Digest32,
    sequence: LogicalSequence,
    event_digest: Digest32,
) -> Digest32 {
    let mut bytes = Vec::with_capacity(CHAIN_DIGEST_DOMAIN.len() + 72);
    bytes.extend_from_slice(CHAIN_DIGEST_DOMAIN);
    bytes.extend_from_slice(predecessor.as_array());
    bytes.extend_from_slice(&sequence.get().to_be_bytes());
    bytes.extend_from_slice(event_digest.as_array());
    Digest32::of_bytes(&bytes)
}

fn push_decision(bytes: &mut Vec<u8>, value: &EpisodeDecision) {
    push_id(bytes, &value.record_id);
    push_id(bytes, &value.episode_id);
    push_digest(bytes, value.objective_digest);
    push_id(bytes, &value.policy_id);
    push_ids(bytes, &value.candidate_ids);
    push_id(bytes, &value.selected_candidate_id);
    bytes.extend_from_slice(&value.selected_propensity.raw().to_be_bytes());
    bytes.push(value.completeness.tag());
    push_digest(bytes, value.support_digest);
}

fn push_authenticated_decision(bytes: &mut Vec<u8>, value: &AuthenticatedDecisionRecordV2) {
    push_id(bytes, &value.record_id);
    push_id(bytes, &value.episode_id);
    push_digest(bytes, value.run_snapshot_digest);
    push_digest(bytes, value.objective_digest);
    push_digest(bytes, value.policy_digest);
    push_id(bytes, &value.generator_id);
    push_id(bytes, &value.generator_controller_id);
    push_digest(bytes, value.generator_credential_chain_digest);
    push_digest(bytes, value.generator_signing_key_digest);
    push_digest(bytes, value.generator_scope_digest);
    bytes.extend_from_slice(&value.generator_authority_epoch.to_be_bytes());
    push_ids(bytes, &value.candidate_ids);
    push_id(bytes, &value.selected_candidate_id);
    bytes.extend_from_slice(&value.selected_propensity.raw().to_be_bytes());
    push_digest(bytes, value.candidate_completeness_digest);
    push_digest(bytes, value.support_digest);
    push_digest(bytes, value.authentication_digest);
}

fn push_outcome(bytes: &mut Vec<u8>, value: &OutcomeObservation) {
    push_id(bytes, &value.record_id);
    push_id(bytes, &value.outcome_id);
    push_id(bytes, &value.episode_id);
    push_id(bytes, &value.observer_id);
    bytes.extend_from_slice(&value.value.raw().to_be_bytes());
    bytes.push(value.finality.tag());
    push_digest(bytes, value.support_digest);
}

fn push_authenticated_outcome(bytes: &mut Vec<u8>, value: &AuthenticatedOutcomeRecordV2) {
    push_id(bytes, &value.record_id);
    push_id(bytes, &value.outcome_id);
    push_id(bytes, &value.episode_id);
    push_id(bytes, &value.observer_id);
    push_id(bytes, &value.observer_controller_id);
    push_digest(bytes, value.observer_credential_chain_digest);
    push_digest(bytes, value.observer_signing_key_digest);
    push_digest(bytes, value.observer_scope_digest);
    bytes.extend_from_slice(&value.observer_authority_epoch.to_be_bytes());
    push_optional_u64(bytes, value.observed_at);
    push_optional_fixed(bytes, value.value);
    push_digest(bytes, value.unit_profile_digest);
    push_digest(bytes, value.support_digest);
    bytes.extend_from_slice(&value.latest_observable_at.to_be_bytes());
    push_digest(bytes, value.expected_delay_profile_digest);
    bytes.push(value.terminality.tag());
    push_optional_id(bytes, value.censoring_reason.as_ref());
    push_optional_id(bytes, value.correction_predecessor.as_ref());
    push_optional_u64(bytes, value.finalized_at);
    push_digest(bytes, value.authentication_digest);
}

fn push_credit(bytes: &mut Vec<u8>, value: &CreditAssignment) {
    push_id(bytes, &value.record_id);
    push_id(bytes, &value.credit_id);
    push_id(bytes, &value.episode_id);
    push_id(bytes, &value.outcome_id);
    push_id(bytes, &value.target_artifact_id);
    push_id(bytes, &value.allocator_id);
    bytes.extend_from_slice(&value.credit.raw().to_be_bytes());
    push_digest(bytes, value.support_digest);
}

fn push_credit_batch(bytes: &mut Vec<u8>, value: &CreditAllocationBatchRecordV2) {
    push_id(bytes, &value.record_id);
    push_id(bytes, &value.batch_id);
    push_id(bytes, &value.episode_id);
    push_id(bytes, &value.outcome_id);
    push_id(bytes, &value.allocator_id);
    push_id(bytes, &value.allocator_controller_id);
    push_digest(bytes, value.allocator_credential_chain_digest);
    push_digest(bytes, value.allocator_signing_key_digest);
    push_digest(bytes, value.allocator_scope_digest);
    bytes.extend_from_slice(&value.allocator_authority_epoch.to_be_bytes());
    bytes.extend_from_slice(&value.terminal_outcome.raw().to_be_bytes());
    push_len(bytes, value.allocations.len());
    for allocation in &value.allocations {
        push_id(bytes, &allocation.target_artifact_id);
        bytes.extend_from_slice(&allocation.credit.raw().to_be_bytes());
    }
    bytes.extend_from_slice(&value.conservation_residual.raw().to_be_bytes());
    push_digest(bytes, value.support_digest);
    push_digest(bytes, value.authentication_digest);
}

fn push_revocation(bytes: &mut Vec<u8>, value: &Revocation) {
    push_id(bytes, &value.record_id);
    push_id(bytes, &value.target_record_id);
    push_id(bytes, &value.authority_id);
    push_digest(bytes, value.reason_digest);
}

fn push_unlearning(bytes: &mut Vec<u8>, value: &UnlearningLineageEventV1) {
    push_id(bytes, &value.record_id);
    push_id(bytes, &value.lineage_id);
    push_id(bytes, &value.source_record_id);
    push_id(bytes, &value.dataset_snapshot_id);
    push_id(bytes, &value.artifact_id);
    push_id(bytes, &value.authority_id);
    push_digest(bytes, value.reason_digest);
    push_digest(bytes, value.authentication_digest);
}

fn push_ids(bytes: &mut Vec<u8>, values: &[StableId]) {
    push_len(bytes, values.len());
    for value in values {
        push_id(bytes, value);
    }
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    let raw = value.as_str().as_bytes();
    push_len(bytes, raw.len());
    bytes.extend_from_slice(raw);
}

fn push_optional_id(bytes: &mut Vec<u8>, value: Option<&StableId>) {
    match value {
        Some(value) => {
            bytes.push(1);
            push_id(bytes, value);
        }
        None => bytes.push(0),
    }
}

fn push_optional_u64(bytes: &mut Vec<u8>, value: Option<u64>) {
    match value {
        Some(value) => {
            bytes.push(1);
            bytes.extend_from_slice(&value.to_be_bytes());
        }
        None => bytes.push(0),
    }
}

fn push_optional_fixed(bytes: &mut Vec<u8>, value: Option<FixedQ32>) {
    match value {
        Some(value) => {
            bytes.push(1);
            bytes.extend_from_slice(&value.raw().to_be_bytes());
        }
        None => bytes.push(0),
    }
}

fn push_digest(bytes: &mut Vec<u8>, value: Digest32) {
    bytes.extend_from_slice(value.as_array());
}

fn push_len(bytes: &mut Vec<u8>, value: usize) {
    let converted = u32::try_from(value).unwrap_or(u32::MAX);
    bytes.extend_from_slice(&converted.to_be_bytes());
}

#[cfg(test)]
#[path = "ledger_tests.rs"]
mod tests;
