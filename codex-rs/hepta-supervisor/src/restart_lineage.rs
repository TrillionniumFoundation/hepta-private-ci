//! Durable identity lineage for one pending main-process restart.
//!
//! The restart budget limits attempts; this record proves which exact process
//! is the predecessor and which later process is the replacement. A live
//! process is never interpreted as a successful replacement merely because a
//! restart budget is pending after daemon recovery.

use std::fs::Metadata;
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
use codex_hepta_fleet::ReleaseId;
use serde::Deserialize;
use serde::Serialize;
use sha2::Digest;
use sha2::Sha256;
use thiserror::Error;

use crate::ProcessIdentity;

pub(crate) const RESTART_LINEAGE_FILE: &str = "supervisor-restart-lineage.json";
const RESTART_LINEAGE_SCHEMA_VERSION: u32 = 1;
const RESTART_LINEAGE_DOMAIN: &[u8] = b"hepta-supervisor:restart-lineage:v1";
const MAX_RESTART_LINEAGE_BYTES: usize = 16_384;
static TEMP_SEQUENCE: AtomicU64 = AtomicU64::new(1);

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct RestartProcessWitness {
    pub(crate) spawn_generation: u64,
    pub(crate) identity: ProcessIdentity,
    pub(crate) release_id: ReleaseId,
}

impl RestartProcessWitness {
    pub(crate) fn new(
        spawn_generation: u64,
        identity: ProcessIdentity,
        release_id: ReleaseId,
    ) -> Result<Self, RestartLineageError> {
        if spawn_generation == 0 {
            return Err(RestartLineageError::Invalid(
                "restart process generation must be non-zero".to_string(),
            ));
        }
        Ok(Self {
            spawn_generation,
            identity,
            release_id,
        })
    }
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
enum RestartLineagePhase {
    PredecessorOwned,
    ReplacementPending,
    ReplacementStarted,
    Completed,
    Cancelled,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
struct DurableRestartLineage {
    schema_version: u32,
    agent_id: AgentId,
    window_started_unix_ms: u64,
    attempt: u32,
    predecessor: Option<RestartProcessWitness>,
    predecessor_exit_observed: bool,
    replacement: Option<RestartProcessWitness>,
    phase: RestartLineagePhase,
    record_sha256: Sha256Digest,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) enum RestartRecoveryRole {
    PredecessorOwned,
    ReplacementPending,
    ReplacementStarted,
    Completed,
    Cancelled,
}

#[derive(Debug, Error)]
pub(crate) enum RestartLineageError {
    #[error("restart lineage is invalid: {0}")]
    Invalid(String),
    #[error("restart lineage digest mismatch")]
    DigestMismatch,
    #[error(transparent)]
    Io(#[from] std::io::Error),
    #[error(transparent)]
    Serialization(#[from] serde_json::Error),
}

impl DurableRestartLineage {
    fn new(
        agent_id: AgentId,
        window_started_unix_ms: u64,
        attempt: u32,
        predecessor: Option<RestartProcessWitness>,
    ) -> Result<Self, RestartLineageError> {
        let predecessor_exit_observed = predecessor.is_none();
        let phase = if predecessor_exit_observed {
            RestartLineagePhase::ReplacementPending
        } else {
            RestartLineagePhase::PredecessorOwned
        };
        let mut lineage = Self {
            schema_version: RESTART_LINEAGE_SCHEMA_VERSION,
            agent_id,
            window_started_unix_ms,
            attempt,
            predecessor,
            predecessor_exit_observed,
            replacement: None,
            phase,
            record_sha256: Sha256Digest::for_bytes(b"pending"),
        };
        lineage.record_sha256 = lineage.compute_digest()?;
        lineage.validate()?;
        Ok(lineage)
    }

    fn with_state(
        &self,
        predecessor_exit_observed: bool,
        replacement: Option<RestartProcessWitness>,
        phase: RestartLineagePhase,
    ) -> Result<Self, RestartLineageError> {
        let mut next = Self {
            predecessor_exit_observed,
            replacement,
            phase,
            ..self.clone()
        };
        next.record_sha256 = next.compute_digest()?;
        next.validate()?;
        Ok(next)
    }

    fn same_operation(&self, window_started_unix_ms: u64, attempt: u32) -> bool {
        self.window_started_unix_ms == window_started_unix_ms && self.attempt == attempt
    }

    fn terminal(&self) -> bool {
        matches!(
            self.phase,
            RestartLineagePhase::Completed | RestartLineagePhase::Cancelled
        )
    }

    fn validate(&self) -> Result<(), RestartLineageError> {
        let state_valid = match self.phase {
            RestartLineagePhase::PredecessorOwned => {
                self.predecessor.is_some()
                    && !self.predecessor_exit_observed
                    && self.replacement.is_none()
            }
            RestartLineagePhase::ReplacementPending => {
                self.predecessor_exit_observed && self.replacement.is_none()
            }
            RestartLineagePhase::ReplacementStarted | RestartLineagePhase::Completed => {
                self.predecessor_exit_observed && self.replacement.is_some()
            }
            RestartLineagePhase::Cancelled => true,
        };
        if self.schema_version != RESTART_LINEAGE_SCHEMA_VERSION
            || self.window_started_unix_ms == 0
            || self.attempt == 0
            || !state_valid
        {
            return Err(RestartLineageError::Invalid(
                "restart operation identity or phase is outside its bounds".to_string(),
            ));
        }
        if let (Some(predecessor), Some(replacement)) = (&self.predecessor, &self.replacement)
            && (predecessor == replacement
                || replacement.spawn_generation <= predecessor.spawn_generation
                || replacement.release_id != predecessor.release_id)
        {
            return Err(RestartLineageError::Invalid(
                "restart replacement does not prove a fresh same-release generation".to_string(),
            ));
        }
        if self.record_sha256 != self.compute_digest()? {
            return Err(RestartLineageError::DigestMismatch);
        }
        Ok(())
    }

    fn compute_digest(&self) -> Result<Sha256Digest, RestartLineageError> {
        let payload = serde_json::to_vec(&(
            self.schema_version,
            &self.agent_id,
            self.window_started_unix_ms,
            self.attempt,
            &self.predecessor,
            self.predecessor_exit_observed,
            &self.replacement,
            self.phase,
        ))?;
        Ok(Sha256Digest::from_sha256_output(Sha256::digest(
            [RESTART_LINEAGE_DOMAIN, payload.as_slice()].concat(),
        )))
    }
}

pub(crate) fn begin(
    run_root: &Path,
    agent_id: &AgentId,
    window_started_unix_ms: u64,
    attempt: u32,
    predecessor: Option<RestartProcessWitness>,
) -> Result<(), RestartLineageError> {
    let next = DurableRestartLineage::new(
        agent_id.clone(),
        window_started_unix_ms,
        attempt,
        predecessor,
    )?;
    if let Some(current) = read(run_root)? {
        if current.same_operation(window_started_unix_ms, attempt) {
            if current.agent_id != *agent_id {
                return Err(RestartLineageError::Invalid(
                    "restart lineage belongs to another Agent".to_string(),
                ));
            }
            if !current.terminal() && current.predecessor != next.predecessor {
                return Err(RestartLineageError::Invalid(
                    "restart predecessor changed for the same operation".to_string(),
                ));
            }
            return Ok(());
        }
        if !current.terminal() {
            return Err(RestartLineageError::Invalid(
                "another restart lineage remains unresolved".to_string(),
            ));
        }
    }
    write(run_root, &next)
}

pub(crate) fn reconcile_pending(
    run_root: &Path,
    agent_id: &AgentId,
    window_started_unix_ms: u64,
    attempt: u32,
    current: Option<&RestartProcessWitness>,
    process_lease_present: bool,
) -> Result<RestartRecoveryRole, RestartLineageError> {
    let mut lineage = match read(run_root)? {
        Some(lineage) if lineage.same_operation(window_started_unix_ms, attempt) => lineage,
        Some(lineage) if !lineage.terminal() => {
            return Err(RestartLineageError::Invalid(
                "pending restart does not match the unresolved lineage".to_string(),
            ));
        }
        _ => {
            if current.is_none() && process_lease_present {
                return Err(RestartLineageError::Invalid(
                    "restart has an unowned process lease".to_string(),
                ));
            }
            let lineage = DurableRestartLineage::new(
                agent_id.clone(),
                window_started_unix_ms,
                attempt,
                current.cloned(),
            )?;
            write(run_root, &lineage)?;
            lineage
        }
    };
    if lineage.agent_id != *agent_id {
        return Err(RestartLineageError::Invalid(
            "restart lineage belongs to another Agent".to_string(),
        ));
    }

    match lineage.phase {
        RestartLineagePhase::PredecessorOwned => match current {
            Some(current) if lineage.predecessor.as_ref() == Some(current) => {
                Ok(RestartRecoveryRole::PredecessorOwned)
            }
            None if !process_lease_present => {
                lineage =
                    lineage.with_state(true, None, RestartLineagePhase::ReplacementPending)?;
                write(run_root, &lineage)?;
                Ok(RestartRecoveryRole::ReplacementPending)
            }
            _ => Err(RestartLineageError::Invalid(
                "live process does not match the durable restart predecessor".to_string(),
            )),
        },
        RestartLineagePhase::ReplacementPending => match current {
            None if !process_lease_present => Ok(RestartRecoveryRole::ReplacementPending),
            Some(current) => {
                if let Some(predecessor) = &lineage.predecessor
                    && (current.spawn_generation <= predecessor.spawn_generation
                        || current.release_id != predecessor.release_id)
                {
                    return Err(RestartLineageError::Invalid(
                        "adopted process cannot be the restart replacement".to_string(),
                    ));
                }
                lineage = lineage.with_state(
                    true,
                    Some(current.clone()),
                    RestartLineagePhase::ReplacementStarted,
                )?;
                write(run_root, &lineage)?;
                Ok(RestartRecoveryRole::ReplacementStarted)
            }
            None => Err(RestartLineageError::Invalid(
                "restart replacement lease is not owned".to_string(),
            )),
        },
        RestartLineagePhase::ReplacementStarted => match current {
            Some(current) if lineage.replacement.as_ref() == Some(current) => {
                Ok(RestartRecoveryRole::ReplacementStarted)
            }
            _ => Err(RestartLineageError::Invalid(
                "live process does not match the durable restart replacement".to_string(),
            )),
        },
        RestartLineagePhase::Completed => Ok(RestartRecoveryRole::Completed),
        RestartLineagePhase::Cancelled => Ok(RestartRecoveryRole::Cancelled),
    }
}

pub(crate) fn bind_replacement(
    run_root: &Path,
    agent_id: &AgentId,
    window_started_unix_ms: u64,
    attempt: u32,
    replacement: RestartProcessWitness,
) -> Result<(), RestartLineageError> {
    let lineage = read(run_root)?
        .ok_or_else(|| RestartLineageError::Invalid("restart lineage is absent".to_string()))?;
    if lineage.agent_id != *agent_id || !lineage.same_operation(window_started_unix_ms, attempt) {
        return Err(RestartLineageError::Invalid(
            "restart lineage operation identity changed".to_string(),
        ));
    }
    if matches!(
        lineage.phase,
        RestartLineagePhase::ReplacementStarted | RestartLineagePhase::Completed
    ) && lineage.replacement.as_ref() == Some(&replacement)
    {
        return Ok(());
    }
    if lineage.phase != RestartLineagePhase::ReplacementPending {
        return Err(RestartLineageError::Invalid(
            "restart lineage is not awaiting a replacement".to_string(),
        ));
    }
    let next = lineage.with_state(
        true,
        Some(replacement),
        RestartLineagePhase::ReplacementStarted,
    )?;
    write(run_root, &next)
}

pub(crate) fn mark_predecessor_exited(
    run_root: &Path,
    agent_id: &AgentId,
    predecessor: &RestartProcessWitness,
) -> Result<(), RestartLineageError> {
    let lineage = read(run_root)?
        .ok_or_else(|| RestartLineageError::Invalid("restart lineage is absent".to_string()))?;
    if lineage.agent_id != *agent_id || lineage.predecessor.as_ref() != Some(predecessor) {
        return Err(RestartLineageError::Invalid(
            "exit does not match the durable restart predecessor".to_string(),
        ));
    }
    if matches!(
        lineage.phase,
        RestartLineagePhase::ReplacementPending
            | RestartLineagePhase::ReplacementStarted
            | RestartLineagePhase::Completed
    ) && lineage.predecessor_exit_observed
    {
        return Ok(());
    }
    if lineage.phase != RestartLineagePhase::PredecessorOwned {
        return Err(RestartLineageError::Invalid(
            "restart lineage cannot accept a predecessor exit".to_string(),
        ));
    }
    write(
        run_root,
        &lineage.with_state(true, None, RestartLineagePhase::ReplacementPending)?,
    )
}

pub(crate) fn complete(
    run_root: &Path,
    agent_id: &AgentId,
    replacement: &RestartProcessWitness,
) -> Result<(), RestartLineageError> {
    let lineage = read(run_root)?
        .ok_or_else(|| RestartLineageError::Invalid("restart lineage is absent".to_string()))?;
    if lineage.agent_id != *agent_id || lineage.replacement.as_ref() != Some(replacement) {
        return Err(RestartLineageError::Invalid(
            "healthy process is not the durable restart replacement".to_string(),
        ));
    }
    if lineage.phase == RestartLineagePhase::Completed {
        return Ok(());
    }
    if lineage.phase != RestartLineagePhase::ReplacementStarted {
        return Err(RestartLineageError::Invalid(
            "restart lineage has not started the replacement".to_string(),
        ));
    }
    write(
        run_root,
        &lineage.with_state(
            true,
            Some(replacement.clone()),
            RestartLineagePhase::Completed,
        )?,
    )
}

pub(crate) fn cancel(run_root: &Path, agent_id: &AgentId) -> Result<(), RestartLineageError> {
    let Some(lineage) = read(run_root)? else {
        return Ok(());
    };
    if lineage.agent_id != *agent_id {
        return Err(RestartLineageError::Invalid(
            "restart lineage belongs to another Agent".to_string(),
        ));
    }
    if lineage.terminal() {
        return Ok(());
    }
    write(
        run_root,
        &lineage.with_state(
            lineage.predecessor_exit_observed,
            lineage.replacement.clone(),
            RestartLineagePhase::Cancelled,
        )?,
    )
}

pub(crate) fn cancel_if_budget_absent(
    run_root: &Path,
    agent_id: &AgentId,
) -> Result<(), RestartLineageError> {
    cancel(run_root, agent_id)
}

pub(crate) fn validate_recovery(
    run_root: &Path,
    agent_id: &AgentId,
) -> Result<(), RestartLineageError> {
    if let Some(lineage) = read(run_root)?
        && lineage.agent_id != *agent_id
    {
        return Err(RestartLineageError::Invalid(
            "restart lineage belongs to another Agent".to_string(),
        ));
    }
    Ok(())
}

fn read(run_root: &Path) -> Result<Option<DurableRestartLineage>, RestartLineageError> {
    let path = run_root.join(RESTART_LINEAGE_FILE);
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
    let opened = file.metadata()?;
    validate_metadata(&opened)?;
    let named = std::fs::symlink_metadata(&path)?;
    validate_metadata(&named)?;
    same_file(&opened, &named)?;
    let mut bytes = Vec::new();
    (&mut file)
        .take((MAX_RESTART_LINEAGE_BYTES + 1) as u64)
        .read_to_end(&mut bytes)?;
    if bytes.len() > MAX_RESTART_LINEAGE_BYTES {
        return Err(RestartLineageError::Invalid(
            "restart lineage exceeds its file bound".to_string(),
        ));
    }
    let after = file.metadata()?;
    let named_after = std::fs::symlink_metadata(&path)?;
    validate_metadata(&after)?;
    validate_metadata(&named_after)?;
    same_file(&opened, &after)?;
    same_file(&opened, &named_after)?;
    if bytes.len() as u64 != after.len() {
        return Err(RestartLineageError::Invalid(
            "restart lineage changed while being read".to_string(),
        ));
    }
    let lineage: DurableRestartLineage = serde_json::from_slice(&bytes)?;
    lineage.validate()?;
    Ok(Some(lineage))
}

fn write(run_root: &Path, lineage: &DurableRestartLineage) -> Result<(), RestartLineageError> {
    lineage.validate()?;
    std::fs::create_dir_all(run_root)?;
    let destination = run_root.join(RESTART_LINEAGE_FILE);
    let sequence = TEMP_SEQUENCE.fetch_add(1, Ordering::Relaxed);
    let nanos = SystemTime::now()
        .duration_since(SystemTime::UNIX_EPOCH)
        .map_err(|_| RestartLineageError::Invalid("system clock is before Unix epoch".to_string()))?
        .as_nanos();
    let staging = run_root.join(format!(".{RESTART_LINEAGE_FILE}.{nanos}.{sequence}.tmp"));
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
    let bytes = serde_json::to_vec(lineage)?;
    if bytes.len() > MAX_RESTART_LINEAGE_BYTES {
        let _ = std::fs::remove_file(&staging);
        return Err(RestartLineageError::Invalid(
            "restart lineage exceeds its file bound".to_string(),
        ));
    }
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

fn validate_metadata(metadata: &Metadata) -> Result<(), RestartLineageError> {
    if !metadata.file_type().is_file()
        || metadata.file_type().is_symlink()
        || metadata.len() > MAX_RESTART_LINEAGE_BYTES as u64
    {
        return Err(RestartLineageError::Invalid(
            "restart lineage is not a bounded regular file".to_string(),
        ));
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::MetadataExt;
        // SAFETY: geteuid has no arguments and no memory-safety preconditions.
        let owner = unsafe { libc::geteuid() };
        if metadata.uid() != owner || metadata.nlink() != 1 || metadata.mode() & 0o022 != 0 {
            return Err(RestartLineageError::Invalid(
                "restart lineage ownership, links, or permissions are unsafe".to_string(),
            ));
        }
    }
    Ok(())
}

fn same_file(before: &Metadata, after: &Metadata) -> Result<(), RestartLineageError> {
    #[cfg(unix)]
    {
        use std::os::unix::fs::MetadataExt;
        if before.dev() != after.dev()
            || before.ino() != after.ino()
            || before.mtime() != after.mtime()
            || before.mtime_nsec() != after.mtime_nsec()
            || before.ctime() != after.ctime()
            || before.ctime_nsec() != after.ctime_nsec()
        {
            return Err(RestartLineageError::Invalid(
                "restart lineage identity changed during open/read".to_string(),
            ));
        }
    }
    if before.len() != after.len() || before.modified()? != after.modified()? {
        return Err(RestartLineageError::Invalid(
            "restart lineage changed during open/read".to_string(),
        ));
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn agent() -> AgentId {
        AgentId::parse("00000000-0000-4000-8000-000000000001").expect("agent")
    }

    fn witness(generation: u64, incarnation: &str) -> RestartProcessWitness {
        RestartProcessWitness::new(
            generation,
            ProcessIdentity::new(generation, incarnation).expect("identity"),
            ReleaseId::parse("release-a").expect("release"),
        )
        .expect("witness")
    }

    #[test]
    fn predecessor_cannot_be_completed_as_the_replacement() {
        let directory = tempfile::tempdir().expect("tempdir");
        let predecessor = witness(11, "predecessor");
        begin(
            directory.path(),
            &agent(),
            100,
            1,
            Some(predecessor.clone()),
        )
        .expect("begin");
        assert_eq!(
            reconcile_pending(directory.path(), &agent(), 100, 1, Some(&predecessor), true,)
                .expect("recover"),
            RestartRecoveryRole::PredecessorOwned
        );
        assert!(complete(directory.path(), &agent(), &predecessor).is_err());
    }

    #[test]
    fn exact_exit_and_fresh_replacement_close_lineage_idempotently() {
        let directory = tempfile::tempdir().expect("tempdir");
        let predecessor = witness(11, "predecessor");
        let replacement = witness(12, "replacement");
        begin(
            directory.path(),
            &agent(),
            100,
            1,
            Some(predecessor.clone()),
        )
        .expect("begin");
        mark_predecessor_exited(directory.path(), &agent(), &predecessor)
            .expect("predecessor exit");
        mark_predecessor_exited(directory.path(), &agent(), &predecessor)
            .expect("replayed predecessor exit");
        bind_replacement(directory.path(), &agent(), 100, 1, replacement.clone())
            .expect("replacement");
        bind_replacement(directory.path(), &agent(), 100, 1, replacement.clone())
            .expect("replayed replacement");
        complete(directory.path(), &agent(), &replacement).expect("complete");
        complete(directory.path(), &agent(), &replacement).expect("replayed complete");
        assert_eq!(
            reconcile_pending(directory.path(), &agent(), 100, 1, Some(&replacement), true,)
                .expect("recover"),
            RestartRecoveryRole::Completed
        );
    }

    #[test]
    fn missing_sidecar_reconstructs_conservatively_from_owned_process() {
        let directory = tempfile::tempdir().expect("tempdir");
        let predecessor = witness(11, "predecessor");
        assert_eq!(
            reconcile_pending(directory.path(), &agent(), 100, 1, Some(&predecessor), true,)
                .expect("reconstruct"),
            RestartRecoveryRole::PredecessorOwned
        );
    }

    #[test]
    fn changed_live_identity_is_rejected() {
        let directory = tempfile::tempdir().expect("tempdir");
        let predecessor = witness(11, "predecessor");
        begin(directory.path(), &agent(), 100, 1, Some(predecessor)).expect("begin");
        assert!(
            reconcile_pending(
                directory.path(),
                &agent(),
                100,
                1,
                Some(&witness(12, "unrelated")),
                true,
            )
            .is_err()
        );
    }
}
