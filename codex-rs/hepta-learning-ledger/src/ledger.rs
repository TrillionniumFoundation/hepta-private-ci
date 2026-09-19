use std::collections::BTreeMap;
use std::collections::BTreeSet;

use codex_hepta_types::Digest32;
use codex_hepta_types::LogicalSequence;
use codex_hepta_types::StableId;

use crate::AppendDisposition;
use crate::AppendReceipt;
use crate::CandidateSetCompleteness;
use crate::CreditAssignment;
use crate::EpisodeDecision;
use crate::LedgerError;
use crate::LedgerEvent;
use crate::LedgerRecord;
use crate::LedgerSnapshot;
use crate::OutcomeFinality;
use crate::OutcomeObservation;
use crate::Revocation;
use crate::RunStartPublicationV1;

const MAX_RECORDS: usize = 1_000_000;
const MAX_CANDIDATES: usize = 128;
const EVENT_DIGEST_DOMAIN: &[u8] = b"hepta.learning-ledger.event.v1";
const CHAIN_DIGEST_DOMAIN: &[u8] = b"hepta.learning-ledger.chain.v1";

#[derive(Clone, Debug)]
pub(crate) struct HistoricalRecordIndex {
    pub(crate) sequence: LogicalSequence,
    pub(crate) predecessor_chain_digest: Digest32,
    pub(crate) event_digest: Digest32,
    pub(crate) chain_digest: Digest32,
    pub(crate) kind: u8,
}

#[derive(Clone, Debug)]
pub(crate) struct DecisionIndex {
    pub(crate) record_id: StableId,
    pub(crate) policy_id: StableId,
}

#[derive(Clone, Debug)]
pub(crate) struct OutcomeIndex {
    pub(crate) record_id: StableId,
    pub(crate) episode_id: StableId,
    pub(crate) finality: OutcomeFinality,
}

/// Validated immutable event prepared for a single-writer commit.
pub(crate) struct PreparedAppend {
    pub(crate) record: LedgerRecord,
    pub(crate) disposition: AppendDisposition,
}

/// Deterministic append-only ledger core. The type performs no ambient I/O.
///
/// The core separates complete causal indexes from retained event payloads. A
/// durable segmented owner can therefore archive an immutable prefix and drop
/// its full `LedgerRecord` payloads without resetting sequence, idempotency,
/// revocation, outcome or credit semantics. Pure in-memory users never invoke
/// that crate-private compaction seam and retain the historical API unchanged.
#[derive(Clone, Debug)]
pub struct LearningLedger {
    /// Full payloads retained since the latest durable archive frontier.
    pub(crate) records: Vec<LedgerRecord>,
    /// Record identities whose complete payload is still present in `records`.
    pub(crate) record_positions: BTreeMap<StableId, usize>,
    /// Compact immutable identity metadata for the complete logical history.
    pub(crate) record_index: BTreeMap<StableId, HistoricalRecordIndex>,
    /// Sequence-to-chain lookup retained independently from event payloads.
    pub(crate) sequence_digests: BTreeMap<u64, Digest32>,
    pub(crate) run_starts: BTreeMap<StableId, StableId>,
    pub(crate) decisions: BTreeMap<StableId, DecisionIndex>,
    pub(crate) outcomes: BTreeMap<StableId, OutcomeIndex>,
    pub(crate) credit_ids: BTreeSet<StableId>,
    pub(crate) credit_keys: BTreeSet<(StableId, StableId, StableId)>,
    pub(crate) revoked: BTreeSet<StableId>,
    /// Last sequence whose complete payload was released to durable archive.
    pub(crate) archived_through_sequence: u64,
    pub(crate) archived_through_digest: Digest32,
}

impl Default for LearningLedger {
    fn default() -> Self {
        Self {
            records: Vec::new(),
            record_positions: BTreeMap::new(),
            record_index: BTreeMap::new(),
            sequence_digests: BTreeMap::new(),
            run_starts: BTreeMap::new(),
            decisions: BTreeMap::new(),
            outcomes: BTreeMap::new(),
            credit_ids: BTreeSet::new(),
            credit_keys: BTreeSet::new(),
            revoked: BTreeSet::new(),
            archived_through_sequence: 0,
            archived_through_digest: Digest32::ZERO,
        }
    }
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

        if let Some(existing) = self.record_index.get(&record_id) {
            if existing.event_digest != event_digest {
                return Err(LedgerError::IdentityConflict(record_id.to_string()));
            }
            let record = if let Some(position) = self.record_positions.get(&record_id).copied() {
                self.records
                    .get(position)
                    .filter(|record| record.event.record_id() == &record_id)
                    .cloned()
                    .ok_or(LedgerError::InternalInvariant)?
            } else {
                // The full payload is archived. The caller supplied the same
                // canonical event (its digest matched above), so reconstructing
                // immutable record metadata is sufficient for an exact replay
                // receipt without paging historical payloads back into memory.
                LedgerRecord {
                    sequence: existing.sequence,
                    predecessor_chain_digest: existing.predecessor_chain_digest,
                    event_digest: existing.event_digest,
                    chain_digest: existing.chain_digest,
                    event,
                }
            };
            return Ok(PreparedAppend {
                record,
                disposition: AppendDisposition::IdempotentReplay,
            });
        }

        if self.records.len() >= MAX_RECORDS {
            return Err(LedgerError::RecordLimitExceeded);
        }
        self.validate_event(&event)?;
        let sequence_value = match self.head_sequence() {
            Some(sequence) => sequence
                .get()
                .checked_add(1)
                .ok_or(LedgerError::SequenceOverflow)?,
            None => 1,
        };
        let sequence =
            LogicalSequence::new(sequence_value).map_err(|_| LedgerError::SequenceOverflow)?;
        let predecessor_chain_digest = self.head_digest();
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
            let expected_sequence = match self.head_sequence() {
                Some(sequence) => sequence
                    .get()
                    .checked_add(1)
                    .ok_or(LedgerError::SequenceOverflow)?,
                None => 1,
            };
            if record.predecessor_chain_digest != self.head_digest()
                || record.sequence.get() != expected_sequence
            {
                return Err(LedgerError::InternalInvariant);
            }
            self.index_record(&record);
            self.records.push(record);
        }
        Ok(result)
    }

    /// Retained payload tail. Pure in-memory ledgers retain the complete history;
    /// segmented durable ledgers may retain only the current unarchived tail.
    #[must_use]
    pub fn records(&self) -> &[LedgerRecord] {
        &self.records
    }

    /// Resolve a record only when its full payload is resident. Durable owners
    /// expose a separate disk-backed archive lookup for compacted history.
    #[must_use]
    pub fn record(&self, record_id: &StableId) -> Option<&LedgerRecord> {
        self.record_positions
            .get(record_id)
            .and_then(|position| self.records.get(*position))
            .filter(|record| record.event.record_id() == record_id)
    }

    /// Current committed sequence without cloning historical records.
    #[must_use]
    pub fn head_sequence(&self) -> Option<LogicalSequence> {
        self.records
            .last()
            .map(|record| record.sequence)
            .or_else(|| {
                LogicalSequence::new(self.archived_through_sequence)
                    .ok()
                    .filter(|_| self.archived_through_sequence != 0)
            })
    }

    /// Current causal chain head without cloning historical records.
    #[must_use]
    pub fn head_digest(&self) -> Digest32 {
        self.records
            .last()
            .map_or(self.archived_through_digest, |record| record.chain_digest)
    }

    /// Borrow a bounded incremental range from the retained payload tail after
    /// `sequence`. When a caller asks before the archive frontier, the returned
    /// slice starts at the first retained record; durable owners must use their
    /// archive API to obtain the missing prefix.
    #[must_use]
    pub fn records_after(
        &self,
        sequence: Option<LogicalSequence>,
        limit: usize,
    ) -> &[LedgerRecord] {
        let requested = sequence.map_or(self.archived_through_sequence, LogicalSequence::get);
        let first_retained = self.archived_through_sequence.saturating_add(1);
        let start = if requested < first_retained {
            0
        } else {
            usize::try_from(requested.saturating_sub(self.archived_through_sequence))
                .unwrap_or(usize::MAX)
                .min(self.records.len())
        };
        let end = start.saturating_add(limit).min(self.records.len());
        &self.records[start..end]
    }

    /// Returns causally effective records from the resident payload set. Pure
    /// in-memory ledgers contain the full history; a segmented durable owner
    /// reconstructs archived payloads explicitly when a complete view is needed.
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
            head_digest: self.head_digest(),
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
        if ledger.head_digest() != expected_head {
            return Err(LedgerError::SnapshotHeadMismatch);
        }
        Ok(ledger)
    }

    /// Release full payloads through the current head after their containing
    /// segments have become immutable durable archive. Compact causal indexes
    /// remain resident and are independently checkpointable.
    pub(crate) fn compact_retained_payloads(&mut self) {
        let Some(last) = self.records.last() else {
            return;
        };
        self.archived_through_sequence = last.sequence.get();
        self.archived_through_digest = last.chain_digest;
        self.records = Vec::new();
        self.record_positions.clear();
    }

    #[must_use]
    pub(crate) fn retained_record_count(&self) -> usize {
        self.records.len()
    }

    fn validate_event(&self, event: &LedgerEvent) -> Result<(), LedgerError> {
        validate_support_digests(event)?;
        match event {
            LedgerEvent::RunStart(value) => self.validate_run_start(value),
            LedgerEvent::Decision(value) => self.validate_decision(value),
            LedgerEvent::Outcome(value) => self.validate_outcome(value),
            LedgerEvent::Credit(value) => self.validate_credit(value),
            LedgerEvent::Revocation(value) => self.validate_revocation(value),
        }
    }

    fn validate_run_start(&self, publication: &RunStartPublicationV1) -> Result<(), LedgerError> {
        if publication.admission.authority.grants_any() {
            return Err(LedgerError::InvalidRunStart("admission grants authority"));
        }
        if publication.compile.disposition != codex_hepta_objective::CompileDisposition::Compiled {
            return Err(LedgerError::InvalidRunStart(
                "compile disposition is not compiled",
            ));
        }
        if !publication.compile.removed_action_ids.is_empty() {
            return Err(LedgerError::InvalidRunStart(
                "successful compile removed requested actions",
            ));
        }
        codex_hepta_objective::validate_compiled_objective_v1(&publication.compile.objective)
            .map_err(|_| LedgerError::InvalidRunStart("compiled objective validation failed"))?;

        let objective_v1 = codex_hepta_objective::ObjectiveFunctionV1::from_canonical_json(
            &publication.objective_v1_json,
        )
        .map_err(|_| LedgerError::InvalidRunStart("canonical objective decode failed"))?;
        let canonical_digest = objective_v1
            .digest()
            .map_err(|_| LedgerError::InvalidRunStart("canonical objective digest failed"))?;
        if canonical_digest != publication.objective_v1_digest
            || objective_v1.objective_id
                != format!(
                    "objective.{}",
                    publication.compile.objective.semantic_digest
                )
            || objective_v1.request_digest != publication.admission.intent_digest.to_string()
            || objective_v1.principal_scope.scope_id
                != publication.compile.objective.principal_scope.to_string()
            || objective_v1.revision != publication.compile.objective.revision.get()
        {
            return Err(LedgerError::InvalidRunStart(
                "canonical objective binding mismatch",
            ));
        }
        publication
            .run_start
            .validate_for_objective(&publication.compile.objective, canonical_digest)
            .map_err(|_| LedgerError::InvalidRunStart("run snapshot validation failed"))?;
        if publication.compile.objective.source_digest
            != publication.admission.admitted_source_digest
        {
            return Err(LedgerError::InvalidRunStart(
                "admitted source digest mismatch",
            ));
        }
        if publication.admission.profile_digest.is_zero()
            || publication.admission.supplied_source_digest.is_zero()
            || publication.admission.intent_digest.is_zero()
            || publication.admission.admitted_source_digest.is_zero()
        {
            return Err(LedgerError::InvalidRunStart("admission digest is zero"));
        }
        if self.run_starts.contains_key(&publication.run_start.run_id) {
            return Err(LedgerError::RunAlreadyExists(
                publication.run_start.run_id.to_string(),
            ));
        }
        Ok(())
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
        if outcome.finality != OutcomeFinality::Terminal {
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

    fn validate_revocation(&self, revocation: &Revocation) -> Result<(), LedgerError> {
        let Some(index) = self.record_index.get(&revocation.target_record_id) else {
            return Err(LedgerError::TargetNotFound(
                revocation.target_record_id.to_string(),
            ));
        };
        if index.kind == event_kind_code(EventKind::Revocation) {
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
        let position = self.records.len();
        self.record_positions.insert(record_id.clone(), position);
        self.record_index.insert(
            record_id,
            HistoricalRecordIndex {
                sequence: record.sequence,
                predecessor_chain_digest: record.predecessor_chain_digest,
                event_digest: record.event_digest,
                chain_digest: record.chain_digest,
                kind: event_kind(&record.event),
            },
        );
        self.sequence_digests
            .insert(record.sequence.get(), record.chain_digest);
        match &record.event {
            LedgerEvent::RunStart(value) => {
                self.run_starts
                    .insert(value.run_start.run_id.clone(), value.record_id.clone());
            }
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
                        finality: value.finality,
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
        }
    }

    pub(crate) fn record_is_active(&self, record: &LedgerRecord) -> bool {
        let record_id = record.event.record_id();
        if self.revoked.contains(record_id) {
            return false;
        }
        match &record.event {
            LedgerEvent::RunStart(_) => true,
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
        }
    }
}

fn validate_support_digests(event: &LedgerEvent) -> Result<(), LedgerError> {
    match event {
        LedgerEvent::RunStart(value) => {
            for (field, digest) in [
                ("objective", value.run_start.objective_digest),
                ("canonical objective", value.objective_v1_digest),
                ("hard constraint", value.run_start.hard_constraint_digest),
                ("admission profile", value.admission.profile_digest),
                ("intent", value.admission.intent_digest),
                ("admitted source", value.admission.admitted_source_digest),
            ] {
                if digest.is_zero() {
                    return Err(LedgerError::EmptyDigest(field));
                }
            }
        }
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
    }
    Ok(())
}

pub(crate) fn normalize_event(event: &mut LedgerEvent) -> Result<(), LedgerError> {
    let LedgerEvent::Decision(decision) = event else {
        return Ok(());
    };
    if decision.candidate_ids.len() > MAX_CANDIDATES {
        return Err(LedgerError::CandidateLimitExceeded);
    }
    decision.candidate_ids.sort();
    for window in decision.candidate_ids.windows(2) {
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
    RunStart,
}

const fn event_kind_code(kind: EventKind) -> u8 {
    match kind {
        EventKind::Decision => 0,
        EventKind::Outcome => 1,
        EventKind::Credit => 2,
        EventKind::Revocation => 3,
        // Preserve durable tags 0..=3 for compatibility with existing ledgers.
        EventKind::RunStart => 4,
    }
}

pub(crate) fn event_kind(event: &LedgerEvent) -> u8 {
    let kind = match event {
        LedgerEvent::RunStart(_) => EventKind::RunStart,
        LedgerEvent::Decision(_) => EventKind::Decision,
        LedgerEvent::Outcome(_) => EventKind::Outcome,
        LedgerEvent::Credit(_) => EventKind::Credit,
        LedgerEvent::Revocation(_) => EventKind::Revocation,
    };
    event_kind_code(kind)
}

pub(crate) fn digest_event(event: &LedgerEvent) -> Digest32 {
    Digest32::of_bytes(&encode_event(event))
}

pub(crate) fn encode_event(event: &LedgerEvent) -> Vec<u8> {
    let mut bytes = Vec::new();
    bytes.extend_from_slice(EVENT_DIGEST_DOMAIN);
    bytes.push(event_kind(event));
    match event {
        LedgerEvent::RunStart(value) => push_run_start(&mut bytes, value),
        LedgerEvent::Decision(value) => push_decision(&mut bytes, value),
        LedgerEvent::Outcome(value) => push_outcome(&mut bytes, value),
        LedgerEvent::Credit(value) => push_credit(&mut bytes, value),
        LedgerEvent::Revocation(value) => push_revocation(&mut bytes, value),
    }
    bytes
}

pub(crate) fn digest_chain(
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

fn push_run_start(bytes: &mut Vec<u8>, value: &RunStartPublicationV1) {
    use codex_hepta_objective::ConfirmationPolicy;
    use codex_hepta_objective::ConstraintClass;
    use codex_hepta_objective::ConstraintRelation;
    use codex_hepta_objective::PredicateTerminality;
    use codex_hepta_objective::SoftDirection;
    use codex_hepta_objective::SourceTrust;

    push_id(bytes, &value.record_id);
    push_id(bytes, &value.admission.profile_id);
    bytes.extend_from_slice(&value.admission.profile_revision.get().to_be_bytes());
    push_digest(bytes, value.admission.profile_digest);
    push_digest(bytes, value.admission.supplied_source_digest);
    push_digest(bytes, value.admission.intent_digest);
    push_digest(bytes, value.admission.admitted_source_digest);
    bytes.extend_from_slice(&value.admission.observed_at_unix_micros.to_be_bytes());
    match value.admission.deadline_unix_micros {
        Some(deadline) => {
            bytes.push(1);
            bytes.extend_from_slice(&deadline.to_be_bytes());
        }
        None => bytes.push(0),
    }
    for granted in [
        value.admission.authority.runtime,
        value.admission.authority.production_writer,
        value.admission.authority.model_invocation,
        value.admission.authority.provider_dispatch,
        value.admission.authority.external_effect,
        value.admission.authority.selection,
        value.admission.authority.promotion,
        value.admission.authority.release,
    ] {
        bytes.push(u8::from(granted));
    }

    bytes.push(match value.compile.disposition {
        codex_hepta_objective::CompileDisposition::Compiled => 0,
        codex_hepta_objective::CompileDisposition::ExplicitAbstain => 1,
    });
    push_ids(bytes, &value.compile.removed_action_ids);

    let objective = &value.compile.objective;
    push_id(bytes, &objective.request_id);
    push_id(bytes, &objective.principal_scope);
    bytes.extend_from_slice(&objective.revision.get().to_be_bytes());
    bytes.push(match objective.source_trust {
        SourceTrust::PrincipalStructured => 0,
        SourceTrust::RegisteredAdapter => 1,
        SourceTrust::UntrustedEvidence => 2,
    });
    push_digest(bytes, objective.source_digest);
    push_digest(bytes, objective.schema_digest);
    push_digest(bytes, objective.hard_constraint_digest);
    push_digest(bytes, objective.semantic_digest);

    push_len(bytes, objective.constraints.len());
    for constraint in &objective.constraints {
        push_id(bytes, &constraint.id);
        bytes.push(match constraint.class {
            ConstraintClass::Constitutional => 0,
            ConstraintClass::Principal => 1,
            ConstraintClass::Environment => 2,
            ConstraintClass::Task => 3,
        });
        push_id(bytes, &constraint.axis);
        bytes.push(match constraint.relation {
            ConstraintRelation::AtLeast => 0,
            ConstraintRelation::AtMost => 1,
            ConstraintRelation::Equal => 2,
        });
        bytes.extend_from_slice(&constraint.bound.raw().to_be_bytes());
        push_id(bytes, &constraint.evidence_source);
    }

    push_len(bytes, objective.success_predicates.len());
    for predicate in &objective.success_predicates {
        push_id(bytes, &predicate.id);
        push_id(bytes, &predicate.axis);
        bytes.push(match predicate.relation {
            ConstraintRelation::AtLeast => 0,
            ConstraintRelation::AtMost => 1,
            ConstraintRelation::Equal => 2,
        });
        bytes.extend_from_slice(&predicate.bound.raw().to_be_bytes());
        push_id(bytes, &predicate.evidence_source);
        bytes.push(match predicate.terminality {
            PredicateTerminality::Intermediate => 0,
            PredicateTerminality::Terminal => 1,
        });
    }

    push_len(bytes, objective.legal_actions.len());
    for action in &objective.legal_actions {
        push_id(bytes, &action.id);
        bytes.push(match action.confirmation {
            ConfirmationPolicy::NotRequired => 0,
            ConfirmationPolicy::Required => 1,
        });
    }

    push_len(bytes, objective.soft_preferences.len());
    for preference in &objective.soft_preferences {
        push_id(bytes, &preference.dimension);
        bytes.push(match preference.direction {
            SoftDirection::Maximize => 0,
            SoftDirection::Minimize => 1,
        });
        bytes.extend_from_slice(&preference.weight.raw().to_be_bytes());
    }

    push_len(bytes, value.objective_v1_json.len());
    bytes.extend_from_slice(&value.objective_v1_json);
    push_digest(bytes, value.objective_v1_digest);

    let snapshot = &value.run_start;
    push_id(bytes, &snapshot.run_id);
    for digest in [
        snapshot.objective_digest,
        snapshot.hard_constraint_digest,
        snapshot.preference_state_digest,
        snapshot.model_tuple_digest,
        snapshot.prompt_registry_digest,
        snapshot.artifact_set_digest,
    ] {
        push_digest(bytes, digest);
    }
    bytes.extend_from_slice(&snapshot.authority_epoch.to_be_bytes());
    bytes.extend_from_slice(&snapshot.generation.to_be_bytes());
    push_digest(bytes, snapshot.fence_digest);
    push_digest(bytes, value.runtime_body_digest);
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
