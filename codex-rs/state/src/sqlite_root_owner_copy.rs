//! Physical Root-to-registered-owner copying without pointer publication.

use super::ExistingSqliteRecoveryGuard;
use super::SqliteConfig;
use super::SqliteRecoveryError;
use std::ffi::OsStr;
use std::path::Path;
use std::path::PathBuf;

#[path = "sqlite_root_owner_publication.rs"]
mod publication;
pub use publication::RootSqliteOwnerPublication;
pub use publication::RootSqliteOwnerPublished;

#[cfg(unix)]
#[path = "sqlite_root_owner_directory.rs"]
mod directory;

#[cfg(unix)]
use directory::DirectoryChain;
#[cfg(unix)]
use directory::LeafOwner;
#[cfg(unix)]
use std::ffi::OsString;
#[cfg(unix)]
use std::fs::File;

/// One exclusively fenced destination selected by the trusted Root launcher.
/// The fixed owner is UID60001. This cannot select or activate a Current cut.
/// The original publisher/process must also be retired: filesystem locks are
/// advisory and do not replace the Root owner's independent lifetime checks.
#[derive(Debug)]
pub struct RootSqliteOwnerCopy {
    #[cfg(unix)]
    destination: Destination,
}

/// A new, synced physical candidate; not a registration or recovery permit.
/// Retains the original lock until consumed/dropped. Drop never publishes an
/// active pointer, removes an orphan, or waits for a detached worker.
#[derive(Debug)]
#[must_use = "retain this capability until the original publication ceremony finishes"]
pub struct RootSqliteOwnerCandidate {
    path: PathBuf,
    #[cfg(unix)]
    candidate: BoundFile,
    #[cfg(unix)]
    source: ExistingSqliteRecoveryGuard,
    #[cfg(unix)]
    source_directories: DirectoryChain,
    // Drop the original exclusive lock last, after the retained file handles.
    #[cfg(unix)]
    destination: Destination,
}

#[cfg(unix)]
#[derive(Debug)]
struct Destination {
    path: PathBuf,
    directories: DirectoryChain,
    lock: BoundFile,
}

#[cfg(unix)]
#[derive(Debug)]
struct BoundFile {
    name: OsString,
    file: File,
    snapshot: super::FileSnapshot,
}

#[cfg(unix)]
impl BoundFile {
    fn retain(name: &OsStr, file: File) -> Result<Self, SqliteRecoveryError> {
        let snapshot = super::FileSnapshot::validated(
            &file.metadata().map_err(super::indeterminate)?,
            super::ObjectKind::PrivateFile,
            super::OwnerRule::RegisteredRootSource(directory::OWNER_UID),
        )?;
        Ok(Self {
            name: name.to_os_string(),
            file,
            snapshot,
        })
    }

    fn verify(&self, directory: &File) -> Result<(), SqliteRecoveryError> {
        let entry = directory::open_owner_file(directory, &self.name, libc::O_RDONLY)?;
        for file in [&self.file, &entry] {
            if super::FileSnapshot::validated(
                &file.metadata().map_err(super::indeterminate)?,
                super::ObjectKind::PrivateFile,
                super::OwnerRule::RegisteredRootSource(directory::OWNER_UID),
            )? != self.snapshot
            {
                return Err(SqliteRecoveryError::Indeterminate);
            }
        }
        Ok(())
    }
}

#[cfg(unix)]
impl Destination {
    fn verify(&self) -> Result<(), SqliteRecoveryError> {
        self.directories.verify()?;
        self.lock.verify(self.directories.directory())
    }
}

impl RootSqliteOwnerCopy {
    /// Open an already provisioned fixed home and its EXISTING original lock.
    /// No path component, lock or database is created here. The lock basename
    /// comes from the original owner's protocol, never an untrusted request.
    pub fn bind_registered(
        destination: &SqliteConfig,
        store_lock_name: &OsStr,
    ) -> Result<Self, SqliteRecoveryError> {
        #[cfg(unix)]
        {
            let directories = DirectoryChain::bind(destination.home(), LeafOwner::RegisteredOwner)?;
            let file =
                directory::open_owner_file(directories.directory(), store_lock_name, libc::O_RDWR)?;
            let lock = BoundFile::retain(store_lock_name, file)?;
            lock.verify(directories.directory())?;
            lock.file
                .try_lock()
                .map_err(|_| SqliteRecoveryError::Indeterminate)?;
            let destination = Destination {
                path: destination.home().to_path_buf(),
                directories,
                lock,
            };
            destination.verify()?;
            Ok(Self { destination })
        }
        #[cfg(not(unix))]
        {
            let _ = (destination, store_lock_name);
            Err(SqliteRecoveryError::Unavailable)
        }
    }

    /// Copy only a consolidated, retained Root-owned image into one new file.
    /// This synchronous operation starts no background task and performs no
    /// SQLite or full-cut validation. The caller supplies the original verified
    /// material and keeps its serialized owner slot through physical completion,
    /// even if its RPC is cancelled. Partial files are never reused or deleted.
    pub fn materialize_consolidated_candidate(
        self,
        source: &ExistingSqliteRecoveryGuard,
        candidate_name: &OsStr,
    ) -> Result<RootSqliteOwnerCandidate, SqliteRecoveryError> {
        #[cfg(unix)]
        {
            use std::io::Write;
            use std::os::fd::AsRawFd;
            use std::os::unix::fs::FileExt;
            use std::os::unix::fs::PermissionsExt;
            self.destination.verify()?;
            directory::name_bytes(candidate_name)?;
            let name = candidate_name
                .to_str()
                .ok_or(SqliteRecoveryError::Indeterminate)?;
            if !name
                .bytes()
                .all(|byte| byte.is_ascii_alphanumeric() || b"._-".contains(&byte))
                || name.starts_with('.')
                || !name.ends_with(".sqlite3")
                || candidate_name == self.destination.lock.name.as_os_str()
            {
                return Err(SqliteRecoveryError::Indeterminate);
            }
            let source_directories =
                DirectoryChain::bind(&source.inner.parent.path, LeafOwner::Root)?;
            source.revalidate()?;
            if source.inner.database.snapshot.owner != 0
                || source
                    .inner
                    .sidecars
                    .iter()
                    .any(|sidecar| !matches!(sidecar, super::RetainedOptionalObject::Absent(_)))
            {
                return Err(SqliteRecoveryError::Indeterminate);
            }
            let length = source.inner.database.snapshot.length;
            if length == 0 || length > 128 * 1024 * 1024 {
                return Err(SqliteRecoveryError::Unavailable);
            }
            let mut bytes =
                vec![0; usize::try_from(length).map_err(|_| SqliteRecoveryError::Unavailable)?];
            source
                .inner
                .database
                .descriptor
                .read_exact_at(&mut bytes, 0)
                .map_err(super::indeterminate)?;
            source.revalidate()?;
            source_directories.verify()?;
            self.destination.verify()?;
            let directory = self.destination.directories.directory();
            directory::require_absent(directory, candidate_name)?;
            require_no_sidecars(directory, candidate_name)?;
            let mut file = directory::open_relative(
                directory,
                candidate_name,
                libc::O_WRONLY | libc::O_CREAT | libc::O_EXCL,
            )?;
            #[cfg(test)]
            tests::checkpoint("created")?;
            file.write_all(&bytes).map_err(super::indeterminate)?;
            #[cfg(test)]
            tests::checkpoint("written")?;
            file.sync_all().map_err(super::indeterminate)?;
            #[cfg(test)]
            tests::checkpoint("data-synced")?;
            // SAFETY: file is the still-owned newly created FD. UID is fixed;
            // all-one gid preserves the existing group. No pathname is used.
            if unsafe { libc::fchown(file.as_raw_fd(), directory::OWNER_UID, !0) } != 0 {
                return Err(SqliteRecoveryError::Indeterminate);
            }
            file.set_permissions(std::fs::Permissions::from_mode(0o600))
                .map_err(super::indeterminate)?;
            file.sync_all().map_err(super::indeterminate)?;
            #[cfg(test)]
            tests::checkpoint("ownership-synced")?;
            let candidate = BoundFile::retain(candidate_name, file)?;
            if candidate.snapshot.length != length {
                return Err(SqliteRecoveryError::Indeterminate);
            }
            candidate.verify(directory)?;
            #[cfg(test)]
            tests::checkpoint("before-directory-sync")?;
            directory.sync_all().map_err(super::indeterminate)?;
            #[cfg(test)]
            tests::checkpoint("directory-synced")?;
            let result = RootSqliteOwnerCandidate {
                path: self.destination.path.join(candidate_name),
                candidate,
                source: source.clone(),
                source_directories,
                destination: self.destination,
            };
            result.verify_unchanged()?;
            Ok(result)
        }
        #[cfg(not(unix))]
        {
            let _ = (source, candidate_name);
            Err(SqliteRecoveryError::Unavailable)
        }
    }
}

impl RootSqliteOwnerCandidate {
    pub fn path(&self) -> &Path {
        &self.path
    }

    /// Recheck the same source/candidate/lock/ancestor descriptors, without
    /// opening SQLite, releasing exclusion, or authenticating a Current cut.
    pub fn verify_unchanged(&self) -> Result<(), SqliteRecoveryError> {
        #[cfg(unix)]
        {
            self.destination.verify()?;
            self.source_directories.verify()?;
            self.source.revalidate()?;
            let directory = self.destination.directories.directory();
            self.candidate.verify(directory)?;
            require_no_sidecars(directory, &self.candidate.name)
        }
        #[cfg(not(unix))]
        {
            Err(SqliteRecoveryError::Unavailable)
        }
    }
}

#[cfg(unix)]
fn require_no_sidecars(directory: &File, name: &OsStr) -> Result<(), SqliteRecoveryError> {
    for suffix in ["-wal", "-shm", "-journal"] {
        let mut sidecar = name.to_os_string();
        sidecar.push(suffix);
        directory::require_absent(directory, &sidecar)?;
    }
    Ok(())
}

#[cfg(all(test, unix))]
#[path = "sqlite_root_owner_copy_tests.rs"]
mod tests;
