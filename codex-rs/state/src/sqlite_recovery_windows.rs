//! Windows recovery retains private source handles and never reopens source
//! paths for SQLite. Native share denial pins each source against writes and
//! replacement; complete metadata and security snapshots reject observed drift.

use std::ffi::OsStr;
use std::fs::File;
use std::io::Write;
use std::os::windows::fs::FileExt;
use std::path::Path;
use std::path::PathBuf;

use codex_utils_path::PrivateStateSnapshot;
use codex_utils_path::create_private_recovery_copy;
use codex_utils_path::discard_private_recovery_copy;
use codex_utils_path::open_existing_private_state_directory;
use codex_utils_path::open_existing_private_state_directory_for_sync;
use codex_utils_path::open_private_recovery_source;
use codex_utils_path::private_state_snapshot;

use super::ExistingSqliteRecoveryGuard;
use super::SqliteConfig;
use super::SqliteRecoveryError;
use super::indeterminate;
use super::sqlite_sidecar_path;

// SqliteConfig uses AbsolutePathBuf's ordinary drive/UNC spelling, while OS
// canonical source paths retain their verbatim prefix. Compare only those
// namespace aliases and the exact absolute component sequence. This performs
// no filesystem lookup, case folding, or parent-component resolution; retained
// native handles and their complete snapshots remain the identity authority.
pub(super) fn same_recovery_path(left: &Path, right: &Path) -> bool {
    use std::path::Component;
    use std::path::Prefix;

    let mut left = left.components();
    let mut right = right.components();
    let (Some(Component::Prefix(left_prefix)), Some(Component::Prefix(right_prefix))) =
        (left.next(), right.next())
    else {
        return false;
    };
    let same_prefix = match (left_prefix.kind(), right_prefix.kind()) {
        (
            Prefix::Disk(left) | Prefix::VerbatimDisk(left),
            Prefix::Disk(right) | Prefix::VerbatimDisk(right),
        ) => left == right,
        (
            Prefix::UNC(left_server, left_share) | Prefix::VerbatimUNC(left_server, left_share),
            Prefix::UNC(right_server, right_share) | Prefix::VerbatimUNC(right_server, right_share),
        ) => left_server == right_server && left_share == right_share,
        _ => false,
    };
    same_prefix
        && matches!(
            (left.next(), right.next()),
            (Some(Component::RootDir), Some(Component::RootDir))
        )
        && left.eq(right)
}

#[derive(Debug)]
pub(super) struct RetainedObject {
    path: PathBuf,
    snapshot: PrivateStateSnapshot,
    pub(super) descriptor: File,
}

impl RetainedObject {
    pub(super) fn bind_parent(path: &Path) -> Result<Self, SqliteRecoveryError> {
        let descriptor = open_existing_private_state_directory(path).map_err(indeterminate)?;
        Self::from_descriptor(path.to_path_buf(), descriptor, /*directory*/ true)
    }

    pub(super) fn bind_file(
        parent: &File,
        path: &Path,
        file_name: &OsStr,
    ) -> Result<Self, SqliteRecoveryError> {
        let descriptor = open_private_recovery_source(parent, file_name).map_err(indeterminate)?;
        Self::from_descriptor(path.to_path_buf(), descriptor, /*directory*/ false)
    }

    fn from_descriptor(
        path: PathBuf,
        descriptor: File,
        directory: bool,
    ) -> Result<Self, SqliteRecoveryError> {
        let snapshot = private_state_snapshot(&descriptor).map_err(indeterminate)?;
        if snapshot.is_directory() != directory {
            return Err(SqliteRecoveryError::Indeterminate);
        }
        Ok(Self {
            path,
            snapshot,
            descriptor,
        })
    }

    pub(super) fn revalidate_parent(&self) -> Result<(), SqliteRecoveryError> {
        // This is an identity-only lookup with FILE_OPEN and native no-reparse;
        // no source bytes are read and SQLite never receives this pathname.
        let lookup = open_existing_private_state_directory(&self.path).map_err(indeterminate)?;
        self.compare(&lookup)
    }

    pub(super) fn revalidate_file(&self, parent: &File) -> Result<(), SqliteRecoveryError> {
        let name = self
            .path
            .file_name()
            .ok_or(SqliteRecoveryError::Indeterminate)?;
        let lookup = open_private_recovery_source(parent, name).map_err(indeterminate)?;
        self.compare(&lookup)
    }

    fn compare(&self, lookup: &File) -> Result<(), SqliteRecoveryError> {
        if private_state_snapshot(&self.descriptor).map_err(indeterminate)? != self.snapshot
            || private_state_snapshot(lookup).map_err(indeterminate)? != self.snapshot
        {
            return Err(SqliteRecoveryError::Indeterminate);
        }
        Ok(())
    }
}

#[derive(Debug)]
pub(super) enum RetainedOptionalObject {
    Absent(PathBuf),
    Present(RetainedObject),
}

impl RetainedOptionalObject {
    pub(super) fn bind(parent: &File, path: PathBuf) -> Result<Self, SqliteRecoveryError> {
        let name = path.file_name().ok_or(SqliteRecoveryError::Indeterminate)?;
        match open_private_recovery_source(parent, name) {
            Ok(descriptor) => {
                RetainedObject::from_descriptor(path, descriptor, /*directory*/ false)
                    .map(Self::Present)
            }
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(Self::Absent(path)),
            Err(_) => Err(SqliteRecoveryError::Indeterminate),
        }
    }

    pub(super) fn revalidate(&self, parent: &File) -> Result<(), SqliteRecoveryError> {
        match self {
            Self::Present(object) => object.revalidate_file(parent),
            Self::Absent(path) => {
                let name = path.file_name().ok_or(SqliteRecoveryError::Indeterminate)?;
                match open_private_recovery_source(parent, name) {
                    Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(()),
                    Ok(_) | Err(_) => Err(SqliteRecoveryError::Indeterminate),
                }
            }
        }
    }
}

pub(super) fn retained_bytes(
    object: &RetainedObject,
    maximum: u64,
    allow_empty: bool,
) -> Result<Vec<u8>, SqliteRecoveryError> {
    let size = object.snapshot.len();
    if (!allow_empty && size == 0) || size > maximum {
        return Err(SqliteRecoveryError::Unavailable);
    }
    let size = usize::try_from(size).map_err(|_| SqliteRecoveryError::Unavailable)?;
    let mut bytes = vec![0; size];
    let mut offset = 0;
    while offset < bytes.len() {
        // Explicit offsets keep concurrent immutable readers independent of a
        // File cursor. No source name or descriptor pseudo-path is reopened.
        let count = object
            .descriptor
            .seek_read(&mut bytes[offset..], offset as u64)
            .map_err(indeterminate)?;
        if count == 0 {
            return Err(SqliteRecoveryError::Indeterminate);
        }
        offset += count;
    }
    Ok(bytes)
}

pub(super) fn materialize(
    config: &SqliteConfig,
    guard: &ExistingSqliteRecoveryGuard,
    target: &Path,
) -> Result<(), SqliteRecoveryError> {
    const MAX_DATABASE_BYTES: u64 = 128 * 1024 * 1024;
    const MAX_SIDECAR_BYTES: u64 = 128 * 1024 * 1024;
    const MAX_BUNDLE_BYTES: usize = 256 * 1024 * 1024;
    if !super::recovery_parent_matches(target, config.home())
        || same_recovery_path(target, &guard.inner.database_path)
        || target.file_name().is_none()
    {
        return Err(SqliteRecoveryError::Indeterminate);
    }
    guard.revalidate_for(config)?;
    let database = retained_bytes(
        &guard.inner.database,
        MAX_DATABASE_BYTES,
        /*allow_empty*/ false,
    )?;
    let mut bundle = vec![(target.to_path_buf(), database)];
    let mut total = bundle[0].1.len();
    for (index, suffix) in [(0, "-wal"), (2, "-journal")] {
        // SHM is identity-bound but intentionally not copied; SQLite rebuilds
        // it using only the private database/WAL copy, as on Unix.
        if let RetainedOptionalObject::Present(object) = &guard.inner.sidecars[index] {
            let bytes = retained_bytes(object, MAX_SIDECAR_BYTES, /*allow_empty*/ true)?;
            total = total
                .checked_add(bytes.len())
                .ok_or(SqliteRecoveryError::Unavailable)?;
            if total > MAX_BUNDLE_BYTES {
                return Err(SqliteRecoveryError::Unavailable);
            }
            bundle.push((sqlite_sidecar_path(target, suffix), bytes));
        }
    }
    guard.revalidate_for(config)?;
    let directory =
        open_existing_private_state_directory_for_sync(config.home()).map_err(indeterminate)?;
    guard.inner.parent.compare(&directory)?;
    let mut created = Vec::new();
    let result = (|| {
        for (path, bytes) in bundle {
            let name = path.file_name().ok_or(SqliteRecoveryError::Indeterminate)?;
            let file = create_private_recovery_copy(&directory, name).map_err(indeterminate)?;
            // Record ownership immediately after CREATE_NEW, before any write.
            created.push(file);
            let file = created
                .last_mut()
                .ok_or(SqliteRecoveryError::Indeterminate)?;
            file.write_all(&bytes).map_err(indeterminate)?;
            file.sync_all().map_err(indeterminate)?;
        }
        // A real writable directory handle is required, and failure remains
        // failure. Acquiring a handle alone never acknowledges durability.
        directory.sync_all().map_err(indeterminate)
    })();
    if result.is_err() {
        let mut cleanup_failed = false;
        for file in created.iter().rev() {
            cleanup_failed |= discard_private_recovery_copy(file).is_err();
        }
        if cleanup_failed {
            return Err(SqliteRecoveryError::Indeterminate);
        }
    }
    result
}
