//! Native private storage used by the Windows cognitive owner.
//!
//! This establishes a private pathname namespace for the ordinary SQLite VFS;
//! it is not a descriptor-backed SQLite VFS. Suspect source files are opened
//! only by the separate read-only recovery guard and copied before SQLite use.

use std::fs;
use std::fs::File;
use std::io::Write;
use std::path::Path;
use std::path::PathBuf;

use codex_utils_path::windows_private::Access;
use codex_utils_path::windows_private::PrivateSqliteDirectory;

use super::COGNITIVE_ACTIVE_DB_POINTER;
use super::COGNITIVE_RECOVERED_DB_PREFIX;
use super::COGNITIVE_STORE_LOCK_FILENAME;
use super::CognitiveStoreError;
use super::unavailable;
use crate::cognitive_path::canonical_path_without_redirection;

pub(super) fn prepare_root(path: &Path) -> Result<PathBuf, CognitiveStoreError> {
    // Create only missing ancestors, each with an atomic owner-only descriptor
    // and a no-reparse native open. Never create a broad root then tighten it.
    let mut missing = Vec::new();
    let mut current = path;
    loop {
        match fs::symlink_metadata(current) {
            Ok(_) => break,
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => {
                missing.push(current);
                current = current.parent().ok_or_else(|| {
                    CognitiveStoreError::Invalid(
                        "private cognitive root has no existing ancestor".to_string(),
                    )
                })?;
            }
            Err(error) => return Err(unavailable(error)),
        }
    }
    for directory in missing.into_iter().rev() {
        PrivateSqliteDirectory::prepare(directory).map_err(unavailable)?;
    }
    let _directory = PrivateSqliteDirectory::prepare(path).map_err(unavailable)?;
    canonical_path_without_redirection(path)
        .map_err(unavailable)?
        .ok_or_else(|| CognitiveStoreError::Invalid("cognitive root is redirected".to_string()))
}

pub(super) fn open_lock(
    root: &Path,
) -> Result<(File, PrivateSqliteDirectory), CognitiveStoreError> {
    let directory = PrivateSqliteDirectory::open_writable(root).map_err(unavailable)?;
    let file = directory
        .open(COGNITIVE_STORE_LOCK_FILENAME, Access::Create)
        .map_err(unavailable)?;
    Ok((file, directory))
}

pub(super) fn open_pointer(root: &Path) -> Result<Option<File>, CognitiveStoreError> {
    let directory = PrivateSqliteDirectory::inspect(root).map_err(unavailable)?;
    let file = match directory.open(COGNITIVE_ACTIVE_DB_POINTER, Access::Read) {
        Ok(file) => file,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(None),
        Err(error) => return Err(unavailable(error)),
    };
    if file.metadata().map_err(unavailable)?.len() > 256 {
        return Err(CognitiveStoreError::Corrupt(
            "cognitive active pointer exceeds its bound".to_string(),
        ));
    }
    Ok(Some(file))
}

pub(super) fn verify_database(path: &Path) -> Result<(), CognitiveStoreError> {
    let root = path
        .parent()
        .ok_or_else(|| CognitiveStoreError::Invalid("database has no parent".to_string()))?;
    let name = path
        .file_name()
        .and_then(|name| name.to_str())
        .ok_or_else(|| CognitiveStoreError::Invalid("database leaf is invalid".to_string()))?;
    let directory = PrivateSqliteDirectory::inspect(root).map_err(unavailable)?;
    directory.open(name, Access::Read).map_err(unavailable)?;
    Ok(())
}

pub(super) fn sync_recovery_candidate(root: &Path, path: &Path) -> Result<(), CognitiveStoreError> {
    if path.parent() != Some(root) {
        return Err(CognitiveStoreError::Invalid(
            "candidate escapes private root".to_string(),
        ));
    }
    let name = path
        .file_name()
        .and_then(|name| name.to_str())
        .ok_or_else(|| CognitiveStoreError::Invalid("candidate leaf is invalid".to_string()))?;
    let directory = PrivateSqliteDirectory::open_writable(root).map_err(unavailable)?;
    directory
        .open(name, Access::Write)
        .map_err(unavailable)?
        .sync_all()
        .map_err(unavailable)?;
    directory.sync_all().map_err(unavailable)
}

pub(super) fn publish_pointer(root: &Path, database: &str) -> Result<(), CognitiveStoreError> {
    let directory = PrivateSqliteDirectory::open_writable(root).map_err(unavailable)?;
    let generation = database
        .strip_prefix(COGNITIVE_RECOVERED_DB_PREFIX)
        .unwrap_or("invalid");
    let temporary = format!(
        "{COGNITIVE_ACTIVE_DB_POINTER}.tmp-{}-{}",
        std::process::id(),
        &generation[..generation.len().min(16)]
    );
    let mut file = directory
        .open(&temporary, Access::CreateNew)
        .map_err(unavailable)?;
    let mut renamed = false;
    let result = (|| {
        file.write_all(database.as_bytes()).map_err(unavailable)?;
        file.write_all(b"\n").map_err(unavailable)?;
        file.sync_all().map_err(unavailable)?;
        directory
            .replace(&temporary, COGNITIVE_ACTIVE_DB_POINTER)
            .map_err(unavailable)?;
        renamed = true;
        directory.sync_all().map_err(unavailable)
    })();
    if result.is_err() && !renamed {
        let _ = directory.remove_created(file);
    }
    // After rename, a failed flush must retain the possibly-active pointer.
    // The caller reconciles it as Indeterminate instead of deleting it.
    result
}
