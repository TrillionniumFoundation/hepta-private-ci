use std::path::Path;

use crate::AuthBusAuthorityError;

const MAX_OWNER_RECORD_BYTES: u64 = 4096;

/// Process-lifetime fence for the sole AuthBus authority writer.
///
/// The lock is deliberately not cloneable. The kernel releases it after normal
/// shutdown and after an uncatchable process exit such as SIGKILL.
pub(crate) struct AuthorityOwnerLock {
    #[cfg(unix)]
    _file: std::fs::File,
}

impl AuthorityOwnerLock {
    #[cfg(unix)]
    pub(crate) fn acquire(
        database_path: &Path,
        owner_id: &str,
    ) -> Result<Self, AuthBusAuthorityError> {
        use std::fs::File;
        use std::io::Seek;
        use std::io::SeekFrom;
        use std::io::Write;
        use std::os::unix::fs::MetadataExt;

        use rustix::fs::FlockOperation;
        use rustix::fs::Mode;
        use rustix::fs::OFlags;

        if owner_id.is_empty() || owner_id.len() > 256 || !database_path.is_absolute() {
            return Err(AuthBusAuthorityError::OwnerLockUnavailable);
        }
        let parent = database_path
            .parent()
            .ok_or(AuthBusAuthorityError::OwnerLockUnavailable)?;
        let canonical_parent = parent
            .canonicalize()
            .map_err(|error| AuthBusAuthorityError::Storage(error.to_string()))?;
        if canonical_parent != parent {
            return Err(AuthBusAuthorityError::OwnerLockUnavailable);
        }
        let directory = std::fs::metadata(parent)
            .map_err(|error| AuthBusAuthorityError::Storage(error.to_string()))?;
        if !directory.is_dir() || directory.mode() & 0o077 != 0 {
            return Err(AuthBusAuthorityError::OwnerLockUnavailable);
        }
        if database_path.exists() {
            let database = std::fs::symlink_metadata(database_path)
                .map_err(|error| AuthBusAuthorityError::Storage(error.to_string()))?;
            if !database.is_file()
                || database.nlink() != 1
                || database.uid() != directory.uid()
                || database.mode() & 0o077 != 0
                || database_path
                    .canonicalize()
                    .map_err(|error| AuthBusAuthorityError::Storage(error.to_string()))?
                    != database_path
            {
                return Err(AuthBusAuthorityError::OwnerLockUnavailable);
            }
        }
        let database_name = database_path
            .file_name()
            .and_then(|name| name.to_str())
            .ok_or(AuthBusAuthorityError::OwnerLockUnavailable)?;
        let lock_path = parent.join(format!(".{database_name}.authbus-owner.lock"));
        let owned = rustix::fs::open(
            &lock_path,
            OFlags::RDWR | OFlags::CREATE | OFlags::CLOEXEC | OFlags::NOFOLLOW,
            Mode::RUSR | Mode::WUSR,
        )
        .map_err(|error| AuthBusAuthorityError::Storage(error.to_string()))?;
        let mut file: File = owned.into();
        let metadata = file
            .metadata()
            .map_err(|error| AuthBusAuthorityError::Storage(error.to_string()))?;
        if !metadata.is_file()
            || metadata.nlink() != 1
            || metadata.uid() != directory.uid()
            || metadata.mode() & 0o077 != 0
            || metadata.len() > MAX_OWNER_RECORD_BYTES
        {
            return Err(AuthBusAuthorityError::OwnerLockUnavailable);
        }
        rustix::fs::flock(&file, FlockOperation::NonBlockingLockExclusive).map_err(|error| {
            if error == rustix::io::Errno::AGAIN {
                AuthBusAuthorityError::OwnerAlreadyActive
            } else {
                AuthBusAuthorityError::Storage(error.to_string())
            }
        })?;

        let acquired_at_ms = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map_err(|_| AuthBusAuthorityError::OwnerLockUnavailable)?
            .as_millis();
        let acquired_at_ms = u64::try_from(acquired_at_ms)
            .map_err(|_| AuthBusAuthorityError::OwnerLockUnavailable)?;
        let database_binding = crate::Digest32::of_bytes(database_path.as_os_str().as_encoded_bytes());
        let payload = serde_json::to_vec(&serde_json::json!({
            "schema_version": 1,
            "owner_id": owner_id,
            "pid": std::process::id(),
            "acquired_at_ms": acquired_at_ms,
            "database_binding": database_binding.to_string(),
        }))
        .map_err(|_| AuthBusAuthorityError::OwnerLockUnavailable)?;
        if payload.len() as u64 > MAX_OWNER_RECORD_BYTES {
            return Err(AuthBusAuthorityError::OwnerLockUnavailable);
        }
        file.set_len(0)
            .map_err(|error| AuthBusAuthorityError::Storage(error.to_string()))?;
        file.seek(SeekFrom::Start(0))
            .map_err(|error| AuthBusAuthorityError::Storage(error.to_string()))?;
        file.write_all(&payload)
            .map_err(|error| AuthBusAuthorityError::Storage(error.to_string()))?;
        file.sync_all()
            .map_err(|error| AuthBusAuthorityError::Storage(error.to_string()))?;
        File::open(parent)
            .and_then(|directory| directory.sync_all())
            .map_err(|error| AuthBusAuthorityError::Storage(error.to_string()))?;
        Ok(Self { _file: file })
    }

    #[cfg(not(unix))]
    pub(crate) fn acquire(
        _database_path: &Path,
        _owner_id: &str,
    ) -> Result<Self, AuthBusAuthorityError> {
        Err(AuthBusAuthorityError::OwnerLockUnavailable)
    }
}
