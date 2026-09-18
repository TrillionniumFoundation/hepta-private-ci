//! Root-confined storage enrollment and conservative orphan cleanup.
//!
//! The host enrolls one canonical root and protects its parent directories from
//! concurrent replacement. This module rejects absolute/parent traversal and
//! canonical parent escapes. Cleanup is intentionally narrow: only a regular,
//! zero-length create-only orphan may be removed.

use std::error::Error as StdError;
use std::fmt;
use std::fs;
use std::fs::File;
use std::io;
use std::path::Component;
use std::path::Path;
use std::path::PathBuf;

use crate::ArtifactStorageError;
use crate::CreateOnlyArtifactFile;

#[derive(Clone, Debug)]
pub struct ArtifactStorageAdminV1 {
    canonical_root: PathBuf,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum OrphanCleanupDispositionV1 {
    Removed,
    Absent,
    NotZeroLengthOrphan,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct StorageEntryInspectionV1 {
    pub relative_path: PathBuf,
    pub exists: bool,
    pub regular_file: bool,
    pub symbolic_link: bool,
    pub encoded_bytes: u64,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum StorageHygieneError {
    InvalidRoot,
    InvalidRelativePath,
    ParentEscape,
    ParentUnavailable,
    ArtifactStorage(ArtifactStorageError),
    Io(io::ErrorKind),
}

impl fmt::Display for StorageHygieneError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for StorageHygieneError {}

impl From<io::Error> for StorageHygieneError {
    fn from(value: io::Error) -> Self {
        Self::Io(value.kind())
    }
}

impl From<ArtifactStorageError> for StorageHygieneError {
    fn from(value: ArtifactStorageError) -> Self {
        Self::ArtifactStorage(value)
    }
}

impl ArtifactStorageAdminV1 {
    pub fn enroll(root: impl AsRef<Path>) -> Result<Self, StorageHygieneError> {
        let root = root.as_ref();
        let metadata = fs::metadata(root).map_err(|_| StorageHygieneError::InvalidRoot)?;
        if !metadata.is_dir() {
            return Err(StorageHygieneError::InvalidRoot);
        }
        let canonical_root = fs::canonicalize(root).map_err(|_| StorageHygieneError::InvalidRoot)?;
        Ok(Self { canonical_root })
    }

    #[must_use]
    pub fn canonical_root(&self) -> &Path {
        &self.canonical_root
    }

    pub fn resolve(&self, relative: impl AsRef<Path>) -> Result<PathBuf, StorageHygieneError> {
        let relative = relative.as_ref();
        validate_relative(relative)?;
        let joined = self.canonical_root.join(relative);
        let parent = joined
            .parent()
            .ok_or(StorageHygieneError::InvalidRelativePath)?;
        let canonical_parent =
            fs::canonicalize(parent).map_err(|_| StorageHygieneError::ParentUnavailable)?;
        if !canonical_parent.starts_with(&self.canonical_root) {
            return Err(StorageHygieneError::ParentEscape);
        }
        let name = joined
            .file_name()
            .ok_or(StorageHygieneError::InvalidRelativePath)?;
        Ok(canonical_parent.join(name))
    }

    pub fn create_artifact(
        &self,
        relative: impl AsRef<Path>,
    ) -> Result<CreateOnlyArtifactFile, StorageHygieneError> {
        let path = self.resolve(relative)?;
        CreateOnlyArtifactFile::create(path).map_err(Into::into)
    }

    pub fn inspect(
        &self,
        relative: impl AsRef<Path>,
    ) -> Result<StorageEntryInspectionV1, StorageHygieneError> {
        let relative = relative.as_ref();
        let path = self.resolve(relative)?;
        match fs::symlink_metadata(&path) {
            Ok(metadata) => Ok(StorageEntryInspectionV1 {
                relative_path: relative.to_path_buf(),
                exists: true,
                regular_file: metadata.file_type().is_file(),
                symbolic_link: metadata.file_type().is_symlink(),
                encoded_bytes: metadata.len(),
            }),
            Err(error) if error.kind() == io::ErrorKind::NotFound => Ok(StorageEntryInspectionV1 {
                relative_path: relative.to_path_buf(),
                exists: false,
                regular_file: false,
                symbolic_link: false,
                encoded_bytes: 0,
            }),
            Err(error) => Err(error.into()),
        }
    }

    /// Remove only an unambiguous create-only orphan. Non-empty files,
    /// directories, symlinks and special files are never removed. The containing
    /// directory is synced after deletion so cleanup itself has a durable result.
    pub fn cleanup_zero_length_orphan(
        &self,
        relative: impl AsRef<Path>,
    ) -> Result<OrphanCleanupDispositionV1, StorageHygieneError> {
        let path = self.resolve(relative)?;
        let metadata = match fs::symlink_metadata(&path) {
            Ok(metadata) => metadata,
            Err(error) if error.kind() == io::ErrorKind::NotFound => {
                return Ok(OrphanCleanupDispositionV1::Absent);
            }
            Err(error) => return Err(error.into()),
        };
        if !metadata.file_type().is_file()
            || metadata.file_type().is_symlink()
            || metadata.len() != 0
        {
            return Ok(OrphanCleanupDispositionV1::NotZeroLengthOrphan);
        }
        fs::remove_file(&path)?;
        let parent = path.parent().ok_or(StorageHygieneError::InvalidRelativePath)?;
        File::open(parent)?.sync_all()?;
        Ok(OrphanCleanupDispositionV1::Removed)
    }
}

fn validate_relative(relative: &Path) -> Result<(), StorageHygieneError> {
    if relative.as_os_str().is_empty() || relative.is_absolute() {
        return Err(StorageHygieneError::InvalidRelativePath);
    }
    let mut saw_component = false;
    for component in relative.components() {
        match component {
            Component::Normal(_) => saw_component = true,
            Component::CurDir
            | Component::ParentDir
            | Component::RootDir
            | Component::Prefix(_) => return Err(StorageHygieneError::InvalidRelativePath),
        }
    }
    if !saw_component {
        return Err(StorageHygieneError::InvalidRelativePath);
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Write;
    use std::sync::atomic::AtomicU64;
    use std::sync::atomic::Ordering;

    static NEXT_ROOT: AtomicU64 = AtomicU64::new(1);

    fn root(label: &str) -> PathBuf {
        std::env::temp_dir().join(format!(
            "hepta-learning-artifacts-admin-{label}-{}-{}",
            std::process::id(),
            NEXT_ROOT.fetch_add(1, Ordering::Relaxed)
        ))
    }

    #[test]
    fn art_09_storage_admin_rejects_parent_escape() {
        let root = root("escape");
        fs::create_dir_all(&root).expect("create root");
        let admin = ArtifactStorageAdminV1::enroll(&root).expect("enroll root");
        assert_eq!(
            admin.resolve("../escape"),
            Err(StorageHygieneError::InvalidRelativePath)
        );
        fs::remove_dir_all(root).expect("cleanup root");
    }

    #[test]
    fn art_09_storage_admin_removes_only_zero_length_orphan() {
        let root = root("cleanup");
        fs::create_dir_all(root.join("generation-1")).expect("create root");
        let admin = ArtifactStorageAdminV1::enroll(&root).expect("enroll root");
        let orphan = "generation-1/orphan.bin";
        drop(admin.create_artifact(orphan).expect("reserve orphan"));
        assert_eq!(
            admin
                .cleanup_zero_length_orphan(orphan)
                .expect("cleanup orphan"),
            OrphanCleanupDispositionV1::Removed
        );
        assert!(!admin.inspect(orphan).expect("inspect").exists);

        let nonempty = admin.resolve("generation-1/nonempty.bin").expect("resolve");
        let mut file = fs::OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&nonempty)
            .expect("create nonempty");
        file.write_all(b"durable").expect("write nonempty");
        file.sync_all().expect("sync nonempty");
        assert_eq!(
            admin
                .cleanup_zero_length_orphan("generation-1/nonempty.bin")
                .expect("refuse cleanup"),
            OrphanCleanupDispositionV1::NotZeroLengthOrphan
        );
        assert!(nonempty.exists());
        fs::remove_dir_all(root).expect("cleanup root");
    }
}
