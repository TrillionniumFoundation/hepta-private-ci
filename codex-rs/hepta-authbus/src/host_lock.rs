use std::fs::File;
use std::fs::TryLockError;
use std::path::Path;
use std::path::PathBuf;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;

use crate::AuthBusAuthorityError;

/// Stable owner-lock inode bound to its private name. Once identity validation
/// fails, this handle stays fenced; recovery requires reopening the host.
pub(super) struct OwnerLockFile {
    file: File,
    path: PathBuf,
    fenced: AtomicBool,
}

impl OwnerLockFile {
    pub(super) fn validate_current(&self) -> Result<(), AuthBusAuthorityError> {
        if self.fenced.load(Ordering::Acquire) {
            return Err(AuthBusAuthorityError::UnsafeCheckpoint);
        }
        self.validate_identity().inspect_err(|_| {
            self.fenced.store(true, Ordering::Release);
        })
    }

    #[cfg(unix)]
    fn validate_identity(&self) -> Result<(), AuthBusAuthorityError> {
        use std::os::unix::fs::MetadataExt;
        let parent = self
            .path
            .parent()
            .ok_or(AuthBusAuthorityError::UnsafeCheckpoint)?;
        let opened = self
            .file
            .metadata()
            .map_err(|_| AuthBusAuthorityError::UnsafeCheckpoint)?;
        let named = std::fs::symlink_metadata(&self.path)
            .map_err(|_| AuthBusAuthorityError::UnsafeCheckpoint)?;
        let directory = std::fs::symlink_metadata(parent)
            .map_err(|_| AuthBusAuthorityError::UnsafeCheckpoint)?;
        if !directory.is_dir()
            || directory.mode() & 0o077 != 0
            || !opened.is_file()
            || !named.is_file()
            || opened.dev() != named.dev()
            || opened.ino() != named.ino()
            || opened.uid() != directory.uid()
            || named.uid() != directory.uid()
            || opened.nlink() != 1
            || named.nlink() != 1
            || opened.mode() & 0o077 != 0
            || named.mode() & 0o077 != 0
            || opened.len() != 0
            || named.len() != 0
            || self
                .path
                .canonicalize()
                .map_err(|_| AuthBusAuthorityError::UnsafeCheckpoint)?
                != self.path
        {
            return Err(AuthBusAuthorityError::UnsafeCheckpoint);
        }
        Ok(())
    }

    #[cfg(not(unix))]
    fn validate_identity(&self) -> Result<(), AuthBusAuthorityError> {
        let _ = &self.path;
        Err(AuthBusAuthorityError::UnsafeCheckpoint)
    }
}

pub(super) struct OwnerFileLockGuard<'a> {
    file: &'a File,
}

impl Drop for OwnerFileLockGuard<'_> {
    fn drop(&mut self) {
        let _ = self.file.unlock();
    }
}

pub(super) fn try_owner_lock(
    lock: &OwnerLockFile,
) -> Result<OwnerFileLockGuard<'_>, AuthBusAuthorityError> {
    lock.validate_current()?;
    let guard = match lock.file.try_lock() {
        Ok(()) => OwnerFileLockGuard { file: &lock.file },
        Err(TryLockError::WouldBlock) => return Err(AuthBusAuthorityError::OwnerBusy),
        Err(TryLockError::Error(error)) => {
            return Err(AuthBusAuthorityError::Storage(error.to_string()));
        }
    };
    // An OS lock on a retired inode cannot establish ownership of its old path.
    lock.validate_current()?;
    Ok(guard)
}

#[cfg(unix)]
pub(super) fn open_private_owner_lock(
    checkpoint_path: &Path,
) -> Result<OwnerLockFile, AuthBusAuthorityError> {
    use std::fs::OpenOptions;
    use std::os::unix::fs::MetadataExt;
    use std::os::unix::fs::OpenOptionsExt;

    let parent = checkpoint_path
        .parent()
        .ok_or(AuthBusAuthorityError::UnsafeCheckpoint)?;
    let checkpoint_name = checkpoint_path
        .file_name()
        .and_then(|value| value.to_str())
        .ok_or(AuthBusAuthorityError::UnsafeCheckpoint)?;
    let lock_path = parent.join(format!(".{checkpoint_name}.owner.lock"));
    let parent_metadata = std::fs::metadata(parent)
        .map_err(|error| AuthBusAuthorityError::Storage(error.to_string()))?;
    if !parent_metadata.is_dir() || parent_metadata.mode() & 0o077 != 0 {
        return Err(AuthBusAuthorityError::UnsafeCheckpoint);
    }

    let mut created = false;
    let file = match OpenOptions::new()
        .read(true)
        .write(true)
        .create_new(true)
        .mode(0o600)
        .open(&lock_path)
    {
        Ok(file) => {
            created = true;
            file
        }
        Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => {
            let before = std::fs::symlink_metadata(&lock_path)
                .map_err(|error| AuthBusAuthorityError::Storage(error.to_string()))?;
            if !before.is_file()
                || before.nlink() != 1
                || before.uid() != parent_metadata.uid()
                || before.mode() & 0o077 != 0
                || before.len() != 0
            {
                return Err(AuthBusAuthorityError::UnsafeCheckpoint);
            }
            let file = OpenOptions::new()
                .read(true)
                .write(true)
                .open(&lock_path)
                .map_err(|error| AuthBusAuthorityError::Storage(error.to_string()))?;
            let opened = file
                .metadata()
                .map_err(|error| AuthBusAuthorityError::Storage(error.to_string()))?;
            let after = std::fs::symlink_metadata(&lock_path)
                .map_err(|error| AuthBusAuthorityError::Storage(error.to_string()))?;
            let identity = |metadata: &std::fs::Metadata| {
                (
                    metadata.dev(),
                    metadata.ino(),
                    metadata.uid(),
                    metadata.nlink(),
                )
            };
            if identity(&before) != identity(&opened) || identity(&after) != identity(&opened) {
                return Err(AuthBusAuthorityError::UnsafeCheckpoint);
            }
            file
        }
        Err(error) => return Err(AuthBusAuthorityError::Storage(error.to_string())),
    };

    let metadata = file
        .metadata()
        .map_err(|error| AuthBusAuthorityError::Storage(error.to_string()))?;
    if !metadata.is_file()
        || metadata.nlink() != 1
        || metadata.uid() != parent_metadata.uid()
        || metadata.mode() & 0o077 != 0
        || metadata.len() != 0
        || lock_path
            .canonicalize()
            .map_err(|error| AuthBusAuthorityError::Storage(error.to_string()))?
            != lock_path
    {
        return Err(AuthBusAuthorityError::UnsafeCheckpoint);
    }
    if created {
        file.sync_all()
            .map_err(|error| AuthBusAuthorityError::Storage(error.to_string()))?;
        File::open(parent)
            .and_then(|directory| directory.sync_all())
            .map_err(|error| AuthBusAuthorityError::Storage(error.to_string()))?;
    }
    let lock = OwnerLockFile {
        file,
        path: lock_path,
        fenced: AtomicBool::new(false),
    };
    lock.validate_current()?;
    Ok(lock)
}

#[cfg(not(unix))]
pub(super) fn open_private_owner_lock(
    _checkpoint_path: &Path,
) -> Result<OwnerLockFile, AuthBusAuthorityError> {
    Err(AuthBusAuthorityError::UnsafeCheckpoint)
}
