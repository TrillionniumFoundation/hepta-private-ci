use std::path::Path;
use std::path::PathBuf;

#[cfg(unix)]
use std::fs::File;
#[cfg(unix)]
use std::fs::OpenOptions;
#[cfg(unix)]
use std::io::Read;
#[cfg(unix)]
use std::io::Write;

use codex_hepta_types::Digest32;
use serde::Deserialize;
use serde::Serialize;

use crate::AuthBusAuthorityError;
use crate::AuthorityCheckpoint;

const CHECKPOINT_SCHEMA_VERSION: u32 = 1;
const MAX_CHECKPOINT_BYTES: u64 = 4096;

#[derive(Clone)]
pub(crate) struct AuthorityCheckpointFile {
    path: PathBuf,
    owner_id: String,
}

impl AuthorityCheckpointFile {
    pub(crate) fn open(
        path: PathBuf,
        database_path: &Path,
        owner_id: &str,
    ) -> Result<(Self, AuthorityCheckpoint), AuthBusAuthorityError> {
        validate_owner(owner_id)?;
        validate_boundary(&path, database_path)?;
        validate_existing_private_file(&path, MAX_CHECKPOINT_BYTES)?;
        let file = Self {
            path,
            owner_id: owner_id.to_owned(),
        };
        let checkpoint = file.read()?;
        Ok((file, checkpoint))
    }

    pub(crate) fn create(
        path: PathBuf,
        database_path: &Path,
        owner_id: &str,
        initial: AuthorityCheckpoint,
    ) -> Result<Self, AuthBusAuthorityError> {
        validate_owner(owner_id)?;
        validate_boundary(&path, database_path)?;
        if initial.generation == 0 || initial.digest.is_zero() {
            return Err(AuthBusAuthorityError::UnsafeCheckpoint);
        }
        write_private_new(&path, owner_id, initial)?;
        validate_existing_private_file(&path, MAX_CHECKPOINT_BYTES)?;
        let file = Self {
            path,
            owner_id: owner_id.to_owned(),
        };
        if file.read()? != initial {
            return Err(AuthBusAuthorityError::UnsafeCheckpoint);
        }
        Ok(file)
    }

    pub(crate) fn read(&self) -> Result<AuthorityCheckpoint, AuthBusAuthorityError> {
        let bytes = read_private_file(&self.path)?;
        let document: CheckpointDocument =
            serde_json::from_slice(&bytes).map_err(|_| AuthBusAuthorityError::UnsafeCheckpoint)?;
        if document.schema_version != CHECKPOINT_SCHEMA_VERSION
            || document.owner_id != self.owner_id
            || document.generation == 0
        {
            return Err(AuthBusAuthorityError::UnsafeCheckpoint);
        }
        let digest = document
            .digest
            .parse::<Digest32>()
            .map_err(|_| AuthBusAuthorityError::UnsafeCheckpoint)?;
        if digest.is_zero() {
            return Err(AuthBusAuthorityError::UnsafeCheckpoint);
        }
        Ok(AuthorityCheckpoint {
            generation: document.generation,
            digest,
        })
    }

    pub(crate) fn replace(
        &self,
        expected: AuthorityCheckpoint,
        next: AuthorityCheckpoint,
    ) -> Result<(), AuthBusAuthorityError> {
        let current = self.read()?;
        if current == next {
            return Ok(());
        }
        if current != expected
            || next.generation
                != expected
                    .generation
                    .checked_add(1)
                    .ok_or(AuthBusAuthorityError::CapacityExceeded)?
            || next.digest.is_zero()
        {
            return Err(AuthBusAuthorityError::RollbackDetected);
        }
        write_private_atomic(&self.path, &self.owner_id, next)?;
        if self.read()? != next {
            return Err(AuthBusAuthorityError::UnsafeCheckpoint);
        }
        Ok(())
    }
}

pub(crate) struct AuthorityWriterLock {
    #[cfg(unix)]
    _file: File,
}

impl AuthorityWriterLock {
    pub(crate) fn acquire(
        checkpoint_path: &Path,
        database_path: &Path,
        owner_id: &str,
    ) -> Result<Self, AuthBusAuthorityError> {
        validate_owner(owner_id)?;
        validate_boundary(checkpoint_path, database_path)?;
        acquire_writer_lock(checkpoint_path)
    }
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct CheckpointDocument {
    schema_version: u32,
    owner_id: String,
    generation: u64,
    digest: String,
}

fn validate_owner(owner_id: &str) -> Result<(), AuthBusAuthorityError> {
    if owner_id.is_empty() || owner_id.len() > 256 {
        return Err(AuthBusAuthorityError::UnsafeCheckpoint);
    }
    Ok(())
}

#[cfg(unix)]
fn validate_boundary(path: &Path, database_path: &Path) -> Result<(), AuthBusAuthorityError> {
    use std::os::unix::fs::MetadataExt;

    if !path.is_absolute() || !database_path.is_absolute() {
        return Err(AuthBusAuthorityError::UnsafeCheckpoint);
    }
    let parent = path
        .parent()
        .ok_or(AuthBusAuthorityError::UnsafeCheckpoint)?;
    let db_parent = database_path
        .parent()
        .ok_or(AuthBusAuthorityError::UnsafeCheckpoint)?;
    let canonical_parent = parent
        .canonicalize()
        .map_err(|error| AuthBusAuthorityError::Storage(error.to_string()))?;
    let canonical_db_parent = db_parent
        .canonicalize()
        .map_err(|error| AuthBusAuthorityError::Storage(error.to_string()))?;
    if canonical_parent == canonical_db_parent || parent != canonical_parent {
        return Err(AuthBusAuthorityError::UnsafeCheckpoint);
    }
    let directory = std::fs::metadata(&canonical_parent)
        .map_err(|error| AuthBusAuthorityError::Storage(error.to_string()))?;
    if !directory.is_dir() || directory.mode() & 0o077 != 0 {
        return Err(AuthBusAuthorityError::UnsafeCheckpoint);
    }
    Ok(())
}

#[cfg(not(unix))]
fn validate_boundary(_path: &Path, _database_path: &Path) -> Result<(), AuthBusAuthorityError> {
    Err(AuthBusAuthorityError::UnsafeCheckpoint)
}

#[cfg(unix)]
fn validate_existing_private_file(
    path: &Path,
    maximum_bytes: u64,
) -> Result<(), AuthBusAuthorityError> {
    use std::os::unix::fs::MetadataExt;

    let parent = path
        .parent()
        .ok_or(AuthBusAuthorityError::UnsafeCheckpoint)?;
    let directory = std::fs::metadata(parent)
        .map_err(|error| AuthBusAuthorityError::Storage(error.to_string()))?;
    let file = std::fs::symlink_metadata(path)
        .map_err(|error| AuthBusAuthorityError::Storage(error.to_string()))?;
    if !file.is_file()
        || file.nlink() != 1
        || file.uid() != directory.uid()
        || file.mode() & 0o077 != 0
        || file.len() > maximum_bytes
        || path
            .canonicalize()
            .map_err(|error| AuthBusAuthorityError::Storage(error.to_string()))?
            != path
    {
        return Err(AuthBusAuthorityError::UnsafeCheckpoint);
    }
    Ok(())
}

#[cfg(not(unix))]
fn validate_existing_private_file(
    _path: &Path,
    _maximum_bytes: u64,
) -> Result<(), AuthBusAuthorityError> {
    Err(AuthBusAuthorityError::UnsafeCheckpoint)
}

#[cfg(unix)]
fn acquire_writer_lock(checkpoint_path: &Path) -> Result<AuthorityWriterLock, AuthBusAuthorityError> {
    use std::os::unix::fs::OpenOptionsExt;

    let name = checkpoint_path
        .file_name()
        .and_then(|value| value.to_str())
        .ok_or(AuthBusAuthorityError::UnsafeCheckpoint)?;
    let path = checkpoint_path.with_file_name(format!(".{name}.writer.lock"));
    let file = OpenOptions::new()
        .create(true)
        .read(true)
        .write(true)
        .mode(0o600)
        .open(&path)
        .map_err(|error| AuthBusAuthorityError::Storage(error.to_string()))?;
    validate_existing_private_file(&path, MAX_CHECKPOINT_BYTES)?;
    file.try_lock().map_err(|error| match error {
        std::fs::TryLockError::WouldBlock => AuthBusAuthorityError::WriterAlreadyActive,
        std::fs::TryLockError::Error(error) => {
            AuthBusAuthorityError::Storage(error.to_string())
        }
    })?;
    Ok(AuthorityWriterLock { _file: file })
}

#[cfg(not(unix))]
fn acquire_writer_lock(
    _checkpoint_path: &Path,
) -> Result<AuthorityWriterLock, AuthBusAuthorityError> {
    Err(AuthBusAuthorityError::UnsafeCheckpoint)
}

#[cfg(unix)]
fn read_private_file(path: &Path) -> Result<Vec<u8>, AuthBusAuthorityError> {
    use std::os::unix::fs::MetadataExt;

    let before = std::fs::symlink_metadata(path)
        .map_err(|error| AuthBusAuthorityError::Storage(error.to_string()))?;
    let mut file =
        File::open(path).map_err(|error| AuthBusAuthorityError::Storage(error.to_string()))?;
    let opened = file
        .metadata()
        .map_err(|error| AuthBusAuthorityError::Storage(error.to_string()))?;
    let identity = |metadata: &std::fs::Metadata| {
        (
            metadata.dev(),
            metadata.ino(),
            metadata.len(),
            metadata.mtime(),
            metadata.mtime_nsec(),
            metadata.ctime(),
            metadata.ctime_nsec(),
        )
    };
    if identity(&opened) != identity(&before) {
        return Err(AuthBusAuthorityError::UnsafeCheckpoint);
    }
    let mut bytes = Vec::new();
    std::io::Read::by_ref(&mut file)
        .take(MAX_CHECKPOINT_BYTES + 1)
        .read_to_end(&mut bytes)
        .map_err(|error| AuthBusAuthorityError::Storage(error.to_string()))?;
    let after = std::fs::symlink_metadata(path)
        .map_err(|error| AuthBusAuthorityError::Storage(error.to_string()))?;
    if bytes.len() as u64 > MAX_CHECKPOINT_BYTES
        || identity(&after) != identity(&before)
        || identity(
            &file
                .metadata()
                .map_err(|error| AuthBusAuthorityError::Storage(error.to_string()))?,
        ) != identity(&before)
    {
        return Err(AuthBusAuthorityError::UnsafeCheckpoint);
    }
    Ok(bytes)
}

#[cfg(not(unix))]
fn read_private_file(_path: &Path) -> Result<Vec<u8>, AuthBusAuthorityError> {
    Err(AuthBusAuthorityError::UnsafeCheckpoint)
}

#[cfg(unix)]
fn write_private_new(
    path: &Path,
    owner_id: &str,
    checkpoint: AuthorityCheckpoint,
) -> Result<(), AuthBusAuthorityError> {
    use std::os::unix::fs::OpenOptionsExt;

    let payload = checkpoint_payload(owner_id, checkpoint)?;
    let mut file = OpenOptions::new()
        .create_new(true)
        .write(true)
        .mode(0o600)
        .open(path)
        .map_err(|error| AuthBusAuthorityError::Storage(error.to_string()))?;
    file.write_all(&payload)
        .and_then(|()| file.sync_all())
        .map_err(|error| AuthBusAuthorityError::Storage(error.to_string()))?;
    sync_parent(path)
}

#[cfg(not(unix))]
fn write_private_new(
    _path: &Path,
    _owner_id: &str,
    _checkpoint: AuthorityCheckpoint,
) -> Result<(), AuthBusAuthorityError> {
    Err(AuthBusAuthorityError::UnsafeCheckpoint)
}

#[cfg(unix)]
fn write_private_atomic(
    path: &Path,
    owner_id: &str,
    next: AuthorityCheckpoint,
) -> Result<(), AuthBusAuthorityError> {
    use std::os::unix::fs::OpenOptionsExt;

    let parent = path
        .parent()
        .ok_or(AuthBusAuthorityError::UnsafeCheckpoint)?;
    let name = path
        .file_name()
        .and_then(|value| value.to_str())
        .ok_or(AuthBusAuthorityError::UnsafeCheckpoint)?;
    let temporary = parent.join(format!(
        ".{name}.{}.{}.tmp",
        std::process::id(),
        next.generation
    ));
    let payload = checkpoint_payload(owner_id, next)?;
    let result = (|| -> Result<(), AuthBusAuthorityError> {
        let mut file = OpenOptions::new()
            .create_new(true)
            .write(true)
            .mode(0o600)
            .open(&temporary)
            .map_err(|error| AuthBusAuthorityError::Storage(error.to_string()))?;
        file.write_all(&payload)
            .and_then(|()| file.sync_all())
            .map_err(|error| AuthBusAuthorityError::Storage(error.to_string()))?;
        std::fs::rename(&temporary, path)
            .map_err(|error| AuthBusAuthorityError::Storage(error.to_string()))?;
        sync_parent(path)
    })();
    if result.is_err() {
        let _ = std::fs::remove_file(&temporary);
    }
    result
}

#[cfg(not(unix))]
fn write_private_atomic(
    _path: &Path,
    _owner_id: &str,
    _next: AuthorityCheckpoint,
) -> Result<(), AuthBusAuthorityError> {
    Err(AuthBusAuthorityError::UnsafeCheckpoint)
}

fn checkpoint_payload(
    owner_id: &str,
    checkpoint: AuthorityCheckpoint,
) -> Result<Vec<u8>, AuthBusAuthorityError> {
    let payload = serde_json::to_vec(&CheckpointDocument {
        schema_version: CHECKPOINT_SCHEMA_VERSION,
        owner_id: owner_id.to_owned(),
        generation: checkpoint.generation,
        digest: checkpoint.digest.to_string(),
    })
    .map_err(|_| AuthBusAuthorityError::UnsafeCheckpoint)?;
    if payload.len() as u64 > MAX_CHECKPOINT_BYTES {
        return Err(AuthBusAuthorityError::UnsafeCheckpoint);
    }
    Ok(payload)
}

#[cfg(unix)]
fn sync_parent(path: &Path) -> Result<(), AuthBusAuthorityError> {
    let parent = path
        .parent()
        .ok_or(AuthBusAuthorityError::UnsafeCheckpoint)?;
    File::open(parent)
        .and_then(|directory| directory.sync_all())
        .map_err(|error| AuthBusAuthorityError::Storage(error.to_string()))
}
