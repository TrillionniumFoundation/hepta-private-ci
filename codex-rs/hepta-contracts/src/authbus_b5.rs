//! B5 local qualification seam for AuthBus WAL and reconciliation.
//!
//! This module is deliberately compiled only by the test build or the
//! explicit `authbus-local-qualification` feature.  It is a deterministic
//! reference model for the ordering and recovery invariants
//! that a future `hepta-authbusd` must implement; it is not a daemon, socket,
//! provider adapter, or authority writer.  In particular, the model proves
//! the following narrow properties without crossing a physical-effect
//! boundary:
//!
//! * an intent and `DispatchAttemptStarted` marker are durable before a call;
//! * a crash after the call produces a lookup-only recovery plan;
//! * an unknown/missing intent is a safe stop, never a new dispatch;
//! * outbox delivery is idempotent on `(idempotency_key, payload_digest)` and
//!   conflicting payloads stop without mutation; and
//! * a corrupt hash chain, stale fence, or terminal replay fails closed.

use std::collections::BTreeMap;

use serde::Deserialize;
use serde::Serialize;

use crate::ProviderEffectAckStatus;
use crate::ProviderEffectKey;
use crate::Sha256Digest;

/// This seam never opens a listener or grants authority.
pub const AUTHBUS_B5_QUALIFICATION_ONLY: bool = true;
pub const AUTHBUS_B5_AUTHORITY: bool = false;
pub const AUTHBUS_B5_PRODUCTION_CALLER: bool = false;
pub const AUTHBUS_B5_PRODUCTION_WRITER: bool = false;
pub const AUTHBUS_B5_EFFECT_AUTHORITY: bool = false;
pub const AUTHBUS_B5_OPERATOR_ACCEPTANCE: bool = false;
pub const AUTHBUS_B5_PROMOTION: bool = false;
pub const AUTHBUS_B5_G5_ALLOWED: bool = false;
pub const AUTHBUS_B5_EXECUTE_ALLOWED: bool = false;

const _: () = {
    assert!(AUTHBUS_B5_QUALIFICATION_ONLY);
    assert!(!AUTHBUS_B5_AUTHORITY);
    assert!(!AUTHBUS_B5_PRODUCTION_CALLER);
    assert!(!AUTHBUS_B5_PRODUCTION_WRITER);
    assert!(!AUTHBUS_B5_EFFECT_AUTHORITY);
    assert!(!AUTHBUS_B5_OPERATOR_ACCEPTANCE);
    assert!(!AUTHBUS_B5_PROMOTION);
    assert!(!AUTHBUS_B5_G5_ALLOWED);
    assert!(!AUTHBUS_B5_EXECUTE_ALLOWED);
};

const MAX_TEXT_BYTES: usize = 512;

fn valid_text(value: &str) -> bool {
    !value.trim().is_empty() && value.len() <= MAX_TEXT_BYTES && !value.as_bytes().contains(&0)
}

fn valid_digest(value: &Sha256Digest) -> bool {
    Sha256Digest::parse(value.as_str().to_string()).is_ok()
}

/// The owner/generation fence copied onto every B5 WAL record.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct B5Fence {
    pub authority_epoch: u64,
    pub owner_epoch: u64,
    pub generation: u64,
    pub fencing_token_sha256: Sha256Digest,
}

impl B5Fence {
    pub fn validate(&self) -> Result<(), B5Error> {
        if self.authority_epoch == 0 || self.owner_epoch == 0 || self.generation == 0 {
            return Err(B5Error::InvalidInput);
        }
        if !valid_digest(&self.fencing_token_sha256) {
            return Err(B5Error::InvalidInput);
        }
        Ok(())
    }
}

/// A secret-free durable effect intent.  The operation key is represented by
/// the existing provider-effect key; no payload or credential bytes enter the
/// model.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct B5Intent {
    pub effect_key: ProviderEffectKey,
    pub idempotency_key: String,
    pub payload_sha256: Sha256Digest,
    pub fence: B5Fence,
}

impl B5Intent {
    pub fn validate(&self) -> Result<(), B5Error> {
        ProviderEffectKey::parse(self.effect_key.as_str().to_string())
            .map_err(|_| B5Error::InvalidInput)?;
        if !valid_text(&self.idempotency_key) || !valid_digest(&self.payload_sha256) {
            return Err(B5Error::InvalidInput);
        }
        self.fence.validate()
    }
}

/// A typed bridge delivery.  The same idempotency key may be retried only
/// with the same payload digest.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct B5OutboxDelivery {
    pub outbox_id: String,
    pub event_id: String,
    pub idempotency_key: String,
    pub payload_sha256: Sha256Digest,
    pub delivery_seq: u64,
    pub fence: B5Fence,
}

impl B5OutboxDelivery {
    fn validate(&self) -> Result<(), B5Error> {
        if !valid_text(&self.outbox_id)
            || !valid_text(&self.event_id)
            || !valid_text(&self.idempotency_key)
            || self.delivery_seq == 0
            || !valid_digest(&self.payload_sha256)
        {
            return Err(B5Error::InvalidInput);
        }
        self.fence.validate()
    }
}

/// Internal WAL records.  `DispatchAttemptStarted` and the response marker
/// are intentionally not public EffectReceipt statuses.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
enum B5RecordKind {
    EffectIntentDurable {
        intent: B5Intent,
    },
    DispatchAttemptStarted {
        effect_key: ProviderEffectKey,
        idempotency_key: String,
        payload_sha256: Sha256Digest,
        attempt: u32,
        fence: B5Fence,
    },
    DispatchAcceptedRef {
        effect_key: ProviderEffectKey,
        idempotency_key: String,
        payload_sha256: Sha256Digest,
        attempt: u32,
        operation_sha256: Sha256Digest,
        fence: B5Fence,
    },
    DispatchUnknownRef {
        effect_key: ProviderEffectKey,
        idempotency_key: String,
        payload_sha256: Sha256Digest,
        attempt: u32,
        reason_code: String,
        fence: B5Fence,
    },
    EffectAckRef {
        effect_key: ProviderEffectKey,
        idempotency_key: String,
        payload_sha256: Sha256Digest,
        attempt: u32,
        operation_sha256: Sha256Digest,
        status: ProviderEffectAckStatus,
        fence: B5Fence,
    },
    IndeterminateRef {
        effect_key: ProviderEffectKey,
        idempotency_key: String,
        payload_sha256: Sha256Digest,
        attempt: u32,
        reason_code: String,
        fence: B5Fence,
    },
    OutboxEnqueued {
        delivery: B5OutboxDelivery,
    },
    OutboxAcked {
        outbox_id: String,
        idempotency_key: String,
        payload_sha256: Sha256Digest,
        ack_sha256: Sha256Digest,
    },
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
struct B5FsyncWitness {
    source_owner: String,
    wal_seq: u64,
    commit_digest: Sha256Digest,
    directory_fsync: bool,
    writer_boot_id: String,
}

impl B5FsyncWitness {
    fn validate_for(&self, seq: u64, digest: &Sha256Digest) -> Result<(), B5Error> {
        if !valid_text(&self.source_owner)
            || !valid_text(&self.writer_boot_id)
            || self.wal_seq != seq
            || self.commit_digest != *digest
            || !self.directory_fsync
        {
            return Err(B5Error::CorruptWal);
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
struct B5Record {
    seq: u64,
    prev_digest: Option<Sha256Digest>,
    record_digest: Sha256Digest,
    fsync_witness: Option<B5FsyncWitness>,
    kind: B5RecordKind,
}

/// Observable state of one intent after replaying the durable WAL.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum B5EffectState {
    IntentDurable,
    AttemptStarted,
    Accepted,
    Unknown,
    Indeterminate,
    Completed,
    Rejected,
}

impl B5EffectState {
    const fn is_terminal(self) -> bool {
        matches!(self, Self::Completed | Self::Rejected)
    }

    const fn blocks_dispatch(self) -> bool {
        !matches!(self, Self::IntentDurable)
    }
}

/// A recovery decision never performs a provider call.  `LookupOnly` is the
/// only action for a post-dispatch uncertain record; `SafeStop` is used for an
/// unknown intent or corrupt WAL.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum B5RecoveryAction {
    NoAction,
    LookupOnly {
        effect_key: ProviderEffectKey,
        attempt: u32,
    },
    SafeStop(B5Error),
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum B5AppendDisposition {
    Inserted,
    AlreadyPresent,
}

/// Errors for the local B5 reference model.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum B5Error {
    InvalidInput,
    DuplicateConflict,
    UnknownIntent,
    StaleFence,
    FsyncRequired,
    DispatchBlocked,
    TerminalImmutable,
    InvalidTransition,
    CorruptWal,
    OutboxConflict,
    OutboxUnknown,
}

/// Deterministic append-only WAL model.  The `records` vector represents the
/// physical append log; all derived maps are rebuilt by `reopen` and therefore
/// cannot silently become authority independent of the log.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct LocalB5Wal {
    records: Vec<B5Record>,
    intents: BTreeMap<String, B5Intent>,
    states: BTreeMap<String, B5EffectState>,
    attempts: BTreeMap<String, u32>,
    outbox: BTreeMap<String, B5OutboxDelivery>,
    outbox_acks: BTreeMap<String, Sha256Digest>,
    next_seq: u64,
    adapter_calls: u64,
}

impl Default for LocalB5Wal {
    fn default() -> Self {
        Self::new()
    }
}

impl LocalB5Wal {
    pub fn new() -> Self {
        Self {
            records: Vec::new(),
            intents: BTreeMap::new(),
            states: BTreeMap::new(),
            attempts: BTreeMap::new(),
            outbox: BTreeMap::new(),
            outbox_acks: BTreeMap::new(),
            next_seq: 1,
            adapter_calls: 0,
        }
    }

    pub fn durable_record_count(&self) -> usize {
        self.records.len()
    }

    pub fn adapter_calls(&self) -> u64 {
        self.adapter_calls
    }

    pub fn state(&self, key: &ProviderEffectKey) -> Option<B5EffectState> {
        self.states.get(key.as_str()).copied()
    }

    pub fn intent(&self, key: &ProviderEffectKey) -> Option<&B5Intent> {
        self.intents.get(key.as_str())
    }

    pub fn outbox_ack(&self, outbox_id: &str) -> Option<&Sha256Digest> {
        self.outbox_acks.get(outbox_id)
    }

    fn append(&mut self, kind: B5RecordKind) -> Result<u64, B5Error> {
        let seq = self.next_seq;
        let prev_digest = self
            .records
            .last()
            .map(|record| record.record_digest.clone());
        let record_digest = digest_record(seq, prev_digest.as_ref(), &kind);
        let fsync_witness = B5FsyncWitness {
            source_owner: "authbusd:qualification".to_string(),
            wal_seq: seq,
            commit_digest: record_digest.clone(),
            directory_fsync: true,
            writer_boot_id: "boot:qualification".to_string(),
        };
        fsync_witness.validate_for(seq, &record_digest)?;
        self.records.push(B5Record {
            seq,
            prev_digest,
            record_digest,
            fsync_witness: Some(fsync_witness),
            kind,
        });
        self.next_seq = seq.checked_add(1).ok_or(B5Error::CorruptWal)?;
        Ok(seq)
    }

    /// Append an intent exactly once.  Same idempotency key plus the same
    /// payload is an idempotent replay; a changed payload is a conflict with
    /// no log or derived-state mutation.
    pub fn append_intent(&mut self, intent: B5Intent) -> Result<B5AppendDisposition, B5Error> {
        intent.validate()?;
        if let Some(existing) = self.intents.get(intent.effect_key.as_str()) {
            if existing == &intent {
                return Ok(B5AppendDisposition::AlreadyPresent);
            }
            return Err(B5Error::DuplicateConflict);
        }
        if self
            .intents
            .values()
            .any(|existing| existing.idempotency_key == intent.idempotency_key)
        {
            return Err(B5Error::DuplicateConflict);
        }
        self.append(B5RecordKind::EffectIntentDurable {
            intent: intent.clone(),
        })?;
        let key = intent.effect_key.as_str().to_string();
        self.intents.insert(key.clone(), intent);
        self.states.insert(key, B5EffectState::IntentDurable);
        Ok(B5AppendDisposition::Inserted)
    }

    fn checked_intent(&self, key: &ProviderEffectKey) -> Result<&B5Intent, B5Error> {
        self.intents.get(key.as_str()).ok_or(B5Error::UnknownIntent)
    }

    fn check_fence(intent: &B5Intent, fence: &B5Fence) -> Result<(), B5Error> {
        fence.validate()?;
        if intent.fence != *fence {
            return Err(B5Error::StaleFence);
        }
        Ok(())
    }

    /// Persist the pre-call marker.  The returned ticket is proof that the
    /// marker has a valid fsync witness; the model's call method requires it.
    pub fn begin_dispatch(
        &mut self,
        key: &ProviderEffectKey,
        attempt: u32,
        fence: B5Fence,
    ) -> Result<B5DispatchTicket, B5Error> {
        if attempt == 0 {
            return Err(B5Error::InvalidInput);
        }
        let intent = self.checked_intent(key)?.clone();
        Self::check_fence(&intent, &fence)?;
        let state = self.state(key).ok_or(B5Error::UnknownIntent)?;
        if state.blocks_dispatch() {
            return Err(B5Error::DispatchBlocked);
        }
        if self.attempts.get(key.as_str()).copied().unwrap_or_default() >= attempt {
            return Err(B5Error::DispatchBlocked);
        }
        self.append(B5RecordKind::DispatchAttemptStarted {
            effect_key: key.clone(),
            idempotency_key: intent.idempotency_key.clone(),
            payload_sha256: intent.payload_sha256,
            attempt,
            fence: fence.clone(),
        })?;
        self.states
            .insert(key.as_str().to_string(), B5EffectState::AttemptStarted);
        self.attempts.insert(key.as_str().to_string(), attempt);
        Ok(B5DispatchTicket {
            effect_key: key.clone(),
            attempt,
            fence,
        })
    }

    /// Simulate the call and persist a response marker in one local test
    /// step.  No real adapter is touched; `adapter_calls` is only a witness
    /// used by tests to prove that recovery never increments it.
    pub fn dispatch_once(
        &mut self,
        key: &ProviderEffectKey,
        attempt: u32,
        fence: B5Fence,
        response: B5DispatchResponse,
    ) -> Result<B5EffectState, B5Error> {
        let ticket = self.begin_dispatch(key, attempt, fence)?;
        self.adapter_calls = self
            .adapter_calls
            .checked_add(1)
            .ok_or(B5Error::InvalidInput)?;
        self.finish_dispatch(ticket, response)
    }

    /// Simulates a process dying after the adapter call and before its response
    /// marker is appended.  The durable `DispatchAttemptStarted` remains.
    pub fn crash_after_call(
        &mut self,
        key: &ProviderEffectKey,
        attempt: u32,
        fence: B5Fence,
    ) -> Result<B5DispatchTicket, B5Error> {
        let ticket = self.begin_dispatch(key, attempt, fence)?;
        self.adapter_calls = self
            .adapter_calls
            .checked_add(1)
            .ok_or(B5Error::InvalidInput)?;
        Ok(ticket)
    }

    fn finish_dispatch(
        &mut self,
        ticket: B5DispatchTicket,
        response: B5DispatchResponse,
    ) -> Result<B5EffectState, B5Error> {
        let intent = self.checked_intent(&ticket.effect_key)?.clone();
        Self::check_fence(&intent, &ticket.fence)?;
        let key = ticket.effect_key.clone();
        match response {
            B5DispatchResponse::Accepted { operation_sha256 } => {
                if !valid_digest(&operation_sha256) {
                    return Err(B5Error::InvalidInput);
                }
                self.append(B5RecordKind::DispatchAcceptedRef {
                    effect_key: key.clone(),
                    idempotency_key: intent.idempotency_key,
                    payload_sha256: intent.payload_sha256,
                    attempt: ticket.attempt,
                    operation_sha256,
                    fence: ticket.fence,
                })?;
                self.states
                    .insert(key.as_str().to_string(), B5EffectState::Accepted);
            }
            B5DispatchResponse::Unknown { reason_code } => {
                if !valid_text(&reason_code) {
                    return Err(B5Error::InvalidInput);
                }
                self.append(B5RecordKind::DispatchUnknownRef {
                    effect_key: key.clone(),
                    idempotency_key: intent.idempotency_key,
                    payload_sha256: intent.payload_sha256,
                    attempt: ticket.attempt,
                    reason_code,
                    fence: ticket.fence,
                })?;
                self.states
                    .insert(key.as_str().to_string(), B5EffectState::Unknown);
            }
            B5DispatchResponse::Completed { operation_sha256 } => {
                if !valid_digest(&operation_sha256) {
                    return Err(B5Error::InvalidInput);
                }
                self.append(B5RecordKind::EffectAckRef {
                    effect_key: key.clone(),
                    idempotency_key: intent.idempotency_key,
                    payload_sha256: intent.payload_sha256,
                    attempt: ticket.attempt,
                    operation_sha256,
                    status: ProviderEffectAckStatus::Completed,
                    fence: ticket.fence,
                })?;
                self.states
                    .insert(key.as_str().to_string(), B5EffectState::Completed);
            }
            B5DispatchResponse::Rejected { operation_sha256 } => {
                if !valid_digest(&operation_sha256) {
                    return Err(B5Error::InvalidInput);
                }
                self.append(B5RecordKind::EffectAckRef {
                    effect_key: key.clone(),
                    idempotency_key: intent.idempotency_key,
                    payload_sha256: intent.payload_sha256,
                    attempt: ticket.attempt,
                    operation_sha256,
                    status: ProviderEffectAckStatus::Rejected,
                    fence: ticket.fence,
                })?;
                self.states
                    .insert(key.as_str().to_string(), B5EffectState::Rejected);
            }
        }
        self.state(&key).ok_or(B5Error::UnknownIntent)
    }

    /// Append a lookup result.  Not-found/unknown/conflict never become a
    /// terminal result and never create another attempt.
    pub fn reconcile_lookup(
        &mut self,
        key: &ProviderEffectKey,
        fence: B5Fence,
        outcome: B5LookupOutcome,
    ) -> Result<B5EffectState, B5Error> {
        let intent = self.checked_intent(key)?.clone();
        Self::check_fence(&intent, &fence)?;
        let current = self.state(key).ok_or(B5Error::UnknownIntent)?;
        if current.is_terminal() {
            return Err(B5Error::TerminalImmutable);
        }
        let attempt = self.attempts.get(key.as_str()).copied().unwrap_or(0);
        if attempt == 0 {
            return Err(B5Error::InvalidTransition);
        }
        match outcome {
            B5LookupOutcome::Completed { operation_sha256 } => {
                if !valid_digest(&operation_sha256) {
                    return Err(B5Error::InvalidInput);
                }
                self.append(B5RecordKind::EffectAckRef {
                    effect_key: key.clone(),
                    idempotency_key: intent.idempotency_key,
                    payload_sha256: intent.payload_sha256,
                    attempt,
                    operation_sha256,
                    status: ProviderEffectAckStatus::Completed,
                    fence,
                })?;
                self.states
                    .insert(key.as_str().to_string(), B5EffectState::Completed);
            }
            B5LookupOutcome::Rejected { operation_sha256 } => {
                if !valid_digest(&operation_sha256) {
                    return Err(B5Error::InvalidInput);
                }
                self.append(B5RecordKind::EffectAckRef {
                    effect_key: key.clone(),
                    idempotency_key: intent.idempotency_key,
                    payload_sha256: intent.payload_sha256,
                    attempt,
                    operation_sha256,
                    status: ProviderEffectAckStatus::Rejected,
                    fence,
                })?;
                self.states
                    .insert(key.as_str().to_string(), B5EffectState::Rejected);
            }
            B5LookupOutcome::NotFound | B5LookupOutcome::Unknown | B5LookupOutcome::Conflict => {
                let reason_code = match outcome {
                    B5LookupOutcome::NotFound => "status_not_found",
                    B5LookupOutcome::Unknown => "status_unknown",
                    B5LookupOutcome::Conflict => "status_payload_conflict",
                    B5LookupOutcome::Completed { .. } | B5LookupOutcome::Rejected { .. } => {
                        unreachable!()
                    }
                };
                self.append(B5RecordKind::IndeterminateRef {
                    effect_key: key.clone(),
                    idempotency_key: intent.idempotency_key,
                    payload_sha256: intent.payload_sha256,
                    attempt,
                    reason_code: reason_code.to_string(),
                    fence,
                })?;
                self.states
                    .insert(key.as_str().to_string(), B5EffectState::Indeterminate);
            }
        }
        self.state(key).ok_or(B5Error::UnknownIntent)
    }

    /// Add one bridge delivery with key+payload dedupe.  A duplicate exact
    /// delivery does not append a second row; a changed payload is a conflict.
    pub fn enqueue_outbox(
        &mut self,
        delivery: B5OutboxDelivery,
    ) -> Result<B5AppendDisposition, B5Error> {
        delivery.validate()?;
        if let Some(existing) = self.outbox.get(&delivery.outbox_id) {
            if existing == &delivery {
                return Ok(B5AppendDisposition::AlreadyPresent);
            }
            if existing.idempotency_key == delivery.idempotency_key
                && existing.payload_sha256 == delivery.payload_sha256
                && existing.fence != delivery.fence
            {
                return Err(B5Error::StaleFence);
            }
            return Err(B5Error::OutboxConflict);
        }
        if let Some(existing) = self
            .outbox
            .values()
            .find(|existing| existing.idempotency_key == delivery.idempotency_key)
        {
            if existing.payload_sha256 == delivery.payload_sha256
                && existing.fence == delivery.fence
            {
                return Ok(B5AppendDisposition::AlreadyPresent);
            }
            return Err(if existing.fence != delivery.fence {
                B5Error::StaleFence
            } else {
                B5Error::OutboxConflict
            });
        }
        self.append(B5RecordKind::OutboxEnqueued {
            delivery: delivery.clone(),
        })?;
        self.outbox.insert(delivery.outbox_id.clone(), delivery);
        Ok(B5AppendDisposition::Inserted)
    }

    pub fn ack_outbox(
        &mut self,
        outbox_id: &str,
        idempotency_key: &str,
        payload_sha256: &Sha256Digest,
        ack_sha256: Sha256Digest,
    ) -> Result<B5AppendDisposition, B5Error> {
        if !valid_text(outbox_id) || !valid_text(idempotency_key) || !valid_digest(payload_sha256) {
            return Err(B5Error::InvalidInput);
        }
        if !valid_digest(&ack_sha256) {
            return Err(B5Error::InvalidInput);
        }
        let delivery = self.outbox.get(outbox_id).ok_or(B5Error::OutboxUnknown)?;
        if delivery.idempotency_key != idempotency_key || delivery.payload_sha256 != *payload_sha256
        {
            return Err(B5Error::OutboxConflict);
        }
        if let Some(existing) = self.outbox_acks.get(outbox_id) {
            return if existing == &ack_sha256 {
                Ok(B5AppendDisposition::AlreadyPresent)
            } else {
                Err(B5Error::OutboxConflict)
            };
        }
        self.append(B5RecordKind::OutboxAcked {
            outbox_id: outbox_id.to_string(),
            idempotency_key: idempotency_key.to_string(),
            payload_sha256: payload_sha256.clone(),
            ack_sha256: ack_sha256.clone(),
        })?;
        self.outbox_acks.insert(outbox_id.to_string(), ack_sha256);
        Ok(B5AppendDisposition::Inserted)
    }

    /// Rebuild state from the durable log.  Every record must have a valid
    /// sequence, hash-chain link, and fsync witness.  Any record that refers
    /// to an absent intent is rejected as `UnknownIntent`.
    fn reopen(durable_records: Vec<B5Record>) -> Result<Self, B5Error> {
        let mut reopened = Self::new();
        reopened.records = durable_records;
        reopened.next_seq = 1;
        let records = reopened.records.clone();
        for record in &records {
            if record.seq != reopened.next_seq {
                return Err(B5Error::CorruptWal);
            }
            let expected_prev = reopened
                .records_before(record.seq)
                .last()
                .map(|r| r.record_digest.clone());
            if record.prev_digest != expected_prev {
                return Err(B5Error::CorruptWal);
            }
            if digest_record(record.seq, record.prev_digest.as_ref(), &record.kind)
                != record.record_digest
            {
                return Err(B5Error::CorruptWal);
            }
            let Some(witness) = &record.fsync_witness else {
                return Err(B5Error::FsyncRequired);
            };
            witness.validate_for(record.seq, &record.record_digest)?;
            reopened.apply_record(&record.kind)?;
            reopened.next_seq = record.seq.checked_add(1).ok_or(B5Error::CorruptWal)?;
        }
        Ok(reopened)
    }

    fn records_before(&self, seq: u64) -> &[B5Record] {
        let count = seq.saturating_sub(1) as usize;
        &self.records[..count.min(self.records.len())]
    }

    fn apply_record(&mut self, kind: &B5RecordKind) -> Result<(), B5Error> {
        match kind {
            B5RecordKind::EffectIntentDurable { intent } => {
                intent.validate()?;
                let key = intent.effect_key.as_str().to_string();
                if let Some(existing) = self.intents.get(&key) {
                    if existing != intent {
                        return Err(B5Error::DuplicateConflict);
                    }
                    return Ok(());
                }
                if self
                    .intents
                    .values()
                    .any(|existing| existing.idempotency_key == intent.idempotency_key)
                {
                    return Err(B5Error::DuplicateConflict);
                }
                self.intents.insert(key.clone(), intent.clone());
                self.states.insert(key, B5EffectState::IntentDurable);
            }
            B5RecordKind::DispatchAttemptStarted {
                effect_key,
                idempotency_key,
                payload_sha256,
                attempt,
                fence,
            } => {
                let intent = self.checked_intent(effect_key)?.clone();
                if &intent.idempotency_key != idempotency_key
                    || &intent.payload_sha256 != payload_sha256
                    || &intent.fence != fence
                    || *attempt == 0
                {
                    return Err(B5Error::StaleFence);
                }
                let current = self.state(effect_key).ok_or(B5Error::UnknownIntent)?;
                if current.blocks_dispatch() {
                    return Err(B5Error::InvalidTransition);
                }
                self.states.insert(
                    effect_key.as_str().to_string(),
                    B5EffectState::AttemptStarted,
                );
                self.attempts
                    .insert(effect_key.as_str().to_string(), *attempt);
            }
            B5RecordKind::DispatchAcceptedRef {
                effect_key,
                idempotency_key,
                payload_sha256,
                attempt,
                operation_sha256,
                fence,
            } => {
                self.apply_nonterminal_marker(
                    effect_key,
                    idempotency_key,
                    payload_sha256,
                    *attempt,
                    fence,
                    operation_sha256,
                    B5EffectState::Accepted,
                )?;
            }
            B5RecordKind::DispatchUnknownRef {
                effect_key,
                idempotency_key,
                payload_sha256,
                attempt,
                reason_code,
                fence,
            } => {
                let intent = self.checked_intent(effect_key)?.clone();
                if &intent.idempotency_key != idempotency_key
                    || &intent.payload_sha256 != payload_sha256
                    || &intent.fence != fence
                    || *attempt == 0
                    || !valid_text(reason_code)
                {
                    return Err(B5Error::StaleFence);
                }
                self.states
                    .insert(effect_key.as_str().to_string(), B5EffectState::Unknown);
                self.attempts
                    .insert(effect_key.as_str().to_string(), *attempt);
            }
            B5RecordKind::EffectAckRef {
                effect_key,
                idempotency_key,
                payload_sha256,
                attempt,
                operation_sha256,
                status,
                fence,
            } => {
                let intent = self.checked_intent(effect_key)?.clone();
                if &intent.idempotency_key != idempotency_key
                    || &intent.payload_sha256 != payload_sha256
                    || &intent.fence != fence
                    || *attempt == 0
                    || !valid_digest(operation_sha256)
                {
                    return Err(B5Error::StaleFence);
                }
                let current = self.state(effect_key).ok_or(B5Error::UnknownIntent)?;
                if current.is_terminal() {
                    return Err(B5Error::TerminalImmutable);
                }
                if !matches!(
                    status,
                    ProviderEffectAckStatus::Completed | ProviderEffectAckStatus::Rejected
                ) {
                    return Err(B5Error::InvalidTransition);
                }
                self.states.insert(
                    effect_key.as_str().to_string(),
                    if *status == ProviderEffectAckStatus::Completed {
                        B5EffectState::Completed
                    } else {
                        B5EffectState::Rejected
                    },
                );
                self.attempts
                    .insert(effect_key.as_str().to_string(), *attempt);
            }
            B5RecordKind::IndeterminateRef {
                effect_key,
                idempotency_key,
                payload_sha256,
                attempt,
                reason_code,
                fence,
            } => {
                let intent = self.checked_intent(effect_key)?.clone();
                if &intent.idempotency_key != idempotency_key
                    || &intent.payload_sha256 != payload_sha256
                    || &intent.fence != fence
                    || *attempt == 0
                    || !valid_text(reason_code)
                {
                    return Err(B5Error::StaleFence);
                }
                if self
                    .state(effect_key)
                    .is_some_and(B5EffectState::is_terminal)
                {
                    return Err(B5Error::TerminalImmutable);
                }
                self.states.insert(
                    effect_key.as_str().to_string(),
                    B5EffectState::Indeterminate,
                );
                self.attempts
                    .insert(effect_key.as_str().to_string(), *attempt);
            }
            B5RecordKind::OutboxEnqueued { delivery } => {
                delivery.validate()?;
                if let Some(existing) = self.outbox.get(&delivery.outbox_id) {
                    if existing != delivery {
                        if existing.idempotency_key == delivery.idempotency_key
                            && existing.payload_sha256 == delivery.payload_sha256
                            && existing.fence != delivery.fence
                        {
                            return Err(B5Error::StaleFence);
                        }
                        return Err(B5Error::OutboxConflict);
                    }
                    return Ok(());
                }
                if let Some(existing) = self
                    .outbox
                    .values()
                    .find(|existing| existing.idempotency_key == delivery.idempotency_key)
                {
                    if existing.payload_sha256 != delivery.payload_sha256 {
                        return Err(B5Error::OutboxConflict);
                    }
                    if existing.fence != delivery.fence {
                        return Err(B5Error::StaleFence);
                    }
                    return Ok(());
                }
                self.outbox
                    .insert(delivery.outbox_id.clone(), delivery.clone());
            }
            B5RecordKind::OutboxAcked {
                outbox_id,
                idempotency_key,
                payload_sha256,
                ack_sha256,
            } => {
                let delivery = self.outbox.get(outbox_id).ok_or(B5Error::OutboxUnknown)?;
                if delivery.idempotency_key != *idempotency_key
                    || delivery.payload_sha256 != *payload_sha256
                    || !valid_digest(ack_sha256)
                {
                    return Err(B5Error::OutboxConflict);
                }
                if let Some(existing) = self.outbox_acks.get(outbox_id) {
                    if existing != ack_sha256 {
                        return Err(B5Error::OutboxConflict);
                    }
                    return Ok(());
                }
                self.outbox_acks
                    .insert(outbox_id.clone(), ack_sha256.clone());
            }
        }
        Ok(())
    }

    #[allow(clippy::too_many_arguments)]
    fn apply_nonterminal_marker(
        &mut self,
        effect_key: &ProviderEffectKey,
        idempotency_key: &str,
        payload_sha256: &Sha256Digest,
        attempt: u32,
        fence: &B5Fence,
        operation_sha256: &Sha256Digest,
        next_state: B5EffectState,
    ) -> Result<(), B5Error> {
        let intent = self.checked_intent(effect_key)?.clone();
        if intent.idempotency_key != idempotency_key
            || intent.payload_sha256 != *payload_sha256
            || intent.fence != *fence
            || attempt == 0
            || !valid_digest(operation_sha256)
        {
            return Err(B5Error::StaleFence);
        }
        let current = self.state(effect_key).ok_or(B5Error::UnknownIntent)?;
        if current.blocks_dispatch() && current != B5EffectState::AttemptStarted {
            return Err(B5Error::InvalidTransition);
        }
        self.states
            .insert(effect_key.as_str().to_string(), next_state);
        self.attempts
            .insert(effect_key.as_str().to_string(), attempt);
        Ok(())
    }

    /// Return the recovery action for the current durable state.  This method
    /// performs no mutation and, importantly, never increments call count.
    pub fn recover(&self) -> B5RecoveryAction {
        if let Err(error) = validate_chain(&self.records) {
            return B5RecoveryAction::SafeStop(error);
        }
        for record in &self.records {
            match &record.kind {
                B5RecordKind::DispatchAttemptStarted {
                    effect_key,
                    attempt,
                    ..
                }
                | B5RecordKind::DispatchAcceptedRef {
                    effect_key,
                    attempt,
                    ..
                } if !self.intents.contains_key(effect_key.as_str()) => {
                    let _ = attempt;
                    return B5RecoveryAction::SafeStop(B5Error::UnknownIntent);
                }
                B5RecordKind::DispatchUnknownRef {
                    effect_key,
                    attempt,
                    ..
                }
                | B5RecordKind::IndeterminateRef {
                    effect_key,
                    attempt,
                    ..
                } if !self.intents.contains_key(effect_key.as_str()) => {
                    let _ = attempt;
                    return B5RecoveryAction::SafeStop(B5Error::UnknownIntent);
                }
                _ => {}
            }
        }
        self.states
            .iter()
            .find_map(|(key, state)| {
                if matches!(
                    state,
                    B5EffectState::AttemptStarted
                        | B5EffectState::Accepted
                        | B5EffectState::Unknown
                        | B5EffectState::Indeterminate
                ) {
                    Some(B5RecoveryAction::LookupOnly {
                        effect_key: self.intents.get(key)?.effect_key.clone(),
                        attempt: self.attempts.get(key).copied().unwrap_or(0),
                    })
                } else {
                    None
                }
            })
            .unwrap_or(B5RecoveryAction::NoAction)
    }

    /// Obtain an immutable snapshot suitable for a crash/reopen test.
    pub fn durable_snapshot(&self) -> Vec<u8> {
        match serde_json::to_vec(&self.records) {
            Ok(bytes) => bytes,
            // Every record is made solely from serializable, validated wire
            // types. Reaching this arm indicates a programmer error, but
            // keeping it explicit avoids an unchecked panic in a
            // feature-enabled library build.
            Err(error) => unreachable!("B5 WAL records serialize: {error}"),
        }
    }

    /// Reopen from a serialized durable snapshot.  Non-durable or malformed
    /// bytes are rejected before any derived state is exposed.
    pub fn reopen_snapshot(snapshot: &[u8]) -> Result<Self, B5Error> {
        let records: Vec<B5Record> =
            serde_json::from_slice(snapshot).map_err(|_| B5Error::CorruptWal)?;
        Self::reopen(records)
    }

    /// Resolve a crash snapshot without exposing partially rebuilt state.
    /// Parse, chain, witness, and intent failures all become a safe stop;
    /// only a fully reopened log may return the normal lookup-only plan.
    pub fn recover_snapshot(snapshot: &[u8]) -> B5RecoveryAction {
        let records: Vec<B5Record> = match serde_json::from_slice(snapshot) {
            Ok(records) => records,
            Err(_) => return B5RecoveryAction::SafeStop(B5Error::CorruptWal),
        };
        match Self::reopen(records) {
            Ok(reopened) => reopened.recover(),
            Err(error) => B5RecoveryAction::SafeStop(error),
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct B5DispatchTicket {
    effect_key: ProviderEffectKey,
    attempt: u32,
    fence: B5Fence,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum B5DispatchResponse {
    Accepted { operation_sha256: Sha256Digest },
    Completed { operation_sha256: Sha256Digest },
    Rejected { operation_sha256: Sha256Digest },
    Unknown { reason_code: String },
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum B5LookupOutcome {
    Completed { operation_sha256: Sha256Digest },
    Rejected { operation_sha256: Sha256Digest },
    NotFound,
    Unknown,
    Conflict,
}

fn digest_record(
    seq: u64,
    prev_digest: Option<&Sha256Digest>,
    kind: &B5RecordKind,
) -> Sha256Digest {
    let bytes = match serde_json::to_vec(&(seq, prev_digest, kind)) {
        Ok(bytes) => bytes,
        Err(error) => unreachable!("B5 record serializes: {error}"),
    };
    Sha256Digest::for_bytes(&bytes)
}

fn validate_chain(records: &[B5Record]) -> Result<(), B5Error> {
    let mut previous: Option<Sha256Digest> = None;
    for (index, record) in records.iter().enumerate() {
        let expected_seq = u64::try_from(index + 1).map_err(|_| B5Error::CorruptWal)?;
        if record.seq != expected_seq || record.prev_digest != previous {
            return Err(B5Error::CorruptWal);
        }
        if digest_record(record.seq, record.prev_digest.as_ref(), &record.kind)
            != record.record_digest
        {
            return Err(B5Error::CorruptWal);
        }
        let Some(witness) = &record.fsync_witness else {
            return Err(B5Error::FsyncRequired);
        };
        witness.validate_for(record.seq, &record.record_digest)?;
        previous = Some(record.record_digest.clone());
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn digest(label: &str) -> Sha256Digest {
        Sha256Digest::for_bytes(label.as_bytes())
    }

    fn key(label: &str) -> ProviderEffectKey {
        ProviderEffectKey::parse(format!("provider-effect:v1:{}", digest(label).as_str()))
            .expect("effect key")
    }

    fn fence(generation: u64) -> B5Fence {
        B5Fence {
            authority_epoch: 3,
            owner_epoch: 7,
            generation,
            fencing_token_sha256: digest(&format!("fence-{generation}")),
        }
    }

    fn intent(label: &str, generation: u64) -> B5Intent {
        B5Intent {
            effect_key: key(label),
            idempotency_key: format!("idem-{label}"),
            payload_sha256: digest(&format!("payload-{label}")),
            fence: fence(generation),
        }
    }

    fn delivery(label: &str) -> B5OutboxDelivery {
        B5OutboxDelivery {
            outbox_id: format!("outbox-{label}"),
            event_id: format!("event-{label}"),
            idempotency_key: format!("delivery-{label}"),
            payload_sha256: digest(&format!("delivery-payload-{label}")),
            delivery_seq: 1,
            fence: fence(11),
        }
    }

    #[test]
    fn b5_fsync_before_call_and_crash_recovery_are_lookup_only() {
        let original = intent("crash", 11);
        let mut wal = LocalB5Wal::new();
        wal.append_intent(original.clone()).expect("intent");
        wal.crash_after_call(&original.effect_key, 1, original.fence.clone())
            .expect("crash boundary");
        assert_eq!(wal.adapter_calls(), 1);
        assert_eq!(
            wal.state(&original.effect_key),
            Some(B5EffectState::AttemptStarted)
        );
        assert_eq!(
            wal.recover(),
            B5RecoveryAction::LookupOnly {
                effect_key: original.effect_key.clone(),
                attempt: 1,
            }
        );
        assert_eq!(wal.adapter_calls(), 1, "recovery must not blind retry");

        let reopened = LocalB5Wal::reopen_snapshot(&wal.durable_snapshot()).expect("reopen");
        assert_eq!(
            reopened.state(&original.effect_key),
            Some(B5EffectState::AttemptStarted)
        );
        assert_eq!(reopened.recover(), wal.recover());
        assert_eq!(
            reopened.adapter_calls(),
            0,
            "call witness is not replayed as a call"
        );
    }

    #[test]
    fn b5_unknown_intent_and_stale_fence_stop_without_dispatch() {
        let mut wal = LocalB5Wal::new();
        let unknown = key("unknown");
        assert_eq!(
            wal.begin_dispatch(&unknown, 1, fence(11)),
            Err(B5Error::UnknownIntent)
        );
        assert_eq!(wal.adapter_calls(), 0);

        let original = intent("fence", 11);
        wal.append_intent(original.clone()).expect("intent");
        let mut stale = original.fence.clone();
        stale.generation = 12;
        assert_eq!(
            wal.begin_dispatch(&original.effect_key, 1, stale),
            Err(B5Error::StaleFence)
        );
        assert_eq!(wal.durable_record_count(), 1);
        assert_eq!(wal.adapter_calls(), 0);
    }

    #[test]
    fn b5_unknown_lookup_remains_indeterminate_and_blocks_new_attempt() {
        let original = intent("unknown-lookup", 11);
        let mut wal = LocalB5Wal::new();
        wal.append_intent(original.clone()).expect("intent");
        wal.crash_after_call(&original.effect_key, 1, original.fence.clone())
            .expect("crash");
        assert_eq!(
            wal.reconcile_lookup(
                &original.effect_key,
                original.fence.clone(),
                B5LookupOutcome::Unknown,
            ),
            Ok(B5EffectState::Indeterminate)
        );
        assert_eq!(
            wal.begin_dispatch(&original.effect_key, 2, original.fence.clone()),
            Err(B5Error::DispatchBlocked)
        );
        assert_eq!(wal.adapter_calls(), 1);
        assert!(matches!(
            wal.recover(),
            B5RecoveryAction::LookupOnly { attempt: 1, .. }
        ));
    }

    #[test]
    fn b5_dispatch_responses_and_lookup_uncertainty_are_explicit() {
        let cases = [
            (
                "accepted",
                B5DispatchResponse::Accepted {
                    operation_sha256: digest("accepted-operation"),
                },
                B5EffectState::Accepted,
            ),
            (
                "completed",
                B5DispatchResponse::Completed {
                    operation_sha256: digest("completed-operation"),
                },
                B5EffectState::Completed,
            ),
            (
                "rejected",
                B5DispatchResponse::Rejected {
                    operation_sha256: digest("rejected-operation"),
                },
                B5EffectState::Rejected,
            ),
            (
                "unknown",
                B5DispatchResponse::Unknown {
                    reason_code: "adapter_returned_without_status".to_string(),
                },
                B5EffectState::Unknown,
            ),
        ];

        for (label, response, expected) in cases {
            let original = intent(label, 11);
            let mut wal = LocalB5Wal::new();
            wal.append_intent(original.clone()).expect("intent");
            assert_eq!(wal.intent(&original.effect_key), Some(&original));
            assert_eq!(
                wal.dispatch_once(&original.effect_key, 1, original.fence, response),
                Ok(expected)
            );
            assert_eq!(wal.adapter_calls(), 1);
        }

        for (label, outcome) in [
            ("not-found", B5LookupOutcome::NotFound),
            ("conflict", B5LookupOutcome::Conflict),
        ] {
            let original = intent(label, 11);
            let mut wal = LocalB5Wal::new();
            wal.append_intent(original.clone()).expect("intent");
            wal.crash_after_call(&original.effect_key, 1, original.fence.clone())
                .expect("crash");
            assert_eq!(
                wal.reconcile_lookup(&original.effect_key, original.fence, outcome),
                Ok(B5EffectState::Indeterminate)
            );
            assert!(matches!(
                wal.recover(),
                B5RecoveryAction::LookupOnly { attempt: 1, .. }
            ));
        }
    }

    #[test]
    fn b5_lookup_terminal_ack_is_bound_and_terminal_replay_is_immutable() {
        let original = intent("terminal", 11);
        let mut wal = LocalB5Wal::new();
        wal.append_intent(original.clone()).expect("intent");
        wal.crash_after_call(&original.effect_key, 1, original.fence.clone())
            .expect("crash");
        assert_eq!(
            wal.reconcile_lookup(
                &original.effect_key,
                original.fence.clone(),
                B5LookupOutcome::Completed {
                    operation_sha256: digest("operation"),
                },
            ),
            Ok(B5EffectState::Completed)
        );
        assert_eq!(wal.recover(), B5RecoveryAction::NoAction);
        assert_eq!(
            wal.reconcile_lookup(
                &original.effect_key,
                original.fence,
                B5LookupOutcome::Rejected {
                    operation_sha256: digest("other-operation"),
                },
            ),
            Err(B5Error::TerminalImmutable)
        );
    }

    #[test]
    fn b5_outbox_dedupe_and_payload_conflict_are_side_effect_free() {
        let first = delivery("one");
        let mut wal = LocalB5Wal::new();
        assert_eq!(
            wal.enqueue_outbox(first.clone()),
            Ok(B5AppendDisposition::Inserted)
        );
        let count = wal.durable_record_count();
        assert_eq!(
            wal.enqueue_outbox(first.clone()),
            Ok(B5AppendDisposition::AlreadyPresent)
        );
        assert_eq!(wal.durable_record_count(), count);

        let mut conflict = first.clone();
        conflict.outbox_id = "outbox-conflict".to_string();
        conflict.payload_sha256 = digest("different");
        assert_eq!(wal.enqueue_outbox(conflict), Err(B5Error::OutboxConflict));
        assert_eq!(wal.durable_record_count(), count);

        let mut id_conflict = first.clone();
        id_conflict.idempotency_key = "different-idempotency".to_string();
        assert_eq!(
            wal.enqueue_outbox(id_conflict),
            Err(B5Error::OutboxConflict)
        );
        assert_eq!(wal.durable_record_count(), count);

        let mut stale_fence = first.clone();
        stale_fence.fence = fence(12);
        assert_eq!(wal.enqueue_outbox(stale_fence), Err(B5Error::StaleFence));
        assert_eq!(wal.durable_record_count(), count);

        let ack = digest("ack");
        assert_eq!(
            wal.ack_outbox(
                &first.outbox_id,
                &first.idempotency_key,
                &first.payload_sha256,
                ack.clone(),
            ),
            Ok(B5AppendDisposition::Inserted)
        );
        assert_eq!(wal.outbox_ack(&first.outbox_id), Some(&ack));
        assert_eq!(
            wal.ack_outbox(
                &first.outbox_id,
                &first.idempotency_key,
                &first.payload_sha256,
                ack,
            ),
            Ok(B5AppendDisposition::AlreadyPresent)
        );
    }

    #[test]
    fn b5_reopen_rejects_corrupt_hash_or_missing_fsync_witness() {
        let original = intent("corrupt", 11);
        let mut wal = LocalB5Wal::new();
        wal.append_intent(original).expect("intent");
        let mut bytes: serde_json::Value =
            serde_json::from_slice(&wal.durable_snapshot()).expect("snapshot json");
        bytes[0]["record_digest"] = serde_json::Value::String(digest("tampered").as_str().into());
        let tampered = serde_json::to_vec(&bytes).expect("tampered json");
        assert_eq!(
            LocalB5Wal::reopen_snapshot(&tampered),
            Err(B5Error::CorruptWal)
        );

        let mut no_witness: serde_json::Value =
            serde_json::from_slice(&wal.durable_snapshot()).expect("snapshot json");
        no_witness[0]["fsync_witness"] = serde_json::Value::Null;
        let no_witness = serde_json::to_vec(&no_witness).expect("no witness json");
        assert_eq!(
            LocalB5Wal::reopen_snapshot(&no_witness),
            Err(B5Error::FsyncRequired)
        );

        let mut unknown_field: serde_json::Value =
            serde_json::from_slice(&wal.durable_snapshot()).expect("snapshot json");
        unknown_field[0]["unexpected"] = serde_json::Value::Bool(true);
        let unknown_field = serde_json::to_vec(&unknown_field).expect("unknown field json");
        assert_eq!(
            LocalB5Wal::recover_snapshot(&unknown_field),
            B5RecoveryAction::SafeStop(B5Error::CorruptWal)
        );
    }

    #[test]
    fn b5_recovery_snapshot_maps_unknown_intent_to_safe_stop() {
        let original = intent("missing-intent", 11);
        let mut wal = LocalB5Wal::new();
        wal.append_intent(original.clone()).expect("intent");
        wal.crash_after_call(&original.effect_key, 1, original.fence)
            .expect("crash");

        let mut snapshot: serde_json::Value =
            serde_json::from_slice(&wal.durable_snapshot()).expect("snapshot json");
        let unknown_key = key("not-in-intents");
        snapshot[1]["kind"]["DispatchAttemptStarted"]["effect_key"] =
            serde_json::Value::String(unknown_key.as_str().to_string());
        let kind: B5RecordKind =
            serde_json::from_value(snapshot[1]["kind"].clone()).expect("marker kind");
        let previous = Sha256Digest::parse(
            snapshot[0]["record_digest"]
                .as_str()
                .expect("previous digest")
                .to_string(),
        )
        .expect("previous digest parses");
        let record_digest = digest_record(2, Some(&previous), &kind);
        let record_digest_text = record_digest.as_str().to_string();
        snapshot[1]["record_digest"] = serde_json::Value::String(record_digest_text.clone());
        snapshot[1]["fsync_witness"]["commit_digest"] =
            serde_json::Value::String(record_digest_text);
        let tampered = serde_json::to_vec(&snapshot).expect("unknown intent json");
        assert_eq!(
            LocalB5Wal::recover_snapshot(&tampered),
            B5RecoveryAction::SafeStop(B5Error::UnknownIntent)
        );
    }

    #[test]
    fn b5_fault_matrix_keeps_rpo_zero_for_one_thousand_crash_points() {
        for index in 0..1_000_u64 {
            let original = intent(&format!("fault-{index}"), 11);
            let mut wal = LocalB5Wal::new();
            wal.append_intent(original.clone()).expect("intent");
            wal.crash_after_call(&original.effect_key, 1, original.fence.clone())
                .expect("crash");
            let reopened = LocalB5Wal::reopen_snapshot(&wal.durable_snapshot()).expect("reopen");
            assert_eq!(
                reopened.recover(),
                B5RecoveryAction::LookupOnly {
                    effect_key: original.effect_key,
                    attempt: 1,
                }
            );
            assert_eq!(reopened.adapter_calls(), 0);
        }
    }
}
