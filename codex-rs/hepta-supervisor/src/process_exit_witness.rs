//! Durable exact-process exit evidence shared across daemon generations.
//!
//! A signal acknowledgement is not an exit observation. This witness is
//! published only after the owned process handle reports a terminal state. It
//! survives daemon restart, binds the exact process incarnation and can be
//! consumed idempotently only after lease/lifecycle finalization succeeds.

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

pub const PROCESS_EXIT_WITNESS_SCHEMA_VERSION: u32 = 1;
pub const PROCESS_EXIT_WITNESS_FILE: &str = "supervisor-process-exit-witness.json";
const PROCESS_EXIT_WITNESS_DOMAIN: &[u8] = b"hepta-supervisor:process-exit-witness:v1";
const MAX_PROCESS_EXIT_WITNESS_BYTES: usize = 16_384;
static TEMP_SEQUENCE: AtomicU64 = AtomicU64::new(1);

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum ProcessExitWitnessPhaseV1 {
    Observed,
    Consumed,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ProcessExitWitnessV1 {
    pub schema_version: u32,
    pub witness_id: Sha256Digest,
    pub agent_id: AgentId,
    pub lifecycle_generation: u64,
    pub spawn_generation: u64,
    pub release_id: ReleaseId,
    pub process_identity: ProcessIdentity,
    pub success: bool,
    pub code: Option<i32>,
    pub observed_unix_ms: u64,
    pub observer_process_id: u32,
    pub phase: ProcessExitWitnessPhaseV1,
    pub record_sha256: Sha256Digest,
}

#[derive(Debug, Error)]
pub enum ProcessExitWitnessError {
    #[error("process exit witness is invalid: {0}")]
    Invalid(String),
    #[error("process exit witness digest mismatch")]
    DigestMismatch,
    #[error("another exact-process exit witness remains unconsumed")]
    Unresolved,
    #[error(transparent)]
    Io(#[from] std::io::Error),
    #[error(transparent)]
    Serialization(#[from] serde_json::Error),
}

impl ProcessExitWitnessV1 {
    fn new(
        agent_id: AgentId,
        lifecycle_generation: u64,
        spawn_generation: u64,
        release_id: ReleaseId,
        process_identity: ProcessIdentity,
        success: bool,
        code: Option<i32>,
        observed_unix_ms: u64,
    ) -> Result<Self, ProcessExitWitnessError> {
        let observer_process_id = std::process::id();
        let mut witness = Self {
            schema_version: PROCESS_EXIT_WITNESS_SCHEMA_VERSION,
            witness_id: Sha256Digest::for_bytes(b"pending"),
            agent_id,
            lifecycle_generation,
            spawn_generation,
            release_id,
            process_identity,
            success,
            code,
            observed_unix_ms,
            observer_process_id,
            phase: ProcessExitWitnessPhaseV1::Observed,
            record_sha256: Sha256Digest::for_bytes(b"pending"),
        };
        witness.witness_id = witness.compute_witness_id()?;
        witness.record_sha256 = witness.compute_record_digest()?;
        witness.validate()?;
        Ok(witness)
    }

    fn with_phase(
        &self,
        phase: ProcessExitWitnessPhaseV1,
    ) -> Result<Self, ProcessExitWitnessError> {
        let mut next = Self {
            phase,
            ..self.clone()
        };
        next.record_sha256 = next.compute_record_digest()?;
        next.validate()?;
        Ok(next)
    }

    fn same_target(
        &self,
        agent_id: &AgentId,
        lifecycle_generation: u64,
        spawn_generation: u64,
        release_id: &ReleaseId,
        process_identity: &ProcessIdentity,
    ) -> bool {
        self.agent_id == *agent_id
            && self.lifecycle_generation == lifecycle_generation
            && self.spawn_generation == spawn_generation
            && self.release_id == *release_id
            && self.process_identity == *process_identity
    }

    fn validate(&self) -> Result<(), ProcessExitWitnessError> {
        if self.schema_version != PROCESS_EXIT_WITNESS_SCHEMA_VERSION
            || self.lifecycle_generation == 0
            || self.spawn_generation == 0
            || self.observed_unix_ms == 0
            || self.observer_process_id == 0
            || (self.success && self.code.is_some_and(|code| code != 0))
        {
            return Err(ProcessExitWitnessError::Invalid(
                "identity, generation, time, observer or exit result is outside its bounds"
                    .to_string(),
            ));
        }
        if self.witness_id != self.compute_witness_id()?
            || self.record_sha256 != self.compute_record_digest()?
        {
            return Err(ProcessExitWitnessError::DigestMismatch);
        }
        Ok(())
    }

    fn compute_witness_id(&self) -> Result<Sha256Digest, ProcessExitWitnessError> {
        let payload = serde_json::to_vec(&(
            self.schema_version,
            &self.agent_id,
            self.lifecycle_generation,
            self.spawn_generation,
            &self.release_id,
            &self.process_identity,
            self.success,
            self.code,
            self.observed_unix_ms,
            self.observer_process_id,
        ))?;
        Ok(Sha256Digest::from_sha256_output(Sha256::digest(
            [PROCESS_EXIT_WITNESS_DOMAIN, payload.as_slice()].concat(),
        )))
    }

    fn compute_record_digest(&self) -> Result<Sha256Digest, ProcessExitWitnessError> {
        let payload = serde_json::to_vec(&(&self.witness_id, self.phase))?;
        Ok(Sha256Digest::from_sha256_output(Sha256::digest(
            [PROCESS_EXIT_WITNESS_DOMAIN, b":record:", payload.as_slice()].concat(),
        )))
    }
}

pub fn record_process_exit(
    run_root: &Path,
    agent_id: &AgentId,
    lifecycle_generation: u64,
    spawn_generation: u64,
    release_id: &ReleaseId,
    process_identity: &ProcessIdentity,
    success: bool,
    code: Option<i32>,
) -> Result<ProcessExitWitnessV1, ProcessExitWitnessError> {
    if let Some(existing) = read_process_exit_witness(run_root)? {
        if existing.same_target(
            agent_id,
            lifecycle_generation,
            spawn_generation,
            release_id,
            process_identity,
        ) {
            if existing.success != success || existing.code != code {
                return Err(ProcessExitWitnessError::Invalid(
                    "the exact process has conflicting terminal observations".to_string(),
                ));
            }
            return Ok(existing);
        }
        if existing.phase == ProcessExitWitnessPhaseV1::Observed {
            return Err(ProcessExitWitnessError::Unresolved);
        }
    }
    let witness = ProcessExitWitnessV1::new(
        agent_id.clone(),
        lifecycle_generation,
        spawn_generation,
        release_id.clone(),
        process_identity.clone(),
        success,
        code,
        unix_ms_now()?,
    )?;
    write_process_exit_witness(run_root, &witness)?;
    Ok(witness)
}

pub fn consume_process_exit_witness(
    run_root: &Path,
    witness_id: &Sha256Digest,
) -> Result<ProcessExitWitnessV1, ProcessExitWitnessError> {
    let current = read_process_exit_witness(run_root)?.ok_or_else(|| {
        ProcessExitWitnessError::Invalid("process exit witness is absent".to_string())
    })?;
    if current.witness_id != *witness_id {
        return Err(ProcessExitWitnessError::Invalid(
            "process exit witness identity changed before consumption".to_string(),
        ));
    }
    if current.phase == ProcessExitWitnessPhaseV1::Consumed {
        return Ok(current);
    }
    let consumed = current.with_phase(ProcessExitWitnessPhaseV1::Consumed)?;
    write_process_exit_witness(run_root, &consumed)?;
    Ok(consumed)
}

pub fn read_process_exit_witness(
    run_root: &Path,
) -> Result<Option<ProcessExitWitnessV1>, ProcessExitWitnessError> {
    let path = run_root.join(PROCESS_EXIT_WITNESS_FILE);
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
        .take((MAX_PROCESS_EXIT_WITNESS_BYTES + 1) as u64)
        .read_to_end(&mut bytes)?;
    if bytes.len() > MAX_PROCESS_EXIT_WITNESS_BYTES {
        return Err(ProcessExitWitnessError::Invalid(
            "process exit witness exceeds its file bound".to_string(),
        ));
    }
    let after = file.metadata()?;
    let named_after = std::fs::symlink_metadata(&path)?;
    validate_metadata(&after)?;
    validate_metadata(&named_after)?;
    same_file(&opened, &after)?;
    same_file(&opened, &named_after)?;
    if bytes.len() as u64 != after.len() {
        return Err(ProcessExitWitnessError::Invalid(
            "process exit witness changed while being read".to_string(),
        ));
    }
    let witness: ProcessExitWitnessV1 = serde_json::from_slice(&bytes)?;
    witness.validate()?;
    Ok(Some(witness))
}

fn write_process_exit_witness(
    run_root: &Path,
    witness: &ProcessExitWitnessV1,
) -> Result<(), ProcessExitWitnessError> {
    witness.validate()?;
    std::fs::create_dir_all(run_root)?;
    let bytes = serde_json::to_vec(witness)?;
    if bytes.len() > MAX_PROCESS_EXIT_WITNESS_BYTES {
        return Err(ProcessExitWitnessError::Invalid(
            "process exit witness exceeds its file bound".to_string(),
        ));
    }
    let sequence = TEMP_SEQUENCE.fetch_add(1, Ordering::Relaxed);
    let nanos = SystemTime::now()
        .duration_since(SystemTime::UNIX_EPOCH)
        .map_err(|_| ProcessExitWitnessError::Invalid("system clock before epoch".to_string()))?
        .as_nanos();
    let staging = run_root.join(format!(
        ".{PROCESS_EXIT_WITNESS_FILE}.{nanos}.{sequence}.tmp"
    ));
    let destination = run_root.join(PROCESS_EXIT_WITNESS_FILE);
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

fn unix_ms_now() -> Result<u64, ProcessExitWitnessError> {
    let millis = SystemTime::now()
        .duration_since(SystemTime::UNIX_EPOCH)
        .map_err(|_| ProcessExitWitnessError::Invalid("system clock before epoch".to_string()))?
        .as_millis();
    u64::try_from(millis)
        .map_err(|_| ProcessExitWitnessError::Invalid("system clock exceeds u64".to_string()))
}

fn validate_metadata(metadata: &Metadata) -> Result<(), ProcessExitWitnessError> {
    if !metadata.file_type().is_file()
        || metadata.file_type().is_symlink()
        || metadata.len() > MAX_PROCESS_EXIT_WITNESS_BYTES as u64
    {
        return Err(ProcessExitWitnessError::Invalid(
            "process exit witness is not a bounded regular file".to_string(),
        ));
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::MetadataExt;
        // SAFETY: geteuid has no arguments and no memory-safety preconditions.
        let owner = unsafe { libc::geteuid() };
        if metadata.uid() != owner || metadata.nlink() != 1 || metadata.mode() & 0o022 != 0 {
            return Err(ProcessExitWitnessError::Invalid(
                "process exit witness ownership, links, or permissions are unsafe".to_string(),
            ));
        }
    }
    Ok(())
}

fn same_file(before: &Metadata, after: &Metadata) -> Result<(), ProcessExitWitnessError> {
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
            return Err(ProcessExitWitnessError::Invalid(
                "process exit witness identity changed during read".to_string(),
            ));
        }
    }
    if before.len() != after.len() || before.modified()? != after.modified()? {
        return Err(ProcessExitWitnessError::Invalid(
            "process exit witness changed during read".to_string(),
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

    fn release() -> ReleaseId {
        ReleaseId::parse("release-a").expect("release")
    }

    fn identity(system_id: u64, incarnation: &str) -> ProcessIdentity {
        ProcessIdentity::new(system_id, incarnation).expect("identity")
    }

    #[test]
    fn exact_terminal_observation_is_idempotent_and_consumable() {
        let directory = tempfile::tempdir().expect("tempdir");
        let first = record_process_exit(
            directory.path(),
            &agent(),
            7,
            5,
            &release(),
            &identity(41, "boot-a:41"),
            false,
            Some(9),
        )
        .expect("record");
        let replay = record_process_exit(
            directory.path(),
            &agent(),
            7,
            5,
            &release(),
            &identity(41, "boot-a:41"),
            false,
            Some(9),
        )
        .expect("replay");
        assert_eq!(first, replay);
        let consumed = consume_process_exit_witness(directory.path(), &first.witness_id)
            .expect("consume");
        assert_eq!(consumed.phase, ProcessExitWitnessPhaseV1::Consumed);
        assert_eq!(
            consume_process_exit_witness(directory.path(), &first.witness_id)
                .expect("replayed consume"),
            consumed
        );
    }

    #[test]
    fn pid_reuse_cannot_replace_an_unconsumed_exact_witness() {
        let directory = tempfile::tempdir().expect("tempdir");
        record_process_exit(
            directory.path(),
            &agent(),
            7,
            5,
            &release(),
            &identity(41, "boot-a:41"),
            false,
            None,
        )
        .expect("record");
        assert!(matches!(
            record_process_exit(
                directory.path(),
                &agent(),
                8,
                6,
                &release(),
                &identity(41, "boot-a:99"),
                false,
                None,
            ),
            Err(ProcessExitWitnessError::Unresolved)
        ));
    }

    #[test]
    fn tampering_is_rejected() {
        let directory = tempfile::tempdir().expect("tempdir");
        record_process_exit(
            directory.path(),
            &agent(),
            7,
            5,
            &release(),
            &identity(41, "boot-a:41"),
            true,
            Some(0),
        )
        .expect("record");
        let path = directory.path().join(PROCESS_EXIT_WITNESS_FILE);
        let mut value: serde_json::Value =
            serde_json::from_slice(&std::fs::read(&path).expect("read")).expect("json");
        value["spawn_generation"] = serde_json::json!(9);
        std::fs::write(path, serde_json::to_vec(&value).expect("encode")).expect("write");
        assert!(matches!(
            read_process_exit_witness(directory.path()),
            Err(ProcessExitWitnessError::DigestMismatch)
        ));
    }
}
