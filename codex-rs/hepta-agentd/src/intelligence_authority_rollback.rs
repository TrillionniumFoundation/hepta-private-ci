//! Durable anti-rollback witness for the signed intelligence authority manifest.
//!
//! The witness is deliberately separate from the authority manifest. Product
//! embeddings must place it in an independently retained host-owned directory;
//! restoring an older Agent home must not restore this file. It stores only the
//! highest admitted authority epoch and the exact signed-manifest digest for
//! that epoch. It owns no authority, owner fact, or capability.

use std::error::Error as StdError;
use std::fmt;
use std::fs::File;
use std::fs::OpenOptions;
use std::io::Read;
use std::io::Write;
use std::path::Path;
use std::path::PathBuf;
use std::str::FromStr;
use std::sync::Mutex;

use codex_hepta_types::Digest32;
use serde::Deserialize;
use serde::Serialize;

const ROLLBACK_SCHEMA_VERSION: u32 = 1;
const MAX_ROLLBACK_RECORD_BYTES: usize = 4 * 1024;

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct RollbackRecordV1 {
    schema_version: u32,
    authority_epoch: u64,
    manifest_digest: String,
}

impl RollbackRecordV1 {
    fn new(authority_epoch: u64, manifest_digest: Digest32) -> Result<Self, IntelligenceAuthorityRollbackErrorV1> {
        if authority_epoch == 0 || manifest_digest.is_zero() {
            return Err(IntelligenceAuthorityRollbackErrorV1::Invalid(
                "authority rollback identity",
            ));
        }
        Ok(Self {
            schema_version: ROLLBACK_SCHEMA_VERSION,
            authority_epoch,
            manifest_digest: manifest_digest.to_string(),
        })
    }

    fn digest(&self) -> Result<Digest32, IntelligenceAuthorityRollbackErrorV1> {
        if self.schema_version != ROLLBACK_SCHEMA_VERSION || self.authority_epoch == 0 {
            return Err(IntelligenceAuthorityRollbackErrorV1::Invalid(
                "authority rollback schema or epoch",
            ));
        }
        let digest = Digest32::from_str(&self.manifest_digest)
            .map_err(|_| IntelligenceAuthorityRollbackErrorV1::Invalid("authority rollback digest"))?;
        if digest.is_zero() {
            return Err(IntelligenceAuthorityRollbackErrorV1::Invalid(
                "authority rollback digest",
            ));
        }
        Ok(digest)
    }
}

#[derive(Debug)]
pub enum IntelligenceAuthorityRollbackErrorV1 {
    Invalid(&'static str),
    Io(String),
    Json(String),
    Locked,
    Rollback {
        observed_epoch: u64,
        required_epoch: u64,
    },
    SameEpochConflict {
        authority_epoch: u64,
    },
    Poisoned,
}

impl fmt::Display for IntelligenceAuthorityRollbackErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}
impl StdError for IntelligenceAuthorityRollbackErrorV1 {}

/// Host-owned durable maximum for the signed authority manifest.
///
/// The lock file is retained for the lifetime of this object. A second process
/// cannot independently advance the same witness. The state update is
/// temp-file -> fsync -> rename -> parent-directory fsync before the in-memory
/// maximum changes.
pub struct IntelligenceAuthorityRollbackGuardV1 {
    path: PathBuf,
    _lock: File,
    state: Mutex<RollbackRecordV1>,
}

impl IntelligenceAuthorityRollbackGuardV1 {
    pub fn open(
        path: &Path,
        initial_authority_epoch: u64,
        initial_manifest_digest: Digest32,
    ) -> Result<Self, IntelligenceAuthorityRollbackErrorV1> {
        if !path.is_absolute() {
            return Err(IntelligenceAuthorityRollbackErrorV1::Invalid(
                "authority rollback path must be absolute",
            ));
        }
        let parent = path.parent().ok_or(IntelligenceAuthorityRollbackErrorV1::Invalid(
            "authority rollback parent",
        ))?;
        ensure_private_directory(parent)?;

        let lock_path = path.with_extension("lock");
        let mut lock_options = OpenOptions::new();
        lock_options.read(true).write(true).create(true);
        #[cfg(unix)]
        {
            use std::os::unix::fs::OpenOptionsExt;
            lock_options.mode(0o600);
        }
        let lock = lock_options
            .open(&lock_path)
            .map_err(|error| IntelligenceAuthorityRollbackErrorV1::Io(error.to_string()))?;
        lock.try_lock()
            .map_err(|_| IntelligenceAuthorityRollbackErrorV1::Locked)?;

        let initial = RollbackRecordV1::new(initial_authority_epoch, initial_manifest_digest)?;
        let state = if path.exists() {
            let current = read_record(path)?;
            let current_digest = current.digest()?;
            if current.authority_epoch < initial.authority_epoch {
                persist_record(path, &initial)?;
                initial
            } else if current.authority_epoch == initial.authority_epoch
                && current_digest != initial_manifest_digest
            {
                return Err(IntelligenceAuthorityRollbackErrorV1::SameEpochConflict {
                    authority_epoch: current.authority_epoch,
                });
            } else {
                current
            }
        } else {
            persist_record(path, &initial)?;
            initial
        };

        Ok(Self {
            path: path.to_path_buf(),
            _lock: lock,
            state: Mutex::new(state),
        })
    }

    /// Admit one already signature-verified manifest and durably advance the
    /// monotonic witness when its authority epoch is newer.
    pub fn admit(
        &self,
        authority_epoch: u64,
        manifest_digest: Digest32,
    ) -> Result<(), IntelligenceAuthorityRollbackErrorV1> {
        let candidate = RollbackRecordV1::new(authority_epoch, manifest_digest)?;
        let mut current = self
            .state
            .lock()
            .map_err(|_| IntelligenceAuthorityRollbackErrorV1::Poisoned)?;
        let current_digest = current.digest()?;
        if authority_epoch < current.authority_epoch {
            return Err(IntelligenceAuthorityRollbackErrorV1::Rollback {
                observed_epoch: authority_epoch,
                required_epoch: current.authority_epoch,
            });
        }
        if authority_epoch == current.authority_epoch {
            if manifest_digest != current_digest {
                return Err(IntelligenceAuthorityRollbackErrorV1::SameEpochConflict {
                    authority_epoch,
                });
            }
            return Ok(());
        }
        persist_record(&self.path, &candidate)?;
        *current = candidate;
        Ok(())
    }

    #[must_use]
    pub fn profile_digest(&self) -> Digest32 {
        let mut bytes = b"hepta.agentd.intelligence-authority-rollback-profile.v1\0".to_vec();
        bytes.extend_from_slice(self.path.to_string_lossy().as_bytes());
        Digest32::of_bytes(&bytes)
    }

    pub fn current(
        &self,
    ) -> Result<(u64, Digest32), IntelligenceAuthorityRollbackErrorV1> {
        let current = self
            .state
            .lock()
            .map_err(|_| IntelligenceAuthorityRollbackErrorV1::Poisoned)?;
        Ok((current.authority_epoch, current.digest()?))
    }
}

fn read_record(path: &Path) -> Result<RollbackRecordV1, IntelligenceAuthorityRollbackErrorV1> {
    let path_metadata = std::fs::symlink_metadata(path)
        .map_err(|error| IntelligenceAuthorityRollbackErrorV1::Io(error.to_string()))?;
    if path_metadata.file_type().is_symlink() || !path_metadata.is_file() {
        return Err(IntelligenceAuthorityRollbackErrorV1::Invalid(
            "authority rollback file",
        ));
    }
    let file = OpenOptions::new()
        .read(true)
        .open(path)
        .map_err(|error| IntelligenceAuthorityRollbackErrorV1::Io(error.to_string()))?;
    let opened_metadata = file
        .metadata()
        .map_err(|error| IntelligenceAuthorityRollbackErrorV1::Io(error.to_string()))?;
    if opened_metadata.len() == 0 || opened_metadata.len() > MAX_ROLLBACK_RECORD_BYTES as u64 {
        return Err(IntelligenceAuthorityRollbackErrorV1::Invalid(
            "authority rollback file size",
        ));
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::MetadataExt;
        use std::os::unix::fs::PermissionsExt;
        if path_metadata.dev() != opened_metadata.dev()
            || path_metadata.ino() != opened_metadata.ino()
            || opened_metadata.permissions().mode() & 0o022 != 0
        {
            return Err(IntelligenceAuthorityRollbackErrorV1::Invalid(
                "authority rollback replacement or permissions",
            ));
        }
    }
    let mut bytes = Vec::with_capacity(
        usize::try_from(opened_metadata.len()).unwrap_or(MAX_ROLLBACK_RECORD_BYTES),
    );
    file.take((MAX_ROLLBACK_RECORD_BYTES + 1) as u64)
        .read_to_end(&mut bytes)
        .map_err(|error| IntelligenceAuthorityRollbackErrorV1::Io(error.to_string()))?;
    if bytes.is_empty() || bytes.len() > MAX_ROLLBACK_RECORD_BYTES {
        return Err(IntelligenceAuthorityRollbackErrorV1::Invalid(
            "authority rollback file size",
        ));
    }
    serde_json::from_slice(&bytes)
        .map_err(|error| IntelligenceAuthorityRollbackErrorV1::Json(error.to_string()))
}

fn persist_record(
    path: &Path,
    record: &RollbackRecordV1,
) -> Result<(), IntelligenceAuthorityRollbackErrorV1> {
    let parent = path.parent().ok_or(IntelligenceAuthorityRollbackErrorV1::Invalid(
        "authority rollback parent",
    ))?;
    let bytes = serde_json::to_vec(record)
        .map_err(|error| IntelligenceAuthorityRollbackErrorV1::Json(error.to_string()))?;
    if bytes.is_empty() || bytes.len() > MAX_ROLLBACK_RECORD_BYTES {
        return Err(IntelligenceAuthorityRollbackErrorV1::Invalid(
            "authority rollback encoded size",
        ));
    }
    let temporary = parent.join(format!(
        ".{}.tmp-{}",
        path.file_name()
            .and_then(|name| name.to_str())
            .ok_or(IntelligenceAuthorityRollbackErrorV1::Invalid(
                "authority rollback file name",
            ))?,
        std::process::id()
    ));
    let mut options = OpenOptions::new();
    options.write(true).create_new(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.mode(0o600);
    }
    let mut file = options
        .open(&temporary)
        .map_err(|error| IntelligenceAuthorityRollbackErrorV1::Io(error.to_string()))?;
    file.write_all(&bytes)
        .and_then(|_| file.sync_all())
        .map_err(|error| IntelligenceAuthorityRollbackErrorV1::Io(error.to_string()))?;
    std::fs::rename(&temporary, path)
        .map_err(|error| IntelligenceAuthorityRollbackErrorV1::Io(error.to_string()))?;
    sync_directory(parent)
}

fn ensure_private_directory(path: &Path) -> Result<(), IntelligenceAuthorityRollbackErrorV1> {
    std::fs::create_dir_all(path)
        .map_err(|error| IntelligenceAuthorityRollbackErrorV1::Io(error.to_string()))?;
    let metadata = std::fs::symlink_metadata(path)
        .map_err(|error| IntelligenceAuthorityRollbackErrorV1::Io(error.to_string()))?;
    if metadata.file_type().is_symlink() || !metadata.is_dir() {
        return Err(IntelligenceAuthorityRollbackErrorV1::Invalid(
            "authority rollback directory",
        ));
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        let mut permissions = metadata.permissions();
        permissions.set_mode(0o700);
        std::fs::set_permissions(path, permissions)
            .map_err(|error| IntelligenceAuthorityRollbackErrorV1::Io(error.to_string()))?;
    }
    sync_directory(path)
}

fn sync_directory(path: &Path) -> Result<(), IntelligenceAuthorityRollbackErrorV1> {
    File::open(path)
        .and_then(|file| file.sync_all())
        .map_err(|error| IntelligenceAuthorityRollbackErrorV1::Io(error.to_string()))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn guard_rejects_rollback_and_same_epoch_drift_and_survives_reopen() {
        let temp = tempfile::tempdir().expect("tempdir");
        let root = temp.path().canonicalize().expect("canonical tempdir");
        let path = root.join("rollback.json");
        let first = Digest32::of_bytes(b"manifest:first");
        let second = Digest32::of_bytes(b"manifest:second");
        {
            let guard = IntelligenceAuthorityRollbackGuardV1::open(&path, 7, first)
                .expect("open guard");
            guard.admit(7, first).expect("idempotent current");
            assert!(matches!(
                guard.admit(6, first),
                Err(IntelligenceAuthorityRollbackErrorV1::Rollback { .. })
            ));
            assert!(matches!(
                guard.admit(7, second),
                Err(IntelligenceAuthorityRollbackErrorV1::SameEpochConflict { .. })
            ));
            guard.admit(8, second).expect("advance epoch");
        }
        let reopened = IntelligenceAuthorityRollbackGuardV1::open(&path, 7, first)
            .expect("reopen newer guard");
        assert_eq!(reopened.current().expect("current"), (8, second));
        assert!(matches!(
            reopened.admit(7, first),
            Err(IntelligenceAuthorityRollbackErrorV1::Rollback { .. })
        ));
    }
}
