//! Fleet-wide mutation coordination and the rebuildable workspace reservation index.
//!
//! The lock is owned by the existing supervisor fleet root. It serializes
//! registry mutations across processes without creating another runtime owner.

use serde::Deserialize;
use serde::Serialize;
use sha2::Digest;
use sha2::Sha256;
use std::collections::BTreeSet;
use std::fs::File;
use std::fs::OpenOptions;
use std::io::ErrorKind;
use std::io::Write;
use std::path::Path;
use std::path::PathBuf;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

use crate::FleetRegistryError;

const REGISTRY_MUTATION_LOCK: &str = ".registry-mutation.lock";
const WORKSPACE_RESERVATIONS_FILE: &str = "workspace-reservations-v1.json";
const WORKSPACE_RESERVATIONS_SCHEMA_VERSION: u32 = 1;
const MAX_WORKSPACE_RESERVATIONS: usize = 4_096;
static RESERVATION_SEQUENCE: AtomicU64 = AtomicU64::new(1);

pub(super) struct RegistryMutationGuard {
    _file: File,
}

impl RegistryMutationGuard {
    pub(super) fn acquire(state_root: &Path) -> Result<Self, FleetRegistryError> {
        let path = state_root.join(REGISTRY_MUTATION_LOCK);
        let file = open_lock_file(&path)?;
        file.lock()?;
        Ok(Self { _file: file })
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct WorkspaceReservationEntryV1 {
    pub(super) agent_id: String,
    pub(super) workspace: PathBuf,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct WorkspaceReservationIndexV1 {
    pub(super) schema_version: u32,
    pub(super) entries: Vec<WorkspaceReservationEntryV1>,
    pub(super) content_sha256: String,
}

pub(super) fn persist_workspace_reservations(
    state_root: &Path,
    reservations: impl IntoIterator<Item = (String, PathBuf)>,
) -> Result<WorkspaceReservationIndexV1, FleetRegistryError> {
    let mut entries = reservations
        .into_iter()
        .map(|(agent_id, workspace)| WorkspaceReservationEntryV1 {
            agent_id,
            workspace,
        })
        .collect::<Vec<_>>();
    entries.sort_unstable_by(|left, right| {
        left.workspace
            .cmp(&right.workspace)
            .then_with(|| left.agent_id.cmp(&right.agent_id))
    });
    validate_entries(&entries)?;
    let content_sha256 = reservation_digest(&entries)?;
    let index = WorkspaceReservationIndexV1 {
        schema_version: WORKSPACE_RESERVATIONS_SCHEMA_VERSION,
        entries,
        content_sha256,
    };
    write_index_atomically(state_root, &index)?;
    Ok(index)
}

pub(super) fn load_workspace_reservations(
    state_root: &Path,
) -> Result<WorkspaceReservationIndexV1, FleetRegistryError> {
    let path = state_root.join(WORKSPACE_RESERVATIONS_FILE);
    let metadata = std::fs::symlink_metadata(&path)?;
    if !metadata.file_type().is_file() || metadata.file_type().is_symlink() {
        return Err(FleetRegistryError::Corrupt(format!(
            "workspace reservation index is not a regular file: {}",
            path.display()
        )));
    }
    let index: WorkspaceReservationIndexV1 =
        serde_json::from_slice(&std::fs::read(&path)?).map_err(|error| {
            FleetRegistryError::Corrupt(format!(
                "decode workspace reservation index {}: {error}",
                path.display()
            ))
        })?;
    if index.schema_version != WORKSPACE_RESERVATIONS_SCHEMA_VERSION {
        return Err(FleetRegistryError::Corrupt(format!(
            "unsupported workspace reservation schema {}",
            index.schema_version
        )));
    }
    validate_entries(&index.entries)?;
    if reservation_digest(&index.entries)? != index.content_sha256 {
        return Err(FleetRegistryError::Corrupt(
            "workspace reservation index digest mismatch".to_string(),
        ));
    }
    Ok(index)
}

fn validate_entries(entries: &[WorkspaceReservationEntryV1]) -> Result<(), FleetRegistryError> {
    if entries.len() > MAX_WORKSPACE_RESERVATIONS {
        return Err(FleetRegistryError::Corrupt(
            "workspace reservation index exceeds its bound".to_string(),
        ));
    }
    let mut identities = BTreeSet::new();
    let mut previous: Option<&WorkspaceReservationEntryV1> = None;
    for entry in entries {
        if entry.agent_id.is_empty()
            || entry.agent_id.len() > 128
            || !entry.workspace.is_absolute()
            || !identities.insert(entry.agent_id.as_str())
        {
            return Err(FleetRegistryError::Corrupt(
                "invalid workspace reservation entry".to_string(),
            ));
        }
        if let Some(previous) = previous {
            if previous.workspace > entry.workspace
                || (previous.workspace == entry.workspace && previous.agent_id >= entry.agent_id)
            {
                return Err(FleetRegistryError::Corrupt(
                    "workspace reservation index is not canonical".to_string(),
                ));
            }
            if entry.workspace.starts_with(&previous.workspace) {
                return Err(FleetRegistryError::Corrupt(
                    "workspace reservation index contains overlapping roots".to_string(),
                ));
            }
        }
        previous = Some(entry);
    }
    Ok(())
}

fn reservation_digest(
    entries: &[WorkspaceReservationEntryV1],
) -> Result<String, FleetRegistryError> {
    let encoded = serde_json::to_vec(&(WORKSPACE_RESERVATIONS_SCHEMA_VERSION, entries)).map_err(
        |error| FleetRegistryError::Invalid(format!("encode workspace reservations: {error}")),
    )?;
    let mut digest = Sha256::new();
    digest.update(b"hepta.runtime.fleet.workspace-reservations.v1\0");
    digest.update(encoded);
    Ok(format!("{:x}", digest.finalize()))
}

fn write_index_atomically(
    state_root: &Path,
    index: &WorkspaceReservationIndexV1,
) -> Result<(), FleetRegistryError> {
    let final_path = state_root.join(WORKSPACE_RESERVATIONS_FILE);
    let temp_path = state_root.join(format!(
        ".workspace-reservations-{}-{}.tmp",
        std::process::id(),
        RESERVATION_SEQUENCE.fetch_add(1, Ordering::Relaxed)
    ));
    let mut encoded = serde_json::to_vec(index).map_err(|error| {
        FleetRegistryError::Invalid(format!("encode workspace reservation index: {error}"))
    })?;
    encoded.push(b'\n');
    let write_result = (|| -> Result<(), FleetRegistryError> {
        let mut file = OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&temp_path)?;
        file.write_all(&encoded)?;
        file.sync_all()?;
        match std::fs::rename(&temp_path, &final_path) {
            Ok(()) => {}
            Err(error)
                if matches!(
                    error.kind(),
                    ErrorKind::AlreadyExists | ErrorKind::PermissionDenied
                ) && final_path.exists() =>
            {
                std::fs::remove_file(&final_path)?;
                std::fs::rename(&temp_path, &final_path)?;
            }
            Err(error) => return Err(error.into()),
        }
        sync_directory(state_root)?;
        Ok(())
    })();
    if write_result.is_err() {
        let _ = std::fs::remove_file(&temp_path);
    }
    write_result
}

#[cfg(unix)]
fn open_lock_file(path: &Path) -> Result<File, FleetRegistryError> {
    use std::os::unix::fs::OpenOptionsExt;
    use std::os::unix::fs::PermissionsExt;

    let file = OpenOptions::new()
        .read(true)
        .write(true)
        .create(true)
        .truncate(false)
        .mode(0o600)
        .open(path)?;
    std::fs::set_permissions(path, std::fs::Permissions::from_mode(0o600))?;
    Ok(file)
}

#[cfg(not(unix))]
fn open_lock_file(path: &Path) -> Result<File, FleetRegistryError> {
    OpenOptions::new()
        .read(true)
        .write(true)
        .create(true)
        .truncate(false)
        .open(path)
        .map_err(Into::into)
}

#[cfg(unix)]
fn sync_directory(path: &Path) -> Result<(), FleetRegistryError> {
    File::open(path)?.sync_all()?;
    Ok(())
}

#[cfg(not(unix))]
fn sync_directory(_path: &Path) -> Result<(), FleetRegistryError> {
    Ok(())
}
