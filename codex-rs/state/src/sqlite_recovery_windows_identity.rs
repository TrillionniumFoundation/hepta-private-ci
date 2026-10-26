//! Compatibility facade over the one canonical Windows identity implementation.

use super::Kind;
use super::SqliteRecoveryError;
use codex_utils_path::PrivateFileIdentity;
use codex_utils_path::PrivateFileKind;
use codex_utils_path::WindowsFileId;
use std::fs::File;

pub(super) type FileId = WindowsFileId;
pub(super) type Snapshot = PrivateFileIdentity;

pub(super) fn file_id(file: &File) -> Result<FileId, SqliteRecoveryError> {
    WindowsFileId::inspect(file).map_err(|_| SqliteRecoveryError::Indeterminate)
}

pub(super) fn snapshot(file: &File, kind: Kind) -> Result<Snapshot, SqliteRecoveryError> {
    let kind = match kind {
        Kind::Directory => PrivateFileKind::Directory,
        Kind::File => PrivateFileKind::RegularFile,
    };
    PrivateFileIdentity::inspect(file, kind).map_err(|_| SqliteRecoveryError::Indeterminate)
}

pub(super) fn require_local_ntfs(file: &File) -> Result<(), SqliteRecoveryError> {
    WindowsFileId::require_local_ntfs(file).map_err(|_| SqliteRecoveryError::Indeterminate)
}
