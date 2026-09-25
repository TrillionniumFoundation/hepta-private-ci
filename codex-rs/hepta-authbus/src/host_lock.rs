use std::fs::File;
use std::path::Path;

use crate::AuthBusAuthorityError;

#[cfg(unix)]
pub(super) fn open_private_owner_lock(
    checkpoint_path: &Path,
) -> Result<File, AuthBusAuthorityError> {
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
    Ok(file)
}

#[cfg(not(unix))]
pub(super) fn open_private_owner_lock(
    _checkpoint_path: &Path,
) -> Result<File, AuthBusAuthorityError> {
    Err(AuthBusAuthorityError::UnsafeCheckpoint)
}
