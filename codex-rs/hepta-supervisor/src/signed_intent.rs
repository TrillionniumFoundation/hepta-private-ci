//! Durable supervisor-side journal for externally signed release mutations.
//!
//! The journal is intentionally tiny and one-file-per-agent.  It is written
//! before a process transition is queued and updated only after the existing
//! release-state CAS commits.  A restart therefore has a durable witness for
//! an in-flight operation and can fail closed instead of guessing.

use std::fs::OpenOptions;
use std::io::ErrorKind;
use std::io::Write;
use std::path::Path;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;
use std::time::SystemTime;

use codex_hepta_contracts::Sha256Digest;
use serde::Deserialize;
use serde::Serialize;
use sha2::Digest;
use sha2::Sha256;
use thiserror::Error;

use crate::H7H89ProductionTransition;

pub const SIGNED_INTENT_SCHEMA_VERSION: u32 = 1;
pub const SIGNED_INTENT_FILE: &str = "supervisor-signed-intent.json";
const INTENT_DOMAIN: &[u8] = b"hepta-supervisor:signed-intent:v1";
static TEMP_SEQUENCE: AtomicU64 = AtomicU64::new(1);

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum SignedIntentStatus {
    Prepared,
    Queued,
    Committed,
    RecoveryRequired,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct SignedSupervisorIntent {
    pub schema_version: u32,
    pub grant_sha256: Sha256Digest,
    pub agent_id: String,
    pub transition: H7H89ProductionTransition,
    pub source_release: String,
    pub target_release: String,
    pub expected_control_revision: u64,
    pub expected_lifecycle_generation: u64,
    pub authority_epoch: u64,
    pub status: SignedIntentStatus,
    pub intent_sha256: Sha256Digest,
}

#[derive(Debug, Error)]
pub enum SignedIntentError {
    #[error("signed supervisor intent is malformed: {0}")]
    Invalid(String),
    #[error("signed supervisor intent digest mismatch")]
    DigestMismatch,
    #[error(transparent)]
    Io(#[from] std::io::Error),
    #[error(transparent)]
    Serialization(#[from] serde_json::Error),
}

impl SignedSupervisorIntent {
    #[expect(
        clippy::too_many_arguments,
        reason = "signed intent constructor keeps every digest-bound field explicit"
    )]
    pub fn new(
        grant_sha256: Sha256Digest,
        agent_id: impl Into<String>,
        transition: H7H89ProductionTransition,
        source_release: impl Into<String>,
        target_release: impl Into<String>,
        expected_control_revision: u64,
        expected_lifecycle_generation: u64,
        authority_epoch: u64,
        status: SignedIntentStatus,
    ) -> Result<Self, SignedIntentError> {
        let mut intent = Self {
            schema_version: SIGNED_INTENT_SCHEMA_VERSION,
            grant_sha256,
            agent_id: agent_id.into(),
            transition,
            source_release: source_release.into(),
            target_release: target_release.into(),
            expected_control_revision,
            expected_lifecycle_generation,
            authority_epoch,
            status,
            intent_sha256: Sha256Digest::for_bytes(b"pending"),
        };
        intent.intent_sha256 = intent.compute_digest()?;
        intent.validate()?;
        Ok(intent)
    }

    pub fn validate(&self) -> Result<(), SignedIntentError> {
        if self.schema_version != SIGNED_INTENT_SCHEMA_VERSION
            || self.agent_id.trim().is_empty()
            || self.agent_id.len() > 256
            || self.source_release.trim().is_empty()
            || self.target_release.trim().is_empty()
            || self.source_release == self.target_release
            || self.expected_lifecycle_generation == 0
            || self.authority_epoch == 0
        {
            return Err(SignedIntentError::Invalid(
                "signed intent fields are outside their bounds".to_string(),
            ));
        }
        if Sha256Digest::parse(self.grant_sha256.as_str().to_string()).is_err()
            || Sha256Digest::parse(self.intent_sha256.as_str().to_string()).is_err()
        {
            return Err(SignedIntentError::Invalid(
                "signed intent digest is malformed".to_string(),
            ));
        }
        if self.intent_sha256 != self.compute_digest()? {
            return Err(SignedIntentError::DigestMismatch);
        }
        Ok(())
    }

    pub(crate) fn with_status(
        &self,
        status: SignedIntentStatus,
    ) -> Result<Self, SignedIntentError> {
        let mut next = Self {
            status,
            ..self.clone()
        };
        next.intent_sha256 = next.compute_digest()?;
        Ok(next)
    }

    fn compute_digest(&self) -> Result<Sha256Digest, SignedIntentError> {
        let payload = serde_json::to_vec(&(
            self.schema_version,
            &self.grant_sha256,
            &self.agent_id,
            self.transition,
            &self.source_release,
            &self.target_release,
            self.expected_control_revision,
            self.expected_lifecycle_generation,
            self.authority_epoch,
            self.status,
        ))?;
        Ok(Sha256Digest::from_sha256_output(Sha256::digest(
            [INTENT_DOMAIN, payload.as_slice()].concat(),
        )))
    }
}

pub fn read_intent(run_root: &Path) -> Result<Option<SignedSupervisorIntent>, SignedIntentError> {
    let path = run_root.join(SIGNED_INTENT_FILE);
    let bytes = match std::fs::read(path) {
        Ok(bytes) => bytes,
        Err(error) if error.kind() == ErrorKind::NotFound => return Ok(None),
        Err(error) => return Err(error.into()),
    };
    let intent: SignedSupervisorIntent = serde_json::from_slice(&bytes)?;
    intent.validate()?;
    Ok(Some(intent))
}

/// Atomically publishes one intent after synchronizing its file. Unix fsyncs
/// the containing directory; Windows uses a same-directory write-through
/// replacement. An unresolved non-terminal intent cannot be overwritten.
pub fn write_intent(
    run_root: &Path,
    intent: &SignedSupervisorIntent,
) -> Result<(), SignedIntentError> {
    intent.validate()?;
    if let Some(existing) = read_intent(run_root)?
        && matches!(
            existing.status,
            SignedIntentStatus::Prepared
                | SignedIntentStatus::Queued
                | SignedIntentStatus::RecoveryRequired
        )
        && existing.grant_sha256 != intent.grant_sha256
    {
        return Err(SignedIntentError::Invalid(
            "another signed supervisor intent is unresolved".to_string(),
        ));
    }
    std::fs::create_dir_all(run_root)?;
    let sequence = TEMP_SEQUENCE.fetch_add(1, Ordering::Relaxed);
    let nanos = SystemTime::now()
        .duration_since(SystemTime::UNIX_EPOCH)
        .map_err(|_| SignedIntentError::Invalid("system clock before epoch".to_string()))?
        .as_nanos();
    let temp = run_root.join(format!(".{SIGNED_INTENT_FILE}.{nanos}.{sequence}.tmp"));
    let final_path = run_root.join(SIGNED_INTENT_FILE);
    let bytes = serde_json::to_vec(intent)?;
    let mut file = OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(&temp)?;
    file.write_all(&bytes)?;
    file.sync_all()?;
    drop(file);
    publish::publish(&temp, &final_path)?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn intent_round_trips_and_rejects_unresolved_overwrite() -> Result<(), SignedIntentError> {
        let dir = tempfile::tempdir().expect("temp");
        let grant = Sha256Digest::for_bytes(b"grant");
        let first = SignedSupervisorIntent::new(
            grant,
            "agent",
            H7H89ProductionTransition::Upgrade,
            "v1",
            "v2",
            0,
            1,
            1,
            SignedIntentStatus::Queued,
        )
        .expect("first");
        write_intent(dir.path(), &first).expect("write");
        assert_eq!(read_intent(dir.path()).expect("read"), Some(first.clone()));
        let other = SignedSupervisorIntent::new(
            Sha256Digest::for_bytes(b"other"),
            "agent",
            H7H89ProductionTransition::Upgrade,
            "v2",
            "v3",
            1,
            2,
            1,
            SignedIntentStatus::Prepared,
        )
        .expect("other");
        assert!(matches!(
            write_intent(dir.path(), &other),
            Err(SignedIntentError::Invalid(message)) if message.contains("unresolved")
        ));
        let committed = SignedSupervisorIntent {
            status: SignedIntentStatus::Committed,
            ..first
        };
        let mut committed = committed;
        committed.intent_sha256 = committed.compute_digest()?;
        write_intent(dir.path(), &committed).expect("terminal replacement");
        Ok(())
    }
}

#[path = "signed_intent_publish.rs"]
mod publish;
