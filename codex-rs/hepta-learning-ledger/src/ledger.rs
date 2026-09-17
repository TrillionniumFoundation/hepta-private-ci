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
use crate::AuthenticatedPrincipalV1;
use crate::CandidateSetCompleteness;
use crate::ConservedCreditBatchRecordV2;
use crate::CreditAssignment;
use crate::EpisodeDecision;
use crate::LedgerError;
use crate::LedgerEvent;
use crate::LedgerRecord;
use crate::LedgerSnapshot;
use crate::OutcomeFinality;
use crate::OutcomeObservation;
use crate::OutcomeTerminalityV1;
use crate::Revocation;
use crate::finalize_credit_batch;
use crate::validate_candidate_set_completeness;

const MAX_RECORDS: usize = 1_000_000;
const MAX_CANDIDATES: usize = 128;
const MAX_DURABLE_CREDIT_ALLOCATIONS: usize = 224;
const EVENT_DIGEST_DOMAIN: &[u8] = b"hepta.learning-ledger.event.v1";
const CHAIN_DIGEST_DOMAIN: &[u8] = b"hepta.learning-ledger.chain.v1";

#[derive(Clone, Debug)]
struct DecisionIndex {
    record_id: StableId,
    policy_id: StableId,
    generator: Option<AuthenticatedPrincipalV1>,
}

#[derive(Clone, Debug)]
struct OutcomeIndex {
    record_id: StableId,
    episode_id: StableId,
    terminal: bool,
    value: Option<FixedQ32>,
}

/// Validated immutable event prepared for a single-writer commit.
pub(crate) struct PreparedAppend {
    pub(crate) record: LedgerRecord,
    pub(crate) disposition: AppendDisposition,
}

/// Deterministic append-only ledger core. The type performs no ambient I/O and
/// exposes immutable snapshots for a separately authorized durable adapter.
#[derive(Clone, Debug, Default)]
pub struct LearningLedger {
    records: Vec<LedgerRecord>,
    record_digests: BTreeMap<StableId, Digest32>,
    record_kinds: BTreeMap<StableId, u8>,
    decisions: BTreeMap<StableId, DecisionIndex>,
    outcomes: BTreeMap<StableId, OutcomeIndex>,
    credit_ids: BTreeSet<StableId>,
    credit_keys: BTreeSet<(StableId, StableId, StableId)>,
    revoked: BTreeSet<StableId>,
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

    /// Returns facts that remain causally effective after applying revocation
    /// edges. Outcomes and credit disappear when their decision ancestor is
    /// revoked, preventing restore-time resurrection.
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
            LedgerEvent::AuthenticatedDecision(value) => {
                self.validate_authenticated_decision(value)
            }
            LedgerEvent::AuthenticatedOutcome(value) => {
                self.validate_authenticated_outcome(value)
            }
            LedgerEvent::ConservedCreditBatch(value) => self.validate_credit_batch(value),
        }
    }

    fn validate_decision(&self, decision: &EpisodeDecision) -> Result<(), LedgerError> {
        if decision.completeness != CandidateSetCompleteness::Complete {
            return Err(LedgerError::IncompleteCandidateSet);
        }
        self.validate_decision_fields(
            &decision.episode_id,
            &decision.candidate_ids,
            &decision.selected_candidate_id,
            decision.selected_propensity.raw(),
        )
    }

    fn validate_authenticated_decision(
        &self,
        decision: &AuthenticatedDecisionRecordV2,
    ) -> Result<(), LedgerError> {
        decision
            .generator
            .validate(decision.generator.authenticated_at)
            .map_err(|_| LedgerError::InvalidAuthenticatedDecision)?;
        validate_candidate_set_completeness(&decision.completeness)
            .map_err(|_| LedgerError::InvalidAuthenticatedDecision)?;
        if decision.completeness.generator_id != decision.generator.principal_id
            || usize::try_from(decision.completeness.candidate_count).ok()
                != Some(decision.candidate_ids.len())
        {
            return Err(LedgerError::InvalidAuthenticatedDecision);
        }
        self.validate_decision_fields(
            &decision.episode_id,
            &decision.candidate_ids,
            &decision.selected_candidate_id,
            decision.selected_propensity.raw(),
        )
    }

    fn validate_decision_fields(
        &self,
        episode_id: &StableId,
        candidate_ids: &[StableId],
        selected_candidate_id: &StableId,
        selected_propensity_raw: u64,
    ) -> Result<(), LedgerError> {
        if candidate_ids.is_empty() {
            return Err(LedgerError::EmptyCandidateSet);
        }
        if candidate_ids.len() > MAX_CANDIDATES {
            return Err(LedgerError::CandidateLimitExceeded);
        }
        if !candidate_ids
            .iter()
            .any(|candidate| candidate.as_str() == "abstain")
        {
            return Err(LedgerError::MissingAbstainCandidate);
        }
        if !candidate_ids.contains(selected_candidate_id) {
            return Err(LedgerError::SelectedCandidateMissing(
                selected_candidate_id.to_string(),
            ));
        }
        if selected_propensity_raw == 0 {
            return Err(LedgerError::ZeroSelectedPropensity);
        }
        if self.decisions.contains_key(episode_id) {
            return Err(LedgerError::EpisodeAlreadyExists(episode_id.to_string()));
        }
        Ok(())
    }

    fn validate_outcome(&self, outcome: &OutcomeObservation) -> Result<(), LedgerError> {
        if self.outcomes.contains_key(&outcome.outcome_id) {
            return Err(LedgerError::OutcomeAlreadyExists(
                outcome.outcome_id.to_string(),
            ));
        }
        let decision = self
            .decisions
            .get(&outcome.episode_id)
            .ok_or_else(|| LedgerError::EpisodeNotFound(outcome.episode_id.to_string()))?;
        if self.revoked.contains(&decision.record_id) {
            return Err(LedgerError::EpisodeRevoked(outcome.episode_id.to_string()));
        }
        if decision.policy_id == outcome.observer_id {
            return Err(LedgerError::PolicySelfLabelsOutcome);
        }
        Ok(())
    }

    fn validate_authenticated_outcome(
        &self,
        record: &AuthenticatedOutcomeRecordV2,
    ) -> Result<(), LedgerError> {
        let outcome = &record.outcome;
        if self.outcomes.contains_key(&outcome.outcome_id) {
            return Err(LedgerError::OutcomeAlreadyExists(
                outcome.outcome_id.to_string(),
            ));
        }
        outcome
            .observer
            .validate(outcome.observer.authenticated_at)
            .map_err(|_| LedgerError::InvalidAuthenticatedDecision)?;
        validate_historical_outcome_state(outcome)?;
        let decision = self
            .decisions
            .get(&outcome.episode_id)
            .ok_or_else(|| LedgerError::EpisodeNotFound(outcome.episode_id.to_string()))?;
        if self.revoked.contains(&decision.record_id) {
            return Err(LedgerError::EpisodeRevoked(outcome.episode_id.to_string()));
        }
        if let Some(generator) = &decision.generator {
            if principals_collide(generator, &outcome.observer) {
                return Err(LedgerError::PolicySelfLabelsOutcome);
            }
        } else if decision.policy_id == outcome.observer.principal_id {
            return Err(LedgerError::PolicySelfLabelsOutcome);
        }
        if let Some(predecessor) = &outcome.watermark.correction_predecessor {
            let previous = self.outcomes.get(predecessor).ok_or_else(|| {
                LedgerError::CorrectionPredecessorNotFound(predecessor.to_string())
            })?;
            if previous.episode_id != outcome.episode_id {
                return Err(LedgerError::CorrectionEpisodeMismatch);
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
        let decision = self
            .decisions
            .get(&credit.episode_id)
            .ok_or_else(|| LedgerError::EpisodeNotFound(credit.episode_id.to_string()))?;
        if self.revoked.contains(&decision.record_id) {
            return Err(LedgerError::EpisodeRevoked(credit.episode_id.to_string()));
        }
        let outcome = self
            .outcomes
            .get(&credit.outcome_id)
            .ok_or_else(|| LedgerError::OutcomeNotFound(credit.outcome_id.to_string()))?;
        if self.revoked.contains(&outcome.record_id) {
            return Err(LedgerError::OutcomeRevoked(credit.outcome_id.to_string()));
        }
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
        record: &ConservedCreditBatchRecordV2,
    ) -> Result<(), LedgerError> {
        let batch = &record.batch;
        if self.credit_ids.contains(&batch.batch_id) {
            return Err(LedgerError::CreditIdentityAlreadyExists(
                batch.batch_id.to_string(),
            ));
        }
        if !batch.finalized {
            return Err(LedgerError::CreditConservation);
        }
        let finalized = finalize_credit_batch(batch.clone(), batch.allocator.authenticated_at)
            .map_err(|_| LedgerError::CreditConservation)?;
        if finalized.batch_digest != record.batch_digest {
            return Err(LedgerError::CreditConservation);
        }
        if batch.allocations.is_empty() {
            return Err(LedgerError::CreditBatchEmpty);
        }
        if batch.allocations.len() > MAX_DURABLE_CREDIT_ALLOCATIONS {
            return Err(LedgerError::CreditBatchLimitExceeded);
        }
        batch
            .allocator
            .validate(batch.allocator.authenticated_at)
            .map_err(|_| LedgerError::InvalidAuthenticatedDecision)?;
        let decision = self
            .decisions
            .get(&batch.episode_id)
            .ok_or_else(|| LedgerError::EpisodeNotFound(batch.episode_id.to_string()))?;
        if self.revoked.contains(&decision.record_id) {
            return Err(LedgerError::EpisodeRevoked(batch.episode_id.to_string()));
        }
        if let Some(generator) = &decision.generator
            && principals_collide(generator, &batch.allocator)
        {
            return Err(LedgerError::PolicySelfAssignsCredit);
        }
        let outcome = self
            .outcomes
            .get(&batch.outcome_id)
            .ok_or_else(|| LedgerError::OutcomeNotFound(batch.outcome_id.to_string()))?;
        if self.revoked.contains(&outcome.record_id) {
            return Err(LedgerError::OutcomeRevoked(batch.outcome_id.to_string()));
        }
        if outcome.episode_id != batch.episode_id {
            return Err(LedgerError::OutcomeEpisodeMismatch);
        }
        if !outcome.terminal {
            return Err(LedgerError::OutcomeNotTerminal);
        }
        if outcome.value != Some(batch.terminal_outcome) {
            return Err(LedgerError::TerminalOutcomeMismatch);
        }
        let allocated = batch.allocations.iter().try_fold(0_i128, |sum, allocation| {
            sum.checked_add(i128::from(allocation.credit.raw()))
                .ok_or(LedgerError::CreditConservation)
        })?;
        let conserved = allocated
            .checked_add(i128::from(batch.conservation_residual.raw()))
            .ok_or(LedgerError::CreditConservation)?;
        if conserved != i128::from(batch.terminal_outcome.raw()) {
            return Err(LedgerError::CreditConservation);
        }
        for allocation in &batch.allocations {
            let key = (
                batch.episode_id.clone(),
                batch.outcome_id.clone(),
                allocation.target_id.clone(),
            );
            if self.credit_keys.contains(&key) {
                return Err(LedgerError::CreditAlreadyAssigned);
            }
        }
        Ok(())
    }

    fn validate_revocation(&self, revocation: &Revocation) -> Result<(), LedgerError> {
        let Some(kind) = self.record_kinds.get(&revocation.target_record_id) else {
            return Err(LedgerError::TargetNotFound(
                revocation.target_record_id.to_string(),
            ));
        };
        if *kind == event_kind_code(EventKind::Revocation) {
            return Err(LedgerError::RevocationOfRevocation);
        }
        if self.revoked.contains(&revocation.target_record_id) {
            return Err(LedgerError::TargetAlreadyRevoked(
                revocation.target_record_id.to_string(),
            ));
        }
        Ok(())
    }

    fn index_record(&mut self, record: &LedgerRecord) {
        let record_id = record.event.record_id().clone();
        self.record_digests
            .insert(record_id.clone(), record.event_digest);
        self.record_kinds.insert(record_id, event_kind(&record.event));
        match &record.event {
            LedgerEvent::Decision(value) => {
                self.decisions.insert(
                    value.episode_id.clone(),
                    DecisionIndex {
                        record_id: value.record_id.clone(),
                        policy_id: value.policy_id.clone(),
                        generator: None,
                    },
                );
            }
            LedgerEvent::AuthenticatedDecision(value) => {
                self.decisions.insert(
                    value.episode_id.clone(),
                    DecisionIndex {
                        record_id: value.record_id.clone(),
                        policy_id: value.policy_id.clone(),
                        generator: Some(value.generator.clone()),
                    },
                );
            }
            LedgerEvent::Outcome(value) => {
                self.outcomes.insert(
                    value.outcome_id.clone(),
                    OutcomeIndex {
                        record_id: value.record_id.clone(),
                        episode_id: value.episode_id.clone(),
                        terminal: value.finality == OutcomeFinality::Terminal,
                        value: Some(value.value),
                    },
                );
            }
            LedgerEvent::AuthenticatedOutcome(value) => {
                self.outcomes.insert(
                    value.outcome.outcome_id.clone(),
                    OutcomeIndex {
                        record_id: value.outcome.record_id.clone(),
                        episode_id: value.outcome.episode_id.clone(),
                        terminal: value.outcome.watermark.terminality
                            == OutcomeTerminalityV1::Terminal,
                        value: value.outcome.value,
                    },
                );
            }
            LedgerEvent::Credit(value) => {
                self.credit_ids.insert(value.credit_id.clone());
                self.credit_keys.insert((
                    value.episode_id.clone(),
                    value.outcome_id.clone(),
                    value.target_artifact_id.clone(),
                ));
            }
            LedgerEvent::ConservedCreditBatch(value) => {
                self.credit_ids.insert(value.batch.batch_id.clone());
                for allocation in &value.batch.allocations {
                    self.credit_keys.insert((
                        value.batch.episode_id.clone(),
                        value.batch.outcome_id.clone(),
                        allocation.target_id.clone(),
                    ));
                }
            }
            LedgerEvent::Revocation(value) => {
                self.revoked.insert(value.target_record_id.clone());
            }
        }
    }

    fn record_is_active(&self, record: &LedgerRecord) -> bool {
        let record_id = record.event.record_id();
        if self.revoked.contains(record_id) {
            return false;
        }
        match &record.event {
            LedgerEvent::Decision(_) | LedgerEvent::AuthenticatedDecision(_) => true,
            LedgerEvent::Outcome(outcome) => self
                .decisions
                .get(&outcome.episode_id)
                .is_some_and(|decision| !self.revoked.contains(&decision.record_id)),
            LedgerEvent::AuthenticatedOutcome(outcome) => self
                .decisions
                .get(&outcome.outcome.episode_id)
                .is_some_and(|decision| !self.revoked.contains(&decision.record_id)),
            LedgerEvent::Credit(credit) => {
                self.credit_ancestry_active(&credit.episode_id, &credit.outcome_id)
            }
            LedgerEvent::ConservedCreditBatch(credit) => {
                self.credit_ancestry_active(&credit.batch.episode_id, &credit.batch.outcome_id)
            }
            LedgerEvent::Revocation(_) => true,
        }
    }

    fn credit_ancestry_active(&self, episode_id: &StableId, outcome_id: &StableId) -> bool {
        let decision_active = self
            .decisions
            .get(episode_id)
            .is_some_and(|decision| !self.revoked.contains(&decision.record_id));
        let outcome_active = self
            .outcomes
            .get(outcome_id)
            .is_some_and(|outcome| !self.revoked.contains(&outcome.record_id));
        decision_active && outcome_active
    }
}

fn validate_historical_outcome_state(
    outcome: &crate::AuthenticatedOutcomeV1,
) -> Result<(), LedgerError> {
    if outcome.unit_profile_digest.is_zero()
        || outcome.support_digest.is_zero()
        || outcome.watermark.expected_delay_profile_digest.is_zero()
    {
        return Err(LedgerError::EmptyDigest("authenticated outcome"));
    }
    let watermark = &outcome.watermark;
    match watermark.terminality {
        OutcomeTerminalityV1::Pending => {
            if outcome.observed_at.is_some()
                || outcome.value.is_some()
                || watermark.finalized_at.is_some()
                || watermark.censoring_reason.is_some()
                || watermark.correction_predecessor.is_some()
            {
                return Err(LedgerError::InvalidAuthenticatedDecision);
            }
        }
        OutcomeTerminalityV1::Censored => {
            let Some(finalized_at) = watermark.finalized_at else {
                return Err(LedgerError::InvalidAuthenticatedDecision);
            };
            if outcome.observed_at.is_some()
                || outcome.value.is_some()
                || watermark.censoring_reason.is_none()
                || finalized_at < watermark.latest_observable_at
            {
                return Err(LedgerError::InvalidAuthenticatedDecision);
            }
        }
        OutcomeTerminalityV1::Terminal => {
            let (Some(observed_at), Some(_), Some(finalized_at)) =
                (outcome.observed_at, outcome.value, watermark.finalized_at)
            else {
                return Err(LedgerError::InvalidAuthenticatedDecision);
            };
            if watermark.censoring_reason.is_some()
                || observed_at > watermark.latest_observable_at
                || finalized_at < observed_at
            {
                return Err(LedgerError::InvalidAuthenticatedDecision);
            }
        }
    }
    Ok(())
}

fn principals_collide(left: &AuthenticatedPrincipalV1, right: &AuthenticatedPrincipalV1) -> bool {
    left.principal_id == right.principal_id
        || left.credential_chain_digest == right.credential_chain_digest
        || left.signing_key_digest == right.signing_key_digest
}

fn validate_support_digests(event: &LedgerEvent) -> Result<(), LedgerError> {
    match event {
        LedgerEvent::Decision(value) => {
            if value.objective_digest.is_zero() {
                return Err(LedgerError::EmptyDigest("objective"));
            }
            if value.support_digest.is_zero() {
                return Err(LedgerError::EmptyDigest("decision support"));
            }
        }
        LedgerEvent::Outcome(value) => {
            if value.support_digest.is_zero() {
                return Err(LedgerError::EmptyDigest("outcome support"));
            }
        }
        LedgerEvent::Credit(value) => {
            if value.support_digest.is_zero() {
                return Err(LedgerError::EmptyDigest("credit support"));
            }
        }
        LedgerEvent::Revocation(value) => {
            if value.reason_digest.is_zero() {
                return Err(LedgerError::EmptyDigest("revocation reason"));
            }
        }
        LedgerEvent::AuthenticatedDecision(value) => {
            if value.objective_digest.is_zero() || value.evidence_digest.is_zero() {
                return Err(LedgerError::EmptyDigest("authenticated decision"));
            }
        }
        LedgerEvent::AuthenticatedOutcome(value) => {
            if value.evidence_digest.is_zero() {
                return Err(LedgerError::EmptyDigest("authenticated outcome evidence"));
            }
        }
        LedgerEvent::ConservedCreditBatch(value) => {
            if value.batch.support_digest.is_zero()
                || value.batch_digest.is_zero()
                || value.evidence_digest.is_zero()
            {
                return Err(LedgerError::EmptyDigest("conserved credit"));
            }
        }
    }
    Ok(())
}

fn normalize_event(event: &mut LedgerEvent) -> Result<(), LedgerError> {
    match event {
        LedgerEvent::Decision(decision) => normalize_candidate_ids(&mut decision.candidate_ids),
        LedgerEvent::AuthenticatedDecision(decision) => {
            normalize_candidate_ids(&mut decision.candidate_ids)
        }
        LedgerEvent::ConservedCreditBatch(record) => {
            if record.batch.allocations.len() > MAX_DURABLE_CREDIT_ALLOCATIONS {
                return Err(LedgerError::CreditBatchLimitExceeded);
            }
            record
                .batch
                .allocations
                .sort_by_key(|allocation| allocation.target_id.clone());
            for window in record.batch.allocations.windows(2) {
                if window[0].target_id == window[1].target_id {
                    return Err(LedgerError::DuplicateCreditTarget(
                        window[0].target_id.to_string(),
                    ));
                }
            }
            Ok(())
        }
        LedgerEvent::Outcome(_)
        | LedgerEvent::Credit(_)
        | LedgerEvent::Revocation(_)
        | LedgerEvent::AuthenticatedOutcome(_) => Ok(()),
    }
}

fn normalize_candidate_ids(candidate_ids: &mut Vec<StableId>) -> Result<(), LedgerError> {
    if candidate_ids.len() > MAX_CANDIDATES {
        return Err(LedgerError::CandidateLimitExceeded);
    }
    candidate_ids.sort();
    for window in candidate_ids.windows(2) {
        if window[0] == window[1] {
            return Err(LedgerError::DuplicateCandidate(window[0].to_string()));
        }
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
    AuthenticatedDecision,
    AuthenticatedOutcome,
    ConservedCreditBatch,
}

const fn event_kind_code(kind: EventKind) -> u8 {
    match kind {
        EventKind::Decision => 0,
        EventKind::Outcome => 1,
        EventKind::Credit => 2,
        EventKind::Revocation => 3,
        EventKind::AuthenticatedDecision => 4,
        EventKind::AuthenticatedOutcome => 5,
        EventKind::ConservedCreditBatch => 6,
    }
}

fn event_kind(event: &LedgerEvent) -> u8 {
    let kind = match event {
        LedgerEvent::Decision(_) => EventKind::Decision,
        LedgerEvent::Outcome(_) => EventKind::Outcome,
        LedgerEvent::Credit(_) => EventKind::Credit,
        LedgerEvent::Revocation(_) => EventKind::Revocation,
        LedgerEvent::AuthenticatedDecision(_) => EventKind::AuthenticatedDecision,
        LedgerEvent::AuthenticatedOutcome(_) => EventKind::AuthenticatedOutcome,
        LedgerEvent::ConservedCreditBatch(_) => EventKind::ConservedCreditBatch,
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
        LedgerEvent::AuthenticatedDecision(value) => {
            push_authenticated_decision(&mut bytes, value)
        }
        LedgerEvent::AuthenticatedOutcome(value) => {
            push_authenticated_outcome(&mut bytes, value)
        }
        LedgerEvent::ConservedCreditBatch(value) => {
            push_conserved_credit_batch(&mut bytes, value)
        }
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
    push_digest(bytes, value.objective_digest);
    push_id(bytes, &value.policy_id);
    push_principal(bytes, &value.generator);
    push_candidate_receipt(bytes, &value.completeness);
    push_ids(bytes, &value.candidate_ids);
    push_id(bytes, &value.selected_candidate_id);
    bytes.extend_from_slice(&value.selected_propensity.raw().to_be_bytes());
    push_digest(bytes, value.evidence_digest);
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
    let outcome = &value.outcome;
    push_id(bytes, &outcome.record_id);
    push_id(bytes, &outcome.outcome_id);
    push_id(bytes, &outcome.episode_id);
    push_principal(bytes, &outcome.observer);
    push_optional_u64(bytes, outcome.observed_at);
    push_optional_fixed(bytes, outcome.value);
    push_digest(bytes, outcome.unit_profile_digest);
    push_digest(bytes, outcome.support_digest);
    bytes.extend_from_slice(&outcome.watermark.latest_observable_at.to_be_bytes());
    push_digest(bytes, outcome.watermark.expected_delay_profile_digest);
    bytes.push(match outcome.watermark.terminality {
        OutcomeTerminalityV1::Pending => 0,
        OutcomeTerminalityV1::Censored => 1,
        OutcomeTerminalityV1::Terminal => 2,
    });
    push_optional_id(bytes, outcome.watermark.censoring_reason.as_ref());
    push_optional_id(bytes, outcome.watermark.correction_predecessor.as_ref());
    push_optional_u64(bytes, outcome.watermark.finalized_at);
    push_digest(bytes, value.evidence_digest);
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

fn push_conserved_credit_batch(bytes: &mut Vec<u8>, value: &ConservedCreditBatchRecordV2) {
    push_id(bytes, &value.record_id);
    let batch = &value.batch;
    push_id(bytes, &batch.batch_id);
    push_id(bytes, &batch.episode_id);
    push_id(bytes, &batch.outcome_id);
    push_principal(bytes, &batch.allocator);
    bytes.extend_from_slice(&batch.terminal_outcome.raw().to_be_bytes());
    push_len(bytes, batch.allocations.len());
    for allocation in &batch.allocations {
        push_id(bytes, &allocation.target_id);
        bytes.extend_from_slice(&allocation.credit.raw().to_be_bytes());
    }
    bytes.extend_from_slice(&batch.conservation_residual.raw().to_be_bytes());
    push_digest(bytes, batch.support_digest);
    bytes.push(u8::from(batch.finalized));
    push_digest(bytes, value.batch_digest);
    push_digest(bytes, value.evidence_digest);
}

fn push_revocation(bytes: &mut Vec<u8>, value: &Revocation) {
    push_id(bytes, &value.record_id);
    push_id(bytes, &value.target_record_id);
    push_id(bytes, &value.authority_id);
    push_digest(bytes, value.reason_digest);
}

fn push_principal(bytes: &mut Vec<u8>, value: &AuthenticatedPrincipalV1) {
    push_id(bytes, &value.principal_id);
    push_digest(bytes, value.credential_chain_digest);
    push_digest(bytes, value.signing_key_digest);
    push_digest(bytes, value.scope_digest);
    bytes.extend_from_slice(&value.authority_epoch.to_be_bytes());
    bytes.extend_from_slice(&value.authenticated_at.to_be_bytes());
    bytes.extend_from_slice(&value.expires_at.to_be_bytes());
}

fn push_candidate_receipt(bytes: &mut Vec<u8>, value: &crate::CandidateSetCompletenessReceiptV1) {
    push_id(bytes, &value.set_id);
    push_digest(bytes, value.state_digest);
    push_id(bytes, &value.generator_id);
    push_digest(bytes, value.generator_code_digest);
    push_digest(bytes, value.grammar_digest);
    push_digest(bytes, value.hard_filter_digest);
    push_digest(bytes, value.truncation_digest);
    push_digest(bytes, value.candidates_digest);
    bytes.extend_from_slice(&value.candidate_count.to_be_bytes());
    bytes.extend_from_slice(&value.omitted_count_bound.to_be_bytes());
    push_digest(bytes, value.canonical_order_digest);
    bytes.push(u8::from(value.complete_for_generator));
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
