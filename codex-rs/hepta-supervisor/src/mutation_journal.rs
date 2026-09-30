//! Durable request identity and outcome journal for ordinary lifecycle mutations.
//!
//! The wire request id is promoted into a deterministic idempotency key bound
//! to daemon epoch, Agent, operation and pre-state digest. A timed-out caller
//! can query this journal; it never needs to replay a side effect to discover
//! whether the first request started.

use std::fs::OpenOptions;
use std::io::ErrorKind;
use std::io::Read;
use std::io::Write;
use std::path::Path;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;
use std::time::SystemTime;

use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::Sha256Digest;
use serde::Deserialize;
use serde::Serialize;
use sha2::Digest;
use sha2::Sha256;
use thiserror::Error;

use crate::SupervisordMutation;

pub const MUTATION_JOURNAL_SCHEMA_VERSION: u32 = 1;
pub const MUTATION_JOURNAL_FILE: &str = "supervisor-mutation-journal.json";
const MUTATION_KEY_DOMAIN: &[u8] = b"hepta-supervisor:ordinary-mutation-key:v1";
const MUTATION_RECORD_DOMAIN: &[u8] = b"hepta-supervisor:ordinary-mutation-record:v1";
const MAX_MUTATION_JOURNAL_BYTES: usize = 32_768;
static TEMP_SEQUENCE: AtomicU64 = AtomicU64::new(1);

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum DurableMutationPhaseV1 {
    Prepared,
    EffectStarted,
    Committed,
    Ambiguous,
    RequiresOperator,
}

impl DurableMutationPhaseV1 {
    fn unresolved(self) -> bool {
        matches!(
            self,
            Self::Prepared | Self::EffectStarted | Self::Ambiguous | Self::RequiresOperator
        )
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct DurableMutationStatusV1 {
    pub schema_version: u32,
    pub request_id: u64,
    pub idempotency_key: Sha256Digest,
    pub agent_id: AgentId,
    pub supervisor_epoch: String,
    pub operation: SupervisordMutation,
    pub accepted_state_digest: String,
    pub observed_state_digest: Option<String>,
    pub attempt_sequence: u64,
    pub intent_sequence: u64,
    pub applied_state_revision: Option<u64>,
    pub read_snapshot_epoch: Option<u64>,
    pub phase: DurableMutationPhaseV1,
    pub detail: Option<String>,
    pub record_sha256: Sha256Digest,
}

#[derive(Debug, Error)]
pub enum MutationJournalError {
    #[error("mutation journal is invalid: {0}")]
    Invalid(String),
    #[error("mutation journal digest mismatch")]
    DigestMismatch,
    #[error("another durable mutation remains unresolved")]
    Unresolved,
    #[error("request id was reused with different mutation identity")]
    IdentityConflict,
    #[error(transparent)]
    Io(#[from] std::io::Error),
    #[error(transparent)]
    Serialization(#[from] serde_json::Error),
}

impl DurableMutationStatusV1 {
    fn new(
        request_id: u64,
        agent_id: AgentId,
        supervisor_epoch: String,
        operation: SupervisordMutation,
        accepted_state_digest: String,
        intent_sequence: u64,
    ) -> Result<Self, MutationJournalError> {
        let idempotency_key = compute_idempotency_key(
            request_id,
            &agent_id,
            &supervisor_epoch,
            operation,
            &accepted_state_digest,
        )?;
        let mut status = Self {
            schema_version: MUTATION_JOURNAL_SCHEMA_VERSION,
            request_id,
            idempotency_key,
            agent_id,
            supervisor_epoch,
            operation,
            accepted_state_digest,
            observed_state_digest: None,
            attempt_sequence: 1,
            intent_sequence,
            applied_state_revision: None,
            read_snapshot_epoch: None,
            phase: DurableMutationPhaseV1::Prepared,
            detail: None,
            record_sha256: Sha256Digest::for_bytes(b"pending"),
        };
        status.record_sha256 = status.compute_record_digest()?;
        status.validate()?;
        Ok(status)
    }

    fn with_state(
        &self,
        phase: DurableMutationPhaseV1,
        observed_state_digest: Option<String>,
        applied_state_revision: Option<u64>,
        read_snapshot_epoch: Option<u64>,
        detail: Option<String>,
    ) -> Result<Self, MutationJournalError> {
        let mut next = Self {
            phase,
            observed_state_digest,
            applied_state_revision,
            read_snapshot_epoch,
            detail,
            ..self.clone()
        };
        next.record_sha256 = next.compute_record_digest()?;
        next.validate()?;
        Ok(next)
    }

    fn increment_attempt(&self) -> Result<Self, MutationJournalError> {
        let mut next = self.clone();
        next.attempt_sequence = next.attempt_sequence.checked_add(1).ok_or_else(|| {
            MutationJournalError::Invalid("mutation attempt sequence overflow".to_string())
        })?;
        next.record_sha256 = next.compute_record_digest()?;
        next.validate()?;
        Ok(next)
    }

    fn validate(&self) -> Result<(), MutationJournalError> {
        let digest = |value: &str| {
            value.len() == 64
                && value
                    .bytes()
                    .all(|byte| matches!(byte, b'0'..=b'9' | b'a'..=b'f'))
        };
        let terminal_fields_valid = match self.phase {
            DurableMutationPhaseV1::Prepared | DurableMutationPhaseV1::EffectStarted => {
                self.applied_state_revision.is_none()
                    && self.read_snapshot_epoch.is_none()
                    && self.detail.is_none()
            }
            DurableMutationPhaseV1::Committed => {
                self.applied_state_revision
                    .zip(self.read_snapshot_epoch)
                    .is_some_and(|(applied, snapshot)| applied > 0 && snapshot >= applied)
                    && self.observed_state_digest.as_deref().is_some_and(digest)
            }
            DurableMutationPhaseV1::Ambiguous | DurableMutationPhaseV1::RequiresOperator => self
                .detail
                .as_ref()
                .is_some_and(|detail| !detail.is_empty() && detail.len() <= 1_024),
        };
        if self.schema_version != MUTATION_JOURNAL_SCHEMA_VERSION
            || self.request_id == 0
            || self.supervisor_epoch.is_empty()
            || self.supervisor_epoch.len() > 128
            || !self.supervisor_epoch.is_ascii()
            || !digest(&self.accepted_state_digest)
            || self
                .observed_state_digest
                .as_deref()
                .is_some_and(|value| !digest(value))
            || self.attempt_sequence == 0
            || self.intent_sequence == 0
            || !terminal_fields_valid
        {
            return Err(MutationJournalError::Invalid(
                "request identity, sequence, digest or phase fields are outside their bounds"
                    .to_string(),
            ));
        }
        if self.idempotency_key
            != compute_idempotency_key(
                self.request_id,
                &self.agent_id,
                &self.supervisor_epoch,
                self.operation,
                &self.accepted_state_digest,
            )?
            || self.record_sha256 != self.compute_record_digest()?
        {
            return Err(MutationJournalError::DigestMismatch);
        }
        Ok(())
    }

    fn compute_record_digest(&self) -> Result<Sha256Digest, MutationJournalError> {
        let payload = serde_json::to_vec(&(
            self.schema_version,
            self.request_id,
            &self.idempotency_key,
            &self.agent_id,
            &self.supervisor_epoch,
            self.operation,
            &self.accepted_state_digest,
            &self.observed_state_digest,
            self.attempt_sequence,
            self.intent_sequence,
            self.applied_state_revision,
            self.read_snapshot_epoch,
            self.phase,
            &self.detail,
        ))?;
        Ok(Sha256Digest::from_sha256_output(Sha256::digest(
            [MUTATION_RECORD_DOMAIN, payload.as_slice()].concat(),
        )))
    }
}

pub fn prepare_mutation(
    run_root: &Path,
    request_id: u64,
    agent_id: &AgentId,
    supervisor_epoch: &str,
    operation: SupervisordMutation,
    accepted_state_digest: &str,
    intent_sequence: u64,
) -> Result<DurableMutationStatusV1, MutationJournalError> {
    let next = DurableMutationStatusV1::new(
        request_id,
        agent_id.clone(),
        supervisor_epoch.to_string(),
        operation,
        accepted_state_digest.to_string(),
        intent_sequence,
    )?;
    if let Some(current) = read_mutation_status(run_root)? {
        if current.request_id == request_id {
            if current.idempotency_key == next.idempotency_key {
                let retried = current.increment_attempt()?;
                write_mutation_status(run_root, &retried)?;
                return Ok(retried);
            }
            return Err(MutationJournalError::IdentityConflict);
        }
        if current.phase.unresolved() {
            return Err(MutationJournalError::Unresolved);
        }
    }
    write_mutation_status(run_root, &next)?;
    Ok(next)
}

pub fn mark_mutation_effect_started(
    run_root: &Path,
    idempotency_key: &Sha256Digest,
) -> Result<DurableMutationStatusV1, MutationJournalError> {
    update(run_root, idempotency_key, |current| {
        if current.phase == DurableMutationPhaseV1::EffectStarted {
            return Ok(current.clone());
        }
        if current.phase != DurableMutationPhaseV1::Prepared {
            return Err(MutationJournalError::Invalid(
                "mutation cannot enter effect_started from its current phase".to_string(),
            ));
        }
        current.with_state(
            DurableMutationPhaseV1::EffectStarted,
            None,
            None,
            None,
            None,
        )
    })
}

pub fn commit_mutation(
    run_root: &Path,
    idempotency_key: &Sha256Digest,
    applied_state_revision: u64,
    read_snapshot_epoch: u64,
    observed_state_digest: &str,
) -> Result<DurableMutationStatusV1, MutationJournalError> {
    update(run_root, idempotency_key, |current| {
        if current.phase == DurableMutationPhaseV1::Committed {
            return Ok(current.clone());
        }
        if current.phase != DurableMutationPhaseV1::EffectStarted {
            return Err(MutationJournalError::Invalid(
                "mutation cannot commit before effect_started".to_string(),
            ));
        }
        current.with_state(
            DurableMutationPhaseV1::Committed,
            Some(observed_state_digest.to_string()),
            Some(applied_state_revision),
            Some(read_snapshot_epoch),
            None,
        )
    })
}

pub fn mark_mutation_ambiguous(
    run_root: &Path,
    idempotency_key: &Sha256Digest,
    observed_state_digest: Option<&str>,
    detail: &str,
) -> Result<DurableMutationStatusV1, MutationJournalError> {
    update(run_root, idempotency_key, |current| {
        if current.phase == DurableMutationPhaseV1::Committed {
            return Ok(current.clone());
        }
        current.with_state(
            DurableMutationPhaseV1::Ambiguous,
            observed_state_digest.map(str::to_string),
            None,
            None,
            Some(detail.to_string()),
        )
    })
}

pub fn require_mutation_operator(
    run_root: &Path,
    idempotency_key: &Sha256Digest,
    detail: &str,
) -> Result<DurableMutationStatusV1, MutationJournalError> {
    update(run_root, idempotency_key, |current| {
        current.with_state(
            DurableMutationPhaseV1::RequiresOperator,
            current.observed_state_digest.clone(),
            current.applied_state_revision,
            current.read_snapshot_epoch,
            Some(detail.to_string()),
        )
    })
}

pub fn read_mutation_status(
    run_root: &Path,
) -> Result<Option<DurableMutationStatusV1>, MutationJournalError> {
    let path = run_root.join(MUTATION_JOURNAL_FILE);
    let mut options = OpenOptions::new();
    options.read(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.custom_flags(libc::O_NOFOLLOW | libc::O_NONBLOCK | libc::O_CLOEXEC);
    }
    let mut file = match options.open(&path) {
        Ok(file) => file,
        Err(error) if error.kind() == ErrorKind::NotFound => return Ok(None),
        Err(error) => return Err(error.into()),
    };
    let metadata = file.metadata()?;
    if !metadata.file_type().is_file()
        || metadata.file_type().is_symlink()
        || metadata.len() > MAX_MUTATION_JOURNAL_BYTES as u64
    {
        return Err(MutationJournalError::Invalid(
            "mutation journal is not a bounded regular file".to_string(),
        ));
    }
    let mut bytes = Vec::new();
    (&mut file)
        .take((MAX_MUTATION_JOURNAL_BYTES + 1) as u64)
        .read_to_end(&mut bytes)?;
    if bytes.len() > MAX_MUTATION_JOURNAL_BYTES || bytes.len() as u64 != metadata.len() {
        return Err(MutationJournalError::Invalid(
            "mutation journal changed while being read or exceeds its bound".to_string(),
        ));
    }
    let status: DurableMutationStatusV1 = serde_json::from_slice(&bytes)?;
    status.validate()?;
    Ok(Some(status))
}

fn update<F>(
    run_root: &Path,
    idempotency_key: &Sha256Digest,
    transition: F,
) -> Result<DurableMutationStatusV1, MutationJournalError>
where
    F: FnOnce(&DurableMutationStatusV1) -> Result<DurableMutationStatusV1, MutationJournalError>,
{
    let current = read_mutation_status(run_root)?
        .ok_or_else(|| MutationJournalError::Invalid("mutation journal is absent".to_string()))?;
    if current.idempotency_key != *idempotency_key {
        return Err(MutationJournalError::IdentityConflict);
    }
    let next = transition(&current)?;
    write_mutation_status(run_root, &next)?;
    Ok(next)
}

fn write_mutation_status(
    run_root: &Path,
    status: &DurableMutationStatusV1,
) -> Result<(), MutationJournalError> {
    status.validate()?;
    std::fs::create_dir_all(run_root)?;
    let bytes = serde_json::to_vec(status)?;
    if bytes.len() > MAX_MUTATION_JOURNAL_BYTES {
        return Err(MutationJournalError::Invalid(
            "mutation journal exceeds its file bound".to_string(),
        ));
    }
    let sequence = TEMP_SEQUENCE.fetch_add(1, Ordering::Relaxed);
    let nanos = SystemTime::now()
        .duration_since(SystemTime::UNIX_EPOCH)
        .map_err(|_| MutationJournalError::Invalid("system clock before epoch".to_string()))?
        .as_nanos();
    let staging = run_root.join(format!(".{MUTATION_JOURNAL_FILE}.{nanos}.{sequence}.tmp"));
    let destination = run_root.join(MUTATION_JOURNAL_FILE);
    let mut options = OpenOptions::new();
    options.write(true).create_new(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options
            .mode(0o600)
            .custom_flags(libc::O_NOFOLLOW | libc::O_CLOEXEC);
    }
    let mut file = options.open(&staging)?;
    if let Err(error) = (|| -> std::io::Result<()> {
        file.write_all(&bytes)?;
        file.sync_all()?;
        crate::durable_publish::publish(&staging, &destination)
    })() {
        let _ = std::fs::remove_file(&staging);
        return Err(error.into());
    }
    Ok(())
}

fn compute_idempotency_key(
    request_id: u64,
    agent_id: &AgentId,
    supervisor_epoch: &str,
    operation: SupervisordMutation,
    accepted_state_digest: &str,
) -> Result<Sha256Digest, MutationJournalError> {
    let payload = serde_json::to_vec(&(
        request_id,
        agent_id,
        supervisor_epoch,
        operation,
        accepted_state_digest,
    ))?;
    Ok(Sha256Digest::from_sha256_output(Sha256::digest(
        [MUTATION_KEY_DOMAIN, payload.as_slice()].concat(),
    )))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn agent() -> AgentId {
        AgentId::parse("00000000-0000-4000-8000-000000000001").expect("agent")
    }

    fn digest(byte: char) -> String {
        std::iter::repeat_n(byte, 64).collect()
    }

    #[test]
    fn retry_with_same_request_identity_is_idempotent() {
        let directory = tempfile::tempdir().expect("tempdir");
        let first = prepare_mutation(
            directory.path(),
            41,
            &agent(),
            "00000000-0000-4000-8000-000000000002",
            SupervisordMutation::Restart,
            &digest('a'),
            8,
        )
        .expect("prepare");
        let replay = prepare_mutation(
            directory.path(),
            41,
            &agent(),
            "00000000-0000-4000-8000-000000000002",
            SupervisordMutation::Restart,
            &digest('a'),
            8,
        )
        .expect("replay");

        assert_eq!(replay.idempotency_key, first.idempotency_key);
        assert_eq!(replay.phase, DurableMutationPhaseV1::Prepared);
        assert_eq!(replay.attempt_sequence, 2);
    }

    #[test]
    fn request_id_collision_is_rejected() {
        let directory = tempfile::tempdir().expect("tempdir");
        prepare_mutation(
            directory.path(),
            41,
            &agent(),
            "00000000-0000-4000-8000-000000000002",
            SupervisordMutation::Restart,
            &digest('a'),
            8,
        )
        .expect("prepare");
        assert!(matches!(
            prepare_mutation(
                directory.path(),
                41,
                &agent(),
                "00000000-0000-4000-8000-000000000002",
                SupervisordMutation::Kill,
                &digest('a'),
                8,
            ),
            Err(MutationJournalError::IdentityConflict)
        ));
    }

    #[test]
    fn ambiguous_result_is_queryable_and_never_becomes_not_started() {
        let directory = tempfile::tempdir().expect("tempdir");
        let prepared = prepare_mutation(
            directory.path(),
            41,
            &agent(),
            "00000000-0000-4000-8000-000000000002",
            SupervisordMutation::Restart,
            &digest('a'),
            8,
        )
        .expect("prepare");
        mark_mutation_effect_started(directory.path(), &prepared.idempotency_key).expect("started");
        let ambiguous = mark_mutation_ambiguous(
            directory.path(),
            &prepared.idempotency_key,
            Some(&digest('b')),
            "driver returned after the effect boundary; inspect exact process evidence",
        )
        .expect("ambiguous");
        assert_eq!(ambiguous.phase, DurableMutationPhaseV1::Ambiguous);
        assert_eq!(
            read_mutation_status(directory.path())
                .expect("read")
                .expect("status")
                .phase,
            DurableMutationPhaseV1::Ambiguous
        );
        assert!(matches!(
            prepare_mutation(
                directory.path(),
                42,
                &agent(),
                "00000000-0000-4000-8000-000000000002",
                SupervisordMutation::Restart,
                &digest('b'),
                9,
            ),
            Err(MutationJournalError::Unresolved)
        ));
    }

    #[test]
    fn attempt_intent_applied_and_snapshot_sequences_are_distinct() {
        let directory = tempfile::tempdir().expect("tempdir");
        let prepared = prepare_mutation(
            directory.path(),
            41,
            &agent(),
            "00000000-0000-4000-8000-000000000002",
            SupervisordMutation::Stop,
            &digest('a'),
            8,
        )
        .expect("prepare");
        mark_mutation_effect_started(directory.path(), &prepared.idempotency_key).expect("started");
        let committed = commit_mutation(
            directory.path(),
            &prepared.idempotency_key,
            9,
            11,
            &digest('b'),
        )
        .expect("commit");
        assert_eq!(committed.attempt_sequence, 1);
        assert_eq!(committed.intent_sequence, 8);
        assert_eq!(committed.applied_state_revision, Some(9));
        assert_eq!(committed.read_snapshot_epoch, Some(11));
    }
}
