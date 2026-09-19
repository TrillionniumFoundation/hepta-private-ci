use std::collections::BTreeMap;
use std::collections::BTreeSet;

use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::LogicalSequence;
use codex_hepta_types::StableId;

use crate::AppendDisposition;
use crate::AppendReceipt;
use crate::AuthenticatedOutcomeV1;
use crate::CandidateSetCompleteness;
use crate::CreditAllocationBatchV1;
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
use crate::UnlearningLineageEventV1;

const MAX_RECORDS: usize = 1_000_000;
const MAX_CANDIDATES: usize = 128;
const EVENT_DIGEST_DOMAIN: &[u8] = b"hepta.learning-ledger.event.v1";
const CHAIN_DIGEST_DOMAIN: &[u8] = b"hepta.learning-ledger.chain.v1";

#[derive(Clone, Debug)]
struct DecisionIndex {
    record_id: StableId,
    policy_id: StableId,
}

#[derive(Clone, Debug)]
struct OutcomeIndex {
    record_id: StableId,
    episode_id: StableId,
    terminal: bool,
    value_raw: Option<i64>,
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
    outcome_heads: BTreeMap<StableId, StableId>,
    credit_ids: BTreeSet<StableId>,
    credit_keys: BTreeSet<(StableId, StableId, StableId)>,
    revoked: BTreeSet<StableId>,
    unlearning_heads: BTreeMap<StableId, StableId>,
    unlearning_records: BTreeMap<StableId, StableId>,
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

    #[must_use]
    pub fn head_digest(&self) -> Digest32 {
        self.records
            .last()
            .map_or(Digest32::ZERO, |record| record.chain_digest)
    }

    #[must_use]
    pub fn head_sequence(&self) -> u64 {
        self.records.last().map_or(0, |record| record.sequence.get())
    }

    #[must_use]
    pub fn dataset_source_record_digests(&self) -> Vec<Digest32> {
        self.records
            .iter()
            .filter(|record| self.record_is_active(record))
            .filter(|record| {
                matches!(
                    record.event,
                    LedgerEvent::Decision(_)
                        | LedgerEvent::Outcome(_)
                        | LedgerEvent::Credit(_)
                        | LedgerEvent::AuthenticatedOutcome(_)
                        | LedgerEvent::CreditBatch(_)
                )
            })
            .map(|record| record.event_digest)
            .collect()
    }

    #[must_use]
    pub fn correction_cut_digest(&self) -> Digest32 {
        let mut bytes = b"hepta.learning-ledger.correction-cut.v1".to_vec();
        for (episode_id, outcome_id) in &self.outcome_heads {
            push_id(&mut bytes, episode_id);
            push_id(&mut bytes, outcome_id);
        }
        Digest32::of_bytes(&bytes)
    }

    #[must_use]
    pub fn revocation_cut_digest(&self) -> Digest32 {
        let mut bytes = b"hepta.learning-ledger.revocation-cut.v1".to_vec();
        for record_id in &self.revoked {
            push_id(&mut bytes, record_id);
        }
        Digest32::of_bytes(&bytes)
    }

    #[must_use]
    pub fn outcome_state_counts(&self) -> (u32, u32) {
        let mut pending = 0_u32;
        let mut censored = 0_u32;
        for record in &self.records {
            if !self.record_is_active(record) {
                continue;
            }
            match &record.event {
                LedgerEvent::Outcome(value) if value.finality == OutcomeFinality::Intermediate => {
                    pending = pending.saturating_add(1);
                }
                LedgerEvent::AuthenticatedOutcome(value) => match value.watermark.terminality {
                    OutcomeTerminalityV1::Pending => pending = pending.saturating_add(1),
                    OutcomeTerminalityV1::Censored => censored = censored.saturating_add(1),
                    OutcomeTerminalityV1::Terminal => {}
                },
                _ => {}
            }
        }
        (pending, censored)
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
            LedgerEvent::AuthenticatedOutcome(value) => self.validate_authenticated_outcome(value),
            LedgerEvent::CreditBatch(value) => self.validate_credit_batch(value),
            LedgerEvent::UnlearningLineage(value) => self.validate_unlearning_lineage(value),
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

    fn validate_authenticated_outcome(
        &self,
        outcome: &AuthenticatedOutcomeV1,
    ) -> Result<(), LedgerError> {
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
        if decision.policy_id == outcome.observer.principal_id {
            return Err(LedgerError::PolicySelfLabelsOutcome);
        }

        match outcome.watermark.correction_predecessor.as_ref() {
            Some(predecessor) => {
                if predecessor == &outcome.outcome_id {
                    return Err(LedgerError::CorrectionSelfReference);
                }
                let prior = self.outcomes.get(predecessor).ok_or_else(|| {
                    LedgerError::CorrectionPredecessorNotFound(predecessor.to_string())
                })?;
                if prior.episode_id != outcome.episode_id {
                    return Err(LedgerError::CorrectionEpisodeMismatch);
                }
                let current = self.outcome_heads.get(&outcome.episode_id).ok_or_else(|| {
                    LedgerError::CorrectionNotHead(predecessor.to_string())
                })?;
                if current != predecessor {
                    return Err(LedgerError::CorrectionNotHead(predecessor.to_string()));
                }
            }
            None => {
                if let Some(current) = self.outcome_heads.get(&outcome.episode_id) {
                    return Err(LedgerError::CorrectionPredecessorRequired(
                        current.to_string(),
                    ));
                }
            }
        }
        Ok(())
    }

    fn validate_credit_batch(&self, batch: &CreditAllocationBatchV1) -> Result<(), LedgerError> {
        if !batch.finalized {
            return Err(LedgerError::CreditBatchNotFinalized);
        }
        if batch.allocations.is_empty() {
            return Err(LedgerError::CreditBatchEmpty);
        }
        if batch.allocations.len() > 256 {
            return Err(LedgerError::CreditBatchLimitExceeded);
        }

        let decision = self
            .decisions
            .get(&batch.episode_id)
            .ok_or_else(|| LedgerError::EpisodeNotFound(batch.episode_id.to_string()))?;
        if self.revoked.contains(&decision.record_id) {
            return Err(LedgerError::EpisodeRevoked(batch.episode_id.to_string()));
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
        if outcome.value_raw != Some(batch.terminal_outcome.raw()) {
            return Err(LedgerError::CreditConservation);
        }

        let mut allocated = 0_i128;
        let mut last_target: Option<&StableId> = None;
        for allocation in &batch.allocations {
            if last_target == Some(&allocation.target_id) {
                return Err(LedgerError::DuplicateCreditTarget(
                    allocation.target_id.to_string(),
                ));
            }
            last_target = Some(&allocation.target_id);
            allocated = allocated
                .checked_add(i128::from(allocation.credit.raw()))
                .ok_or(LedgerError::CreditConservation)?;
            let key = (
                batch.episode_id.clone(),
                batch.outcome_id.clone(),
                allocation.target_id.clone(),
            );
            if self.credit_keys.contains(&key) {
                return Err(LedgerError::CreditAlreadyAssigned);
            }
        }
        let conserved = allocated
            .checked_add(i128::from(batch.conservation_residual.raw()))
            .ok_or(LedgerError::CreditConservation)?;
        if conserved != i128::from(batch.terminal_outcome.raw()) {
            return Err(LedgerError::CreditConservation);
        }
        Ok(())
    }

    fn validate_unlearning_lineage(
        &self,
        lineage: &UnlearningLineageEventV1,
    ) -> Result<(), LedgerError> {
        if !self.record_digests.contains_key(&lineage.source_record_id)
            || !self.revoked.contains(&lineage.source_record_id)
        {
            return Err(LedgerError::UnlearningSourceNotRevoked(
                lineage.source_record_id.to_string(),
            ));
        }
        match lineage.predecessor.as_ref() {
            Some(predecessor) => {
                if predecessor == &lineage.record_id {
                    return Err(LedgerError::UnlearningSelfReference);
                }
                let prior_derived = self.unlearning_records.get(predecessor).ok_or_else(|| {
                    LedgerError::UnlearningPredecessorNotFound(predecessor.to_string())
                })?;
                if prior_derived != &lineage.derived_id {
                    return Err(LedgerError::UnlearningPredecessorMismatch);
                }
                let current = self.unlearning_heads.get(&lineage.derived_id).ok_or_else(|| {
                    LedgerError::UnlearningNotHead(predecessor.to_string())
                })?;
                if current != predecessor {
                    return Err(LedgerError::UnlearningNotHead(predecessor.to_string()));
                }
            }
            None => {
                if let Some(current) = self.unlearning_heads.get(&lineage.derived_id) {
                    return Err(LedgerError::UnlearningPredecessorRequired(
                        current.to_string(),
                    ));
                }
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
        if *kind == event_kind_code(EventKind::Revocation)
            || *kind == event_kind_code(EventKind::UnlearningLineage)
        {
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
        self.record_kinds
            .insert(record_id, event_kind(&record.event));
        match &record.event {
            LedgerEvent::Decision(value) => {
                self.decisions.insert(
                    value.episode_id.clone(),
                    DecisionIndex {
                        record_id: value.record_id.clone(),
                        policy_id: value.policy_id.clone(),
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
                        value_raw: Some(value.value.raw()),
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
            LedgerEvent::Revocation(value) => {
                self.revoked.insert(value.target_record_id.clone());
            }
            LedgerEvent::AuthenticatedOutcome(value) => {
                self.outcomes.insert(
                    value.outcome_id.clone(),
                    OutcomeIndex {
                        record_id: value.record_id.clone(),
                        episode_id: value.episode_id.clone(),
                        terminal: value.watermark.terminality == OutcomeTerminalityV1::Terminal,
                        value_raw: value.value.map(|item| item.raw()),
                    },
                );
                self.outcome_heads
                    .insert(value.episode_id.clone(), value.outcome_id.clone());
            }
            LedgerEvent::CreditBatch(value) => {
                self.credit_ids.insert(value.batch_id.clone());
                for allocation in &value.allocations {
                    self.credit_keys.insert((
                        value.episode_id.clone(),
                        value.outcome_id.clone(),
                        allocation.target_id.clone(),
                    ));
                }
            }
            LedgerEvent::UnlearningLineage(value) => {
                self.unlearning_heads
                    .insert(value.derived_id.clone(), value.record_id.clone());
                self.unlearning_records
                    .insert(value.record_id.clone(), value.derived_id.clone());
            }
        }
    }

    fn record_is_active(&self, record: &LedgerRecord) -> bool {
        let record_id = record.event.record_id();
        if self.revoked.contains(record_id) {
            return false;
        }
        match &record.event {
            LedgerEvent::Decision(_) => true,
            LedgerEvent::Outcome(outcome) => self
                .decisions
                .get(&outcome.episode_id)
                .is_some_and(|decision| !self.revoked.contains(&decision.record_id)),
            LedgerEvent::Credit(credit) => {
                let decision_active = self
                    .decisions
                    .get(&credit.episode_id)
                    .is_some_and(|decision| !self.revoked.contains(&decision.record_id));
                let outcome_active = self
                    .outcomes
                    .get(&credit.outcome_id)
                    .is_some_and(|outcome| !self.revoked.contains(&outcome.record_id));
                decision_active && outcome_active
            }
            LedgerEvent::Revocation(_) => true,
            LedgerEvent::AuthenticatedOutcome(outcome) => self
                .decisions
                .get(&outcome.episode_id)
                .is_some_and(|decision| !self.revoked.contains(&decision.record_id)),
            LedgerEvent::CreditBatch(batch) => {
                let decision_active = self
                    .decisions
                    .get(&batch.episode_id)
                    .is_some_and(|decision| !self.revoked.contains(&decision.record_id));
                let outcome_active = self
                    .outcomes
                    .get(&batch.outcome_id)
                    .is_some_and(|outcome| !self.revoked.contains(&outcome.record_id));
                decision_active && outcome_active
            }
            LedgerEvent::UnlearningLineage(_) => true,
        }
    }
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
        LedgerEvent::AuthenticatedOutcome(value) => {
            if value.unit_profile_digest.is_zero() {
                return Err(LedgerError::EmptyDigest("outcome unit profile"));
            }
            if value.support_digest.is_zero() {
                return Err(LedgerError::EmptyDigest("outcome support"));
            }
            if value.observer.credential_chain_digest.is_zero()
                || value.observer.signing_key_digest.is_zero()
                || value.observer.scope_digest.is_zero()
            {
                return Err(LedgerError::EmptyDigest("authenticated observer"));
            }
            if value.watermark.expected_delay_profile_digest.is_zero() {
                return Err(LedgerError::EmptyDigest("expected delay profile"));
            }
        }
        LedgerEvent::CreditBatch(value) => {
            if value.support_digest.is_zero() {
                return Err(LedgerError::EmptyDigest("credit support"));
            }
            if value.allocator.credential_chain_digest.is_zero()
                || value.allocator.signing_key_digest.is_zero()
                || value.allocator.scope_digest.is_zero()
            {
                return Err(LedgerError::EmptyDigest("authenticated allocator"));
            }
        }
        LedgerEvent::UnlearningLineage(value) => {
            if value.reason_digest.is_zero() {
                return Err(LedgerError::EmptyDigest("unlearning reason"));
            }
            if value.source_digest.is_zero() {
                return Err(LedgerError::EmptyDigest("unlearning source"));
            }
            if value.derived_digest.is_zero() {
                return Err(LedgerError::EmptyDigest("unlearning derived object"));
            }
        }
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
        LedgerEvent::CreditBatch(batch) => {
            if batch.allocations.len() > 256 {
                return Err(LedgerError::CreditBatchLimitExceeded);
            }
            batch.allocations
                .sort_by_key(|allocation| allocation.target_id.clone());
            for window in batch.allocations.windows(2) {
                if window[0].target_id == window[1].target_id {
                    return Err(LedgerError::DuplicateCreditTarget(
                        window[0].target_id.to_string(),
                    ));
                }
            }
        }
        _ => {}
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
    AuthenticatedOutcome,
    CreditBatch,
    UnlearningLineage,
}

const fn event_kind_code(kind: EventKind) -> u8 {
    match kind {
        EventKind::Decision => 0,
        EventKind::Outcome => 1,
        EventKind::Credit => 2,
        EventKind::Revocation => 3,
        EventKind::AuthenticatedOutcome => 4,
        EventKind::CreditBatch => 5,
        EventKind::UnlearningLineage => 6,
    }
}

fn event_kind(event: &LedgerEvent) -> u8 {
    let kind = match event {
        LedgerEvent::Decision(_) => EventKind::Decision,
        LedgerEvent::Outcome(_) => EventKind::Outcome,
        LedgerEvent::Credit(_) => EventKind::Credit,
        LedgerEvent::Revocation(_) => EventKind::Revocation,
        LedgerEvent::AuthenticatedOutcome(_) => EventKind::AuthenticatedOutcome,
        LedgerEvent::CreditBatch(_) => EventKind::CreditBatch,
        LedgerEvent::UnlearningLineage(_) => EventKind::UnlearningLineage,
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
        LedgerEvent::AuthenticatedOutcome(value) => push_authenticated_outcome(&mut bytes, value),
        LedgerEvent::CreditBatch(value) => push_credit_batch(&mut bytes, value),
        LedgerEvent::UnlearningLineage(value) => push_unlearning_lineage(&mut bytes, value),
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

fn push_outcome(bytes: &mut Vec<u8>, value: &OutcomeObservation) {
    push_id(bytes, &value.record_id);
    push_id(bytes, &value.outcome_id);
    push_id(bytes, &value.episode_id);
    push_id(bytes, &value.observer_id);
    bytes.extend_from_slice(&value.value.raw().to_be_bytes());
    bytes.push(value.finality.tag());
    push_digest(bytes, value.support_digest);
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

fn push_revocation(bytes: &mut Vec<u8>, value: &Revocation) {
    push_id(bytes, &value.record_id);
    push_id(bytes, &value.target_record_id);
    push_id(bytes, &value.authority_id);
    push_digest(bytes, value.reason_digest);
}

fn push_principal(bytes: &mut Vec<u8>, value: &crate::AuthenticatedPrincipalV1) {
    push_id(bytes, &value.principal_id);
    push_digest(bytes, value.credential_chain_digest);
    push_digest(bytes, value.signing_key_digest);
    push_digest(bytes, value.scope_digest);
    bytes.extend_from_slice(&value.authority_epoch.to_be_bytes());
    bytes.extend_from_slice(&value.authenticated_at.to_be_bytes());
    bytes.extend_from_slice(&value.expires_at.to_be_bytes());
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

fn push_authenticated_outcome(bytes: &mut Vec<u8>, value: &AuthenticatedOutcomeV1) {
    push_id(bytes, &value.record_id);
    push_id(bytes, &value.outcome_id);
    push_id(bytes, &value.episode_id);
    push_principal(bytes, &value.observer);
    push_optional_u64(bytes, value.observed_at);
    push_optional_fixed(bytes, value.value);
    push_digest(bytes, value.unit_profile_digest);
    push_digest(bytes, value.support_digest);
    bytes.extend_from_slice(&value.watermark.latest_observable_at.to_be_bytes());
    push_digest(bytes, value.watermark.expected_delay_profile_digest);
    bytes.push(value.watermark.terminality.tag());
    push_optional_id(bytes, value.watermark.censoring_reason.as_ref());
    push_optional_id(bytes, value.watermark.correction_predecessor.as_ref());
    push_optional_u64(bytes, value.watermark.finalized_at);
}

fn push_credit_batch(bytes: &mut Vec<u8>, value: &CreditAllocationBatchV1) {
    push_id(bytes, &value.batch_id);
    push_id(bytes, &value.episode_id);
    push_id(bytes, &value.outcome_id);
    push_principal(bytes, &value.allocator);
    bytes.extend_from_slice(&value.terminal_outcome.raw().to_be_bytes());
    push_len(bytes, value.allocations.len());
    for allocation in &value.allocations {
        push_id(bytes, &allocation.target_id);
        bytes.extend_from_slice(&allocation.credit.raw().to_be_bytes());
    }
    bytes.extend_from_slice(&value.conservation_residual.raw().to_be_bytes());
    push_digest(bytes, value.support_digest);
    bytes.push(u8::from(value.finalized));
}

fn push_unlearning_lineage(bytes: &mut Vec<u8>, value: &UnlearningLineageEventV1) {
    push_id(bytes, &value.record_id);
    push_id(bytes, &value.source_record_id);
    push_id(bytes, &value.derived_id);
    bytes.push(value.derived_kind.tag());
    push_optional_id(bytes, value.predecessor.as_ref());
    push_id(bytes, &value.authority_id);
    push_digest(bytes, value.reason_digest);
    push_digest(bytes, value.source_digest);
    push_digest(bytes, value.derived_digest);
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
