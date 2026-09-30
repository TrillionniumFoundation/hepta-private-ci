//! Kernel ownership outlives every task that can reach the lifecycle writer.
//! The containing fleet directory remains a trusted, owner-controlled path.

use std::fs::File;
use std::fs::OpenOptions;
use std::io::Error;
use std::io::ErrorKind;
use std::io::Seek;
use std::io::SeekFrom;
use std::io::Write;
use std::os::fd::AsRawFd;
use std::os::unix::fs::MetadataExt;
use std::os::unix::fs::OpenOptionsExt;
use std::os::unix::fs::PermissionsExt;
use std::path::Path;

use crate::SupervisorError;

/// Never unlink this file on release: a new inode would be a second lock domain.
/// Keep this guard as the last field of the shared daemon writer state, so the
/// writer (including its destructor) is gone before the kernel lock is released.
pub(super) struct SingleInstanceLock {
    file: File,
}

impl SingleInstanceLock {
    pub(super) fn acquire(path: &Path) -> Result<Self, SupervisorError> {
        let file = OpenOptions::new()
            .create(true)
            .read(true)
            .write(true)
            .truncate(false)
            .mode(0o600)
            .custom_flags(libc::O_NOFOLLOW | libc::O_NONBLOCK | libc::O_CLOEXEC)
            .open(path)?;
        let opened = file.metadata()?;
        // SAFETY: geteuid takes no pointers and has no memory-safety preconditions.
        let uid = unsafe { libc::geteuid() };
        if !opened.is_file() || opened.uid() != uid || opened.nlink() != 1 {
            return Err(Error::new(
                ErrorKind::PermissionDenied,
                "supervisord lock must be an owner-held regular file with one link",
            )
            .into());
        }
        // SAFETY: operates on this live, owned descriptor with fixed flock flags.
        if unsafe { libc::flock(file.as_raw_fd(), libc::LOCK_EX | libc::LOCK_NB) } == -1 {
            let error = Error::last_os_error();
            return Err(if error.kind() == ErrorKind::WouldBlock {
                Error::new(ErrorKind::AddrInUse, "another supervisord owns the fleet")
            } else {
                error
            }
            .into());
        }
        let mut owner = Self { file };
        let current = std::fs::symlink_metadata(path)?;
        if !current.is_file()
            || current.dev() != opened.dev()
            || current.ino() != opened.ino()
            || current.nlink() != 1
        {
            return Err(Error::new(
                ErrorKind::PermissionDenied,
                "supervisord lock identity changed during acquisition",
            )
            .into());
        }
        // Do not chmod or truncate a path before acquiring its exact descriptor.
        // In particular a losing contender must not modify the live owner's file.
        owner
            .file
            .set_permissions(std::fs::Permissions::from_mode(0o600))?;
        owner.file.set_len(0)?;
        owner.file.seek(SeekFrom::Start(0))?;
        writeln!(owner.file, "{}", std::process::id())?;
        owner.file.sync_all()?;
        Ok(owner)
    }
}

impl Drop for SingleInstanceLock {
    fn drop(&mut self) {
        // SAFETY: the same live descriptor is still owned exclusively by this guard.
        let _ = unsafe { libc::flock(self.file.as_raw_fd(), libc::LOCK_UN) };
    }
}

#[cfg(test)]
#[path = "daemon_owner_tests.rs"]
mod tests;
