//! Preflight identity checks for the ordinary path-based SQLite opener.
//!
//! These reject existing aliases before SQLite can write through them. The
//! retained file detects replacement during initialization on Unix; it does
//! not make a reconnecting SQLite pool descriptor-bound against a hostile
//! process with continuous write access to the private directory.

use std::fs::File;
use std::fs::Metadata;
use std::fs::OpenOptions;
use std::path::Path;
use std::path::PathBuf;

use super::CognitiveStoreError;
use super::unavailable;

pub(super) struct DatabaseFileGuard {
    file: File,
    path: PathBuf,
}

impl DatabaseFileGuard {
    pub(super) fn prepare(path: &Path) -> Result<Self, CognitiveStoreError> {
        let mut options = OpenOptions::new();
        options.read(true).write(true);
        #[cfg(unix)]
        {
            use std::os::unix::fs::OpenOptionsExt;
            options
                .mode(0o600)
                .custom_flags(libc::O_CLOEXEC | libc::O_NOFOLLOW | libc::O_NONBLOCK);
        }
        let file = match options.create_new(true).open(path) {
            Ok(file) => file,
            Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => {
                options.create_new(false).open(path).map_err(unavailable)?
            }
            Err(error) => return Err(unavailable(error)),
        };
        let guard = Self {
            file,
            path: path.to_path_buf(),
        };
        guard.verify()?;
        Ok(guard)
    }

    pub(super) fn verify(&self) -> Result<(), CognitiveStoreError> {
        let retained = self.file.metadata().map_err(unavailable)?;
        validate_private_file(&retained)?;
        let named = std::fs::symlink_metadata(&self.path).map_err(unavailable)?;
        validate_private_file(&named)?;
        #[cfg(unix)]
        {
            use std::os::unix::fs::MetadataExt;
            if retained.dev() != named.dev() || retained.ino() != named.ino() {
                return Err(CognitiveStoreError::Corrupt(
                    "cognitive database identity changed during initialization".to_string(),
                ));
            }
        }
        for suffix in ["-wal", "-shm", "-journal"] {
            let mut name = self.path.as_os_str().to_os_string();
            name.push(suffix);
            match std::fs::symlink_metadata(PathBuf::from(name)) {
                Ok(metadata) => validate_private_file(&metadata)?,
                Err(error) if error.kind() == std::io::ErrorKind::NotFound => {}
                Err(error) => return Err(unavailable(error)),
            }
        }
        Ok(())
    }
}

fn validate_private_file(metadata: &Metadata) -> Result<(), CognitiveStoreError> {
    if !metadata.is_file() {
        return Err(CognitiveStoreError::Corrupt(
            "cognitive database and sidecars must be private regular files".to_string(),
        ));
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::MetadataExt;
        if metadata.nlink() != 1 || metadata.mode() & 0o7777 != 0o600 {
            return Err(CognitiveStoreError::Corrupt(
                "cognitive database and sidecars must each have one link and mode 0600".to_string(),
            ));
        }
    }
    Ok(())
}
