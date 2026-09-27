//! Durable product Decision/Outcome delivery for canonical intelligence.
//!
//! The outbox persists the exact product request before invoking the canonical
//! `LedgerWriter`.  A crash after the destination append but before local
//! acknowledgement leaves the intent retryable; recovery replays the identical
//! request and predecessor, relying on the ledger owner's semantic idempotency.
//! No pending or indeterminate record authorizes model, tool, provider or effect
//! replay.

use std::collections::BTreeMap;
use std::error::Error as StdError;
use std::fmt;
use std::fs::File;
use std::fs::OpenOptions;
use std::io::Read;
use std::io::Seek;
use std::io::SeekFrom;
use std::io::Write;
use std::path::Path;
use std::path::PathBuf;
use std::str::FromStr;
use std::sync::Mutex;

use codex_hepta_learning_ledger::AppendDisposition;
use codex_hepta_learning_ledger::AppendReceipt;
use codex_hepta_learning_ledger::AuthenticatedOutcomeV1;
use codex_hepta_learning_ledger::AuthenticatedPrincipalV1;
use codex_hepta_learning_ledger::CandidateSetCompletenessReceiptV1;
use codex_hepta_learning_ledger::DurableLedgerError;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::LedgerWriter;
use codex_hepta_learning_ledger::OutcomeTerminalityV1;
use codex_hepta_learning_ledger::OutcomeWatermarkV1;
use codex_hepta_learning_ledger::ProductionDecisionV2;
use codex_hepta_learning_ledger::ProductionLedgerError;
use codex_hepta_learning_ledger::SignedEvidenceError;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_learning_ledger::decision_signing_payload_v2;
use codex_hepta_learning_ledger::outcome_signing_payload_v2;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::ProbabilityQ32;
use codex_hepta_types::StableId;
use serde::Deserialize;
use serde::Serialize;

const OUTBOX_SCHEMA_VERSION: u32 = 1;
const MAX_OUTBOX_RECORDS: usize = 4_096;
const MAX_OUTBOX_ATTEMPTS: u32 = 64;
const MAX_OUTBOX_BYTES: u64 = 64 * 1024 * 1024;
const MAX_OUTBOX_FRAME_BYTES: usize = 1024 * 1024;
const FRAME_DOMAIN: &[u8] = b"hepta.agentd.intelligence-learning-outbox-frame.v1\0";
const INTENT_DOMAIN: &[u8] = b"hepta.agentd.intelligence-learning-intent.v1\0";
const RECORD_DOMAIN: &[u8] = b"hepta.agentd.intelligence-learning-record.v1\0";
const OUTCOME_SUPPORT_DOMAIN: &[u8] = b"hepta.agentd.intelligence-terminal-outcome.v1\0";
const RECEIPT_DOMAIN: &[u8] = b"hepta.agentd.intelligence-learning-ack.v1\0";

/// Immutable identity shared by the physical run, Decision and Outcome.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct IntelligenceLearningBindingV1 {
    run_id: StableId,
    run_snapshot_digest: Digest32,
    objective_digest: Digest32,
    envelope_digest: Digest32,
    candidate_set_digest: Digest32,
    dispatch_proposal_digest: Digest32,
    decision_record_id: StableId,
    episode_id: StableId,
    selected_candidate_id: StableId,
    binding_digest: Digest32,
}

impl IntelligenceLearningBindingV1 {
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        run_id: StableId,
        run_snapshot_digest: Digest32,
        objective_digest: Digest32,
        envelope_digest: Digest32,
        candidate_set_digest: Digest32,
        dispatch_proposal_digest: Digest32,
        decision_record_id: StableId,
        episode_id: StableId,
        selected_candidate_id: StableId,
    ) -> Result<Self, IntelligenceLearningErrorV1> {
        if decision_record_id != run_id {
            return Err(IntelligenceLearningErrorV1::Invalid(
                "decision record must equal the canonical run id",
            ));
        }
        let digests = [
            run_snapshot_digest,
            objective_digest,
            envelope_digest,
            candidate_set_digest,
            dispatch_proposal_digest,
        ];
        if digests.into_iter().any(|digest| digest.is_zero()) {
            return Err(IntelligenceLearningErrorV1::Invalid(
                "learning binding digest",
            ));
        }
        let mut bytes = b"hepta.agentd.intelligence-learning-binding.v1\0".to_vec();
        push_id(&mut bytes, &run_id)?;
        for digest in digests {
            bytes.extend_from_slice(digest.as_array());
        }
        push_id(&mut bytes, &decision_record_id)?;
        push_id(&mut bytes, &episode_id)?;
        push_id(&mut bytes, &selected_candidate_id)?;
        Ok(Self {
            run_id,
            run_snapshot_digest,
            objective_digest,
            envelope_digest,
            candidate_set_digest,
            dispatch_proposal_digest,
            decision_record_id,
            episode_id,
            selected_candidate_id,
            binding_digest: Digest32::of_bytes(&bytes),
        })
    }

    #[must_use]
    pub fn run_id(&self) -> &StableId {
        &self.run_id
    }

    #[must_use]
    pub const fn run_snapshot_digest(&self) -> Digest32 {
        self.run_snapshot_digest
    }

    #[must_use]
    pub const fn objective_digest(&self) -> Digest32 {
        self.objective_digest
    }

    #[must_use]
    pub const fn envelope_digest(&self) -> Digest32 {
        self.envelope_digest
    }

    #[must_use]
    pub const fn candidate_set_digest(&self) -> Digest32 {
        self.candidate_set_digest
    }

    #[must_use]
    pub const fn dispatch_proposal_digest(&self) -> Digest32 {
        self.dispatch_proposal_digest
    }

    #[must_use]
    pub fn decision_record_id(&self) -> &StableId {
        &self.decision_record_id
    }

    #[must_use]
    pub fn episode_id(&self) -> &StableId {
        &self.episode_id
    }

    #[must_use]
    pub fn selected_candidate_id(&self) -> &StableId {
        &self.selected_candidate_id
    }

    #[must_use]
    pub const fn digest(&self) -> Digest32 {
        self.binding_digest
    }

    #[must_use]
    pub fn outcome_support_digest(&self, terminal_observation_digest: Digest32) -> Digest32 {
        let mut bytes = OUTCOME_SUPPORT_DOMAIN.to_vec();
        bytes.extend_from_slice(self.binding_digest.as_array());
        bytes.extend_from_slice(terminal_observation_digest.as_array());
        Digest32::of_bytes(&bytes)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum IntelligenceLearningIntentV1 {
    Decision {
        intent_id: StableId,
        binding: IntelligenceLearningBindingV1,
        expected_predecessor: Digest32,
        decision: ProductionDecisionV2,
        evidence: SignedLearningEvidenceV1,
        admitted_at: u64,
    },
    Outcome {
        intent_id: StableId,
        binding: IntelligenceLearningBindingV1,
        expected_predecessor: Digest32,
        terminal_observation_digest: Digest32,
        outcome: AuthenticatedOutcomeV1,
        evidence: SignedLearningEvidenceV1,
        admitted_at: u64,
    },
}

impl IntelligenceLearningIntentV1 {
    fn decision(
        binding: IntelligenceLearningBindingV1,
        expected_predecessor: Digest32,
        decision: ProductionDecisionV2,
        evidence: SignedLearningEvidenceV1,
        admitted_at: u64,
    ) -> Result<Self, IntelligenceLearningErrorV1> {
        let mut value = Self::Decision {
            intent_id: StableId::new("pending.intelligence.decision")
                .map_err(|_| IntelligenceLearningErrorV1::Invalid("intent id"))?,
            binding,
            expected_predecessor,
            decision,
            evidence,
            admitted_at,
        };
        let intent_id = intent_id_for(&value)?;
        value.set_intent_id(intent_id);
        value.validate()?;
        Ok(value)
    }

    fn outcome(
        binding: IntelligenceLearningBindingV1,
        expected_predecessor: Digest32,
        terminal_observation_digest: Digest32,
        outcome: AuthenticatedOutcomeV1,
        evidence: SignedLearningEvidenceV1,
        admitted_at: u64,
    ) -> Result<Self, IntelligenceLearningErrorV1> {
        let mut value = Self::Outcome {
            intent_id: StableId::new("pending.intelligence.outcome")
                .map_err(|_| IntelligenceLearningErrorV1::Invalid("intent id"))?,
            binding,
            expected_predecessor,
            terminal_observation_digest,
            outcome,
            evidence,
            admitted_at,
        };
        let intent_id = intent_id_for(&value)?;
        value.set_intent_id(intent_id);
        value.validate()?;
        Ok(value)
    }

    #[must_use]
    pub fn intent_id(&self) -> &StableId {
        match self {
            Self::Decision { intent_id, .. } | Self::Outcome { intent_id, .. } => intent_id,
        }
    }

    #[must_use]
    pub fn binding(&self) -> &IntelligenceLearningBindingV1 {
        match self {
            Self::Decision { binding, .. } | Self::Outcome { binding, .. } => binding,
        }
    }

    #[must_use]
    pub const fn admitted_at(&self) -> u64 {
        match self {
            Self::Decision { admitted_at, .. } | Self::Outcome { admitted_at, .. } => *admitted_at,
        }
    }

    fn expected_predecessor(&self) -> Digest32 {
        match self {
            Self::Decision {
                expected_predecessor,
                ..
            }
            | Self::Outcome {
                expected_predecessor,
                ..
            } => *expected_predecessor,
        }
    }

    fn set_intent_id(&mut self, value: StableId) {
        match self {
            Self::Decision { intent_id, .. } | Self::Outcome { intent_id, .. } => {
                *intent_id = value;
            }
        }
    }

    fn validate(&self) -> Result<(), IntelligenceLearningErrorV1> {
        if self.admitted_at() == 0 {
            return Err(IntelligenceLearningErrorV1::Invalid("admission time"));
        }
        let canonical_id = intent_id_for(self)?;
        if self.intent_id() != &canonical_id {
            return Err(IntelligenceLearningErrorV1::Invalid(
                "intent semantic identity",
            ));
        }
        match self {
            Self::Decision {
                binding,
                decision,
                evidence,
                ..
            } => validate_decision(binding, decision, evidence),
            Self::Outcome {
                binding,
                terminal_observation_digest,
                outcome,
                evidence,
                ..
            } => validate_outcome(
                binding,
                *terminal_observation_digest,
                outcome,
                evidence,
            ),
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum IntelligenceLearningStateV1 {
    Pending,
    Acknowledged { acknowledgement_digest: Digest32 },
    Rejected { reason_digest: Digest32 },
    Revoked { reason_digest: Digest32 },
    Indeterminate { reason_digest: Digest32 },
}

impl IntelligenceLearningStateV1 {
    fn retryable(&self) -> bool {
        matches!(self, Self::Pending | Self::Indeterminate { .. })
    }

    fn terminal(&self) -> bool {
        matches!(
            self,
            Self::Acknowledged { .. } | Self::Rejected { .. } | Self::Revoked { .. }
        )
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct IntelligenceLearningStatusV1 {
    pub intent_id: StableId,
    pub state: IntelligenceLearningStateV1,
    pub attempts: u32,
    pub binding_digest: Digest32,
}

#[derive(Clone, Debug)]
struct OutboxRecordV1 {
    intent: IntelligenceLearningIntentV1,
    state: IntelligenceLearningStateV1,
    attempts: u32,
}

pub struct AgentdIntelligenceLearningOutboxV1 {
    path: PathBuf,
    file: File,
    records: BTreeMap<StableId, OutboxRecordV1>,
    sequence: u64,
    head_digest: Digest32,
    poisoned: bool,
}

impl AgentdIntelligenceLearningOutboxV1 {
    pub fn open(path: PathBuf) -> Result<Self, IntelligenceLearningErrorV1> {
        if !path.is_absolute() {
            return Err(IntelligenceLearningErrorV1::Invalid(
                "outbox path must be absolute",
            ));
        }
        let parent = path
            .parent()
            .ok_or(IntelligenceLearningErrorV1::Invalid("outbox parent"))?;
        if !parent.is_dir() {
            return Err(IntelligenceLearningErrorV1::Invalid("outbox parent"));
        }
        if path.exists() {
            let metadata = std::fs::symlink_metadata(&path)?;
            if metadata.file_type().is_symlink() || !metadata.is_file() {
                return Err(IntelligenceLearningErrorV1::Invalid(
                    "outbox must be a regular non-symlink file",
                ));
            }
        }
        let created = !path.exists();
        let mut file = OpenOptions::new()
            .create(true)
            .truncate(false)
            .read(true)
            .write(true)
            .open(&path)?;
        file.try_lock()
            .map_err(|_| IntelligenceLearningErrorV1::Busy)?;
        if !file.metadata()?.is_file() {
            return Err(IntelligenceLearningErrorV1::Invalid("outbox file"));
        }
        if created {
            File::open(parent)?.sync_all()?;
        }
        if file.metadata()?.len() > MAX_OUTBOX_BYTES {
            return Err(IntelligenceLearningErrorV1::Capacity);
        }
        let mut bytes = Vec::new();
        file.seek(SeekFrom::Start(0))?;
        file.read_to_end(&mut bytes)?;
        let complete_length = if bytes.is_empty() || bytes.ends_with(b"\n") {
            bytes.len()
        } else {
            bytes
                .iter()
                .rposition(|byte| *byte == b'\n')
                .map_or(0, |index| index + 1)
        };
        if complete_length != bytes.len() {
            file.set_len(u64::try_from(complete_length).map_err(|_| {
                IntelligenceLearningErrorV1::Invalid("outbox length")
            })?)?;
            file.sync_all()?;
            bytes.truncate(complete_length);
        }
        let mut value = Self {
            path,
            file,
            records: BTreeMap::new(),
            sequence: 0,
            head_digest: Digest32::ZERO,
            poisoned: false,
        };
        for line in bytes.split(|byte| *byte == b'\n') {
            if line.is_empty() {
                continue;
            }
            if line.len() > MAX_OUTBOX_FRAME_BYTES {
                return Err(IntelligenceLearningErrorV1::Corrupt);
            }
            let frame: JournalFrameFileV1 =
                serde_json::from_slice(line).map_err(|_| IntelligenceLearningErrorV1::Corrupt)?;
            value.replay_frame(frame)?;
        }
        value.file.seek(SeekFrom::End(0))?;
        Ok(value)
    }

    pub fn enqueue_decision(
        &mut self,
        binding: IntelligenceLearningBindingV1,
        expected_predecessor: Digest32,
        decision: ProductionDecisionV2,
        evidence: SignedLearningEvidenceV1,
        admitted_at: u64,
    ) -> Result<IntelligenceLearningStatusV1, IntelligenceLearningErrorV1> {
        self.enqueue(IntelligenceLearningIntentV1::decision(
            binding,
            expected_predecessor,
            decision,
            evidence,
            admitted_at,
        )?)
    }

    pub fn enqueue_outcome(
        &mut self,
        binding: IntelligenceLearningBindingV1,
        expected_predecessor: Digest32,
        terminal_observation_digest: Digest32,
        outcome: AuthenticatedOutcomeV1,
        evidence: SignedLearningEvidenceV1,
        admitted_at: u64,
    ) -> Result<IntelligenceLearningStatusV1, IntelligenceLearningErrorV1> {
        self.enqueue(IntelligenceLearningIntentV1::outcome(
            binding,
            expected_predecessor,
            terminal_observation_digest,
            outcome,
            evidence,
            admitted_at,
        )?)
    }

    pub fn status(&self, intent_id: &StableId) -> Option<IntelligenceLearningStatusV1> {
        self.records
            .get(intent_id)
            .map(|record| status(intent_id.clone(), record))
    }

    #[must_use]
    pub fn backlog(&self) -> usize {
        self.records
            .values()
            .filter(|record| record.state.retryable())
            .count()
    }

    #[must_use]
    pub fn path(&self) -> &Path {
        &self.path
    }

    pub fn reconcile_with_writer(
        &mut self,
        writer: &mut LedgerWriter,
        now: u64,
        maximum: usize,
    ) -> Result<Vec<IntelligenceLearningStatusV1>, IntelligenceLearningErrorV1> {
        let mut destination = LedgerWriterDestinationV1 { writer };
        self.reconcile_with(&mut destination, now, maximum)
    }

    fn enqueue(
        &mut self,
        intent: IntelligenceLearningIntentV1,
    ) -> Result<IntelligenceLearningStatusV1, IntelligenceLearningErrorV1> {
        self.require_healthy()?;
        intent.validate()?;
        let intent_id = intent.intent_id().clone();
        if let Some(existing) = self.records.get(&intent_id) {
            if existing.intent == intent {
                return Ok(status(intent_id, existing));
            }
            return Err(IntelligenceLearningErrorV1::Conflict);
        }
        if self.records.len() >= MAX_OUTBOX_RECORDS {
            return Err(IntelligenceLearningErrorV1::Capacity);
        }
        self.append_event(JournalEventFileV1::Enqueue {
            intent: IntentFileV1::from_intent(&intent),
        })?;
        self.status(&intent_id)
            .ok_or(IntelligenceLearningErrorV1::Corrupt)
    }

    fn reconcile_with<D: IntelligenceLearningDestinationV1>(
        &mut self,
        destination: &mut D,
        now: u64,
        maximum: usize,
    ) -> Result<Vec<IntelligenceLearningStatusV1>, IntelligenceLearningErrorV1> {
        self.require_healthy()?;
        if now == 0 || maximum == 0 || maximum > MAX_OUTBOX_RECORDS {
            return Err(IntelligenceLearningErrorV1::Invalid(
                "reconciliation bound",
            ));
        }
        let ids = self
            .records
            .iter()
            .filter(|(_, record)| record.state.retryable())
            .map(|(id, _)| id.clone())
            .take(maximum)
            .collect::<Vec<_>>();
        ids.into_iter()
            .map(|id| self.reconcile_one(destination, &id, now))
            .collect()
    }

    fn reconcile_one<D: IntelligenceLearningDestinationV1>(
        &mut self,
        destination: &mut D,
        intent_id: &StableId,
        now: u64,
    ) -> Result<IntelligenceLearningStatusV1, IntelligenceLearningErrorV1> {
        let record = self
            .records
            .get(intent_id)
            .cloned()
            .ok_or(IntelligenceLearningErrorV1::Missing)?;
        if record.state.terminal() {
            return Ok(status(intent_id.clone(), &record));
        }
        if record.attempts >= MAX_OUTBOX_ATTEMPTS {
            let reason = Digest32::of_bytes(b"hepta.intelligence.outbox.attempt-limit.v1");
            self.transition(intent_id, IntelligenceLearningStateV1::Rejected {
                reason_digest: reason,
            })?;
            return self
                .status(intent_id)
                .ok_or(IntelligenceLearningErrorV1::Corrupt);
        }
        let expected_record_digest = record_digest(&record)?;
        self.append_event(JournalEventFileV1::Attempt {
            intent_id: intent_id.to_string(),
            expected_record_digest: expected_record_digest.to_string(),
            attempt: record
                .attempts
                .checked_add(1)
                .ok_or(IntelligenceLearningErrorV1::Capacity)?,
        })?;
        let current = self
            .records
            .get(intent_id)
            .cloned()
            .ok_or(IntelligenceLearningErrorV1::Missing)?;
        let disposition = destination.append(&current.intent, now);
        let next = match disposition {
            IntelligenceLearningAppendDispositionV1::Acknowledged(digest) => {
                IntelligenceLearningStateV1::Acknowledged {
                    acknowledgement_digest: digest,
                }
            }
            IntelligenceLearningAppendDispositionV1::Rejected(digest) => {
                IntelligenceLearningStateV1::Rejected {
                    reason_digest: digest,
                }
            }
            IntelligenceLearningAppendDispositionV1::Revoked(digest) => {
                IntelligenceLearningStateV1::Revoked {
                    reason_digest: digest,
                }
            }
            IntelligenceLearningAppendDispositionV1::Indeterminate(digest) => {
                IntelligenceLearningStateV1::Indeterminate {
                    reason_digest: digest,
                }
            }
        };
        self.transition(intent_id, next)?;
        self.status(intent_id)
            .ok_or(IntelligenceLearningErrorV1::Corrupt)
    }

    fn transition(
        &mut self,
        intent_id: &StableId,
        state: IntelligenceLearningStateV1,
    ) -> Result<(), IntelligenceLearningErrorV1> {
        if state.terminal() || matches!(state, IntelligenceLearningStateV1::Indeterminate { .. }) {
            let record = self
                .records
                .get(intent_id)
                .ok_or(IntelligenceLearningErrorV1::Missing)?;
            let expected_record_digest = record_digest(record)?;
            self.append_event(JournalEventFileV1::Transition {
                intent_id: intent_id.to_string(),
                expected_record_digest: expected_record_digest.to_string(),
                state: StateFileV1::from_state(&state),
            })
        } else {
            Err(IntelligenceLearningErrorV1::Invalid("outbox transition"))
        }
    }

    fn append_event(
        &mut self,
        event: JournalEventFileV1,
    ) -> Result<(), IntelligenceLearningErrorV1> {
        self.require_healthy()?;
        let sequence = self
            .sequence
            .checked_add(1)
            .ok_or(IntelligenceLearningErrorV1::Capacity)?;
        let predecessor_digest = self.head_digest;
        let digest = journal_frame_digest(sequence, predecessor_digest, &event)?;
        let frame = JournalFrameFileV1 {
            schema_version: OUTBOX_SCHEMA_VERSION,
            sequence,
            predecessor_digest: predecessor_digest.to_string(),
            event,
            frame_digest: digest.to_string(),
        };
        let mut encoded = serde_json::to_vec(&frame)?;
        if encoded.len() > MAX_OUTBOX_FRAME_BYTES {
            return Err(IntelligenceLearningErrorV1::Capacity);
        }
        encoded.push(b'\n');
        let current_len = self.file.metadata()?.len();
        let next_len = current_len
            .checked_add(u64::try_from(encoded.len()).map_err(|_| {
                IntelligenceLearningErrorV1::Capacity
            })?)
            .ok_or(IntelligenceLearningErrorV1::Capacity)?;
        if next_len > MAX_OUTBOX_BYTES {
            return Err(IntelligenceLearningErrorV1::Capacity);
        }
        self.poisoned = true;
        if self.file.seek(SeekFrom::End(0))? != current_len {
            return Err(IntelligenceLearningErrorV1::Corrupt);
        }
        if let Err(error) = self.file.write_all(&encoded).and_then(|()| self.file.sync_all()) {
            return Err(IntelligenceLearningErrorV1::Io(error.kind()));
        }
        if let Err(error) = self.apply_frame(&frame) {
            return Err(error);
        }
        self.sequence = sequence;
        self.head_digest = digest;
        self.poisoned = false;
        Ok(())
    }

    fn replay_frame(
        &mut self,
        frame: JournalFrameFileV1,
    ) -> Result<(), IntelligenceLearningErrorV1> {
        if frame.schema_version != OUTBOX_SCHEMA_VERSION
            || frame.sequence != self.sequence + 1
        {
            return Err(IntelligenceLearningErrorV1::Corrupt);
        }
        let predecessor = parse_digest(&frame.predecessor_digest, "frame predecessor")?;
        let digest = parse_digest(&frame.frame_digest, "frame digest")?;
        if predecessor != self.head_digest
            || digest != journal_frame_digest(frame.sequence, predecessor, &frame.event)?
        {
            return Err(IntelligenceLearningErrorV1::Corrupt);
        }
        self.apply_frame(&frame)?;
        self.sequence = frame.sequence;
        self.head_digest = digest;
        Ok(())
    }

    fn apply_frame(
        &mut self,
        frame: &JournalFrameFileV1,
    ) -> Result<(), IntelligenceLearningErrorV1> {
        match &frame.event {
            JournalEventFileV1::Enqueue { intent } => {
                if self.records.len() >= MAX_OUTBOX_RECORDS {
                    return Err(IntelligenceLearningErrorV1::Capacity);
                }
                let intent = intent.to_intent()?;
                intent.validate()?;
                let id = intent.intent_id().clone();
                if self.records.contains_key(&id) {
                    return Err(IntelligenceLearningErrorV1::Corrupt);
                }
                self.records.insert(
                    id,
                    OutboxRecordV1 {
                        intent,
                        state: IntelligenceLearningStateV1::Pending,
                        attempts: 0,
                    },
                );
            }
            JournalEventFileV1::Attempt {
                intent_id,
                expected_record_digest,
                attempt,
            } => {
                let id = parse_id(intent_id, "attempt intent")?;
                let expected = parse_digest(expected_record_digest, "record digest")?;
                let record = self
                    .records
                    .get_mut(&id)
                    .ok_or(IntelligenceLearningErrorV1::Corrupt)?;
                if !record.state.retryable()
                    || record_digest(record)? != expected
                    || *attempt != record.attempts + 1
                    || *attempt > MAX_OUTBOX_ATTEMPTS
                {
                    return Err(IntelligenceLearningErrorV1::Corrupt);
                }
                record.attempts = *attempt;
            }
            JournalEventFileV1::Transition {
                intent_id,
                expected_record_digest,
                state,
            } => {
                let id = parse_id(intent_id, "transition intent")?;
                let expected = parse_digest(expected_record_digest, "record digest")?;
                let next = state.to_state()?;
                let record = self
                    .records
                    .get_mut(&id)
                    .ok_or(IntelligenceLearningErrorV1::Corrupt)?;
                if !record.state.retryable()
                    || record_digest(record)? != expected
                    || !(next.terminal()
                        || matches!(next, IntelligenceLearningStateV1::Indeterminate { .. }))
                {
                    return Err(IntelligenceLearningErrorV1::Corrupt);
                }
                record.state = next;
            }
        }
        Ok(())
    }

    fn require_healthy(&self) -> Result<(), IntelligenceLearningErrorV1> {
        if self.poisoned {
            Err(IntelligenceLearningErrorV1::Poisoned)
        } else {
            Ok(())
        }
    }
}

struct IntelligenceLearningHostStateV1 {
    outbox: AgentdIntelligenceLearningOutboxV1,
    writer: LedgerWriter,
}

/// Single-owner product host combining the durable outbox and canonical writer.
pub struct AgentdIntelligenceLearningHostV1 {
    state: Mutex<IntelligenceLearningHostStateV1>,
}

impl AgentdIntelligenceLearningHostV1 {
    pub fn open(
        outbox_path: PathBuf,
        writer: LedgerWriter,
        now: u64,
    ) -> Result<Self, IntelligenceLearningErrorV1> {
        let mut outbox = AgentdIntelligenceLearningOutboxV1::open(outbox_path)?;
        let mut writer = writer;
        outbox.reconcile_with_writer(&mut writer, now, MAX_OUTBOX_RECORDS)?;
        Ok(Self {
            state: Mutex::new(IntelligenceLearningHostStateV1 { outbox, writer }),
        })
    }

    pub fn enqueue_decision(
        &self,
        binding: IntelligenceLearningBindingV1,
        expected_predecessor: Digest32,
        decision: ProductionDecisionV2,
        evidence: SignedLearningEvidenceV1,
        now: u64,
    ) -> Result<IntelligenceLearningStatusV1, IntelligenceLearningErrorV1> {
        let mut state = self.lock()?;
        let status = state.outbox.enqueue_decision(
            binding,
            expected_predecessor,
            decision,
            evidence,
            now,
        )?;
        let id = status.intent_id.clone();
        reconcile_host_one(&mut state, &id, now)
    }

    pub fn enqueue_outcome(
        &self,
        binding: IntelligenceLearningBindingV1,
        expected_predecessor: Digest32,
        terminal_observation_digest: Digest32,
        outcome: AuthenticatedOutcomeV1,
        evidence: SignedLearningEvidenceV1,
        now: u64,
    ) -> Result<IntelligenceLearningStatusV1, IntelligenceLearningErrorV1> {
        let mut state = self.lock()?;
        let status = state.outbox.enqueue_outcome(
            binding,
            expected_predecessor,
            terminal_observation_digest,
            outcome,
            evidence,
            now,
        )?;
        let id = status.intent_id.clone();
        reconcile_host_one(&mut state, &id, now)
    }

    pub fn reconcile(
        &self,
        now: u64,
        maximum: usize,
    ) -> Result<Vec<IntelligenceLearningStatusV1>, IntelligenceLearningErrorV1> {
        let mut state = self.lock()?;
        reconcile_host(&mut state, now, maximum)
    }

    pub fn status(
        &self,
        intent_id: &StableId,
    ) -> Result<Option<IntelligenceLearningStatusV1>, IntelligenceLearningErrorV1> {
        Ok(self.lock()?.outbox.status(intent_id))
    }

    pub fn backlog(&self) -> Result<usize, IntelligenceLearningErrorV1> {
        Ok(self.lock()?.outbox.backlog())
    }

    fn lock(
        &self,
    ) -> Result<std::sync::MutexGuard<'_, IntelligenceLearningHostStateV1>, IntelligenceLearningErrorV1>
    {
        self.state
            .lock()
            .map_err(|_| IntelligenceLearningErrorV1::Poisoned)
    }
}

fn reconcile_host_one(
    state: &mut IntelligenceLearningHostStateV1,
    intent_id: &StableId,
    now: u64,
) -> Result<IntelligenceLearningStatusV1, IntelligenceLearningErrorV1> {
    let IntelligenceLearningHostStateV1 { outbox, writer } = state;
    let mut destination = LedgerWriterDestinationV1 { writer };
    outbox.reconcile_one(&mut destination, intent_id, now)
}

fn reconcile_host(
    state: &mut IntelligenceLearningHostStateV1,
    now: u64,
    maximum: usize,
) -> Result<Vec<IntelligenceLearningStatusV1>, IntelligenceLearningErrorV1> {
    let IntelligenceLearningHostStateV1 { outbox, writer } = state;
    let mut destination = LedgerWriterDestinationV1 { writer };
    outbox.reconcile_with(&mut destination, now, maximum)
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum IntelligenceLearningAppendDispositionV1 {
    Acknowledged(Digest32),
    Rejected(Digest32),
    Revoked(Digest32),
    Indeterminate(Digest32),
}

trait IntelligenceLearningDestinationV1 {
    fn append(
        &mut self,
        intent: &IntelligenceLearningIntentV1,
        now: u64,
    ) -> IntelligenceLearningAppendDispositionV1;
}

struct LedgerWriterDestinationV1<'a> {
    writer: &'a mut LedgerWriter,
}

impl IntelligenceLearningDestinationV1 for LedgerWriterDestinationV1<'_> {
    fn append(
        &mut self,
        intent: &IntelligenceLearningIntentV1,
        now: u64,
    ) -> IntelligenceLearningAppendDispositionV1 {
        let result = match intent {
            IntelligenceLearningIntentV1::Decision {
                expected_predecessor,
                decision,
                evidence,
                ..
            } => self
                .writer
                .append_decision(*expected_predecessor, decision.clone(), evidence, now),
            IntelligenceLearningIntentV1::Outcome {
                binding,
                expected_predecessor,
                outcome,
                evidence,
                ..
            } => self
                .writer
                .verify_active_decision_binding(
                    binding.decision_record_id(),
                    binding.episode_id(),
                )
                .and_then(|()| {
                    self.writer
                        .append_outcome(*expected_predecessor, outcome.clone(), evidence, now)
                }),
        };
        match result {
            Ok(receipt) => {
                IntelligenceLearningAppendDispositionV1::Acknowledged(receipt_digest(&receipt))
            }
            Err(error) => classify_production_error(&error),
        }
    }
}

fn validate_decision(
    binding: &IntelligenceLearningBindingV1,
    decision: &ProductionDecisionV2,
    evidence: &SignedLearningEvidenceV1,
) -> Result<(), IntelligenceLearningErrorV1> {
    let mut candidates = decision.candidate_ids.clone();
    candidates.sort();
    if candidates.is_empty()
        || candidates.len() > 128
        || candidates.windows(2).any(|pair| pair[0] == pair[1])
        || !candidates.contains(binding.selected_candidate_id())
        || decision.record_id != *binding.decision_record_id()
        || decision.episode_id != *binding.episode_id()
        || decision.run_snapshot_digest != binding.run_snapshot_digest()
        || decision.objective_digest != binding.objective_digest()
        || decision.selected_candidate_id != *binding.selected_candidate_id()
        || decision.selected_propensity.raw() == 0
        || decision.completeness.candidates_digest != binding.candidate_set_digest()
        || decision.support_digest != binding.dispatch_proposal_digest()
        || evidence.role != LearningEvidenceRoleV1::Generator
        || evidence.objective_digest != binding.objective_digest()
        || evidence.authority_epoch == 0
    {
        return Err(IntelligenceLearningErrorV1::Invalid("Decision binding"));
    }
    let payload = decision_signing_payload_v2(decision)
        .map_err(|_| IntelligenceLearningErrorV1::Invalid("Decision payload"))?;
    if evidence.payload_digest != Digest32::of_bytes(&payload) {
        return Err(IntelligenceLearningErrorV1::Invalid(
            "Decision evidence payload",
        ));
    }
    Ok(())
}

fn validate_outcome(
    binding: &IntelligenceLearningBindingV1,
    terminal_observation_digest: Digest32,
    outcome: &AuthenticatedOutcomeV1,
    evidence: &SignedLearningEvidenceV1,
) -> Result<(), IntelligenceLearningErrorV1> {
    if terminal_observation_digest.is_zero()
        || outcome.episode_id != *binding.episode_id()
        || outcome.support_digest
            != binding.outcome_support_digest(terminal_observation_digest)
        || outcome.watermark.terminality == OutcomeTerminalityV1::Pending
        || evidence.role != LearningEvidenceRoleV1::Observer
        || evidence.objective_digest != binding.objective_digest()
        || evidence.authority_epoch == 0
    {
        return Err(IntelligenceLearningErrorV1::Invalid("Outcome binding"));
    }
    let payload = outcome_signing_payload_v2(outcome);
    if evidence.payload_digest != Digest32::of_bytes(&payload) {
        return Err(IntelligenceLearningErrorV1::Invalid(
            "Outcome evidence payload",
        ));
    }
    Ok(())
}

fn classify_production_error(
    error: &ProductionLedgerError,
) -> IntelligenceLearningAppendDispositionV1 {
    let reason = Digest32::of_bytes(format!("{error:?}").as_bytes());
    match error {
        ProductionLedgerError::Evidence(SignedEvidenceError::Revoked) => {
            IntelligenceLearningAppendDispositionV1::Revoked(reason)
        }
        ProductionLedgerError::IndeterminateAfterLedgerCommit { .. }
        | ProductionLedgerError::IndeterminateAfterTopologyChange { .. }
        | ProductionLedgerError::Durable(
            DurableLedgerError::Indeterminate
            | DurableLedgerError::Poisoned
            | DurableLedgerError::Io(_),
        ) => IntelligenceLearningAppendDispositionV1::Indeterminate(reason),
        _ => IntelligenceLearningAppendDispositionV1::Rejected(reason),
    }
}

fn receipt_digest(receipt: &AppendReceipt) -> Digest32 {
    let mut bytes = RECEIPT_DOMAIN.to_vec();
    bytes.push(match receipt.disposition {
        AppendDisposition::Appended => 0,
        AppendDisposition::IdempotentReplay => 1,
    });
    bytes.extend_from_slice(&receipt.sequence.get().to_be_bytes());
    bytes.extend_from_slice(receipt.event_digest.as_array());
    bytes.extend_from_slice(receipt.chain_digest.as_array());
    Digest32::of_bytes(&bytes)
}

fn status(intent_id: StableId, record: &OutboxRecordV1) -> IntelligenceLearningStatusV1 {
    IntelligenceLearningStatusV1 {
        intent_id,
        state: record.state.clone(),
        attempts: record.attempts,
        binding_digest: record.intent.binding().digest(),
    }
}

fn intent_id_for(
    intent: &IntelligenceLearningIntentV1,
) -> Result<StableId, IntelligenceLearningErrorV1> {
    let file = IntentFileV1::from_intent_without_canonical_id(intent);
    let mut bytes = INTENT_DOMAIN.to_vec();
    bytes.extend_from_slice(&serde_json::to_vec(&file)?);
    StableId::new(format!("intelligence-learning:{}", Digest32::of_bytes(&bytes)))
        .map_err(|_| IntelligenceLearningErrorV1::Invalid("intent id"))
}

fn record_digest(record: &OutboxRecordV1) -> Result<Digest32, IntelligenceLearningErrorV1> {
    let mut bytes = RECORD_DOMAIN.to_vec();
    bytes.extend_from_slice(&serde_json::to_vec(&IntentFileV1::from_intent(
        &record.intent,
    ))?);
    bytes.extend_from_slice(&serde_json::to_vec(&StateFileV1::from_state(
        &record.state,
    ))?);
    bytes.extend_from_slice(&record.attempts.to_be_bytes());
    Ok(Digest32::of_bytes(&bytes))
}

fn journal_frame_digest(
    sequence: u64,
    predecessor: Digest32,
    event: &JournalEventFileV1,
) -> Result<Digest32, IntelligenceLearningErrorV1> {
    let mut bytes = FRAME_DOMAIN.to_vec();
    bytes.extend_from_slice(&OUTBOX_SCHEMA_VERSION.to_be_bytes());
    bytes.extend_from_slice(&sequence.to_be_bytes());
    bytes.extend_from_slice(predecessor.as_array());
    bytes.extend_from_slice(&serde_json::to_vec(event)?);
    Ok(Digest32::of_bytes(&bytes))
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct BindingFileV1 {
    run_id: String,
    run_snapshot_digest: String,
    objective_digest: String,
    envelope_digest: String,
    candidate_set_digest: String,
    dispatch_proposal_digest: String,
    decision_record_id: String,
    episode_id: String,
    selected_candidate_id: String,
}

impl BindingFileV1 {
    fn from_binding(value: &IntelligenceLearningBindingV1) -> Self {
        Self {
            run_id: value.run_id.to_string(),
            run_snapshot_digest: value.run_snapshot_digest.to_string(),
            objective_digest: value.objective_digest.to_string(),
            envelope_digest: value.envelope_digest.to_string(),
            candidate_set_digest: value.candidate_set_digest.to_string(),
            dispatch_proposal_digest: value.dispatch_proposal_digest.to_string(),
            decision_record_id: value.decision_record_id.to_string(),
            episode_id: value.episode_id.to_string(),
            selected_candidate_id: value.selected_candidate_id.to_string(),
        }
    }

    fn to_binding(&self) -> Result<IntelligenceLearningBindingV1, IntelligenceLearningErrorV1> {
        IntelligenceLearningBindingV1::new(
            parse_id(&self.run_id, "run id")?,
            parse_digest(&self.run_snapshot_digest, "run snapshot")?,
            parse_digest(&self.objective_digest, "objective")?,
            parse_digest(&self.envelope_digest, "envelope")?,
            parse_digest(&self.candidate_set_digest, "candidate set")?,
            parse_digest(&self.dispatch_proposal_digest, "dispatch proposal")?,
            parse_id(&self.decision_record_id, "decision record")?,
            parse_id(&self.episode_id, "episode")?,
            parse_id(&self.selected_candidate_id, "selected candidate")?,
        )
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
enum IntentFileV1 {
    Decision {
        intent_id: String,
        binding: BindingFileV1,
        expected_predecessor: String,
        decision: DecisionFileV1,
        evidence: EvidenceFileV1,
        admitted_at: u64,
    },
    Outcome {
        intent_id: String,
        binding: BindingFileV1,
        expected_predecessor: String,
        terminal_observation_digest: String,
        outcome: OutcomeFileV1,
        evidence: EvidenceFileV1,
        admitted_at: u64,
    },
}

impl IntentFileV1 {
    fn from_intent(value: &IntelligenceLearningIntentV1) -> Self {
        match value {
            IntelligenceLearningIntentV1::Decision {
                intent_id,
                binding,
                expected_predecessor,
                decision,
                evidence,
                admitted_at,
            } => Self::Decision {
                intent_id: intent_id.to_string(),
                binding: BindingFileV1::from_binding(binding),
                expected_predecessor: expected_predecessor.to_string(),
                decision: DecisionFileV1::from_decision(decision),
                evidence: EvidenceFileV1::from_evidence(evidence),
                admitted_at: *admitted_at,
            },
            IntelligenceLearningIntentV1::Outcome {
                intent_id,
                binding,
                expected_predecessor,
                terminal_observation_digest,
                outcome,
                evidence,
                admitted_at,
            } => Self::Outcome {
                intent_id: intent_id.to_string(),
                binding: BindingFileV1::from_binding(binding),
                expected_predecessor: expected_predecessor.to_string(),
                terminal_observation_digest: terminal_observation_digest.to_string(),
                outcome: OutcomeFileV1::from_outcome(outcome),
                evidence: EvidenceFileV1::from_evidence(evidence),
                admitted_at: *admitted_at,
            },
        }
    }

    fn from_intent_without_canonical_id(value: &IntelligenceLearningIntentV1) -> Self {
        let mut file = Self::from_intent(value);
        match &mut file {
            Self::Decision { intent_id, .. } | Self::Outcome { intent_id, .. } => {
                *intent_id = String::new();
            }
        }
        file
    }

    fn to_intent(&self) -> Result<IntelligenceLearningIntentV1, IntelligenceLearningErrorV1> {
        let value = match self {
            Self::Decision {
                intent_id,
                binding,
                expected_predecessor,
                decision,
                evidence,
                admitted_at,
            } => IntelligenceLearningIntentV1::Decision {
                intent_id: parse_id(intent_id, "intent")?,
                binding: binding.to_binding()?,
                expected_predecessor: parse_digest(expected_predecessor, "predecessor")?,
                decision: decision.to_decision()?,
                evidence: evidence.to_evidence()?,
                admitted_at: *admitted_at,
            },
            Self::Outcome {
                intent_id,
                binding,
                expected_predecessor,
                terminal_observation_digest,
                outcome,
                evidence,
                admitted_at,
            } => IntelligenceLearningIntentV1::Outcome {
                intent_id: parse_id(intent_id, "intent")?,
                binding: binding.to_binding()?,
                expected_predecessor: parse_digest(expected_predecessor, "predecessor")?,
                terminal_observation_digest: parse_digest(
                    terminal_observation_digest,
                    "terminal observation",
                )?,
                outcome: outcome.to_outcome()?,
                evidence: evidence.to_evidence()?,
                admitted_at: *admitted_at,
            },
        };
        value.validate()?;
        Ok(value)
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct CompletenessFileV1 {
    set_id: String,
    state_digest: String,
    generator_id: String,
    generator_code_digest: String,
    grammar_digest: String,
    hard_filter_digest: String,
    truncation_digest: String,
    candidates_digest: String,
    candidate_count: u32,
    omitted_count_bound: u32,
    canonical_order_digest: String,
    complete_for_generator: bool,
}

impl CompletenessFileV1 {
    fn from_completeness(value: &CandidateSetCompletenessReceiptV1) -> Self {
        Self {
            set_id: value.set_id.to_string(),
            state_digest: value.state_digest.to_string(),
            generator_id: value.generator_id.to_string(),
            generator_code_digest: value.generator_code_digest.to_string(),
            grammar_digest: value.grammar_digest.to_string(),
            hard_filter_digest: value.hard_filter_digest.to_string(),
            truncation_digest: value.truncation_digest.to_string(),
            candidates_digest: value.candidates_digest.to_string(),
            candidate_count: value.candidate_count,
            omitted_count_bound: value.omitted_count_bound,
            canonical_order_digest: value.canonical_order_digest.to_string(),
            complete_for_generator: value.complete_for_generator,
        }
    }

    fn to_completeness(
        &self,
    ) -> Result<CandidateSetCompletenessReceiptV1, IntelligenceLearningErrorV1> {
        Ok(CandidateSetCompletenessReceiptV1 {
            set_id: parse_id(&self.set_id, "candidate set")?,
            state_digest: parse_digest(&self.state_digest, "candidate state")?,
            generator_id: parse_id(&self.generator_id, "candidate generator")?,
            generator_code_digest: parse_digest(
                &self.generator_code_digest,
                "generator code",
            )?,
            grammar_digest: parse_digest(&self.grammar_digest, "grammar")?,
            hard_filter_digest: parse_digest(&self.hard_filter_digest, "hard filter")?,
            truncation_digest: parse_digest(&self.truncation_digest, "truncation")?,
            candidates_digest: parse_digest(&self.candidates_digest, "candidates")?,
            candidate_count: self.candidate_count,
            omitted_count_bound: self.omitted_count_bound,
            canonical_order_digest: parse_digest(
                &self.canonical_order_digest,
                "candidate order",
            )?,
            complete_for_generator: self.complete_for_generator,
        })
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct DecisionFileV1 {
    record_id: String,
    episode_id: String,
    run_snapshot_digest: String,
    objective_digest: String,
    policy_digest: String,
    candidate_ids: Vec<String>,
    selected_candidate_id: String,
    selected_propensity_raw: u64,
    completeness: CompletenessFileV1,
    support_digest: String,
}

impl DecisionFileV1 {
    fn from_decision(value: &ProductionDecisionV2) -> Self {
        Self {
            record_id: value.record_id.to_string(),
            episode_id: value.episode_id.to_string(),
            run_snapshot_digest: value.run_snapshot_digest.to_string(),
            objective_digest: value.objective_digest.to_string(),
            policy_digest: value.policy_digest.to_string(),
            candidate_ids: value.candidate_ids.iter().map(ToString::to_string).collect(),
            selected_candidate_id: value.selected_candidate_id.to_string(),
            selected_propensity_raw: value.selected_propensity.raw(),
            completeness: CompletenessFileV1::from_completeness(&value.completeness),
            support_digest: value.support_digest.to_string(),
        }
    }

    fn to_decision(&self) -> Result<ProductionDecisionV2, IntelligenceLearningErrorV1> {
        Ok(ProductionDecisionV2 {
            record_id: parse_id(&self.record_id, "decision record")?,
            episode_id: parse_id(&self.episode_id, "episode")?,
            run_snapshot_digest: parse_digest(&self.run_snapshot_digest, "run snapshot")?,
            objective_digest: parse_digest(&self.objective_digest, "objective")?,
            policy_digest: parse_digest(&self.policy_digest, "policy")?,
            candidate_ids: self
                .candidate_ids
                .iter()
                .map(|value| parse_id(value, "candidate"))
                .collect::<Result<Vec<_>, _>>()?,
            selected_candidate_id: parse_id(&self.selected_candidate_id, "selected candidate")?,
            selected_propensity: ProbabilityQ32::from_raw(self.selected_propensity_raw)
                .map_err(|_| IntelligenceLearningErrorV1::Invalid("propensity"))?,
            completeness: self.completeness.to_completeness()?,
            support_digest: parse_digest(&self.support_digest, "decision support")?,
        })
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct PrincipalFileV1 {
    principal_id: String,
    credential_chain_digest: String,
    signing_key_digest: String,
    scope_digest: String,
    authority_epoch: u64,
    authenticated_at: u64,
    expires_at: u64,
}

impl PrincipalFileV1 {
    fn from_principal(value: &AuthenticatedPrincipalV1) -> Self {
        Self {
            principal_id: value.principal_id.to_string(),
            credential_chain_digest: value.credential_chain_digest.to_string(),
            signing_key_digest: value.signing_key_digest.to_string(),
            scope_digest: value.scope_digest.to_string(),
            authority_epoch: value.authority_epoch,
            authenticated_at: value.authenticated_at,
            expires_at: value.expires_at,
        }
    }

    fn to_principal(&self) -> Result<AuthenticatedPrincipalV1, IntelligenceLearningErrorV1> {
        Ok(AuthenticatedPrincipalV1 {
            principal_id: parse_id(&self.principal_id, "principal")?,
            credential_chain_digest: parse_digest(
                &self.credential_chain_digest,
                "credential chain",
            )?,
            signing_key_digest: parse_digest(&self.signing_key_digest, "signing key")?,
            scope_digest: parse_digest(&self.scope_digest, "scope")?,
            authority_epoch: self.authority_epoch,
            authenticated_at: self.authenticated_at,
            expires_at: self.expires_at,
        })
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct WatermarkFileV1 {
    latest_observable_at: u64,
    expected_delay_profile_digest: String,
    terminality: String,
    censoring_reason: Option<String>,
    correction_predecessor: Option<String>,
    finalized_at: Option<u64>,
}

impl WatermarkFileV1 {
    fn from_watermark(value: &OutcomeWatermarkV1) -> Self {
        Self {
            latest_observable_at: value.latest_observable_at,
            expected_delay_profile_digest: value.expected_delay_profile_digest.to_string(),
            terminality: match value.terminality {
                OutcomeTerminalityV1::Pending => "pending",
                OutcomeTerminalityV1::Censored => "censored",
                OutcomeTerminalityV1::Terminal => "terminal",
            }
            .to_string(),
            censoring_reason: value.censoring_reason.as_ref().map(ToString::to_string),
            correction_predecessor: value
                .correction_predecessor
                .as_ref()
                .map(ToString::to_string),
            finalized_at: value.finalized_at,
        }
    }

    fn to_watermark(&self) -> Result<OutcomeWatermarkV1, IntelligenceLearningErrorV1> {
        let terminality = match self.terminality.as_str() {
            "pending" => OutcomeTerminalityV1::Pending,
            "censored" => OutcomeTerminalityV1::Censored,
            "terminal" => OutcomeTerminalityV1::Terminal,
            _ => return Err(IntelligenceLearningErrorV1::Invalid("terminality")),
        };
        Ok(OutcomeWatermarkV1 {
            latest_observable_at: self.latest_observable_at,
            expected_delay_profile_digest: parse_digest(
                &self.expected_delay_profile_digest,
                "delay profile",
            )?,
            terminality,
            censoring_reason: self
                .censoring_reason
                .as_deref()
                .map(|value| parse_id(value, "censoring reason"))
                .transpose()?,
            correction_predecessor: self
                .correction_predecessor
                .as_deref()
                .map(|value| parse_id(value, "correction predecessor"))
                .transpose()?,
            finalized_at: self.finalized_at,
        })
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct OutcomeFileV1 {
    record_id: String,
    outcome_id: String,
    episode_id: String,
    observer: PrincipalFileV1,
    observed_at: Option<u64>,
    value_raw: Option<i64>,
    unit_profile_digest: String,
    support_digest: String,
    watermark: WatermarkFileV1,
}

impl OutcomeFileV1 {
    fn from_outcome(value: &AuthenticatedOutcomeV1) -> Self {
        Self {
            record_id: value.record_id.to_string(),
            outcome_id: value.outcome_id.to_string(),
            episode_id: value.episode_id.to_string(),
            observer: PrincipalFileV1::from_principal(&value.observer),
            observed_at: value.observed_at,
            value_raw: value.value.map(FixedQ32::raw),
            unit_profile_digest: value.unit_profile_digest.to_string(),
            support_digest: value.support_digest.to_string(),
            watermark: WatermarkFileV1::from_watermark(&value.watermark),
        }
    }

    fn to_outcome(&self) -> Result<AuthenticatedOutcomeV1, IntelligenceLearningErrorV1> {
        Ok(AuthenticatedOutcomeV1 {
            record_id: parse_id(&self.record_id, "outcome record")?,
            outcome_id: parse_id(&self.outcome_id, "outcome")?,
            episode_id: parse_id(&self.episode_id, "episode")?,
            observer: self.observer.to_principal()?,
            observed_at: self.observed_at,
            value: self.value_raw.map(FixedQ32::from_raw),
            unit_profile_digest: parse_digest(&self.unit_profile_digest, "unit profile")?,
            support_digest: parse_digest(&self.support_digest, "outcome support")?,
            watermark: self.watermark.to_watermark()?,
        })
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct EvidenceFileV1 {
    evidence_id: String,
    principal_id: String,
    role: String,
    trust_digest: String,
    scope_digest: String,
    objective_digest: String,
    authority_epoch: u64,
    issued_at: u64,
    expires_at: u64,
    payload_digest: String,
    signature_hex: String,
}

impl EvidenceFileV1 {
    fn from_evidence(value: &SignedLearningEvidenceV1) -> Self {
        Self {
            evidence_id: value.evidence_id.to_string(),
            principal_id: value.principal_id.to_string(),
            role: role_name(value.role).to_string(),
            trust_digest: value.trust_digest.to_string(),
            scope_digest: value.scope_digest.to_string(),
            objective_digest: value.objective_digest.to_string(),
            authority_epoch: value.authority_epoch,
            issued_at: value.issued_at,
            expires_at: value.expires_at,
            payload_digest: value.payload_digest.to_string(),
            signature_hex: encode_hex(&value.signature),
        }
    }

    fn to_evidence(&self) -> Result<SignedLearningEvidenceV1, IntelligenceLearningErrorV1> {
        Ok(SignedLearningEvidenceV1 {
            evidence_id: parse_id(&self.evidence_id, "evidence")?,
            principal_id: parse_id(&self.principal_id, "evidence principal")?,
            role: parse_role(&self.role)?,
            trust_digest: parse_digest(&self.trust_digest, "evidence trust")?,
            scope_digest: parse_digest(&self.scope_digest, "evidence scope")?,
            objective_digest: parse_digest(&self.objective_digest, "evidence objective")?,
            authority_epoch: self.authority_epoch,
            issued_at: self.issued_at,
            expires_at: self.expires_at,
            payload_digest: parse_digest(&self.payload_digest, "evidence payload")?,
            signature: decode_signature(&self.signature_hex)?,
        })
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(tag = "state", rename_all = "snake_case", deny_unknown_fields)]
enum StateFileV1 {
    Pending,
    Acknowledged { acknowledgement_digest: String },
    Rejected { reason_digest: String },
    Revoked { reason_digest: String },
    Indeterminate { reason_digest: String },
}

impl StateFileV1 {
    fn from_state(value: &IntelligenceLearningStateV1) -> Self {
        match value {
            IntelligenceLearningStateV1::Pending => Self::Pending,
            IntelligenceLearningStateV1::Acknowledged {
                acknowledgement_digest,
            } => Self::Acknowledged {
                acknowledgement_digest: acknowledgement_digest.to_string(),
            },
            IntelligenceLearningStateV1::Rejected { reason_digest } => Self::Rejected {
                reason_digest: reason_digest.to_string(),
            },
            IntelligenceLearningStateV1::Revoked { reason_digest } => Self::Revoked {
                reason_digest: reason_digest.to_string(),
            },
            IntelligenceLearningStateV1::Indeterminate { reason_digest } => {
                Self::Indeterminate {
                    reason_digest: reason_digest.to_string(),
                }
            }
        }
    }

    fn to_state(&self) -> Result<IntelligenceLearningStateV1, IntelligenceLearningErrorV1> {
        match self {
            Self::Pending => Ok(IntelligenceLearningStateV1::Pending),
            Self::Acknowledged {
                acknowledgement_digest,
            } => Ok(IntelligenceLearningStateV1::Acknowledged {
                acknowledgement_digest: nonzero_digest(acknowledgement_digest, "acknowledgement")?,
            }),
            Self::Rejected { reason_digest } => Ok(IntelligenceLearningStateV1::Rejected {
                reason_digest: nonzero_digest(reason_digest, "rejection")?,
            }),
            Self::Revoked { reason_digest } => Ok(IntelligenceLearningStateV1::Revoked {
                reason_digest: nonzero_digest(reason_digest, "revocation")?,
            }),
            Self::Indeterminate { reason_digest } => {
                Ok(IntelligenceLearningStateV1::Indeterminate {
                    reason_digest: nonzero_digest(reason_digest, "indeterminate")?,
                })
            }
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(tag = "event", rename_all = "snake_case", deny_unknown_fields)]
enum JournalEventFileV1 {
    Enqueue {
        intent: IntentFileV1,
    },
    Attempt {
        intent_id: String,
        expected_record_digest: String,
        attempt: u32,
    },
    Transition {
        intent_id: String,
        expected_record_digest: String,
        state: StateFileV1,
    },
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct JournalFrameFileV1 {
    schema_version: u32,
    sequence: u64,
    predecessor_digest: String,
    event: JournalEventFileV1,
    frame_digest: String,
}

fn parse_id(value: &str, field: &'static str) -> Result<StableId, IntelligenceLearningErrorV1> {
    StableId::new(value.to_string()).map_err(|_| IntelligenceLearningErrorV1::Invalid(field))
}

fn parse_digest(
    value: &str,
    field: &'static str,
) -> Result<Digest32, IntelligenceLearningErrorV1> {
    Digest32::from_str(value).map_err(|_| IntelligenceLearningErrorV1::Invalid(field))
}

fn nonzero_digest(
    value: &str,
    field: &'static str,
) -> Result<Digest32, IntelligenceLearningErrorV1> {
    let digest = parse_digest(value, field)?;
    if digest.is_zero() {
        Err(IntelligenceLearningErrorV1::Invalid(field))
    } else {
        Ok(digest)
    }
}

fn role_name(value: LearningEvidenceRoleV1) -> &'static str {
    match value {
        LearningEvidenceRoleV1::Generator => "generator",
        LearningEvidenceRoleV1::Observer => "observer",
        LearningEvidenceRoleV1::Evaluator => "evaluator",
        LearningEvidenceRoleV1::CreditAllocator => "credit_allocator",
        LearningEvidenceRoleV1::UnlearningAuthority => "unlearning_authority",
        LearningEvidenceRoleV1::Selector => "selector",
    }
}

fn parse_role(value: &str) -> Result<LearningEvidenceRoleV1, IntelligenceLearningErrorV1> {
    match value {
        "generator" => Ok(LearningEvidenceRoleV1::Generator),
        "observer" => Ok(LearningEvidenceRoleV1::Observer),
        "evaluator" => Ok(LearningEvidenceRoleV1::Evaluator),
        "credit_allocator" => Ok(LearningEvidenceRoleV1::CreditAllocator),
        "unlearning_authority" => Ok(LearningEvidenceRoleV1::UnlearningAuthority),
        "selector" => Ok(LearningEvidenceRoleV1::Selector),
        _ => Err(IntelligenceLearningErrorV1::Invalid("evidence role")),
    }
}

fn encode_hex(value: &[u8]) -> String {
    const HEX: &[u8; 16] = b"0123456789abcdef";
    let mut output = String::with_capacity(value.len() * 2);
    for byte in value {
        output.push(char::from(HEX[usize::from(byte >> 4)]));
        output.push(char::from(HEX[usize::from(byte & 0x0f)]));
    }
    output
}

fn decode_signature(value: &str) -> Result<[u8; 64], IntelligenceLearningErrorV1> {
    if value.len() != 128 || !value.bytes().all(|byte| byte.is_ascii_hexdigit()) {
        return Err(IntelligenceLearningErrorV1::Invalid("evidence signature"));
    }
    let mut output = [0_u8; 64];
    for (index, slot) in output.iter_mut().enumerate() {
        let offset = index * 2;
        *slot = u8::from_str_radix(&value[offset..offset + 2], 16)
            .map_err(|_| IntelligenceLearningErrorV1::Invalid("evidence signature"))?;
    }
    Ok(output)
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) -> Result<(), IntelligenceLearningErrorV1> {
    let raw = value.as_str().as_bytes();
    let length = u32::try_from(raw.len())
        .map_err(|_| IntelligenceLearningErrorV1::Invalid("identifier length"))?;
    bytes.extend_from_slice(&length.to_be_bytes());
    bytes.extend_from_slice(raw);
    Ok(())
}

#[derive(Debug)]
pub enum IntelligenceLearningErrorV1 {
    Invalid(&'static str),
    Busy,
    Missing,
    Conflict,
    Capacity,
    Corrupt,
    Poisoned,
    Io(std::io::ErrorKind),
    Serialization,
}

impl fmt::Display for IntelligenceLearningErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for IntelligenceLearningErrorV1 {}

impl From<std::io::Error> for IntelligenceLearningErrorV1 {
    fn from(value: std::io::Error) -> Self {
        Self::Io(value.kind())
    }
}

impl From<serde_json::Error> for IntelligenceLearningErrorV1 {
    fn from(_value: serde_json::Error) -> Self {
        Self::Serialization
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::VecDeque;

    fn id(value: &str) -> StableId {
        StableId::new(value).unwrap()
    }

    fn digest(value: &str) -> Digest32 {
        Digest32::of_bytes(value.as_bytes())
    }

    fn binding() -> IntelligenceLearningBindingV1 {
        IntelligenceLearningBindingV1::new(
            id("run.learning"),
            digest("snapshot"),
            digest("objective"),
            digest("envelope"),
            digest("candidate-set"),
            digest("dispatch"),
            id("run.learning"),
            id("episode.learning"),
            id("candidate.selected"),
        )
        .unwrap()
    }

    fn decision(binding: &IntelligenceLearningBindingV1) -> ProductionDecisionV2 {
        ProductionDecisionV2 {
            record_id: binding.decision_record_id().clone(),
            episode_id: binding.episode_id().clone(),
            run_snapshot_digest: binding.run_snapshot_digest(),
            objective_digest: binding.objective_digest(),
            policy_digest: digest("policy"),
            candidate_ids: vec![binding.selected_candidate_id().clone()],
            selected_candidate_id: binding.selected_candidate_id().clone(),
            selected_propensity: ProbabilityQ32::from_raw(1).unwrap(),
            completeness: CandidateSetCompletenessReceiptV1 {
                set_id: id("candidate.set"),
                state_digest: binding.objective_digest(),
                generator_id: id("intelligence.control"),
                generator_code_digest: digest("generator"),
                grammar_digest: digest("grammar"),
                hard_filter_digest: digest("hard-filter"),
                truncation_digest: digest("truncation"),
                candidates_digest: binding.candidate_set_digest(),
                candidate_count: 1,
                omitted_count_bound: 0,
                canonical_order_digest: digest("candidate-order"),
                complete_for_generator: true,
            },
            support_digest: binding.dispatch_proposal_digest(),
        }
    }

    fn evidence(
        role: LearningEvidenceRoleV1,
        objective_digest: Digest32,
        payload_digest: Digest32,
    ) -> SignedLearningEvidenceV1 {
        SignedLearningEvidenceV1 {
            evidence_id: id(match role {
                LearningEvidenceRoleV1::Generator => "evidence.generator",
                _ => "evidence.observer",
            }),
            principal_id: id(match role {
                LearningEvidenceRoleV1::Generator => "principal.generator",
                _ => "principal.observer",
            }),
            role,
            trust_digest: digest("trust"),
            scope_digest: digest("scope"),
            objective_digest,
            authority_epoch: 7,
            issued_at: 1,
            expires_at: 10_000,
            payload_digest,
            signature: [7; 64],
        }
    }

    struct FakeDestination {
        results: VecDeque<IntelligenceLearningAppendDispositionV1>,
        calls: usize,
    }

    impl IntelligenceLearningDestinationV1 for FakeDestination {
        fn append(
            &mut self,
            _intent: &IntelligenceLearningIntentV1,
            _now: u64,
        ) -> IntelligenceLearningAppendDispositionV1 {
            self.calls += 1;
            self.results.pop_front().unwrap()
        }
    }

    #[test]
    fn pending_intent_reopens_and_acknowledges_exactly() {
        let temp = tempfile::tempdir().unwrap();
        let path = temp.path().join("learning-outbox.jsonl");
        let binding = binding();
        let decision = decision(&binding);
        let payload = decision_signing_payload_v2(&decision).unwrap();
        let evidence = evidence(
            LearningEvidenceRoleV1::Generator,
            binding.objective_digest(),
            Digest32::of_bytes(&payload),
        );
        let intent_id = {
            let mut outbox = AgentdIntelligenceLearningOutboxV1::open(path.clone()).unwrap();
            let status = outbox
                .enqueue_decision(binding, Digest32::ZERO, decision, evidence, 10)
                .unwrap();
            assert_eq!(status.state, IntelligenceLearningStateV1::Pending);
            status.intent_id
        };
        let mut outbox = AgentdIntelligenceLearningOutboxV1::open(path.clone()).unwrap();
        assert_eq!(outbox.backlog(), 1);
        let acknowledgement = digest("ack");
        let mut destination = FakeDestination {
            results: VecDeque::from([
                IntelligenceLearningAppendDispositionV1::Acknowledged(acknowledgement),
            ]),
            calls: 0,
        };
        let status = outbox
            .reconcile_one(&mut destination, &intent_id, 11)
            .unwrap();
        assert_eq!(destination.calls, 1);
        assert_eq!(
            status.state,
            IntelligenceLearningStateV1::Acknowledged {
                acknowledgement_digest: acknowledgement
            }
        );
        drop(outbox);
        let reopened = AgentdIntelligenceLearningOutboxV1::open(path).unwrap();
        assert_eq!(reopened.backlog(), 0);
        assert_eq!(reopened.status(&intent_id).unwrap(), status);
    }

    #[test]
    fn indeterminate_is_reconcile_only_and_can_close_on_exact_retry() {
        let temp = tempfile::tempdir().unwrap();
        let path = temp.path().join("learning-outbox.jsonl");
        let binding = binding();
        let decision = decision(&binding);
        let payload = decision_signing_payload_v2(&decision).unwrap();
        let evidence = evidence(
            LearningEvidenceRoleV1::Generator,
            binding.objective_digest(),
            Digest32::of_bytes(&payload),
        );
        let mut outbox = AgentdIntelligenceLearningOutboxV1::open(path).unwrap();
        let status = outbox
            .enqueue_decision(binding, Digest32::ZERO, decision, evidence, 10)
            .unwrap();
        let reason = digest("ambiguous");
        let acknowledgement = digest("acknowledged");
        let mut destination = FakeDestination {
            results: VecDeque::from([
                IntelligenceLearningAppendDispositionV1::Indeterminate(reason),
                IntelligenceLearningAppendDispositionV1::Acknowledged(acknowledgement),
            ]),
            calls: 0,
        };
        let first = outbox
            .reconcile_one(&mut destination, &status.intent_id, 11)
            .unwrap();
        assert_eq!(
            first.state,
            IntelligenceLearningStateV1::Indeterminate {
                reason_digest: reason
            }
        );
        let second = outbox
            .reconcile_one(&mut destination, &status.intent_id, 12)
            .unwrap();
        assert_eq!(second.attempts, 2);
        assert_eq!(
            second.state,
            IntelligenceLearningStateV1::Acknowledged {
                acknowledgement_digest: acknowledgement
            }
        );
    }

    #[test]
    fn physical_outcome_must_bind_terminal_observation_and_decision() {
        let binding = binding();
        let observation = digest("physical-terminal-observation");
        let observer = AuthenticatedPrincipalV1 {
            principal_id: id("principal.observer"),
            credential_chain_digest: digest("observer-chain"),
            signing_key_digest: digest("observer-key"),
            scope_digest: digest("scope"),
            authority_epoch: 7,
            authenticated_at: 1,
            expires_at: 10_000,
        };
        let outcome = AuthenticatedOutcomeV1 {
            record_id: id("outcome.record"),
            outcome_id: id("outcome.id"),
            episode_id: binding.episode_id().clone(),
            observer,
            observed_at: Some(20),
            value: Some(FixedQ32::from_raw(1)),
            unit_profile_digest: digest("unit"),
            support_digest: digest("wrong-support"),
            watermark: OutcomeWatermarkV1 {
                latest_observable_at: 20,
                expected_delay_profile_digest: digest("delay"),
                terminality: OutcomeTerminalityV1::Terminal,
                censoring_reason: None,
                correction_predecessor: None,
                finalized_at: Some(20),
            },
        };
        let payload = outcome_signing_payload_v2(&outcome);
        let evidence = evidence(
            LearningEvidenceRoleV1::Observer,
            binding.objective_digest(),
            Digest32::of_bytes(&payload),
        );
        assert!(
            IntelligenceLearningIntentV1::outcome(
                binding,
                Digest32::ZERO,
                observation,
                outcome,
                evidence,
                20,
            )
            .is_err()
        );
    }
}
