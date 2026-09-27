//! Durable owner journal for Stop and Kill operations.
//!
//! The journal is written before restart cancellation, lifecycle CAS or process
//! signaling. It binds the exact owned process identity and preserves the
//! original wall-clock deadline across supervisor restarts. Signal success is
//! represented separately from terminal exit observation.

use std::fs::OpenOptions;
use std::io::ErrorKind;
use std::io::Write;
use std::path::Path;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;
use std::time::Duration;
use std::time::SystemTime;

use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::Sha256Digest;
use serde::Deserialize;
use serde::Serialize;
use sha2::Digest;
use sha2::Sha256;
use thiserror::Error;

use crate::ProcessIdentity;

pub(crate) const CONTROL_INTENT_SCHEMA_VERSION: u32 = 1;
pub(crate) const CONTROL_INTENT_FILE: &str = "supervisor-control-intent.json";
const CONTROL_INTENT_DOMAIN: &[u8] = b"hepta-supervisor:control-intent:v1";
const CONTROL_RECORD_DOMAIN: &[u8] = b"hepta-supervisor:control-record:v1";
const MAX_CONTROL_INTENT_BYTES: usize = 8_192;
static TEMP_SEQUENCE: AtomicU64 = AtomicU64::new(1);

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub(crate) enum DurableControlKind {
    Stop,
    Kill,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub(crate) enum DurableControlPhase {
    Prepared,
    StopRequested,
    KillRequested,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct DurableControlIntent {
    pub schema_version: u32,
    pub agent_id: AgentId,
    pub kind: DurableControlKind,
    pub target_spawn_generation: u64,
    pub target_process_identity: ProcessIdentity,
    pub expected_lifecycle_generation: u64,
    pub requested_unix_ms: u64,
    pub stop_deadline_unix_ms: Option<u64>,
    pub phase: DurableControlPhase,
    pub operation_sha256: Sha256Digest,
    pub record_sha256: Sha256Digest,
}

#[derive(Debug, Error)]
pub(crate) enum DurableControlIntentError {
    #[error("durable supervisor control intent is malformed: {0}")]
    Invalid(String),
    #[error("durable supervisor control intent digest mismatch")]
    DigestMismatch,
    #[error("another durable supervisor control intent is unresolved")]
    Unresolved,
    #[error(transparent)]
    Io(#[from] std::io::Error),
    #[error(transparent)]
    Serialization(#[from] serde_json::Error),
}

impl DurableControlIntent {
    fn new(
        agent_id: AgentId,
        kind: DurableControlKind,
        target_spawn_generation: u64,
        target_process_identity: ProcessIdentity,
        expected_lifecycle_generation: u64,
        requested_unix_ms: u64,
        stop_deadline_unix_ms: Option<u64>,
    ) -> Result<Self, DurableControlIntentError> {
        let mut intent = Self {
            schema_version: CONTROL_INTENT_SCHEMA_VERSION,
            agent_id,
            kind,
            target_spawn_generation,
            target_process_identity,
            expected_lifecycle_generation,
            requested_unix_ms,
            stop_deadline_unix_ms,
            phase: DurableControlPhase::Prepared,
            operation_sha256: Sha256Digest::for_bytes(b"pending"),
            record_sha256: Sha256Digest::for_bytes(b"pending"),
        };
        intent.operation_sha256 = intent.compute_operation_digest()?;
        intent.record_sha256 = intent.compute_record_digest()?;
        intent.validate()?;
        Ok(intent)
    }

    fn with_phase(
        &self,
        phase: DurableControlPhase,
    ) -> Result<Self, DurableControlIntentError> {
        let mut next = Self {
            phase,
            ..self.clone()
        };
        next.record_sha256 = next.compute_record_digest()?;
        next.validate()?;
        Ok(next)
    }

    fn validate(&self) -> Result<(), DurableControlIntentError> {
        let stop_deadline_valid = match self.kind {
            DurableControlKind::Stop => self
                .stop_deadline_unix_ms
                .is_some_and(|deadline| deadline >= self.requested_unix_ms),
            DurableControlKind::Kill => self.stop_deadline_unix_ms.is_none(),
        };
        if self.schema_version != CONTROL_INTENT_SCHEMA_VERSION
            || self.target_spawn_generation == 0
            || self.expected_lifecycle_generation == 0
            || self.requested_unix_ms == 0
            || !stop_deadline_valid
            || (self.kind == DurableControlKind::Stop
                && self.phase == DurableControlPhase::KillRequested)
            || (self.kind == DurableControlKind::Kill
                && self.phase == DurableControlPhase::StopRequested)
        {
            return Err(DurableControlIntentError::Invalid(
                "control identity, deadline or phase is outside its bounds".to_string(),
            ));
        }
        if self.operation_sha256 != self.compute_operation_digest()?
            || self.record_sha256 != self.compute_record_digest()?
        {
            return Err(DurableControlIntentError::DigestMismatch);
        }
        Ok(())
    }

    fn same_target(&self, other: &Self) -> bool {
        self.agent_id == other.agent_id
            && self.target_spawn_generation == other.target_spawn_generation
            && self.target_process_identity == other.target_process_identity
    }

    fn compute_operation_digest(&self) -> Result<Sha256Digest, DurableControlIntentError> {
        let payload = serde_json::to_vec(&(
            self.schema_version,
            &self.agent_id,
            self.kind,
            self.target_spawn_generation,
            &self.target_process_identity,
            self.expected_lifecycle_generation,
            self.requested_unix_ms,
            self.stop_deadline_unix_ms,
        ))?;
        Ok(Sha256Digest::from_sha256_output(Sha256::digest(
            [CONTROL_INTENT_DOMAIN, payload.as_slice()].concat(),
        )))
    }

    fn compute_record_digest(&self) -> Result<Sha256Digest, DurableControlIntentError> {
        let payload = serde_json::to_vec(&(&self.operation_sha256, self.phase))?;
        Ok(Sha256Digest::from_sha256_output(Sha256::digest(
            [CONTROL_RECORD_DOMAIN, payload.as_slice()].concat(),
        )))
    }
}

pub(crate) fn prepare_stop(
    run_root: &Path,
    agent_id: &AgentId,
    target_spawn_generation: u64,
    target_process_identity: &ProcessIdentity,
    expected_lifecycle_generation: u64,
    stop_grace: Duration,
) -> Result<(), DurableControlIntentError> {
    let requested_unix_ms = unix_ms_now()?;
    let stop_deadline_unix_ms = requested_unix_ms
        .checked_add(duration_ms(stop_grace)?)
        .ok_or_else(|| DurableControlIntentError::Invalid("stop deadline overflow".to_string()))?;
    prepare(
        run_root,
        DurableControlIntent::new(
            agent_id.clone(),
            DurableControlKind::Stop,
            target_spawn_generation,
            target_process_identity.clone(),
            expected_lifecycle_generation,
            requested_unix_ms,
            Some(stop_deadline_unix_ms),
        )?,
    )
}

pub(crate) fn prepare_kill(
    run_root: &Path,
    agent_id: &AgentId,
    target_spawn_generation: u64,
    target_process_identity: &ProcessIdentity,
    expected_lifecycle_generation: u64,
) -> Result<(), DurableControlIntentError> {
    prepare(
        run_root,
        DurableControlIntent::new(
            agent_id.clone(),
            DurableControlKind::Kill,
            target_spawn_generation,
            target_process_identity.clone(),
            expected_lifecycle_generation,
            unix_ms_now()?,
            None,
        )?,
    )
}

pub(crate) fn mark_stop_requested(run_root: &Path) -> Result<(), DurableControlIntentError> {
    advance(
        run_root,
        DurableControlKind::Stop,
        DurableControlPhase::StopRequested,
    )
}

pub(crate) fn mark_kill_requested(run_root: &Path) -> Result<(), DurableControlIntentError> {
    advance(
        run_root,
        DurableControlKind::Kill,
        DurableControlPhase::KillRequested,
    )
}

fn prepare(run_root: &Path, next: DurableControlIntent) -> Result<(), DurableControlIntentError> {
    if let Some(existing) = read_control_intent(run_root)? {
        if existing.kind == next.kind && existing.same_target(&next) {
            return Ok(());
        }
        if next.kind == DurableControlKind::Kill && existing.same_target(&next) {
            return write_control_intent(run_root, &next);
        }
        let current_lease = crate::lease::read_lease(run_root)
            .map_err(|error| DurableControlIntentError::Invalid(error.to_string()))?;
        if current_lease.as_ref().is_some_and(|lease| {
            lease.agent_id == next.agent_id
                && lease.spawn_generation == next.target_spawn_generation
                && lease.identity == next.target_process_identity
        }) {
            return write_control_intent(run_root, &next);
        }
        return Err(DurableControlIntentError::Unresolved);
    }
    write_control_intent(run_root, &next)
}

fn advance(
    run_root: &Path,
    expected_kind: DurableControlKind,
    phase: DurableControlPhase,
) -> Result<(), DurableControlIntentError> {
    let current = read_control_intent(run_root)?.ok_or_else(|| {
        DurableControlIntentError::Invalid("control intent is absent".to_string())
    })?;
    if current.kind != expected_kind {
        return Err(DurableControlIntentError::Invalid(
            "control intent kind changed before acknowledgement".to_string(),
        ));
    }
    write_control_intent(run_root, &current.with_phase(phase)?)
}

fn read_control_intent(
    run_root: &Path,
) -> Result<Option<DurableControlIntent>, DurableControlIntentError> {
    let path = run_root.join(CONTROL_INTENT_FILE);
    let bytes = match std::fs::read(path) {
        Ok(bytes) => bytes,
        Err(error) if error.kind() == ErrorKind::NotFound => return Ok(None),
        Err(error) => return Err(error.into()),
    };
    if bytes.len() > MAX_CONTROL_INTENT_BYTES {
        return Err(DurableControlIntentError::Invalid(
            "control intent exceeds the bounded file size".to_string(),
        ));
    }
    let intent: DurableControlIntent = serde_json::from_slice(&bytes)?;
    intent.validate()?;
    Ok(Some(intent))
}

fn write_control_intent(
    run_root: &Path,
    intent: &DurableControlIntent,
) -> Result<(), DurableControlIntentError> {
    intent.validate()?;
    std::fs::create_dir_all(run_root)?;
    let sequence = TEMP_SEQUENCE.fetch_add(1, Ordering::Relaxed);
    let nanos = SystemTime::now()
        .duration_since(SystemTime::UNIX_EPOCH)
        .map_err(|_| DurableControlIntentError::Invalid("system clock before epoch".to_string()))?
        .as_nanos();
    let temp = run_root.join(format!(".{CONTROL_INTENT_FILE}.{nanos}.{sequence}.tmp"));
    let final_path = run_root.join(CONTROL_INTENT_FILE);
    let bytes = serde_json::to_vec(intent)?;
    if bytes.len() > MAX_CONTROL_INTENT_BYTES {
        return Err(DurableControlIntentError::Invalid(
            "control intent exceeds the bounded file size".to_string(),
        ));
    }
    let mut file = OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(&temp)?;
    file.write_all(&bytes)?;
    file.sync_all()?;
    drop(file);
    crate::durable_publish::publish(&temp, &final_path)?;
    Ok(())
}

fn unix_ms_now() -> Result<u64, DurableControlIntentError> {
    let millis = SystemTime::now()
        .duration_since(SystemTime::UNIX_EPOCH)
        .map_err(|_| DurableControlIntentError::Invalid("system clock before epoch".to_string()))?
        .as_millis();
    u64::try_from(millis)
        .map_err(|_| DurableControlIntentError::Invalid("system clock exceeds u64".to_string()))
}

fn duration_ms(duration: Duration) -> Result<u64, DurableControlIntentError> {
    u64::try_from(duration.as_millis())
        .map_err(|_| DurableControlIntentError::Invalid("duration exceeds u64".to_string()))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn identity(label: &str) -> ProcessIdentity {
        ProcessIdentity::new(41, label).expect("identity")
    }

    fn agent() -> AgentId {
        AgentId::parse("00000000-0000-4000-8000-000000000001").expect("agent")
    }

    #[test]
    fn stop_round_trips_and_retry_preserves_the_original_deadline() {
        let dir = tempfile::tempdir().expect("temp");
        prepare_stop(
            dir.path(),
            &agent(),
            7,
            &identity("incarnation-a"),
            8,
            Duration::from_secs(5),
        )
        .expect("prepare");
        let prepared = read_control_intent(dir.path())
            .expect("read")
            .expect("intent");
        prepare_stop(
            dir.path(),
            &agent(),
            7,
            &identity("incarnation-a"),
            8,
            Duration::from_secs(60),
        )
        .expect("idempotent retry");
        let replayed = read_control_intent(dir.path())
            .expect("read")
            .expect("intent");
        assert_eq!(replayed.operation_sha256, prepared.operation_sha256);
        assert_eq!(
            replayed.stop_deadline_unix_ms,
            prepared.stop_deadline_unix_ms
        );
        mark_stop_requested(dir.path()).expect("requested");
        let requested = read_control_intent(dir.path())
            .expect("read")
            .expect("intent");
        assert_eq!(requested.operation_sha256, prepared.operation_sha256);
        assert_eq!(requested.phase, DurableControlPhase::StopRequested);
    }

    #[test]
    fn tampering_is_rejected() {
        let dir = tempfile::tempdir().expect("temp");
        prepare_kill(
            dir.path(),
            &agent(),
            7,
            &identity("incarnation-a"),
            8,
        )
        .expect("prepare");
        let path = dir.path().join(CONTROL_INTENT_FILE);
        let mut value: serde_json::Value =
            serde_json::from_slice(&std::fs::read(&path).expect("read")).expect("json");
        value["target_spawn_generation"] = serde_json::json!(9);
        std::fs::write(path, serde_json::to_vec(&value).expect("encode")).expect("write");
        assert!(matches!(
            read_control_intent(dir.path()),
            Err(DurableControlIntentError::DigestMismatch)
        ));
    }

    #[test]
    fn kill_may_supersede_stop_only_for_the_same_exact_process() {
        let dir = tempfile::tempdir().expect("temp");
        prepare_stop(
            dir.path(),
            &agent(),
            7,
            &identity("incarnation-a"),
            8,
            Duration::from_secs(5),
        )
        .expect("stop");
        prepare_kill(
            dir.path(),
            &agent(),
            7,
            &identity("incarnation-a"),
            8,
        )
        .expect("dominant kill");
        assert!(matches!(
            prepare_stop(
                dir.path(),
                &agent(),
                7,
                &identity("incarnation-a"),
                8,
                Duration::from_secs(5),
            ),
            Err(DurableControlIntentError::Unresolved)
        ));
        assert!(matches!(
            prepare_kill(
                dir.path(),
                &agent(),
                7,
                &identity("incarnation-b"),
                8,
            ),
            Err(DurableControlIntentError::Unresolved)
        ));
    }
}
