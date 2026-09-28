//! Physical publisher ownership spans SQLite preparation, external CAS and ACK.
//! A durable lease alone does not serialize processes reusing the same owner ID.
//! Lock the private home directory itself: never unlink a lock file on release.

use std::fs::File;
use std::fs::OpenOptions;
use std::fs::TryLockError;
use std::io;
use std::os::unix::fs::MetadataExt;
use std::os::unix::fs::OpenOptionsExt;
use std::path::Path;
use std::path::PathBuf;

pub(super) struct PublicationProcessGuard {
    home: PathBuf,
    directory: File,
    identity: (u64, u64, u32),
}

impl PublicationProcessGuard {
    pub(super) fn acquire(home: &Path) -> io::Result<Self> {
        if !home.is_absolute() || home.canonicalize()? != home {
            return Err(io::Error::other("publication home is not canonical"));
        }
        let directory = OpenOptions::new()
            .read(true)
            .custom_flags(libc::O_DIRECTORY | libc::O_NOFOLLOW | libc::O_CLOEXEC)
            .open(home)?;
        let metadata = directory.metadata()?;
        if !metadata.is_dir() || metadata.mode() & 0o077 != 0 {
            return Err(io::Error::other("publication home is not a private directory"));
        }
        match directory.try_lock() {
            Ok(()) => {}
            Err(TryLockError::WouldBlock) => {
                return Err(io::Error::new(
                    io::ErrorKind::WouldBlock,
                    "another publication or reconciliation holds the process fence",
                ));
            }
            Err(TryLockError::Error(error)) => return Err(error),
        }
        let guard = Self {
            home: home.to_path_buf(),
            directory,
            identity: (metadata.dev(), metadata.ino(), metadata.uid()),
        };
        guard.validate()?;
        Ok(guard)
    }

    pub(super) fn validate(&self) -> io::Result<()> {
        for metadata in [
            self.directory.metadata()?,
            std::fs::symlink_metadata(&self.home)?,
        ] {
            if !metadata.is_dir()
                || metadata.mode() & 0o077 != 0
                || (metadata.dev(), metadata.ino(), metadata.uid()) != self.identity
            {
                return Err(io::Error::other("publication directory identity changed"));
            }
        }
        Ok(())
    }
}

// File ownership releases the OS lock on return, error, future cancellation or
// process exit. No explicit unlock/unlink can accidentally release a successor.

#[cfg(test)]
#[path = "evidence_publication_process_lock_tests.rs"]
mod tests;
