#[cfg(unix)]
use std::fs::File;
use std::fs::OpenOptions;
use std::io::ErrorKind;
use std::io::Write;
use std::path::Path;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_fleet::AgentLifecycle;
use codex_hepta_fleet::ReleaseId;
use serde::Deserialize;
use serde::Serialize;

use crate::ProcessIdentity;
use crate::SupervisorError;

pub(crate) const PROCESS_LEASE_SCHEMA_VERSION: u32 = 2;
pub(crate) const MATRIX_PROCESS_LEASE_SCHEMA_VERSION: u32 = 2;
const PROCESS_LEASE_FILE: &str = "supervisor-process.json";
const MAX_LEASE_BYTES: u64 = 4_096;
static LEASE_SEQUENCE: AtomicU64 = AtomicU64::new(1);

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct ProcessLease {
    pub schema_version: u32,
    pub agent_id: AgentId,
    pub spawn_generation: u64,
    pub release_id: ReleaseId,
    pub identity: ProcessIdentity,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct MatrixProcessLease {
    pub schema_version: u32,
    pub agent_id: AgentId,
    pub attached_agent_generation: u64,
    pub release_id: ReleaseId,
    pub binding_revision: u64,
    pub binding_digest: Sha256Digest,
    pub process_incarnation: String,
    pub plane_epoch: u64,
    pub identity: ProcessIdentity,
}

pub(crate) fn validate_lease(
    lease: &ProcessLease,
    agent_id: &AgentId,
    registry_generation: u64,
    lifecycle: AgentLifecycle,
) -> Result<(), SupervisorError> {
    let distance = registry_generation.checked_sub(lease.spawn_generation);
    let generation_matches = match lifecycle {
        AgentLifecycle::Starting => distance == Some(0),
        AgentLifecycle::Running => distance == Some(1),
        AgentLifecycle::Draining => distance == Some(2),
        AgentLifecycle::Failed => matches!(distance, Some(1..=3)),
        AgentLifecycle::Stopped => matches!(distance, Some(0..=4)),
    };
    if lease.schema_version != PROCESS_LEASE_SCHEMA_VERSION
        || &lease.agent_id != agent_id
        || !generation_matches
    {
        return Err(SupervisorError::CorruptLease(format!(
            "lease does not match agent {agent_id} generation {registry_generation}"
        )));
    }
    Ok(())
}

pub(crate) fn read_lease(run_root: &Path) -> Result<Option<ProcessLease>, SupervisorError> {
    let path = lease_path(run_root);
    let metadata = match std::fs::symlink_metadata(&path) {
        Ok(metadata) => metadata,
        Err(error) if error.kind() == ErrorKind::NotFound => return Ok(None),
        Err(error) => return Err(error.into()),
    };
    if !metadata.file_type().is_file() || metadata.file_type().is_symlink() {
        return Err(SupervisorError::CorruptLease(format!(
            "lease path is not a regular file: {}",
            path.display()
        )));
    }
    if metadata.len() > MAX_LEASE_BYTES {
        return Err(SupervisorError::CorruptLease(
            "process lease exceeds the bounded control-state limit".to_string(),
        ));
    }
    serde_json::from_slice(&std::fs::read(path)?)
        .map(Some)
        .map_err(|error| SupervisorError::CorruptLease(error.to_string()))
}

pub(crate) fn write_lease(run_root: &Path, lease: &ProcessLease) -> Result<(), SupervisorError> {
    let final_path = lease_path(run_root);
    if final_path.exists() {
        return Err(SupervisorError::UnresolvedLease(lease.agent_id.clone()));
    }
    let temp_path = run_root.join(format!(
        ".supervisor-process-{}-{}.tmp",
        std::process::id(),
        LEASE_SEQUENCE.fetch_add(1, Ordering::Relaxed)
    ));
    let mut bytes = serde_json::to_vec(lease)
        .map_err(|error| SupervisorError::CorruptLease(error.to_string()))?;
    bytes.push(b'\n');
    let mut file = OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(&temp_path)?;
    file.write_all(&bytes)?;
    file.sync_all()?;
    match std::fs::hard_link(&temp_path, &final_path) {
        Ok(()) => {}
        Err(error) if error.kind() == ErrorKind::AlreadyExists => {
            let _ = std::fs::remove_file(&temp_path);
            return Err(SupervisorError::UnresolvedLease(lease.agent_id.clone()));
        }
        Err(error) => {
            let _ = std::fs::remove_file(&temp_path);
            return Err(error.into());
        }
    }
    let _ = std::fs::remove_file(temp_path);
    sync_directory(run_root)
}

pub(crate) fn remove_lease(
    run_root: &Path,
    expected: &ProcessLease,
) -> Result<(), SupervisorError> {
    let actual = read_lease(run_root)?.ok_or_else(|| {
        SupervisorError::CorruptLease("active process lease is missing".to_string())
    })?;
    if &actual != expected {
        return Err(SupervisorError::CorruptLease(
            "active process lease identity changed".to_string(),
        ));
    }
    std::fs::remove_file(lease_path(run_root))?;
    sync_directory(run_root)
}

fn lease_path(run_root: &Path) -> std::path::PathBuf {
    run_root.join(PROCESS_LEASE_FILE)
}

pub(crate) fn read_matrix_lease(
    path: &Path,
) -> Result<Option<MatrixProcessLease>, SupervisorError> {
    let metadata = match std::fs::symlink_metadata(path) {
        Ok(metadata) => metadata,
        Err(error) if error.kind() == ErrorKind::NotFound => return Ok(None),
        Err(error) => return Err(error.into()),
    };
    if !metadata.file_type().is_file() || metadata.file_type().is_symlink() {
        return Err(SupervisorError::CorruptLease(format!(
            "Matrix lease path is not a regular file: {}",
            path.display()
        )));
    }
    if metadata.len() > MAX_LEASE_BYTES {
        return Err(SupervisorError::CorruptLease(
            "Matrix process lease exceeds the bounded control-state limit".to_string(),
        ));
    }
    let lease: MatrixProcessLease = serde_json::from_slice(&std::fs::read(path)?)
        .map_err(|error| SupervisorError::CorruptLease(error.to_string()))?;
    if lease.schema_version != MATRIX_PROCESS_LEASE_SCHEMA_VERSION
        || lease.attached_agent_generation == 0
        || lease.binding_revision == 0
        || lease.plane_epoch == 0
        || lease.process_incarnation.is_empty()
        || lease.process_incarnation.len() > 512
    {
        return Err(SupervisorError::CorruptLease(
            "Matrix process lease has invalid bounded identity fields".to_string(),
        ));
    }
    Ok(Some(lease))
}

pub(crate) fn write_matrix_lease(
    path: &Path,
    lease: &MatrixProcessLease,
) -> Result<(), SupervisorError> {
    if path.exists() {
        return Err(SupervisorError::UnresolvedLease(lease.agent_id.clone()));
    }
    let parent = path.parent().ok_or_else(|| {
        SupervisorError::CorruptLease("Matrix lease path has no parent".to_string())
    })?;
    let temp_path = parent.join(format!(
        ".supervisor-matrix-process-{}-{}.tmp",
        std::process::id(),
        LEASE_SEQUENCE.fetch_add(1, Ordering::Relaxed)
    ));
    let mut bytes = serde_json::to_vec(lease)
        .map_err(|error| SupervisorError::CorruptLease(error.to_string()))?;
    bytes.push(b'\n');
    let mut file = OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(&temp_path)?;
    file.write_all(&bytes)?;
    file.sync_all()?;
    match std::fs::hard_link(&temp_path, path) {
        Ok(()) => {}
        Err(error) if error.kind() == ErrorKind::AlreadyExists => {
            let _ = std::fs::remove_file(&temp_path);
            return Err(SupervisorError::UnresolvedLease(lease.agent_id.clone()));
        }
        Err(error) => {
            let _ = std::fs::remove_file(&temp_path);
            return Err(error.into());
        }
    }
    let _ = std::fs::remove_file(temp_path);
    sync_directory(parent)
}

pub(crate) fn remove_matrix_lease(
    path: &Path,
    expected: &MatrixProcessLease,
) -> Result<(), SupervisorError> {
    let actual = read_matrix_lease(path)?.ok_or_else(|| {
        SupervisorError::CorruptLease("active Matrix process lease is missing".to_string())
    })?;
    if &actual != expected {
        return Err(SupervisorError::CorruptLease(
            "active Matrix process lease identity changed".to_string(),
        ));
    }
    std::fs::remove_file(path)?;
    let parent = path.parent().ok_or_else(|| {
        SupervisorError::CorruptLease("Matrix lease path has no parent".to_string())
    })?;
    sync_directory(parent)
}

#[cfg(unix)]
fn sync_directory(path: &Path) -> Result<(), SupervisorError> {
    File::open(path)?.sync_all()?;
    Ok(())
}

#[cfg(not(unix))]
fn sync_directory(_path: &Path) -> Result<(), SupervisorError> {
    Ok(())
}
