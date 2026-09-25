//! Private, independently retained authority checkpoint file protocol.
use crate::AuthBusAuthorityError;
use crate::AuthorityCheckpoint;
use crate::authority_store::storage;
use codex_hepta_types::Digest32;
use serde::Deserialize;
use serde::Serialize;
use std::fs::File;
#[cfg(unix)]
use std::fs::OpenOptions;
#[cfg(unix)]
use std::io::Read;
#[cfg(unix)]
use std::io::Write;
use std::path::Path;
use std::path::PathBuf;

const CHECKPOINT_SCHEMA_VERSION: u32 = 1;
const MAX_CHECKPOINT_BYTES: u64 = 4096;

pub(super) fn checkpoint_path_exists(path: &Path) -> Result<bool, AuthBusAuthorityError> {
    match std::fs::symlink_metadata(path) {
        Ok(_) => Ok(true),
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(false),
        Err(error) => Err(AuthBusAuthorityError::Storage(error.to_string())),
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

pub(super) struct AuthorityCheckpointFile {
    path: PathBuf,
    owner_id: String,
}

impl AuthorityCheckpointFile {
    pub(super) fn open(
        path: PathBuf,
        database_path: &Path,
        owner_id: &str,
    ) -> Result<(Self, AuthorityCheckpoint), AuthBusAuthorityError> {
        if owner_id.is_empty() || owner_id.len() > 256 {
            return Err(AuthBusAuthorityError::UnsafeCheckpoint);
        }
        validate_path(&path, database_path)?;
        let file = Self {
            path,
            owner_id: owner_id.to_owned(),
        };
        let checkpoint = file.read()?;
        Ok((file, checkpoint))
    }

    pub(super) fn create(
        path: PathBuf,
        database_path: &Path,
        owner_id: &str,
        initial: AuthorityCheckpoint,
    ) -> Result<Self, AuthBusAuthorityError> {
        if owner_id.is_empty()
            || owner_id.len() > 256
            || initial.generation == 0
            || initial.digest.is_zero()
        {
            return Err(AuthBusAuthorityError::UnsafeCheckpoint);
        }
        validate_new_checkpoint_path(&path, database_path)?;
        write_private_initial(&path, owner_id, initial)?;
        validate_path(&path, database_path)?;
        let file = Self {
            path,
            owner_id: owner_id.to_owned(),
        };
        if file.read()? != initial {
            return Err(AuthBusAuthorityError::UnsafeCheckpoint);
        }
        Ok(file)
    }

    pub(super) fn read(&self) -> Result<AuthorityCheckpoint, AuthBusAuthorityError> {
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

    /// An external rename may have succeeded even though its fsync/ACK failed.
    /// Re-establish durability before promoting that witness locally.
    pub(super) fn confirm_durable(&self) -> Result<AuthorityCheckpoint, AuthBusAuthorityError> {
        let checkpoint = self.read()?;
        File::open(&self.path)
            .and_then(|file| file.sync_all())
            .map_err(storage)?;
        File::open(
            self.path
                .parent()
                .ok_or(AuthBusAuthorityError::UnsafeCheckpoint)?,
        )
        .and_then(|directory| directory.sync_all())
        .map_err(storage)?;
        if self.read()? != checkpoint {
            return Err(AuthBusAuthorityError::UnsafeCheckpoint);
        }
        Ok(checkpoint)
    }

    pub(super) fn replace(
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

#[cfg(unix)]
pub(super) fn validate_checkpoint_location(
    path: &Path,
    database_path: &Path,
) -> Result<(), AuthBusAuthorityError> {
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
    let parent = parent
        .canonicalize()
        .map_err(|error| AuthBusAuthorityError::Storage(error.to_string()))?;
    if let Ok(metadata) = std::fs::symlink_metadata(database_path)
        && (!metadata.is_file()
            || metadata.nlink() != 1
            || database_path.canonicalize().map_err(storage)? != database_path)
    {
        return Err(AuthBusAuthorityError::UnsafeCheckpoint);
    }
    let db_parent = db_parent
        .canonicalize()
        .map_err(|error| AuthBusAuthorityError::Storage(error.to_string()))?;
    if parent == db_parent {
        return Err(AuthBusAuthorityError::UnsafeCheckpoint);
    }
    let directory = std::fs::metadata(&parent)
        .map_err(|error| AuthBusAuthorityError::Storage(error.to_string()))?;
    if !directory.is_dir() || directory.mode() & 0o077 != 0 {
        return Err(AuthBusAuthorityError::UnsafeCheckpoint);
    }
    Ok(())
}

#[cfg(not(unix))]
pub(super) fn validate_checkpoint_location(
    _path: &Path,
    _database_path: &Path,
) -> Result<(), AuthBusAuthorityError> {
    Err(AuthBusAuthorityError::UnsafeCheckpoint)
}

#[cfg(unix)]
fn validate_new_checkpoint_path(
    path: &Path,
    database_path: &Path,
) -> Result<(), AuthBusAuthorityError> {
    validate_checkpoint_location(path, database_path)?;
    match std::fs::symlink_metadata(path) {
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(()),
        _ => Err(AuthBusAuthorityError::UnsafeCheckpoint),
    }
}

#[cfg(not(unix))]
fn validate_new_checkpoint_path(
    _path: &Path,
    _database_path: &Path,
) -> Result<(), AuthBusAuthorityError> {
    Err(AuthBusAuthorityError::UnsafeCheckpoint)
}

#[cfg(unix)]
fn validate_path(path: &Path, database_path: &Path) -> Result<(), AuthBusAuthorityError> {
    use std::os::unix::fs::MetadataExt;

    validate_checkpoint_location(path, database_path)?;
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
        || file.len() > MAX_CHECKPOINT_BYTES
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
fn validate_path(_path: &Path, _database_path: &Path) -> Result<(), AuthBusAuthorityError> {
    Err(AuthBusAuthorityError::UnsafeCheckpoint)
}

#[cfg(unix)]
fn read_private_file(path: &Path) -> Result<Vec<u8>, AuthBusAuthorityError> {
    use std::os::unix::fs::MetadataExt;

    let before = std::fs::symlink_metadata(path)
        .map_err(|error| AuthBusAuthorityError::Storage(error.to_string()))?;
    let parent = std::fs::metadata(
        path.parent()
            .ok_or(AuthBusAuthorityError::UnsafeCheckpoint)?,
    )
    .map_err(storage)?;
    if !before.is_file()
        || before.nlink() != 1
        || before.mode() & 0o077 != 0
        || before.uid() != parent.uid()
    {
        return Err(AuthBusAuthorityError::UnsafeCheckpoint);
    }
    let mut file =
        File::open(path).map_err(|error| AuthBusAuthorityError::Storage(error.to_string()))?;
    let opened = file
        .metadata()
        .map_err(|error| AuthBusAuthorityError::Storage(error.to_string()))?;
    let identity = |m: &std::fs::Metadata| {
        (
            m.dev(),
            m.ino(),
            m.len(),
            m.mtime(),
            m.mtime_nsec(),
            m.ctime(),
            m.ctime_nsec(),
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
fn write_private_initial(
    path: &Path,
    owner_id: &str,
    initial: AuthorityCheckpoint,
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
        ".{name}.{}.{}.bootstrap.tmp",
        std::process::id(),
        initial.generation
    ));
    let payload = checkpoint_payload(owner_id, initial)?;
    let result = (|| -> Result<(), AuthBusAuthorityError> {
        let mut file = OpenOptions::new()
            .create_new(true)
            .write(true)
            .mode(0o600)
            .open(&temporary)
            .map_err(|error| AuthBusAuthorityError::Storage(error.to_string()))?;
        file.write_all(&payload)
            .map_err(|error| AuthBusAuthorityError::Storage(error.to_string()))?;
        file.sync_all()
            .map_err(|error| AuthBusAuthorityError::Storage(error.to_string()))?;
        if checkpoint_path_exists(path)? {
            return Err(AuthBusAuthorityError::UnsafeCheckpoint);
        }
        std::fs::rename(&temporary, path)
            .map_err(|error| AuthBusAuthorityError::Storage(error.to_string()))?;
        File::open(parent)
            .and_then(|directory| directory.sync_all())
            .map_err(|error| AuthBusAuthorityError::Storage(error.to_string()))?;
        Ok(())
    })();
    if result.is_err() {
        let _ = std::fs::remove_file(&temporary);
    }
    result
}

#[cfg(not(unix))]
fn write_private_initial(
    _path: &Path,
    _owner_id: &str,
    _initial: AuthorityCheckpoint,
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
            .map_err(|error| AuthBusAuthorityError::Storage(error.to_string()))?;
        file.sync_all()
            .map_err(|error| AuthBusAuthorityError::Storage(error.to_string()))?;
        std::fs::rename(&temporary, path)
            .map_err(|error| AuthBusAuthorityError::Storage(error.to_string()))?;
        File::open(parent)
            .and_then(|directory| directory.sync_all())
            .map_err(|error| AuthBusAuthorityError::Storage(error.to_string()))?;
        Ok(())
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
