//! Durable anti-rollback witness for the signed intelligence authority manifest.
//!
//! The witness is deliberately separate from the authority manifest. Product
//! embeddings must place it in an independently retained host-owned directory;
//! restoring an older Agent home must not restore this file. It stores only the
//! highest admitted authority epoch and the exact signed-manifest digest for
//! that epoch. It owns no authority, owner fact, or capability.

use std::error::Error as StdError;
use std::ffi::OsString;
use std::fmt;
use std::fs::File;
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
    fn new(
        authority_epoch: u64,
        manifest_digest: Digest32,
    ) -> Result<Self, IntelligenceAuthorityRollbackErrorV1> {
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
        let digest = Digest32::from_str(&self.manifest_digest).map_err(|_| {
            IntelligenceAuthorityRollbackErrorV1::Invalid("authority rollback digest")
        })?;
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
    directory: File,
    name: OsString,
    state: Mutex<RollbackRecordV1>,
    unavailable: std::sync::atomic::AtomicBool,
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
        let parent = path
            .parent()
            .ok_or(IntelligenceAuthorityRollbackErrorV1::Invalid(
                "authority rollback parent",
            ))?;
        // Provisioning the independently retained private host directory is
        // explicit; never create/chmod through attacker-replaceable ancestors.
        let directory = open_private_directory(parent)?;
        let name = path
            .file_name()
            .ok_or(IntelligenceAuthorityRollbackErrorV1::Invalid("record name"))?
            .to_os_string();
        let mut lock_name = name.clone();
        lock_name.push(".lock");
        let lock = open_lock(&directory, &lock_name)?;
        lock.try_lock()
            .map_err(|_| IntelligenceAuthorityRollbackErrorV1::Locked)?;
        directory.sync_all().map_err(io_error)?;

        let initial = RollbackRecordV1::new(initial_authority_epoch, initial_manifest_digest)?;
        let state = match read_record(&directory, &name)? {
            Some(current) => {
                let current_digest = current.digest()?;
                if current.authority_epoch < initial.authority_epoch {
                    persist_record(&directory, &name, &initial)?;
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
            }
            None => {
                persist_record(&directory, &name, &initial)?;
                initial
            }
        };

        Ok(Self {
            path: path.to_path_buf(),
            _lock: lock,
            directory,
            name,
            state: Mutex::new(state),
            unavailable: std::sync::atomic::AtomicBool::new(false),
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
        if self.unavailable.load(std::sync::atomic::Ordering::Acquire) {
            return Err(IntelligenceAuthorityRollbackErrorV1::Poisoned);
        }
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
        if let Err(error) = persist_record(&self.directory, &self.name, &candidate) {
            // Rename may have happened before directory fsync failed. No later
            // call may accept the old in-memory epoch until authoritative reopen.
            self.unavailable
                .store(true, std::sync::atomic::Ordering::Release);
            return Err(error);
        }
        *current = candidate;
        Ok(())
    }

    #[must_use]
    pub fn path(&self) -> &Path {
        &self.path
    }

    #[must_use]
    pub fn profile_digest(&self) -> Digest32 {
        let mut bytes = b"hepta.agentd.intelligence-authority-rollback-profile.v1\0".to_vec();
        bytes.extend_from_slice(self.path.to_string_lossy().as_bytes());
        Digest32::of_bytes(&bytes)
    }

    pub fn current(&self) -> Result<(u64, Digest32), IntelligenceAuthorityRollbackErrorV1> {
        let current = self
            .state
            .lock()
            .map_err(|_| IntelligenceAuthorityRollbackErrorV1::Poisoned)?;
        if self.unavailable.load(std::sync::atomic::Ordering::Acquire) {
            return Err(IntelligenceAuthorityRollbackErrorV1::Poisoned);
        }
        Ok((current.authority_epoch, current.digest()?))
    }
}

fn io_error(error: std::io::Error) -> IntelligenceAuthorityRollbackErrorV1 {
    IntelligenceAuthorityRollbackErrorV1::Io(error.to_string())
}

#[cfg(unix)]
fn open_private_directory(path: &Path) -> Result<File, IntelligenceAuthorityRollbackErrorV1> {
    use std::os::unix::fs::PermissionsExt;
    let directory = crate::intelligence_files::open_directory_no_follow(path).map_err(io_error)?;
    if directory.metadata().map_err(io_error)?.permissions().mode() & 0o077 != 0 {
        return Err(IntelligenceAuthorityRollbackErrorV1::Invalid(
            "host rollback directory must be private",
        ));
    }
    Ok(directory)
}

#[cfg(not(unix))]
fn open_private_directory(_path: &Path) -> Result<File, IntelligenceAuthorityRollbackErrorV1> {
    Err(IntelligenceAuthorityRollbackErrorV1::Invalid(
        "anchored rollback profile unavailable",
    ))
}

#[cfg(unix)]
fn open_lock(
    directory: &File,
    name: &std::ffi::OsStr,
) -> Result<File, IntelligenceAuthorityRollbackErrorV1> {
    use rustix::fs::{Mode, OFlags};
    use std::os::unix::fs::MetadataExt;
    let fd = rustix::fs::openat(
        directory,
        name,
        OFlags::RDWR | OFlags::CREATE | OFlags::NOFOLLOW | OFlags::NONBLOCK | OFlags::CLOEXEC,
        Mode::from_raw_mode(0o600),
    )
    .map_err(|e| io_error(e.into()))?;
    let file = File::from(fd);
    let metadata = file.metadata().map_err(io_error)?;
    if !metadata.is_file() || metadata.nlink() != 1 || metadata.mode() & 0o077 != 0 {
        return Err(IntelligenceAuthorityRollbackErrorV1::Invalid(
            "unsafe rollback lock",
        ));
    }
    Ok(file)
}

#[cfg(not(unix))]
fn open_lock(
    _directory: &File,
    _name: &std::ffi::OsStr,
) -> Result<File, IntelligenceAuthorityRollbackErrorV1> {
    Err(IntelligenceAuthorityRollbackErrorV1::Invalid(
        "anchored rollback profile unavailable",
    ))
}

#[cfg(unix)]
fn read_record(
    directory: &File,
    name: &std::ffi::OsStr,
) -> Result<Option<RollbackRecordV1>, IntelligenceAuthorityRollbackErrorV1> {
    use rustix::fs::{Mode, OFlags};
    let fd = match rustix::fs::openat(
        directory,
        name,
        OFlags::RDONLY | OFlags::NOFOLLOW | OFlags::NONBLOCK | OFlags::CLOEXEC,
        Mode::empty(),
    ) {
        Ok(fd) => fd,
        Err(rustix::io::Errno::NOENT) => return Ok(None),
        Err(error) => return Err(io_error(error.into())),
    };
    let bytes =
        crate::intelligence_files::read_opened_bounded(File::from(fd), MAX_ROLLBACK_RECORD_BYTES)
            .map_err(io_error)?;
    serde_json::from_slice(&bytes)
        .map(Some)
        .map_err(|error| IntelligenceAuthorityRollbackErrorV1::Json(error.to_string()))
}

#[cfg(not(unix))]
fn read_record(
    _directory: &File,
    _name: &std::ffi::OsStr,
) -> Result<Option<RollbackRecordV1>, IntelligenceAuthorityRollbackErrorV1> {
    Err(IntelligenceAuthorityRollbackErrorV1::Invalid(
        "anchored rollback profile unavailable",
    ))
}

#[cfg(unix)]
fn persist_record(
    directory: &File,
    name: &std::ffi::OsStr,
    record: &RollbackRecordV1,
) -> Result<(), IntelligenceAuthorityRollbackErrorV1> {
    use rustix::fs::{AtFlags, Mode, OFlags};
    use std::sync::atomic::{AtomicU64, Ordering};
    static SERIAL: AtomicU64 = AtomicU64::new(0);
    let bytes = serde_json::to_vec(record)
        .map_err(|error| IntelligenceAuthorityRollbackErrorV1::Json(error.to_string()))?;
    if bytes.is_empty() || bytes.len() > MAX_ROLLBACK_RECORD_BYTES {
        return Err(IntelligenceAuthorityRollbackErrorV1::Invalid(
            "rollback record size",
        ));
    }
    let serial = SERIAL.fetch_add(1, Ordering::Relaxed);
    let mut temporary = name.to_os_string();
    temporary.push(format!(".tmp-{}-{serial}", std::process::id()));
    let fd = rustix::fs::openat(
        directory,
        temporary.as_os_str(),
        OFlags::WRONLY | OFlags::CREATE | OFlags::EXCL | OFlags::NOFOLLOW | OFlags::CLOEXEC,
        Mode::from_raw_mode(0o600),
    )
    .map_err(|e| io_error(e.into()))?;
    let mut file = File::from(fd);
    let result = (|| -> Result<(), IntelligenceAuthorityRollbackErrorV1> {
        file.write_all(&bytes)
            .and_then(|_| file.sync_all())
            .map_err(io_error)?;
        rustix::fs::renameat(directory, temporary.as_os_str(), directory, name)
            .map_err(|e| io_error(e.into()))?;
        directory.sync_all().map_err(io_error)
    })();
    if result.is_err() {
        // Only the exact temporary created by this call may be removed.
        let _ = rustix::fs::unlinkat(directory, temporary.as_os_str(), AtFlags::empty());
    }
    result
}

#[cfg(not(unix))]
fn persist_record(
    _directory: &File,
    _name: &std::ffi::OsStr,
    _record: &RollbackRecordV1,
) -> Result<(), IntelligenceAuthorityRollbackErrorV1> {
    Err(IntelligenceAuthorityRollbackErrorV1::Invalid(
        "anchored rollback profile unavailable",
    ))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn guard_rejects_rollback_and_same_epoch_drift_and_survives_reopen() {
        let temp = tempfile::tempdir().expect("tempdir");
        let root = temp.path().canonicalize().expect("canonical tempdir");
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            std::fs::set_permissions(&root, std::fs::Permissions::from_mode(0o700))
                .expect("private root");
        }
        let path = root.join("rollback.json");
        let first = Digest32::of_bytes(b"manifest:first");
        let second = Digest32::of_bytes(b"manifest:second");
        {
            let guard =
                IntelligenceAuthorityRollbackGuardV1::open(&path, 7, first).expect("open guard");
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

#[cfg(all(test, unix))]
mod anchored_tests {
    use super::*;
    use std::os::unix::fs::symlink;

    #[test]
    fn rollback_lock_and_parent_links_fail_without_mutating_target() {
        let temporary = tempfile::tempdir().expect("root");
        let root = temporary.path().canonicalize().expect("canonical root");
        use std::os::unix::fs::PermissionsExt;
        std::fs::set_permissions(&root, std::fs::Permissions::from_mode(0o700))
            .expect("private root");
        let record = root.join("floor.json");
        let target = root.join("unrelated");
        std::fs::write(&target, b"must not change").expect("target");
        symlink(&target, root.join("floor.json.lock")).expect("lock link");
        assert!(
            IntelligenceAuthorityRollbackGuardV1::open(&record, 1, Digest32::of_bytes(b"manifest"))
                .is_err()
        );
        assert_eq!(
            std::fs::read(&target).expect("target bytes"),
            b"must not change"
        );
        std::fs::remove_file(root.join("floor.json.lock")).expect("remove test link");
        let alias = root.join("alias");
        symlink(&root, &alias).expect("parent link");
        assert!(
            IntelligenceAuthorityRollbackGuardV1::open(
                &alias.join("floor.json"),
                1,
                Digest32::of_bytes(b"manifest")
            )
            .is_err()
        );
        assert!(!record.exists());
    }
}
