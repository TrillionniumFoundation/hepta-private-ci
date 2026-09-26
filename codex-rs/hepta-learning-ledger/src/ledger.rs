use std::collections::BTreeMap;
use std::collections::BTreeSet;

use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::LogicalSequence;
use codex_hepta_types::PromptDeliveryObservationV1 as RuntimePromptDeliveryObservationV1;
use codex_hepta_types::PromptDeliveryRejectReasonV1;
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
use crate::PromptDeliveryLineageV1;
use crate::PromptDeliveryObservation;
use crate::RetrievalAssignmentFact;
use crate::Revocation;
use crate::UnlearningLineageEventV1;

const MAX_RECORDS: usize = 1_000_000;
const MAX_CANDIDATES: usize = 128;
const MAX_RETRIEVAL_CANDIDATES: usize = 512;
const MAX_RETRIEVAL_SELECTED: usize = 16;
const MAX_CREDIT_ALLOCATIONS: usize = 256;
const EVENT_DIGEST_DOMAIN: &[u8] = b"hepta.learning-ledger.event.v1";
const CHAIN_DIGEST_DOMAIN: &[u8] = b"hepta.learning-ledger.chain.v1";

#[derive(Clone, Debug)]
struct DecisionIndex {
    record_id: StableId,
    policy_id: StableId,
    controller_id: Option<StableId>,
    credential_chain_digest: Option<Digest32>,
    signing_key_digest: Option<Digest32>,
}

#[derive(Clone, Debug)]
struct OutcomeIndex {
    record_id: StableId,
    episode_id: StableId,
    observer_id: StableId,
    controller_id: Option<StableId>,
    credential_chain_digest: Option<Digest32>,
    signing_key_digest: Option<Digest32>,
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
    record_digests: BTreeMap<StableId, (Digest32, usize)>,
    digest_positions: BTreeMap<Digest32, usize>,
    dataset_index: crate::dataset_index::DatasetRecordIndex,
    record_kinds: BTreeMap<StableId, u8>,
    decisions: BTreeMap<StableId, DecisionIndex>,
    outcomes: BTreeMap<StableId, OutcomeIndex>,
    outcome_lineage_heads: BTreeMap<StableId, StableId>,
    deliveries: BTreeMap<StableId, StableId>,
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

    /// Consume the canonical runtime.codex prompt-delivery protocol and append
    /// the learning-owned causal lineage in one validated operation.
    ///
    /// The runtime observation owns physical-delivery facts. The ledger adds
    /// only its own episode/portfolio lineage and never lets the evaluated
    /// policy certify delivery on its own behalf.
    pub fn append_runtime_prompt_delivery_v1(
        &mut self,
        lineage: PromptDeliveryLineageV1,
        observation: RuntimePromptDeliveryObservationV1,
    ) -> Result<AppendReceipt, LedgerError> {
        observation
            .validate()
            .map_err(|_| LedgerError::InvalidDeliveryObservation)?;
        if lineage.portfolio_receipt_digest.is_zero() {
            return Err(LedgerError::EmptyDigest("prompt portfolio"));
        }
        if lineage.support_digest.is_zero() {
            return Err(LedgerError::EmptyDigest("prompt delivery support"));
        }

        let context_delivery_observation_digest = observation
            .semantic_digest()
            .map_err(|_| LedgerError::InvalidDeliveryObservation)?;
        let rejected_reason_digest = observation.rejected_reason.map(rejection_digest);
        let observed_token_positions_digest = observation
            .observed_token_positions
            .as_deref()
            .and_then(token_positions_digest);
        let observer_id =
            StableId::new("runtime.codex").map_err(|_| LedgerError::InternalInvariant)?;

        self.append(LedgerEvent::PromptDelivery(PromptDeliveryObservation {
            record_id: lineage.record_id,
            episode_id: lineage.episode_id,
            compilation_id: observation.compilation_id,
            observer_id,
            portfolio_receipt_digest: lineage.portfolio_receipt_digest,
            provider_request_digest: observation.provider_request_digest,
            delivered: observation.delivered,
            rejected_reason_digest,
            observed_token_positions_digest,
            truncation_observed: observation.truncation_observed,
            context_delivery_observation_digest,
            support_digest: lineage.support_digest,
        }))
    }

    pub(crate) fn prepare(&self, mut event: LedgerEvent) -> Result<PreparedAppend, LedgerError> {
        normalize_event(&mut event)?;
        let record_id = event.record_id().clone();
        let event_digest = digest_event(&event);

        if let Some((existing_digest, position)) = self.record_digests.get(&record_id) {
            if *existing_digest != event_digest {
                return Err(LedgerError::IdentityConflict(record_id.to_string()));
            }
            let record = self
                .records
                .get(*position)
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

    /// Exact owner-local lookup through the replay-built index. It shares the
    /// same activity predicate as full projection reads; it cannot resurrect a
    /// revoked/corrected record, and never allocates the full active history.
    pub(crate) fn active_record_by_id(
        &self,
        record_id: &StableId,
    ) -> Result<Option<&LedgerRecord>, LedgerError> {
        Ok(self
            .record_by_id(record_id)?
            .filter(|record| self.record_is_active(record)))
    }

    /// Historical identity lookup, including inactive records, for exact retries.
    /// This is not active evidence and does not resurrect corrected/revoked facts.
    pub(crate) fn record_by_id(
        &self,
        record_id: &StableId,
    ) -> Result<Option<&LedgerRecord>, LedgerError> {
        let Some((digest, position)) = self.record_digests.get(record_id) else {
            return Ok(None);
        };
        let record = self
            .records
            .get(*position)
            .ok_or(LedgerError::InternalInvariant)?;
        if record.event.record_id() != record_id || record.event_digest != *digest {
            return Err(LedgerError::InternalInvariant);
        }
        Ok(Some(record))
    }

    /// Replay-derived exact content identity lookup with the same active-state
    /// predicate as projection reads. No history scan or new authority is involved.
    pub(crate) fn active_record_by_digest(
        &self,
        digest: &Digest32,
    ) -> Result<Option<&LedgerRecord>, LedgerError> {
        let Some(position) = self.digest_positions.get(digest) else {
            return Ok(None);
        };
        let record = self
            .records
            .get(*position)
            .ok_or(LedgerError::InternalInvariant)?;
        if record.event_digest != *digest {
            return Err(LedgerError::InternalInvariant);
        }
        Ok(self.record_is_active(record).then_some(record))
    }

    pub(crate) fn active_authenticated_decision(
        &self,
        episode_id: &StableId,
    ) -> Result<Option<&AuthenticatedDecisionRecordV2>, LedgerError> {
        let Some(indexed) = self.decisions.get(episode_id) else {
            return Ok(None);
        };
        let Some(record) = self.active_record_by_id(&indexed.record_id)? else {
            return Ok(None);
        };
        match &record.event {
            LedgerEvent::AuthenticatedDecisionV2(value) if &value.episode_id == episode_id => {
                Ok(Some(value))
            }
            LedgerEvent::Decision(_) => Ok(None),
            _ => Err(LedgerError::InternalInvariant),
        }
    }

    /// Returns facts that remain causally effective after corrections,
    /// revocations and explicit unlearning lineage have been applied.
    #[must_use]
    pub fn active_records(&self) -> Vec<&LedgerRecord> {
        self.active_records_iter().collect()
    }

    /// Borrow the same activity predicate without allocating a global pointer
    /// list when an owner operation only needs a sequential projection pass.
    pub(crate) fn active_records_iter(&self) -> impl Iterator<Item = &LedgerRecord> {
        self.records
            .iter()
            .filter(|record| self.record_is_active(record))
    }

    /// Dataset-only authenticated history for one objective, in append order.
    /// These private offsets are populated only together with the records; no
    /// caller or persisted checkpoint may supply an index or suppress an event.
    pub(crate) fn records_for_objective(
        &self,
        objective: &Digest32,
    ) -> impl Iterator<Item = &LedgerRecord> {
        self.dataset_index
            .objective(objective)
            .iter()
            .map(|position| &self.records[*position])
    }

    pub(crate) fn active_records_for_objective(
        &self,
        objective: &Digest32,
    ) -> impl Iterator<Item = &LedgerRecord> {
        self.records_for_objective(objective)
            .filter(|record| self.record_is_active(record))
    }

    pub(crate) fn dataset_revocations(&self) -> impl Iterator<Item = &LedgerRecord> {
        self.dataset_index
            .revocations()
            .iter()
            .map(|position| &self.records[*position])
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
            LedgerEvent::RetrievalAssignment(value) => self.validate_retrieval_assignment(value),
            LedgerEvent::Outcome(value) => self.validate_outcome(value),
            LedgerEvent::Credit(value) => self.validate_credit(value),
            LedgerEvent::PromptDelivery(value) => self.validate_prompt_delivery(value),
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

    fn validate_retrieval_assignment(
        &self,
        assignment: &RetrievalAssignmentFact,
    ) -> Result<(), LedgerError> {
        if assignment.enumerated_candidate_digests.len() > MAX_RETRIEVAL_CANDIDATES
            || assignment.selected_candidate_indices.len() > MAX_RETRIEVAL_SELECTED
            || assignment.delivered_candidate_indices.len() > MAX_RETRIEVAL_SELECTED
        {
            return Err(LedgerError::RetrievalCandidateLimitExceeded);
        }
        if assignment.assignment_propensity.raw() == 0 {
            return Err(LedgerError::ZeroSelectedPropensity);
        }
        if assignment.delivery_propensity.raw() == 0 {
            return Err(LedgerError::ZeroDeliveryPropensity);
        }
        let candidate_count = assignment.enumerated_candidate_digests.len();
        for index in assignment
            .legal_candidate_indices
            .iter()
            .chain(assignment.selected_candidate_indices.iter())
            .chain(assignment.delivered_candidate_indices.iter())
        {
            if usize::try_from(*index).unwrap_or(usize::MAX) >= candidate_count {
                return Err(LedgerError::RetrievalIndexOutOfRange);
            }
        }
        let legal = assignment
            .legal_candidate_indices
            .iter()
            .copied()
            .collect::<BTreeSet<_>>();
        if assignment
            .selected_candidate_indices
            .iter()
            .any(|index| !legal.contains(index))
        {
            return Err(LedgerError::RetrievalSelectionOutsideLegal);
        }
        let selected = assignment
            .selected_candidate_indices
            .iter()
            .copied()
            .collect::<BTreeSet<_>>();
        if assignment
            .delivered_candidate_indices
            .iter()
            .any(|index| !selected.contains(index))
        {
            return Err(LedgerError::RetrievalDeliveryOutsideSelection);
        }
        if assignment.context_exposed == assignment.delivered_candidate_indices.is_empty()
            || assignment.context_exposed != assignment.published_context_digest.is_some()
        {
            return Err(LedgerError::RetrievalExposureStateMismatch);
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
        if decision.controller_id.is_none()
            || decision.credential_chain_digest.is_none()
            || decision.signing_key_digest.is_none()
        {
            return Err(LedgerError::AuthenticatedDecisionRequired(
                outcome.episode_id.to_string(),
            ));
        }
        if decision.policy_id == outcome.observer_id
            || decision.controller_id.as_ref() == Some(&outcome.observer_controller_id)
            || decision.credential_chain_digest == Some(outcome.observer_credential_chain_digest)
            || decision.signing_key_digest == Some(outcome.observer_signing_key_digest)
        {
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

    fn validate_prompt_delivery(
        &self,
        delivery: &PromptDeliveryObservation,
    ) -> Result<(), LedgerError> {
        if self.deliveries.contains_key(&delivery.episode_id) {
            return Err(LedgerError::DeliveryAlreadyExists(
                delivery.episode_id.to_string(),
            ));
        }
        let decision = self
            .decisions
            .get(&delivery.episode_id)
            .ok_or_else(|| LedgerError::EpisodeNotFound(delivery.episode_id.to_string()))?;
        if self.revoked.contains(&decision.record_id) {
            return Err(LedgerError::EpisodeRevoked(delivery.episode_id.to_string()));
        }
        if decision.policy_id == delivery.observer_id {
            return Err(LedgerError::PolicySelfObservesDelivery);
        }
        if (delivery.delivered && delivery.rejected_reason_digest.is_some())
            || (!delivery.delivered && delivery.rejected_reason_digest.is_none())
        {
            return Err(LedgerError::InvalidDeliveryObservation);
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
        if decision.controller_id.is_none()
            || decision.credential_chain_digest.is_none()
            || decision.signing_key_digest.is_none()
        {
            return Err(LedgerError::AuthenticatedDecisionRequired(
                batch.episode_id.to_string(),
            ));
        }
        let outcome = self.effective_outcome(&batch.outcome_id)?;
        if outcome.controller_id.is_none()
            || outcome.credential_chain_digest.is_none()
            || outcome.signing_key_digest.is_none()
        {
            return Err(LedgerError::AuthenticatedOutcomeRequired(
                batch.outcome_id.to_string(),
            ));
        }
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
            || decision.credential_chain_digest == Some(batch.allocator_credential_chain_digest)
            || outcome.credential_chain_digest == Some(batch.allocator_credential_chain_digest)
            || decision.signing_key_digest == Some(batch.allocator_signing_key_digest)
            || outcome.signing_key_digest == Some(batch.allocator_signing_key_digest)
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
        if self
            .record_digests
            .get(&value.source_record_id)
            .map(|(digest, _)| digest)
            != Some(&value.source_event_digest)
        {
            return Err(LedgerError::UnlearningSourceDigestMismatch);
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
        self.dataset_index.append(&record.event, self.records.len());
        self.digest_positions
            .insert(record.event_digest, self.records.len());
        let record_id = record.event.record_id().clone();
        self.record_digests
            .insert(record_id.clone(), (record.event_digest, self.records.len()));
        self.record_kinds
            .insert(record_id, event_kind(&record.event));
        match &record.event {
            LedgerEvent::RetrievalAssignment(_) => {}
            LedgerEvent::Decision(value) => {
                self.decisions.insert(
                    value.episode_id.clone(),
                    DecisionIndex {
                        record_id: value.record_id.clone(),
                        policy_id: value.policy_id.clone(),
                        controller_id: None,
                        credential_chain_digest: None,
                        signing_key_digest: None,
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
                        credential_chain_digest: Some(value.generator_credential_chain_digest),
                        signing_key_digest: Some(value.generator_signing_key_digest),
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
                        credential_chain_digest: None,
                        signing_key_digest: None,
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
                        credential_chain_digest: Some(value.observer_credential_chain_digest),
                        signing_key_digest: Some(value.observer_signing_key_digest),
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
            LedgerEvent::PromptDelivery(value) => {
                self.deliveries
                    .insert(value.episode_id.clone(), value.record_id.clone());
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
            LedgerEvent::Decision(_)
            | LedgerEvent::AuthenticatedDecisionV2(_)
            | LedgerEvent::RetrievalAssignment(_) => true,
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
            LedgerEvent::PromptDelivery(delivery) => self
                .decisions
                .get(&delivery.episode_id)
                .is_some_and(|decision| !self.revoked.contains(&decision.record_id)),
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

fn rejection_digest(reason: PromptDeliveryRejectReasonV1) -> Digest32 {
    let mut bytes = b"hepta.learning-ledger.prompt-delivery-rejection.v1".to_vec();
    bytes.extend_from_slice(reason.as_str().as_bytes());
    Digest32::of_bytes(&bytes)
}

fn token_positions_digest(positions: &[u32]) -> Option<Digest32> {
    if positions.is_empty() {
        return None;
    }
    let mut bytes = b"hepta.learning-ledger.prompt-token-positions.v1".to_vec();
    bytes.extend_from_slice(
        &u32::try_from(positions.len())
            .unwrap_or(u32::MAX)
            .to_be_bytes(),
    );
    for position in positions {
        bytes.extend_from_slice(&position.to_be_bytes());
    }
    Some(Digest32::of_bytes(&bytes))
}

fn validate_support_digests(event: &LedgerEvent) -> Result<(), LedgerError> {
    match event {
        LedgerEvent::RetrievalAssignment(value) => {
            for (name, digest) in [
                ("retrieval cue", value.cue_digest),
                ("retrieval policy", value.policy_digest),
                (
                    "retrieval source completeness",
                    value.source_completeness_digest,
                ),
                ("retrieval candidate union", value.candidate_union_digest),
                ("retrieval recall packet", value.recall_packet_digest),
                ("retrieval assignment support", value.support_digest),
            ] {
                if digest.is_zero() {
                    return Err(LedgerError::EmptyDigest(name));
                }
            }
            if value
                .published_context_digest
                .is_some_and(Digest32::is_zero)
            {
                return Err(LedgerError::EmptyDigest("retrieval published context"));
            }
            if value
                .downstream_policy_digest
                .is_some_and(Digest32::is_zero)
            {
                return Err(LedgerError::EmptyDigest("retrieval downstream policy"));
            }
            if value
                .enumerated_candidate_digests
                .iter()
                .any(|digest| digest.is_zero())
            {
                return Err(LedgerError::EmptyDigest("retrieval candidate identity"));
            }
        }
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
        LedgerEvent::PromptDelivery(value) => {
            for (name, digest) in [
                ("prompt portfolio", value.portfolio_receipt_digest),
                ("provider request", value.provider_request_digest),
                (
                    "context delivery observation",
                    value.context_delivery_observation_digest,
                ),
                ("prompt delivery support", value.support_digest),
            ] {
                if digest.is_zero() {
                    return Err(LedgerError::EmptyDigest(name));
                }
            }
            for (name, digest) in [
                ("prompt delivery rejection", value.rejected_reason_digest),
                (
                    "prompt token positions",
                    value.observed_token_positions_digest,
                ),
            ] {
                if digest.is_some_and(Digest32::is_zero) {
                    return Err(LedgerError::EmptyDigest(name));
                }
            }
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
            require_digest(value.source_event_digest, "unlearning source event")?;
            require_digest(value.dataset_digest, "unlearning dataset")?;
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
        LedgerEvent::RetrievalAssignment(assignment) => {
            if assignment.enumerated_candidate_digests.len() > MAX_RETRIEVAL_CANDIDATES {
                return Err(LedgerError::RetrievalCandidateLimitExceeded);
            }
            // Every index refers to an identity, not its pre-normalization slot.
            // Reorder the bounded identity vector and remap all three index sets
            // together, so sorting cannot change which memory was delivered.
            let original = &assignment.enumerated_candidate_digests;
            let mut order: Vec<usize> = (0..original.len()).collect();
            order.sort_by_key(|index| original[*index]);
            let mut remapped = vec![0_u32; original.len()];
            for (canonical_index, original_index) in order.iter().copied().enumerate() {
                remapped[original_index] = u32::try_from(canonical_index)
                    .map_err(|_| LedgerError::RetrievalIndexOutOfRange)?;
            }
            let canonical = order.iter().map(|index| original[*index]).collect();
            for indices in [
                &mut assignment.legal_candidate_indices,
                &mut assignment.selected_candidate_indices,
                &mut assignment.delivered_candidate_indices,
            ] {
                for index in indices {
                    let original_index = usize::try_from(*index)
                        .map_err(|_| LedgerError::RetrievalIndexOutOfRange)?;
                    *index = *remapped
                        .get(original_index)
                        .ok_or(LedgerError::RetrievalIndexOutOfRange)?;
                }
            }
            assignment.enumerated_candidate_digests = canonical;
            if assignment
                .enumerated_candidate_digests
                .windows(2)
                .any(|pair| pair[0] == pair[1])
            {
                return Err(LedgerError::DuplicateCandidate(
                    "retrieval-candidate-digest".to_string(),
                ));
            }
            assignment.legal_candidate_indices.sort_unstable();
            assignment.selected_candidate_indices.sort_unstable();
            assignment.delivered_candidate_indices.sort_unstable();
            if assignment
                .legal_candidate_indices
                .windows(2)
                .any(|pair| pair[0] == pair[1])
                || assignment
                    .selected_candidate_indices
                    .windows(2)
                    .any(|pair| pair[0] == pair[1])
                || assignment
                    .delivered_candidate_indices
                    .windows(2)
                    .any(|pair| pair[0] == pair[1])
            {
                return Err(LedgerError::DuplicateRetrievalIndex);
            }
        }
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
        | LedgerEvent::UnlearningLineageV1(_)
        | LedgerEvent::PromptDelivery(_) => {}
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
    RetrievalAssignment,
    PromptDelivery,
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
        EventKind::PromptDelivery => 8,
        // 0..=8 are reserved for the canonical decision/outcome/prompt formats.
        EventKind::RetrievalAssignment => 9,
    }
}

fn event_kind(event: &LedgerEvent) -> u8 {
    let kind = match event {
        LedgerEvent::Decision(_) => EventKind::Decision,
        LedgerEvent::RetrievalAssignment(_) => EventKind::RetrievalAssignment,
        LedgerEvent::Outcome(_) => EventKind::Outcome,
        LedgerEvent::Credit(_) => EventKind::Credit,
        LedgerEvent::PromptDelivery(_) => EventKind::PromptDelivery,
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
        LedgerEvent::RetrievalAssignment(value) => push_retrieval_assignment(&mut bytes, value),
        LedgerEvent::Outcome(value) => push_outcome(&mut bytes, value),
        LedgerEvent::Credit(value) => push_credit(&mut bytes, value),
        LedgerEvent::PromptDelivery(value) => push_prompt_delivery(&mut bytes, value),
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

fn push_retrieval_assignment(bytes: &mut Vec<u8>, value: &RetrievalAssignmentFact) {
    push_id(bytes, &value.record_id);
    push_id(bytes, &value.episode_id);
    push_digest(bytes, value.cue_digest);
    push_digest(bytes, value.policy_digest);
    push_digest(bytes, value.source_completeness_digest);
    push_digest(bytes, value.candidate_union_digest);
    push_digest(bytes, value.recall_packet_digest);
    push_len(bytes, value.enumerated_candidate_digests.len());
    for digest in &value.enumerated_candidate_digests {
        push_digest(bytes, *digest);
    }
    push_len(bytes, value.legal_candidate_indices.len());
    for index in &value.legal_candidate_indices {
        bytes.extend_from_slice(&index.to_be_bytes());
    }
    push_len(bytes, value.selected_candidate_indices.len());
    for index in &value.selected_candidate_indices {
        bytes.extend_from_slice(&index.to_be_bytes());
    }
    push_len(bytes, value.delivered_candidate_indices.len());
    for index in &value.delivered_candidate_indices {
        bytes.extend_from_slice(&index.to_be_bytes());
    }
    bytes.push(u8::from(value.context_exposed));
    match value.published_context_digest {
        Some(digest) => {
            bytes.push(1);
            push_digest(bytes, digest);
        }
        None => bytes.push(0),
    }
    bytes.extend_from_slice(&value.omitted_by_policy_limits.to_be_bytes());
    bytes.extend_from_slice(&value.assignment_propensity.raw().to_be_bytes());
    match value.downstream_policy_digest {
        Some(digest) => {
            bytes.push(1);
            push_digest(bytes, digest);
        }
        None => bytes.push(0),
    }
    bytes.extend_from_slice(&value.delivery_propensity.raw().to_be_bytes());
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

fn push_prompt_delivery(bytes: &mut Vec<u8>, value: &PromptDeliveryObservation) {
    push_id(bytes, &value.record_id);
    push_id(bytes, &value.episode_id);
    push_id(bytes, &value.compilation_id);
    push_id(bytes, &value.observer_id);
    push_digest(bytes, value.portfolio_receipt_digest);
    push_digest(bytes, value.provider_request_digest);
    bytes.push(u8::from(value.delivered));
    push_optional_digest(bytes, value.rejected_reason_digest);
    push_optional_digest(bytes, value.observed_token_positions_digest);
    bytes.push(u8::from(value.truncation_observed));
    push_digest(bytes, value.context_delivery_observation_digest);
    push_digest(bytes, value.support_digest);
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
    push_digest(bytes, value.source_event_digest);
    push_id(bytes, &value.dataset_snapshot_id);
    push_digest(bytes, value.dataset_digest);
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

fn push_optional_digest(bytes: &mut Vec<u8>, value: Option<Digest32>) {
    match value {
        Some(digest) => {
            bytes.push(1);
            push_digest(bytes, digest);
        }
        None => bytes.push(0),
    }
}

fn push_len(bytes: &mut Vec<u8>, value: usize) {
    let converted = u32::try_from(value).unwrap_or(u32::MAX);
    bytes.extend_from_slice(&converted.to_be_bytes());
}

#[cfg(test)]
#[path = "ledger_tests.rs"]
mod tests;
