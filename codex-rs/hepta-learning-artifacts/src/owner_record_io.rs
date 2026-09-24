//! Immutable owner records: equal readable bytes do not prove durable storage.
use super::*;
use std::io::Write;

pub(super) fn write_create_only_or_exact(
    path: &Path,
    bytes: &[u8],
) -> Result<(), ArtifactOwnerHostError> {
    write_bounded_create_only_or_exact(path, bytes, MAX_SMALL_RECORD_BYTES)
}

pub(super) fn write_bounded_create_only_or_exact(
    path: &Path,
    bytes: &[u8],
    limit: usize,
) -> Result<(), ArtifactOwnerHostError> {
    write_bounded_with_sync(path, bytes, limit, &File::sync_all)
}

/// One implementation for initial writes and exact retries. The injected sync
/// operation allows both filesystem acknowledgement cuts to be exercised; the
/// product owner always uses the actual File::sync_all syscall.
pub(super) fn write_bounded_with_sync(
    path: &Path,
    bytes: &[u8],
    limit: usize,
    sync: &impl Fn(&File) -> std::io::Result<()>,
) -> Result<(), ArtifactOwnerHostError> {
    if bytes.len() > limit {
        return Err(ArtifactOwnerHostError::Capacity);
    }
    let parent = path
        .parent()
        .ok_or(ArtifactOwnerHostError::CheckpointMismatch)?;
    let mut options = OpenOptions::new();
    options.read(true).write(true).create_new(true);
    #[cfg(unix)]
    options.mode(0o600);
    let file = match options.open(path) {
        Ok(mut file) => {
            file.write_all(bytes)
                .map_err(|_| ArtifactOwnerHostError::Indeterminate)?;
            file
        }
        Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => {
            if read_small_record(path, limit)? != bytes {
                return Err(ArtifactOwnerHostError::IdentityConflict);
            }
            // Keep one writable descriptor from comparison through file sync.
            // A previous complete write may have failed at either durability cut.
            let mut file = OpenOptions::new().read(true).write(true).open(path)?;
            match file.try_lock_shared() {
                Ok(()) => {}
                Err(TryLockError::WouldBlock) => {
                    return Err(ArtifactOwnerHostError::WriterFenceBusy);
                }
                Err(TryLockError::Error(error)) => return Err(error.into()),
            }
            let metadata = file.metadata()?;
            if !metadata.is_file() || metadata.len() > limit as u64 {
                return Err(ArtifactOwnerHostError::Capacity);
            }
            let mut existing = Vec::new();
            (&mut file)
                .take(limit as u64 + 1)
                .read_to_end(&mut existing)?;
            if existing != bytes {
                return Err(ArtifactOwnerHostError::IdentityConflict);
            }
            file
        }
        Err(error) => return Err(error.into()),
    };
    sync(&file).map_err(|_| ArtifactOwnerHostError::Indeterminate)?;
    File::open(parent)
        .and_then(|directory| sync(&directory))
        .map_err(|_| ArtifactOwnerHostError::Indeterminate)
}

// Unsupported directory flushing must fail closed, never imply durability.
pub(super) fn sync_owner_directory(path: &Path) -> Result<(), ArtifactOwnerHostError> {
    File::open(path)
        .and_then(|directory| directory.sync_all())
        .map_err(|_| ArtifactOwnerHostError::Indeterminate)
}

#[cfg(test)]
#[path = "owner_record_io_tests.rs"]
mod tests;
