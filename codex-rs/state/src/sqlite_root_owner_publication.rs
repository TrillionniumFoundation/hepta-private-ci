//! Same-directory physical activation while retaining the original owner lock.

#[cfg(unix)]
use super::BoundFile;
use super::RootSqliteOwnerCandidate;
use super::SqliteRecoveryError;
#[cfg(unix)]
use super::directory;
use std::ffi::OsStr;
#[cfg(unix)]
use std::ffi::OsString;
#[cfg(unix)]
use std::fs::File;
#[cfg(unix)]
use std::os::unix::fs::FileExt;
use std::path::Path;

/// Retains the predecessor pointer and original exclusive owner lock. The
/// original owner must validate `previous_pointer_bytes` with its own parser.
/// This capability only publishes physical bytes, never a protected Current.
#[derive(Debug)]
#[must_use]
pub struct RootSqliteOwnerPublication {
    #[cfg(unix)]
    pointer_name: OsString,
    #[cfg(unix)]
    previous: PointerSnapshot,
    candidate: RootSqliteOwnerCandidate,
}

/// A completed physical pointer switch, still holding the original lock.
/// The caller must finish its original Root slot checks before releasing this
/// object. No factory, writer, recovery permission or Current is returned.
#[derive(Debug)]
#[must_use]
pub struct RootSqliteOwnerPublished {
    #[cfg(unix)]
    pointer: BoundFile,
    candidate: RootSqliteOwnerCandidate,
}

#[cfg(unix)]
#[derive(Debug)]
enum PointerSnapshot {
    Absent,
    Present { file: BoundFile, bytes: Vec<u8> },
}

#[cfg(unix)]
impl PointerSnapshot {
    fn retain(directory: &File, name: &OsStr) -> Result<Self, SqliteRecoveryError> {
        if directory::require_absent(directory, name).is_ok() {
            return Ok(Self::Absent);
        }
        let file = BoundFile::retain(
            name,
            directory::open_owner_file(directory, name, libc::O_RDONLY)?,
        )?;
        if file.snapshot.length > 256 {
            return Err(SqliteRecoveryError::Indeterminate);
        }
        let mut bytes = vec![0; file.snapshot.length as usize];
        file.file
            .read_exact_at(&mut bytes, 0)
            .map_err(super::super::indeterminate)?;
        file.verify(directory)?;
        Ok(Self::Present { file, bytes })
    }

    fn verify(&self, directory: &File, name: &OsStr) -> Result<(), SqliteRecoveryError> {
        match self {
            Self::Absent => directory::require_absent(directory, name),
            Self::Present { file, bytes } => {
                file.verify(directory)?;
                let mut observed = vec![0; bytes.len()];
                file.file
                    .read_exact_at(&mut observed, 0)
                    .map_err(super::super::indeterminate)?;
                if observed != *bytes {
                    return Err(SqliteRecoveryError::Indeterminate);
                }
                file.verify(directory)
            }
        }
    }
}

impl RootSqliteOwnerCandidate {
    /// Bind the original owner's fixed pointer basename using the same held
    /// directory. No caller-supplied pointer payload is accepted. The original
    /// parser must admit the observed bytes before `publish` is invoked.
    pub fn observe_active_pointer(
        self,
        pointer_name: &OsStr,
    ) -> Result<RootSqliteOwnerPublication, SqliteRecoveryError> {
        #[cfg(unix)]
        {
            self.verify_unchanged()?;
            directory::name_bytes(pointer_name)?;
            if pointer_name == self.candidate.name || pointer_name == self.destination.lock.name {
                return Err(SqliteRecoveryError::Indeterminate);
            }
            let previous =
                PointerSnapshot::retain(self.destination.directories.directory(), pointer_name)?;
            let result = RootSqliteOwnerPublication {
                pointer_name: pointer_name.to_os_string(),
                previous,
                candidate: self,
            };
            result.verify_unchanged()?;
            Ok(result)
        }
        #[cfg(not(unix))]
        {
            let _ = pointer_name;
            Err(SqliteRecoveryError::Unavailable)
        }
    }
}

impl RootSqliteOwnerPublication {
    pub fn previous_pointer_bytes(&self) -> Option<&[u8]> {
        #[cfg(unix)]
        {
            match &self.previous {
                PointerSnapshot::Absent => None,
                PointerSnapshot::Present { bytes, .. } => Some(bytes),
            }
        }
        #[cfg(not(unix))]
        {
            None
        }
    }

    pub fn verify_unchanged(&self) -> Result<(), SqliteRecoveryError> {
        self.candidate.verify_unchanged()?;
        #[cfg(unix)]
        return self.previous.verify(
            self.candidate.destination.directories.directory(),
            &self.pointer_name,
        );
        #[cfg(not(unix))]
        Err(SqliteRecoveryError::Unavailable)
    }

    /// Publish candidate basename + newline using the original owner's fixed
    /// temporary-name protocol. Uses only retained DirFD-relative operations.
    /// The call is synchronous: no task outlives cancellation. Its Root caller
    /// must retain the serialized slot until physical completion, then recheck
    /// its own full Current/token/lifetime before ACK. Any error may follow a
    /// rename; preserve all files and reconcile, never blindly retry or clean.
    pub fn publish(
        self,
        temporary_name: &OsStr,
    ) -> Result<RootSqliteOwnerPublished, SqliteRecoveryError> {
        #[cfg(unix)]
        {
            use std::io::Write;
            use std::os::fd::AsRawFd;
            use std::os::unix::fs::PermissionsExt;
            self.verify_unchanged()?;
            directory::name_bytes(temporary_name)?;
            if temporary_name == self.pointer_name
                || temporary_name == self.candidate.candidate.name
                || temporary_name == self.candidate.destination.lock.name
            {
                return Err(SqliteRecoveryError::Indeterminate);
            }
            let name = self
                .candidate
                .candidate
                .name
                .to_str()
                .ok_or(SqliteRecoveryError::Indeterminate)?;
            let bytes = format!("{name}\n").into_bytes();
            if bytes.len() > 256 {
                return Err(SqliteRecoveryError::Indeterminate);
            }
            let directory = self.candidate.destination.directories.directory();
            directory::require_absent(directory, temporary_name)?;
            let mut file = directory::open_relative(
                directory,
                temporary_name,
                libc::O_RDWR | libc::O_CREAT | libc::O_EXCL,
            )?;
            file.write_all(&bytes)
                .map_err(super::super::indeterminate)?;
            file.sync_all().map_err(super::super::indeterminate)?;
            // SAFETY: exclusively owned new FD, fixed registered UID; all-one
            // gid preserves the group. No caller pathname enters fchown.
            if unsafe { libc::fchown(file.as_raw_fd(), directory::OWNER_UID, !0) } != 0 {
                return Err(SqliteRecoveryError::Indeterminate);
            }
            file.set_permissions(std::fs::Permissions::from_mode(0o600))
                .map_err(super::super::indeterminate)?;
            file.sync_all().map_err(super::super::indeterminate)?;
            let temporary = BoundFile::retain(temporary_name, file)?;
            self.verify_unchanged()?;
            temporary.verify(directory)?;
            let from = directory::name_bytes(temporary_name)?;
            let to = directory::name_bytes(&self.pointer_name)?;
            // SAFETY: both names are NUL-terminated single components; both
            // retained parent FDs refer to the same bound destination.
            if unsafe {
                libc::renameat(
                    directory.as_raw_fd(),
                    from.as_ptr(),
                    directory.as_raw_fd(),
                    to.as_ptr(),
                )
            } != 0
            {
                return Err(SqliteRecoveryError::Indeterminate);
            }
            let pointer = BoundFile::retain(&self.pointer_name, temporary.file)?;
            // Rename can advance ctime, but must preserve every other field.
            let mut before = temporary.snapshot;
            before.changed_seconds = pointer.snapshot.changed_seconds;
            before.changed_nanoseconds = pointer.snapshot.changed_nanoseconds;
            if before != pointer.snapshot {
                return Err(SqliteRecoveryError::Indeterminate);
            }
            let mut observed = vec![0; bytes.len()];
            pointer
                .file
                .read_exact_at(&mut observed, 0)
                .map_err(super::super::indeterminate)?;
            if observed != bytes {
                return Err(SqliteRecoveryError::Indeterminate);
            }
            pointer.verify(directory)?;
            directory.sync_all().map_err(super::super::indeterminate)?;
            let published = RootSqliteOwnerPublished {
                pointer,
                candidate: self.candidate,
            };
            published.verify_unchanged()?;
            Ok(published)
        }
        #[cfg(not(unix))]
        {
            let _ = temporary_name;
            Err(SqliteRecoveryError::Unavailable)
        }
    }
}

impl RootSqliteOwnerPublished {
    pub fn path(&self) -> &Path {
        self.candidate.path()
    }

    pub fn verify_unchanged(&self) -> Result<(), SqliteRecoveryError> {
        self.candidate.verify_unchanged()?;
        #[cfg(unix)]
        return self
            .pointer
            .verify(self.candidate.destination.directories.directory());
        #[cfg(not(unix))]
        Err(SqliteRecoveryError::Unavailable)
    }
}
