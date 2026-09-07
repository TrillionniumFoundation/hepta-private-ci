//! Fail-closed admission for recovery of existing SQLite evidence.
//!
//! A normal SQLite filename, including a descriptor pseudo-path, does not bind
//! SQLite's WAL and shared-memory opens to the same retained filesystem objects.
//! A pool can also reconnect after the caller inspected a different object.
//! Until the state crate has a qualified descriptor-backed VFS and one
//! non-reconnecting connection, this module validates and retains the complete
//! local file identity but deliberately returns `Unavailable` before SQLite is
//! opened.

use crate::SqliteConfig;
use sqlx::SqlitePool;
use std::fmt;
use std::path::Path;
use std::path::PathBuf;
use std::sync::Arc;

#[cfg(unix)]
use std::ffi::CString;
#[cfg(unix)]
use std::ffi::OsStr;
#[cfg(unix)]
use std::fs::File;
#[cfg(unix)]
use std::fs::Metadata;
#[cfg(unix)]
use std::fs::OpenOptions;
#[cfg(unix)]
use std::os::fd::AsRawFd;
#[cfg(unix)]
use std::os::fd::FromRawFd;
#[cfg(unix)]
use std::os::unix::ffi::OsStrExt;
#[cfg(unix)]
use std::os::unix::fs::MetadataExt;
#[cfg(unix)]
use std::os::unix::fs::OpenOptionsExt;

/// A stable, fail-closed result from SQLite recovery admission.
///
/// `Unavailable` means the input identities were validated but this build has
/// no safe connection mechanism. `Indeterminate` means the identities could
/// not be established or changed while they were retained. Neither result
/// grants read or write access.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
#[non_exhaustive]
pub enum SqliteRecoveryError {
    Unavailable,
    Indeterminate,
}

impl fmt::Display for SqliteRecoveryError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Unavailable => formatter.write_str(
                "SQLite recovery is unavailable: a descriptor-backed, single-connection VFS is required",
            ),
            Self::Indeterminate => formatter.write_str(
                "SQLite recovery is indeterminate: the complete immutable file identity was not established",
            ),
        }
    }
}

impl std::error::Error for SqliteRecoveryError {}

/// Retained, read-only filesystem identities for one recovery attempt.
///
/// This is not a recovery capability. It cannot be converted into a SQLite
/// connection by this module. Clones share the same descriptors rather than
/// reopening any path.
#[derive(Clone, Debug)]
pub struct ExistingSqliteRecoveryGuard {
    inner: Arc<RecoveryGuardInner>,
}

#[derive(Debug)]
struct RecoveryGuardInner {
    database_path: PathBuf,
    #[cfg(unix)]
    parent: RetainedObject,
    #[cfg(unix)]
    database: RetainedObject,
    #[cfg(unix)]
    sidecars: [RetainedOptionalObject; 3],
}

impl SqliteConfig {
    /// Retain the parent, database, WAL, SHM, and rollback-journal identities.
    ///
    /// Opening descriptors is read-only and uses `O_NOFOLLOW`; this operation
    /// never creates, truncates, renames, chmods, checkpoints, or opens SQLite.
    pub fn bind_existing_recovery_database(
        &self,
        path: &Path,
    ) -> Result<ExistingSqliteRecoveryGuard, SqliteRecoveryError> {
        if path.parent() != Some(self.home()) {
            return Err(SqliteRecoveryError::Indeterminate);
        }
        ExistingSqliteRecoveryGuard::bind(path)
    }

    /// Fail closed instead of returning a reconnect-capable inspection pool.
    pub async fn open_immutable_recovery_pool(
        &self,
        guard: &ExistingSqliteRecoveryGuard,
    ) -> Result<SqlitePool, SqliteRecoveryError> {
        guard.revalidate_for(self)?;
        Err(SqliteRecoveryError::Unavailable)
    }

    /// Fail closed instead of opening a path-based recovery writer.
    ///
    /// A positive implementation must use the retained database and sidecar
    /// descriptors through a qualified VFS, enforce a current writer fence,
    /// and disable implicit reconnect before this can return a pool.
    pub async fn open_identity_bound_durable_evidence_pool(
        &self,
        guard: ExistingSqliteRecoveryGuard,
    ) -> Result<SqlitePool, SqliteRecoveryError> {
        guard.revalidate_for(self)?;
        Err(SqliteRecoveryError::Unavailable)
    }
}

impl ExistingSqliteRecoveryGuard {
    #[cfg(unix)]
    fn bind(database_path: &Path) -> Result<Self, SqliteRecoveryError> {
        let parent_path = database_path
            .parent()
            .ok_or(SqliteRecoveryError::Indeterminate)?;
        let canonical_parent = parent_path.canonicalize().map_err(indeterminate)?;
        if canonical_parent != parent_path {
            return Err(SqliteRecoveryError::Indeterminate);
        }

        let parent = RetainedObject::bind_parent(parent_path)?;
        let database_name = database_path
            .file_name()
            .ok_or(SqliteRecoveryError::Indeterminate)?;
        let database = RetainedObject::bind_file(&parent.descriptor, database_path, database_name)?;
        let sidecars = [
            RetainedOptionalObject::bind(
                &parent.descriptor,
                sqlite_sidecar_path(database_path, "-wal"),
            )?,
            RetainedOptionalObject::bind(
                &parent.descriptor,
                sqlite_sidecar_path(database_path, "-shm"),
            )?,
            RetainedOptionalObject::bind(
                &parent.descriptor,
                sqlite_sidecar_path(database_path, "-journal"),
            )?,
        ];
        let guard = Self {
            inner: Arc::new(RecoveryGuardInner {
                database_path: database_path.to_path_buf(),
                parent,
                database,
                sidecars,
            }),
        };
        guard.revalidate()?;
        Ok(guard)
    }

    #[cfg(not(unix))]
    fn bind(database_path: &Path) -> Result<Self, SqliteRecoveryError> {
        let _ = database_path;
        Err(SqliteRecoveryError::Indeterminate)
    }

    /// Revalidate that no bound path, identity, size, timestamp, link count, or
    /// permission mode changed. No SQLite inspection is performed in this
    /// fail-closed implementation.
    pub fn verify_inspection_unchanged(&self) -> Result<(), SqliteRecoveryError> {
        self.revalidate()
    }

    fn revalidate_for(&self, config: &SqliteConfig) -> Result<(), SqliteRecoveryError> {
        if self.inner.database_path.parent() != Some(config.home()) {
            return Err(SqliteRecoveryError::Indeterminate);
        }
        self.revalidate()
    }

    #[cfg(unix)]
    fn revalidate(&self) -> Result<(), SqliteRecoveryError> {
        self.inner.parent.revalidate()?;
        self.inner.database.revalidate()?;
        for sidecar in &self.inner.sidecars {
            sidecar.revalidate()?;
        }
        Ok(())
    }

    #[cfg(not(unix))]
    fn revalidate(&self) -> Result<(), SqliteRecoveryError> {
        Err(SqliteRecoveryError::Indeterminate)
    }
}

#[cfg(unix)]
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum ObjectKind {
    PrivateDirectory,
    PrivateFile,
}

#[cfg(unix)]
#[derive(Debug)]
struct RetainedObject {
    path: PathBuf,
    kind: ObjectKind,
    snapshot: FileSnapshot,
    descriptor: File,
}

#[cfg(unix)]
impl RetainedObject {
    fn bind_parent(path: &Path) -> Result<Self, SqliteRecoveryError> {
        let before = std::fs::symlink_metadata(path).map_err(indeterminate)?;
        let snapshot = FileSnapshot::validated(&before, ObjectKind::PrivateDirectory)?;
        let descriptor = OpenOptions::new()
            .read(true)
            .custom_flags(libc::O_CLOEXEC | libc::O_DIRECTORY | libc::O_NOFOLLOW | libc::O_NONBLOCK)
            .open(path)
            .map_err(indeterminate)?;
        let opened = FileSnapshot::validated(
            &descriptor.metadata().map_err(indeterminate)?,
            ObjectKind::PrivateDirectory,
        )?;
        if opened != snapshot {
            return Err(SqliteRecoveryError::Indeterminate);
        }
        Ok(Self {
            path: path.to_path_buf(),
            kind: ObjectKind::PrivateDirectory,
            snapshot,
            descriptor,
        })
    }

    fn bind_file(
        parent: &File,
        path: &Path,
        file_name: &OsStr,
    ) -> Result<Self, SqliteRecoveryError> {
        let before = std::fs::symlink_metadata(path).map_err(indeterminate)?;
        let snapshot = FileSnapshot::validated(&before, ObjectKind::PrivateFile)?;
        let descriptor = openat_read_only(parent, file_name)?;
        let opened = FileSnapshot::validated(
            &descriptor.metadata().map_err(indeterminate)?,
            ObjectKind::PrivateFile,
        )?;
        if opened != snapshot {
            return Err(SqliteRecoveryError::Indeterminate);
        }
        Ok(Self {
            path: path.to_path_buf(),
            kind: ObjectKind::PrivateFile,
            snapshot,
            descriptor,
        })
    }

    fn revalidate(&self) -> Result<(), SqliteRecoveryError> {
        let path_snapshot = FileSnapshot::validated(
            &std::fs::symlink_metadata(&self.path).map_err(indeterminate)?,
            self.kind,
        )?;
        let descriptor_snapshot = FileSnapshot::validated(
            &self.descriptor.metadata().map_err(indeterminate)?,
            self.kind,
        )?;
        if path_snapshot != self.snapshot || descriptor_snapshot != self.snapshot {
            return Err(SqliteRecoveryError::Indeterminate);
        }
        Ok(())
    }
}

#[cfg(unix)]
#[derive(Debug)]
enum RetainedOptionalObject {
    Absent(PathBuf),
    Present(RetainedObject),
}

#[cfg(unix)]
impl RetainedOptionalObject {
    fn bind(parent: &File, path: PathBuf) -> Result<Self, SqliteRecoveryError> {
        match std::fs::symlink_metadata(&path) {
            Ok(_) => {
                let file_name = path.file_name().ok_or(SqliteRecoveryError::Indeterminate)?;
                RetainedObject::bind_file(parent, &path, file_name).map(Self::Present)
            }
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(Self::Absent(path)),
            Err(_) => Err(SqliteRecoveryError::Indeterminate),
        }
    }

    fn revalidate(&self) -> Result<(), SqliteRecoveryError> {
        match self {
            Self::Absent(path) => match std::fs::symlink_metadata(path) {
                Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(()),
                Ok(_) | Err(_) => Err(SqliteRecoveryError::Indeterminate),
            },
            Self::Present(object) => object.revalidate(),
        }
    }
}

#[cfg(unix)]
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
struct FileSnapshot {
    device: u64,
    inode: u64,
    mode: u32,
    owner: u32,
    links: u64,
    length: u64,
    modified_seconds: i64,
    modified_nanoseconds: i64,
    changed_seconds: i64,
    changed_nanoseconds: i64,
}

#[cfg(unix)]
impl FileSnapshot {
    fn validated(metadata: &Metadata, kind: ObjectKind) -> Result<Self, SqliteRecoveryError> {
        let mode = metadata.mode() & 0o7777;
        // SAFETY: `geteuid` has no preconditions and does not dereference memory.
        let effective_user = unsafe { libc::geteuid() };
        let valid = match kind {
            ObjectKind::PrivateDirectory => {
                metadata.is_dir()
                    && !metadata.file_type().is_symlink()
                    && metadata.uid() == effective_user
                    && mode == 0o700
            }
            ObjectKind::PrivateFile => {
                metadata.is_file()
                    && !metadata.file_type().is_symlink()
                    && metadata.uid() == effective_user
                    && mode == 0o600
                    && metadata.nlink() == 1
            }
        };
        if !valid {
            return Err(SqliteRecoveryError::Indeterminate);
        }
        Ok(Self {
            device: metadata.dev(),
            inode: metadata.ino(),
            mode: metadata.mode(),
            owner: metadata.uid(),
            links: metadata.nlink(),
            length: metadata.len(),
            modified_seconds: metadata.mtime(),
            modified_nanoseconds: metadata.mtime_nsec(),
            changed_seconds: metadata.ctime(),
            changed_nanoseconds: metadata.ctime_nsec(),
        })
    }
}

#[cfg(unix)]
fn openat_read_only(parent: &File, file_name: &OsStr) -> Result<File, SqliteRecoveryError> {
    let file_name =
        CString::new(file_name.as_bytes()).map_err(|_| SqliteRecoveryError::Indeterminate)?;
    // SAFETY: the retained parent descriptor and NUL-terminated name are valid
    // for this call. The returned descriptor is checked before it is wrapped.
    let descriptor = unsafe {
        libc::openat(
            parent.as_raw_fd(),
            file_name.as_ptr(),
            libc::O_RDONLY | libc::O_CLOEXEC | libc::O_NOFOLLOW | libc::O_NONBLOCK,
        )
    };
    if descriptor < 0 {
        return Err(SqliteRecoveryError::Indeterminate);
    }
    // SAFETY: `openat` returned a new owned descriptor, transferred exactly
    // once to `File` here.
    Ok(unsafe { File::from_raw_fd(descriptor) })
}

#[cfg(unix)]
fn sqlite_sidecar_path(database_path: &Path, suffix: &str) -> PathBuf {
    let mut path = database_path.as_os_str().to_os_string();
    path.push(suffix);
    PathBuf::from(path)
}

#[cfg(unix)]
fn indeterminate(_: std::io::Error) -> SqliteRecoveryError {
    SqliteRecoveryError::Indeterminate
}

#[cfg(all(test, unix))]
#[path = "sqlite_recovery_tests.rs"]
mod tests;
