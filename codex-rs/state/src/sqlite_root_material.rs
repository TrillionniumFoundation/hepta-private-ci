//! Root-only capture of a registered owner's retained SQLite material.
//!
//! This capability does not authenticate a Current cut or open SQLite. The
//! caller must validate the private candidate with the original full-cut,
//! schema and integrity checks before any protected publication can reference it.

#[cfg(unix)]
use super::ExistingSqliteRecoveryGuard;
use super::SqliteConfig;
use super::SqliteRecoveryError;
use std::ffi::OsStr;
use std::path::Path;
use std::path::PathBuf;

/// One capture attempt between a fixed registered owner and a fixed Root home.
///
/// Only actual Root may register a non-Root source UID. Neither a source path,
/// UID nor destination is accepted from a checkpoint request. The Root launcher
/// derives these inputs from its original immutable registration. Default
/// same-owner recovery admission is unchanged; this type exposes no guard,
/// database connection, writer, issuer or activation operation.
#[derive(Debug)]
pub struct RootSqliteMaterialSource {
    _private: (),
    #[cfg(unix)]
    source: ExistingSqliteRecoveryGuard,
    #[cfg(unix)]
    destination: super::RetainedObject,
}

#[cfg(all(test, unix))]
#[path = "sqlite_root_material_tests.rs"]
mod tests;

impl RootSqliteMaterialSource {
    /// Retain original source descriptors and one Root-owned private directory.
    /// All arguments must come from the trusted launch registration. No source
    /// file is opened by SQLite or modified, and no whole-owner exclusive lock
    /// is acquired. The caller separately serializes its original publication.
    pub fn bind_registered(
        source: &SqliteConfig,
        database: &Path,
        registered_uid: u32,
        destination: &SqliteConfig,
    ) -> Result<Self, SqliteRecoveryError> {
        #[cfg(unix)]
        {
            let rule = super::OwnerRule::RegisteredRootSource(registered_uid);
            rule.expected_uid()?;
            verify_root_ancestors(destination.home())?;
            if database.parent() != Some(source.home())
                || destination.home() == source.home()
                || destination
                    .home()
                    .canonicalize()
                    .map_err(super::indeterminate)?
                    != destination.home()
            {
                return Err(SqliteRecoveryError::Indeterminate);
            }
            let destination = super::RetainedObject::bind_parent(
                destination.home(),
                super::OwnerRule::CurrentUser,
            )?;
            let source = ExistingSqliteRecoveryGuard::bind_for_owner(database, rule)?;
            destination.revalidate()?;
            Ok(Self {
                _private: (),
                source,
                destination,
            })
        }
        #[cfg(not(unix))]
        {
            let _ = (source, database, registered_uid, destination);
            Err(SqliteRecoveryError::Unavailable)
        }
    }

    /// Copy the retained database/WAL/journal to one new Root-private candidate.
    ///
    /// The original 128-MiB per-file and 256-MiB bundle limits, identity/drift
    /// checks, single-link modes and file/directory synchronization apply.
    /// SHM is not copied. This consumes the attempt even on failure: a partial
    /// result is not a Current witness and is never a reason to retry dispatch.
    /// A plain filename cannot select a different destination directory.
    pub fn materialize_private_candidate(
        self,
        file_name: &OsStr,
    ) -> Result<PathBuf, SqliteRecoveryError> {
        #[cfg(unix)]
        {
            let name = Path::new(file_name);
            if name.components().count() != 1
                || !matches!(
                    name.components().next(),
                    Some(std::path::Component::Normal(_))
                )
            {
                return Err(SqliteRecoveryError::Indeterminate);
            }
            self.destination.revalidate()?;
            verify_root_ancestors(&self.destination.path)?;
            self.source.revalidate()?;
            let target = self.destination.path.join(name);
            for suffix in ["", "-wal", "-shm", "-journal"] {
                let mut path = target.as_os_str().to_os_string();
                path.push(suffix);
                match std::fs::symlink_metadata(PathBuf::from(path)) {
                    Err(error) if error.kind() == std::io::ErrorKind::NotFound => {}
                    Ok(_) | Err(_) => return Err(SqliteRecoveryError::Indeterminate),
                }
            }
            super::image::materialize_retained_copy(&self.destination.path, &self.source, &target)?;
            self.source.revalidate()?;
            // Creating our candidate changes directory timestamps. Recheck
            // strict ownership and the actual retained directory identity,
            // then sync that same opened directory, not a replacement path.
            let observed = super::RetainedObject::bind_parent(
                &self.destination.path,
                super::OwnerRule::CurrentUser,
            )?;
            verify_root_ancestors(&self.destination.path)?;
            if observed.snapshot.device != self.destination.snapshot.device
                || observed.snapshot.inode != self.destination.snapshot.inode
            {
                return Err(SqliteRecoveryError::Indeterminate);
            }
            self.destination
                .descriptor
                .sync_all()
                .map_err(super::indeterminate)?;
            Ok(target)
        }
        #[cfg(not(unix))]
        {
            let _ = file_name;
            Err(SqliteRecoveryError::Unavailable)
        }
    }
}

#[cfg(unix)]
fn verify_root_ancestors(path: &Path) -> Result<(), SqliteRecoveryError> {
    use std::os::unix::fs::MetadataExt;
    if !path.is_absolute() {
        return Err(SqliteRecoveryError::Indeterminate);
    }
    let mut current = PathBuf::new();
    for component in path.components() {
        match component {
            std::path::Component::RootDir | std::path::Component::Normal(_) => {
                current.push(component);
            }
            _ => return Err(SqliteRecoveryError::Indeterminate),
        }
        let metadata = std::fs::symlink_metadata(&current).map_err(super::indeterminate)?;
        if !metadata.is_dir()
            || metadata.file_type().is_symlink()
            || metadata.uid() != 0
            || metadata.mode() & 0o022 != 0
        {
            return Err(SqliteRecoveryError::Indeterminate);
        }
    }
    Ok(())
}
