use std::path::Path;
use std::path::PathBuf;

use crate::AuthBusAuthorityError;

/// Process-lifetime exclusive ownership fence for one authority database.
/// SQLite serializes individual transactions; this guard serializes the larger
/// database + external checkpoint protocol across independent processes.
pub(crate) struct AuthorityOwnerGuard {
    #[cfg(unix)]
    _file: std::fs::File,
    _path: PathBuf,
}

impl AuthorityOwnerGuard {
    pub(crate) fn acquire(
        database_path: &Path,
        owner_id: &str,
    ) -> Result<Self, AuthBusAuthorityError> {
        #[cfg(unix)]
        {
            acquire_unix(database_path, owner_id)
        }
        #[cfg(not(unix))]
        {
            let _ = (database_path, owner_id);
            Err(AuthBusAuthorityError::UnsafeOwnerLock)
        }
    }

    #[cfg(test)]
    pub(crate) fn path(&self) -> &Path {
        &self._path
    }
}

#[cfg(unix)]
fn acquire_unix(
    database_path: &Path,
    owner_id: &str,
) -> Result<AuthorityOwnerGuard, AuthBusAuthorityError> {
    use std::fs::OpenOptions;
    use std::fs::TryLockError;
    use std::io::Seek;
    use std::io::SeekFrom;
    use std::io::Write;
    use std::os::unix::fs::MetadataExt;
    use std::os::unix::fs::OpenOptionsExt;

    if owner_id.is_empty() || owner_id.len() > 256 || !database_path.is_absolute() {
        return Err(AuthBusAuthorityError::UnsafeOwnerLock);
    }
    let parent = database_path
        .parent()
        .ok_or(AuthBusAuthorityError::UnsafeOwnerLock)?;
    let canonical_parent = parent
        .canonicalize()
        .map_err(|error| AuthBusAuthorityError::Storage(error.to_string()))?;
    if canonical_parent != parent {
        return Err(AuthBusAuthorityError::UnsafeOwnerLock);
    }
    let parent_metadata = std::fs::metadata(parent)
        .map_err(|error| AuthBusAuthorityError::Storage(error.to_string()))?;
    if !parent_metadata.is_dir() || parent_metadata.mode() & 0o077 != 0 {
        return Err(AuthBusAuthorityError::UnsafeOwnerLock);
    }
    let database_name = database_path
        .file_name()
        .and_then(|name| name.to_str())
        .filter(|name| !name.is_empty() && name.len() <= 192)
        .ok_or(AuthBusAuthorityError::UnsafeOwnerLock)?;
    let path = parent.join(format!(".{database_name}.authbus-owner.lock"));
    let mut file = OpenOptions::new()
        .read(true)
        .write(true)
        .create(true)
        .mode(0o600)
        .custom_flags(libc::O_CLOEXEC | libc::O_NOFOLLOW)
        .open(&path)
        .map_err(|error| AuthBusAuthorityError::Storage(error.to_string()))?;
    let metadata = file
        .metadata()
        .map_err(|error| AuthBusAuthorityError::Storage(error.to_string()))?;
    let named = std::fs::symlink_metadata(&path)
        .map_err(|error| AuthBusAuthorityError::Storage(error.to_string()))?;
    if !metadata.is_file()
        || !named.is_file()
        || metadata.dev() != named.dev()
        || metadata.ino() != named.ino()
        || metadata.nlink() != 1
        || metadata.uid() != parent_metadata.uid()
        || metadata.mode() & 0o077 != 0
        || path
            .canonicalize()
            .map_err(|error| AuthBusAuthorityError::Storage(error.to_string()))?
            != path
    {
        return Err(AuthBusAuthorityError::UnsafeOwnerLock);
    }
    match file.try_lock() {
        Ok(()) => {}
        Err(TryLockError::WouldBlock) => return Err(AuthBusAuthorityError::OwnerAlreadyActive),
        Err(TryLockError::Error(error)) => {
            return Err(AuthBusAuthorityError::Storage(error.to_string()));
        }
    }
    file.set_len(0)
        .map_err(|error| AuthBusAuthorityError::Storage(error.to_string()))?;
    file.seek(SeekFrom::Start(0))
        .map_err(|error| AuthBusAuthorityError::Storage(error.to_string()))?;
    let record = serde_json::json!({
        "schemaVersion": 1,
        "ownerId": owner_id,
        "processId": std::process::id(),
    });
    serde_json::to_writer(&mut file, &record)
        .map_err(|error| AuthBusAuthorityError::Storage(error.to_string()))?;
    file.write_all(b"\n")
        .map_err(|error| AuthBusAuthorityError::Storage(error.to_string()))?;
    file.sync_all()
        .map_err(|error| AuthBusAuthorityError::Storage(error.to_string()))?;
    Ok(AuthorityOwnerGuard { _file: file, _path: path })
}
