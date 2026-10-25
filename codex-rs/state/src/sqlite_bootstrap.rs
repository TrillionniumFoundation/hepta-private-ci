//! Private main-file initialization before SQLite derives sidecar permissions.

use super::*;
use std::os::unix::fs::PermissionsExt;

// Only creation/normalization/descriptor disposal is serialized. This is not
// a migration lock. Every ordinary bootstrap caller must pass this gate before
// opening SQLite, so no caller can observe our new main inode while its raw
// descriptor is still alive. Existing live SQLite pools need no raw descriptor.
static BOOTSTRAP_CREATION: std::sync::Mutex<()> = std::sync::Mutex::new(());

impl SqliteConfig {
    /// Prepare one owner-held private main file before opening a bootstrap pool.
    ///
    /// Only newly created files are permission-normalized. Existing files must
    /// already satisfy the recovery filesystem owner's private-file checks.
    /// Existing files are checked through metadata only: closing an unrelated
    /// descriptor could discard another live SQLite connection's POSIX locks.
    /// New descriptors are closed inside the process-local creation gate before
    /// this method returns. This is not a migration barrier, recovery capability
    /// or descriptor-backed VFS; later SQLite pathname opens remain vulnerable
    /// to hostile same-user replacement or callers bypassing this protocol.
    pub fn prepare_private_bootstrap_database(
        &self,
        path: &Path,
    ) -> Result<(), SqliteRecoveryError> {
        let _creation = BOOTSTRAP_CREATION
            .lock()
            .map_err(|_| SqliteRecoveryError::Indeterminate)?;
        if path.parent() != Some(self.home())
            || self.home().canonicalize().map_err(indeterminate)? != self.home()
        {
            return Err(SqliteRecoveryError::Indeterminate);
        }
        let parent = RetainedObject::bind_parent(self.home())?;
        let file = match OpenOptions::new()
            .read(true)
            .write(true)
            .create_new(true)
            .mode(0o600)
            .custom_flags(libc::O_CLOEXEC | libc::O_NOFOLLOW | libc::O_NONBLOCK)
            .open(path)
        {
            Ok(file) => file,
            Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => {
                FileSnapshot::validated(
                    &std::fs::symlink_metadata(path).map_err(indeterminate)?,
                    ObjectKind::PrivateFile,
                )?;
                return Ok(());
            }
            Err(error) => return Err(indeterminate(error)),
        };
        let metadata = file.metadata().map_err(indeterminate)?;
        if !metadata.is_file() || metadata.nlink() != 1 {
            return Err(SqliteRecoveryError::Indeterminate);
        }
        // A restrictive umask can remove owner bits. Normalize only this
        // exclusive newly created descriptor, never an existing pathname.
        file.set_permissions(std::fs::Permissions::from_mode(/*mode*/ 0o600))
            .map_err(indeterminate)?;
        FileSnapshot::validated(
            &file.metadata().map_err(indeterminate)?,
            ObjectKind::PrivateFile,
        )?;
        file.sync_all().map_err(indeterminate)?;
        parent.descriptor.sync_all().map_err(indeterminate)?;
        drop(file);
        Ok(())
    }
}
