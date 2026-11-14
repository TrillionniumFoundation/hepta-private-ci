//! Windows cognitive state operations bound to validated private directory handles.

use std::fs;
use std::io;
use std::io::Read;
use std::io::Write;
use std::path::Path;
use std::path::PathBuf;

use codex_utils_path::windows_private_fs::PrivateDirectory;
use codex_utils_path::windows_private_fs::snapshot_private_file;

use super::COGNITIVE_ACTIVE_DB_POINTER;
use super::COGNITIVE_DB_FILENAME;
use super::COGNITIVE_RECOVERED_DB_PREFIX;
use super::COGNITIVE_STORE_LOCK_FILENAME;
use super::CognitiveStoreError;
use super::CognitiveStoreOpenGuard;
use super::unavailable;
use super::valid_recovered_database_filename;
use crate::cognitive_path::canonical_path_without_redirection;

pub(super) fn open_guard(root: &Path) -> Result<CognitiveStoreOpenGuard, CognitiveStoreError> {
    let directory = PrivateDirectory::open_existing(root).map_err(unavailable)?;
    let file = directory
        .open_write(COGNITIVE_STORE_LOCK_FILENAME)
        .map_err(unavailable)?;
    ensure_root_binding(root, &directory)?;
    Ok(CognitiveStoreOpenGuard {
        _file: file,
        _path: root.join(COGNITIVE_STORE_LOCK_FILENAME),
        _directory: directory,
    })
}

pub(super) fn create_private_directory(path: &Path) -> Result<PathBuf, CognitiveStoreError> {
    if !path.is_absolute() {
        return Err(invalid("cognitive root must be absolute"));
    }
    let mut missing = Vec::new();
    let mut ancestor = path;
    loop {
        match fs::symlink_metadata(ancestor) {
            Ok(_) => break,
            Err(error) if error.kind() == io::ErrorKind::NotFound => {
                missing.push(ancestor);
                ancestor = ancestor
                    .parent()
                    .ok_or_else(|| invalid("cognitive root has no existing ancestor"))?;
            }
            Err(error) => return Err(unavailable(error)),
        }
    }
    // Each new component receives a private DACL at creation. NT opens reject
    // reparse points before any write, including in an existing ancestor.
    for directory in missing.into_iter().rev() {
        PrivateDirectory::open_or_create(directory).map_err(unavailable)?;
    }
    let directory = PrivateDirectory::open_existing(path).map_err(unavailable)?;
    let canonical = canonical_path_without_redirection(path)
        .map_err(unavailable)?
        .ok_or_else(|| invalid("cognitive root is redirected"))?;
    ensure_root_binding(&canonical, &directory)?;
    Ok(canonical)
}

pub(super) fn protect_database_file(path: &Path) -> Result<(), CognitiveStoreError> {
    let parent = path
        .parent()
        .ok_or_else(|| invalid("cognitive database has no parent"))?;
    let directory = PrivateDirectory::open_existing_read_only(parent).map_err(unavailable)?;
    directory.open_read(file_name(path)?).map_err(unavailable)?;
    ensure_root_binding(parent, &directory)
}

pub(super) fn resolve_active_database_path(root: &Path) -> Result<PathBuf, CognitiveStoreError> {
    let directory = PrivateDirectory::open_existing_read_only(root).map_err(unavailable)?;
    let mut pointer = match directory.open_read(COGNITIVE_ACTIVE_DB_POINTER) {
        Ok(file) => file,
        Err(error) if error.kind() == io::ErrorKind::NotFound => {
            ensure_root_binding(root, &directory)?;
            return Ok(root.join(COGNITIVE_DB_FILENAME));
        }
        Err(error) => return Err(unavailable(error)),
    };
    let before = snapshot_private_file(&pointer).map_err(unavailable)?;
    if before.len() > 256 {
        return Err(CognitiveStoreError::Corrupt(
            "cognitive active database pointer exceeds its bound".to_string(),
        ));
    }
    let mut value = String::new();
    Read::by_ref(&mut pointer)
        .take(257)
        .read_to_string(&mut value)
        .map_err(unavailable)?;
    if value.len() > 256 || !valid_recovered_database_filename(value.trim()) {
        return Err(CognitiveStoreError::Corrupt(
            "cognitive active database pointer is invalid".to_string(),
        ));
    }
    if snapshot_private_file(&pointer).map_err(unavailable)? != before
        || snapshot_private_file(
            &directory
                .open_read(COGNITIVE_ACTIVE_DB_POINTER)
                .map_err(unavailable)?,
        )
        .map_err(unavailable)?
            != before
    {
        return Err(CognitiveStoreError::Corrupt(
            "cognitive active database pointer changed during read".to_string(),
        ));
    }
    let name = value.trim();
    directory.open_read(name).map_err(|error| {
        CognitiveStoreError::Corrupt(format!(
            "cognitive active database target is missing, redirected, or unsafe: {error}"
        ))
    })?;
    ensure_root_binding(root, &directory)?;
    Ok(root.join(name))
}

pub(crate) fn publish_active_database(
    root: &Path,
    database: &Path,
) -> Result<(), CognitiveStoreError> {
    if database.parent() != Some(root) {
        return Err(invalid(
            "recovered cognitive database must remain in the private root",
        ));
    }
    let name = file_name(database)?;
    if !valid_recovered_database_filename(name) {
        return Err(invalid(
            "recovered cognitive database has an invalid generation name",
        ));
    }
    let directory = PrivateDirectory::open_existing(root).map_err(unavailable)?;
    directory.open_read(name).map_err(unavailable)?;
    let generation = name
        .strip_prefix(COGNITIVE_RECOVERED_DB_PREFIX)
        .ok_or_else(|| invalid("missing recovered generation"))?;
    let temporary = format!(
        "{COGNITIVE_ACTIVE_DB_POINTER}.tmp-{}-{}",
        std::process::id(),
        &generation[..16]
    );
    let mut file = directory.create_new(&temporary).map_err(unavailable)?;
    let result = (|| {
        file.write_all(name.as_bytes()).map_err(unavailable)?;
        file.write_all(b"\n").map_err(unavailable)?;
        file.sync_all().map_err(unavailable)?;
        ensure_root_binding(root, &directory)?;
        directory
            .replace(&temporary, COGNITIVE_ACTIVE_DB_POINTER)
            .map_err(unavailable)?;
        directory.sync_all().map_err(unavailable)?;
        ensure_root_binding(root, &directory)
    })();
    if result.is_err()
        && let Ok(snapshot) = snapshot_private_file(&file)
    {
        // If publication already renamed this file, the temporary name is
        // absent. Never remove the pointer or another file substituted there.
        let _ = directory.remove_if_unchanged(&temporary, &snapshot);
    }
    result
}

pub(super) fn sync_candidate(root: &Path, database: &Path) -> Result<(), CognitiveStoreError> {
    if database.parent() != Some(root) {
        return Err(invalid("cognitive candidate escapes its root"));
    }
    let directory = PrivateDirectory::open_existing(root).map_err(unavailable)?;
    directory
        .open_write_existing(file_name(database)?)
        .map_err(unavailable)?
        .sync_all()
        .map_err(unavailable)?;
    directory.sync_all().map_err(unavailable)?;
    ensure_root_binding(root, &directory)
}

pub(super) fn cleanup_candidate(
    path: &Path,
    include_database: bool,
) -> Result<(), CognitiveStoreError> {
    let parent = path
        .parent()
        .ok_or_else(|| invalid("cognitive candidate has no parent"))?;
    let directory = PrivateDirectory::open_existing(parent).map_err(unavailable)?;
    let name = file_name(path)?;
    let suffixes: &[&str] = if include_database {
        &["-wal", "-shm", "-journal", ""]
    } else {
        &["-wal", "-shm", "-journal"]
    };
    for suffix in suffixes {
        let entry = format!("{name}{suffix}");
        let file = match directory.open_read(&entry) {
            Ok(file) => file,
            Err(error) if error.kind() == io::ErrorKind::NotFound => continue,
            Err(error) => return Err(unavailable(error)),
        };
        let snapshot = snapshot_private_file(&file).map_err(unavailable)?;
        directory
            .remove_if_unchanged(&entry, &snapshot)
            .map_err(unavailable)?;
    }
    directory.sync_all().map_err(unavailable)?;
    ensure_root_binding(parent, &directory)
}

pub(super) fn ensure_root_binding(
    path: &Path,
    retained: &PrivateDirectory,
) -> Result<(), CognitiveStoreError> {
    let current = PrivateDirectory::open_existing_read_only(path).map_err(unavailable)?;
    let retained = snapshot_private_file(retained.as_file()).map_err(unavailable)?;
    let current = snapshot_private_file(current.as_file()).map_err(unavailable)?;
    if !retained.same_file(&current) {
        return Err(invalid("cognitive root identity changed"));
    }
    Ok(())
}

fn file_name(path: &Path) -> Result<&str, CognitiveStoreError> {
    path.file_name()
        .and_then(|value| value.to_str())
        .ok_or_else(|| invalid("cognitive state file name is invalid"))
}

fn invalid(message: &str) -> CognitiveStoreError {
    CognitiveStoreError::Invalid(message.to_string())
}

#[cfg(test)]
#[path = "cognitive_store_windows_tests.rs"]
mod tests;
