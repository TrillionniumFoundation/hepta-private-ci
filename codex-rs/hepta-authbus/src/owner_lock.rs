use std::fs::File;
use std::io::Seek;
use std::io::SeekFrom;
use std::io::Write;
use std::path::Path;
use std::path::PathBuf;

use rustix::fs::FlockOperation;
use rustix::fs::Mode;
use rustix::fs::OFlags;

use crate::AuthBusAuthorityError;

/// Lifetime owner fence. The open file description holds an advisory exclusive
/// lock until the host is dropped, so a second process cannot run checkpoint or
/// authority mutations for the same database.
pub(crate) struct AuthorityOwnerLock {
    _file: File,
    path: PathBuf,
}

impl AuthorityOwnerLock {
    pub(crate) fn acquire(
        database_path: &Path,
        owner_id: &str,
    ) -> Result<Self, AuthBusAuthorityError> {
        if owner_id.is_empty() || owner_id.len() > 256 || !database_path.is_absolute() {
            return Err(AuthBusAuthorityError::UnsafeOwnerLock);
        }
        let parent = database_path
            .parent()
            .ok_or(AuthBusAuthorityError::UnsafeOwnerLock)?
            .canonicalize()
            .map_err(|error| AuthBusAuthorityError::Storage(error.to_string()))?;
        let database_name = database_path
            .file_name()
            .and_then(|name| name.to_str())
            .ok_or(AuthBusAuthorityError::UnsafeOwnerLock)?;
        let lock_path = parent.join(format!(".{database_name}.authbus-owner.lock"));
        let descriptor = rustix::fs::open(
            &lock_path,
            OFlags::RDWR | OFlags::CREATE | OFlags::CLOEXEC | OFlags::NOFOLLOW,
            Mode::RUSR | Mode::WUSR,
        )
        .map_err(|error| AuthBusAuthorityError::Storage(error.to_string()))?;
        let mut file: File = descriptor.into();
        match rustix::fs::flock(&file, FlockOperation::NonBlockingLockExclusive) {
            Ok(()) => {}
            Err(error)
                if error == rustix::io::Errno::AGAIN
                    || error == rustix::io::Errno::WOULDBLOCK =>
            {
                return Err(AuthBusAuthorityError::OwnerAlreadyActive);
            }
            Err(error) => return Err(AuthBusAuthorityError::Storage(error.to_string())),
        }
        validate_lock_file(&lock_path, &parent, &file)?;
        let payload = serde_json::to_vec(&serde_json::json!({
            "schema_version": 1,
            "owner_id": owner_id,
            "pid": std::process::id(),
        }))
        .map_err(|_| AuthBusAuthorityError::UnsafeOwnerLock)?;
        file.set_len(0)
            .and_then(|()| file.seek(SeekFrom::Start(0)).map(|_| ()))
            .and_then(|()| file.write_all(&payload))
            .and_then(|()| file.sync_all())
            .map_err(|error| AuthBusAuthorityError::Storage(error.to_string()))?;
        Ok(Self {
            _file: file,
            path: lock_path,
        })
    }

    pub(crate) fn path(&self) -> &Path {
        &self.path
    }
}

#[cfg(unix)]
fn validate_lock_file(
    path: &Path,
    parent: &Path,
    file: &File,
) -> Result<(), AuthBusAuthorityError> {
    use std::os::unix::fs::MetadataExt;

    let directory = std::fs::metadata(parent)
        .map_err(|error| AuthBusAuthorityError::Storage(error.to_string()))?;
    let path_metadata = std::fs::symlink_metadata(path)
        .map_err(|error| AuthBusAuthorityError::Storage(error.to_string()))?;
    let file_metadata = file
        .metadata()
        .map_err(|error| AuthBusAuthorityError::Storage(error.to_string()))?;
    if !directory.is_dir()
        || directory.mode() & 0o022 != 0
        || !path_metadata.is_file()
        || path_metadata.nlink() != 1
        || path_metadata.uid() != directory.uid()
        || path_metadata.mode() & 0o077 != 0
        || path_metadata.dev() != file_metadata.dev()
        || path_metadata.ino() != file_metadata.ino()
    {
        return Err(AuthBusAuthorityError::UnsafeOwnerLock);
    }
    Ok(())
}

#[cfg(not(unix))]
fn validate_lock_file(
    _path: &Path,
    _parent: &Path,
    _file: &File,
) -> Result<(), AuthBusAuthorityError> {
    Err(AuthBusAuthorityError::UnsafeOwnerLock)
}
