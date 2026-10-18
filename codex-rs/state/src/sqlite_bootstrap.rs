//! Private main-file initialization before SQLite derives sidecar permissions.

use super::*;
use std::os::unix::fs::PermissionsExt;

impl SqliteConfig {
    /// Prepare one owner-held private main file before opening a bootstrap pool.
    ///
    /// Only newly created files are permission-normalized. Existing files must
    /// already satisfy the recovery filesystem owner's private-file checks.
    /// Retain the returned descriptor through initialization. This is not a
    /// recovery capability or a descriptor-backed SQLite VFS; later path-based
    /// SQLite opens do not gain hostile same-user replacement protection.
    pub fn prepare_private_bootstrap_database(
        &self,
        path: &Path,
    ) -> Result<File, SqliteRecoveryError> {
        if path.parent() != Some(self.home())
            || self.home().canonicalize().map_err(indeterminate)? != self.home()
        {
            return Err(SqliteRecoveryError::Indeterminate);
        }
        let parent = RetainedObject::bind_parent(self.home())?;
        let (file, created) = match OpenOptions::new()
            .read(true)
            .write(true)
            .create_new(true)
            .mode(0o600)
            .custom_flags(libc::O_CLOEXEC | libc::O_NOFOLLOW | libc::O_NONBLOCK)
            .open(path)
        {
            Ok(file) => (file, true),
            Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => (
                OpenOptions::new()
                    .read(true)
                    .write(true)
                    .custom_flags(libc::O_CLOEXEC | libc::O_NOFOLLOW | libc::O_NONBLOCK)
                    .open(path)
                    .map_err(indeterminate)?,
                false,
            ),
            Err(error) => return Err(indeterminate(error)),
        };
        if created {
            let metadata = file.metadata().map_err(indeterminate)?;
            if !metadata.is_file() || metadata.nlink() != 1 {
                return Err(SqliteRecoveryError::Indeterminate);
            }
            // A restrictive umask can remove owner bits. Normalize only this
            // exclusive newly created descriptor, never an existing pathname.
            file.set_permissions(std::fs::Permissions::from_mode(/*mode*/ 0o600))
                .map_err(indeterminate)?;
        }
        FileSnapshot::validated(
            &file.metadata().map_err(indeterminate)?,
            ObjectKind::PrivateFile,
        )?;
        if created {
            file.sync_all().map_err(indeterminate)?;
            parent.descriptor.sync_all().map_err(indeterminate)?;
        }
        Ok(file)
    }
}
