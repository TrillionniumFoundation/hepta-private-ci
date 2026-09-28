//! Single-writer Unix filesystem implementation of the existing recovery store.
//!
//! The caller provisions an owner-only directory on a local filesystem with
//! working file locks, atomic same-directory rename and directory fsync. Parent
//! directories are trusted. This is not a distributed lock or an anti-rollback
//! witness. Client and server use separate directories; neither stores secrets.

use std::fs;
use std::fs::File;
use std::fs::Metadata;
use std::fs::OpenOptions;
use std::fs::TryLockError;
use std::io::Read;
use std::io::Write;
use std::os::unix::fs::MetadataExt;
use std::os::unix::fs::OpenOptionsExt;
use std::path::Path;
use std::path::PathBuf;

use crate::recovery::FederationRecoveryError;
use crate::recovery::FederationRecoveryStoreV1;

pub const MAX_FEDERATION_SNAPSHOT_BYTES: usize = crate::recovery::MAX_FEDERATION_RECOVERY_BYTES;
const LOCK: &str = "recovery.lock";
const SNAPSHOT: &str = "recovery.snapshot";
const PENDING: &str = "recovery.pending";

/// Blocking, crash-consistent snapshot backend. Keep this handle for the entire
/// host lifetime; opening a second writer fails rather than waiting indefinitely.
/// An ambiguous post-rename failure poisons this handle until close and reopen.
/// Do not place this directory on NFS or a filesystem without fsync guarantees.
pub struct FileFederationRecoveryStoreV1 {
    directory: PathBuf,
    directory_handle: File,
    lock: File,
    maximum_bytes: usize,
    poisoned: bool,
    #[cfg(test)]
    fail_at: Option<FailurePoint>,
}

impl FileFederationRecoveryStoreV1 {
    pub fn open(directory: &Path, maximum_bytes: usize) -> Result<Self, FederationRecoveryError> {
        if maximum_bytes == 0 || maximum_bytes > MAX_FEDERATION_SNAPSHOT_BYTES {
            return Err(FederationRecoveryError::InvalidLimits);
        }
        if !directory.is_absolute() {
            return Err(FederationRecoveryError::StoreInvalidPath);
        }
        let metadata = fs::symlink_metadata(directory).map_err(unavailable)?;
        if !metadata.is_dir() || metadata.mode() & 0o077 != 0 {
            return Err(FederationRecoveryError::StoreInvalidPath);
        }
        let directory_handle = File::open(directory).map_err(unavailable)?;
        if !same_file(
            &metadata,
            &directory_handle.metadata().map_err(unavailable)?,
        ) {
            return Err(FederationRecoveryError::StoreInvalidPath);
        }
        let lock_path = directory.join(LOCK);
        check_regular_if_present(&lock_path)?;
        let lock = OpenOptions::new()
            .read(true)
            .write(true)
            .create(true)
            .truncate(false)
            .mode(0o600)
            .open(&lock_path)
            .map_err(unavailable)?;
        check_open_file(&lock_path, &lock)?;
        match lock.try_lock() {
            Ok(()) => {}
            Err(TryLockError::WouldBlock) => return Err(FederationRecoveryError::StoreLocked),
            Err(TryLockError::Error(_)) => return Err(FederationRecoveryError::StoreUnavailable),
        }
        let store = Self {
            directory: directory.to_path_buf(),
            directory_handle,
            lock,
            maximum_bytes,
            poisoned: false,
            #[cfg(test)]
            fail_at: None,
        };
        store.check_identity()?;
        // The locked inode is never removed, including on Drop. Removing it
        // would allow a new writer to lock a different inode at the same path.
        let pending = store.directory.join(PENDING);
        if check_regular_if_present(&pending)?.is_some() {
            fs::remove_file(pending).map_err(unavailable)?;
        }
        store.directory_handle.sync_all().map_err(unavailable)?;
        Ok(store)
    }

    fn check_identity(&self) -> Result<(), FederationRecoveryError> {
        if self.poisoned {
            return Err(FederationRecoveryError::StoreIndeterminate);
        }
        let current = fs::symlink_metadata(&self.directory).map_err(unavailable)?;
        let opened = self.directory_handle.metadata().map_err(unavailable)?;
        if !current.is_dir() || current.mode() & 0o077 != 0 || !same_file(&current, &opened) {
            return Err(FederationRecoveryError::StoreInvalidPath);
        }
        check_open_file(&self.directory.join(LOCK), &self.lock)
    }

    fn commit(&mut self, snapshot: &[u8]) -> Result<(), FederationRecoveryError> {
        self.check_identity()?;
        if snapshot.is_empty() || snapshot.len() > self.maximum_bytes {
            return Err(FederationRecoveryError::StoreCapacityExceeded);
        }
        check_regular_if_present(&self.directory.join(SNAPSHOT))?;
        let pending = self.directory.join(PENDING);
        let mut file = OpenOptions::new()
            .write(true)
            .create_new(true)
            .mode(0o600)
            .open(&pending)
            .map_err(unavailable)?;
        let prepared = (|| {
            file.write_all(snapshot).map_err(unavailable)?;
            file.sync_all().map_err(unavailable)?;
            self.check_identity()?;
            #[cfg(test)]
            if self.fail_at == Some(FailurePoint::BeforeRename) {
                return Err(FederationRecoveryError::StoreUnavailable);
            }
            fs::rename(&pending, self.directory.join(SNAPSHOT)).map_err(unavailable)
        })();
        if let Err(error) = prepared {
            // No rename succeeded. The old snapshot is still authoritative.
            // Failure to remove staging is fail-closed on the next create_new.
            let _ = fs::remove_file(&pending);
            return Err(error);
        }
        // The new name is visible now. Never let the old live host retry and
        // overwrite it after an ambiguous durability acknowledgement.
        self.poisoned = true;
        #[cfg(test)]
        if self.fail_at == Some(FailurePoint::AfterRename) {
            return Err(FederationRecoveryError::StoreIndeterminate);
        }
        self.directory_handle
            .sync_all()
            .map_err(|_| FederationRecoveryError::StoreIndeterminate)?;
        self.poisoned = false;
        Ok(())
    }
}

impl FederationRecoveryStoreV1 for FileFederationRecoveryStoreV1 {
    fn load(&mut self) -> Result<Option<Vec<u8>>, FederationRecoveryError> {
        self.check_identity()?;
        let path = self.directory.join(SNAPSHOT);
        let Some(metadata) = check_regular_if_present(&path)? else {
            return Ok(None);
        };
        if metadata.len() == 0 || metadata.len() > self.maximum_bytes as u64 {
            return Err(FederationRecoveryError::StoreCapacityExceeded);
        }
        let file = File::open(&path).map_err(unavailable)?;
        check_open_file(&path, &file)?;
        if !same_file(&metadata, &file.metadata().map_err(unavailable)?) {
            return Err(FederationRecoveryError::StoreInvalidPath);
        }
        let mut bytes = Vec::new();
        file.take(self.maximum_bytes as u64 + 1)
            .read_to_end(&mut bytes)
            .map_err(unavailable)?;
        if bytes.is_empty() || bytes.len() > self.maximum_bytes {
            return Err(FederationRecoveryError::StoreCapacityExceeded);
        }
        self.check_identity()?;
        Ok(Some(bytes))
    }

    fn store(&mut self, snapshot: &[u8]) -> Result<(), FederationRecoveryError> {
        self.commit(snapshot)
    }
}

fn unavailable(_: std::io::Error) -> FederationRecoveryError {
    FederationRecoveryError::StoreUnavailable
}

fn same_file(left: &Metadata, right: &Metadata) -> bool {
    left.dev() == right.dev() && left.ino() == right.ino()
}

fn check_regular_if_present(path: &Path) -> Result<Option<Metadata>, FederationRecoveryError> {
    match fs::symlink_metadata(path) {
        Ok(metadata) => {
            if !metadata.is_file() || metadata.nlink() != 1 || metadata.mode() & 0o077 != 0 {
                return Err(FederationRecoveryError::StoreInvalidPath);
            }
            Ok(Some(metadata))
        }
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(None),
        Err(error) => Err(unavailable(error)),
    }
}

fn check_open_file(path: &Path, file: &File) -> Result<(), FederationRecoveryError> {
    let metadata =
        check_regular_if_present(path)?.ok_or(FederationRecoveryError::StoreInvalidPath)?;
    if !same_file(&metadata, &file.metadata().map_err(unavailable)?) {
        return Err(FederationRecoveryError::StoreInvalidPath);
    }
    Ok(())
}

#[cfg(test)]
#[derive(Clone, Copy, Eq, PartialEq)]
enum FailurePoint {
    BeforeRename,
    AfterRename,
}

#[cfg(test)]
#[path = "file_store_tests.rs"]
mod tests;
