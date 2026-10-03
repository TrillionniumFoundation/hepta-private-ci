//! Durable owner journal for Stop and Kill operations.
//!
//! The journal is written before restart cancellation, lifecycle CAS or process
//! signaling. It binds the exact owned process identity and preserves the
//! original wall-clock deadline across supervisor restarts. Signal success is
//! represented separately from terminal exit observation.

use std::fs::OpenOptions;
use std::io::Write;
use std::path::Path;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;
use std::time::Duration;
use std::time::Instant;
use std::time::SystemTime;

use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_fleet::AgentLifecycle;
use serde::Deserialize;
use serde::Serialize;
use sha2::Digest;
use sha2::Sha256;
use thiserror::Error;

use crate::ProcessIdentity;
use crate::control::pending::PendingControl;

pub(crate) const CONTROL_INTENT_SCHEMA_VERSION: u32 = 1;
pub(crate) const CONTROL_INTENT_FILE: &str = "supervisor-control-intent.json";
const CONTROL_INTENT_DOMAIN: &[u8] = b"hepta-supervisor:control-intent:v1";
const CONTROL_RECORD_DOMAIN: &[u8] = b"hepta-supervisor:control-record:v1";
const MAX_CONTROL_INTENT_BYTES: usize = 8_192;

#[path = "control_intent_io.rs"]
mod bounded_io;

#[cfg(test)]
#[path = "control_completion_tests.rs"]
mod completion_tests;
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
    Completed,
}

impl DurableControlPhase {
    fn terminal(self) -> bool {
        matches!(self, Self::Completed)
    }
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
    pub completed_unix_ms: Option<u64>,
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
            completed_unix_ms: None,
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
        completed_unix_ms: Option<u64>,
    ) -> Result<Self, DurableControlIntentError> {
        let mut next = Self {
            phase,
            completed_unix_ms,
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
        let completion_valid = match self.phase {
            DurableControlPhase::Completed => self
                .completed_unix_ms
                .is_some_and(|completed| completed >= self.requested_unix_ms),
            DurableControlPhase::Prepared
            | DurableControlPhase::StopRequested
            | DurableControlPhase::KillRequested => self.completed_unix_ms.is_none(),
        };
        if self.schema_version != CONTROL_INTENT_SCHEMA_VERSION
            || self.target_spawn_generation == 0
            || self.expected_lifecycle_generation == 0
            || self.requested_unix_ms == 0
            || !stop_deadline_valid
            || !completion_valid
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

    fn matches_target(
        &self,
        agent_id: &AgentId,
        spawn_generation: u64,
        identity: &ProcessIdentity,
    ) -> bool {
        self.agent_id == *agent_id
            && self.target_spawn_generation == spawn_generation
            && self.target_process_identity == *identity
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
        let payload =
            serde_json::to_vec(&(&self.operation_sha256, self.phase, self.completed_unix_ms))?;
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

pub(crate) fn recover_pending(
    run_root: &Path,
    agent_id: &AgentId,
    spawn_generation: u64,
    identity: &ProcessIdentity,
    now: Instant,
) -> Result<Option<PendingControl>, DurableControlIntentError> {
    let Some(intent) = read_control_intent(run_root)? else {
        return Ok(None);
    };
    if intent.phase.terminal() {
        return Ok(None);
    }
    if !intent.matches_target(agent_id, spawn_generation, identity) {
        return Err(DurableControlIntentError::Invalid(
            "unresolved control intent does not bind the current process lease".to_string(),
        ));
    }
    Ok(Some(match intent.kind {
        DurableControlKind::Kill => PendingControl::Kill { spawn_generation },
        DurableControlKind::Stop => PendingControl::Stop {
            spawn_generation,
            deadline: restore_deadline(
                now,
                intent.requested_unix_ms,
                intent.stop_deadline_unix_ms.ok_or_else(|| {
                    DurableControlIntentError::Invalid(
                        "durable Stop intent has no deadline".to_string(),
                    )
                })?,
            )?,
        },
    }))
}

pub(crate) fn reconcile_absent(
    run_root: &Path,
    agent_id: &AgentId,
    lifecycle: AgentLifecycle,
) -> Result<(), DurableControlIntentError> {
    let Some(intent) = read_control_intent(run_root)? else {
        return Ok(());
    };
    if intent.phase.terminal() {
        return Ok(());
    }
    if intent.agent_id != *agent_id
        || !matches!(lifecycle, AgentLifecycle::Stopped | AgentLifecycle::Failed)
        || crate::lease::read_lease(run_root)
            .map_err(|error| DurableControlIntentError::Invalid(error.to_string()))?
            .is_some()
    {
        return Err(DurableControlIntentError::Unresolved);
    }
    // A crash may follow durable Stop/Kill preparation but precede restart
    // cancellation. Never hide that override behind Completed while the old
    // restart remains pending. Cancellation preserves attempt/window history
    // and the independent companion domain in the existing restart owner.
    crate::restart_budget::cancel_restart(run_root)
        .map_err(|error| DurableControlIntentError::Invalid(error.to_string()))?;
    write_control_intent(
        run_root,
        &intent.with_phase(DurableControlPhase::Completed, Some(unix_ms_now()?))?,
    )
}

/// Reconcile the prepare -> cancellation crash cut before restoring a restart.
/// Completed intents do not suppress a subsequently authorized new restart.
pub(crate) fn cancel_restart_if_unresolved(
    run_root: &Path,
    agent_id: &AgentId,
) -> Result<bool, DurableControlIntentError> {
    let Some(intent) = read_control_intent(run_root)? else {
        return Ok(false);
    };
    if intent.phase.terminal() {
        return Ok(false);
    }
    if intent.agent_id != *agent_id {
        return Err(DurableControlIntentError::Invalid(
            "termination intent belongs to another Agent".to_string(),
        ));
    }
    crate::restart_budget::cancel_restart(run_root)
        .map_err(|error| DurableControlIntentError::Invalid(error.to_string()))?;
    Ok(true)
}

pub(crate) fn has_unresolved(run_root: &Path) -> Result<bool, DurableControlIntentError> {
    Ok(read_control_intent(run_root)?.is_some_and(|intent| !intent.phase.terminal()))
}

fn prepare(run_root: &Path, next: DurableControlIntent) -> Result<(), DurableControlIntentError> {
    if let Some(existing) = read_control_intent(run_root)? {
        if existing.kind == next.kind && existing.same_target(&next) {
            return Ok(());
        }
        if next.kind == DurableControlKind::Kill && existing.same_target(&next) {
            return write_control_intent(run_root, &next);
        }
        if !existing.phase.terminal() {
            return Err(DurableControlIntentError::Unresolved);
        }
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
    if current.kind != expected_kind || current.phase.terminal() {
        return Err(DurableControlIntentError::Invalid(
            "control intent kind or phase changed before acknowledgement".to_string(),
        ));
    }
    write_control_intent(run_root, &current.with_phase(phase, None)?)
}

fn restore_deadline(
    now: Instant,
    requested_unix_ms: u64,
    deadline_unix_ms: u64,
) -> Result<Instant, DurableControlIntentError> {
    let current_unix_ms = unix_ms_now()?;
    if current_unix_ms < requested_unix_ms {
        return Err(DurableControlIntentError::Invalid(
            "wall-clock rollback precedes the durable control request".to_string(),
        ));
    }
    let remaining = deadline_unix_ms.saturating_sub(current_unix_ms);
    now.checked_add(Duration::from_millis(remaining))
        .ok_or_else(|| DurableControlIntentError::Invalid("deadline overflow".to_string()))
}

fn read_control_intent(
    run_root: &Path,
) -> Result<Option<DurableControlIntent>, DurableControlIntentError> {
    let path = run_root.join(CONTROL_INTENT_FILE);
    let Some(bytes) = bounded_io::read(&path, MAX_CONTROL_INTENT_BYTES)? else {
        return Ok(None);
    };
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
    let mut options = OpenOptions::new();
    options.write(true).create_new(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.mode(0o600);
    }
    let mut file = options.open(&temp)?;
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
    fn stop_retry_preserves_original_deadline_and_recovers_exact_target() {
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
        assert!(matches!(
            recover_pending(
                dir.path(),
                &agent(),
                7,
                &identity("incarnation-a"),
                Instant::now(),
            )
            .expect("recover"),
            Some(PendingControl::Stop {
                spawn_generation: 7,
                ..
            })
        ));
        assert!(
            recover_pending(
                dir.path(),
                &agent(),
                7,
                &identity("incarnation-b"),
                Instant::now(),
            )
            .is_err()
        );
    }

    #[test]
    fn tampering_is_rejected() {
        let dir = tempfile::tempdir().expect("temp");
        prepare_kill(dir.path(), &agent(), 7, &identity("incarnation-a"), 8).expect("prepare");
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
    fn kill_supersedes_stop_only_for_same_process_and_absence_completes() {
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
        prepare_kill(dir.path(), &agent(), 7, &identity("incarnation-a"), 8)
            .expect("dominant kill");
        assert!(matches!(
            prepare_kill(dir.path(), &agent(), 7, &identity("incarnation-b"), 8,),
            Err(DurableControlIntentError::Unresolved)
        ));
        reconcile_absent(dir.path(), &agent(), AgentLifecycle::Stopped).expect("terminal absence");
        assert!(!has_unresolved(dir.path()).expect("status"));
    }
}
