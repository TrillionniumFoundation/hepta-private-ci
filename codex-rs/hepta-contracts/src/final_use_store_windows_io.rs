//! Windows storage adapters preserve the established path owner while keeping
//! explicit held namespace capabilities distinct.

use std::fs::File;
use std::io;
use std::io::Read;
use std::io::Seek;
use std::io::SeekFrom;
use std::io::Write;
use std::path::Path;

use super::FinalUseError;
use super::io::Access;
use super::io::LockedDirectory;
use super::windows;
use crate::windows_private_owner::OriginalFileAccess;
use crate::windows_private_owner::OriginalStoreFile;
use crate::windows_private_owner::OwnerLock;
use crate::windows_private_owner::OwnerLockError;
use crate::windows_private_owner::OwnerLockOrigin;
use crate::windows_private_owner::PrivateStoreDirectory;

/// This distinction is chosen by the original constructor, never a wire flag.
pub(super) enum Directory {
    Path(File),
    Held(OwnerLock),
}

impl Directory {
    pub(super) fn sync_all(&self) -> Result<(), FinalUseError> {
        match self {
            Self::Path(root) => root.sync_all().map_err(|_| FinalUseError::Unavailable),
            Self::Held(root) => root.sync_all().map_err(|_| FinalUseError::Unavailable),
        }
    }

    pub(super) fn revalidate_held_owner(&self) -> Result<(), FinalUseError> {
        match self {
            // Preserve the existing path owner's checks at each file operation.
            // It is not converted into a held original-marker capability.
            Self::Path(_) => Ok(()),
            Self::Held(root) => root
                .revalidate_shared()
                .map_err(|_| FinalUseError::Unavailable),
        }
    }
}

pub(super) enum StoreFile<'owner> {
    Path(File),
    Held(OriginalStoreFile<'owner>),
}

impl StoreFile<'_> {
    pub(super) fn set_len(&self, length: u64) -> io::Result<()> {
        match self {
            Self::Path(file) => file.set_len(length),
            Self::Held(file) => file.set_len(length),
        }
    }

    pub(super) fn sync_all(&self) -> io::Result<()> {
        match self {
            Self::Path(file) => file.sync_all(),
            Self::Held(file) => file.sync_all(),
        }
    }
}

impl Read for StoreFile<'_> {
    fn read(&mut self, bytes: &mut [u8]) -> io::Result<usize> {
        match self {
            Self::Path(file) => file.read(bytes),
            Self::Held(file) => file.read(bytes),
        }
    }
}

impl Write for StoreFile<'_> {
    fn write(&mut self, bytes: &[u8]) -> io::Result<usize> {
        match self {
            Self::Path(file) => file.write(bytes),
            Self::Held(file) => file.write(bytes),
        }
    }

    fn flush(&mut self) -> io::Result<()> {
        match self {
            Self::Path(file) => file.flush(),
            Self::Held(file) => file.flush(),
        }
    }
}

impl Seek for StoreFile<'_> {
    fn seek(&mut self, position: SeekFrom) -> io::Result<u64> {
        match self {
            Self::Path(file) => file.seek(position),
            Self::Held(file) => file.seek(position),
        }
    }
}

pub(super) fn lock_directory(path: &Path) -> Result<LockedDirectory, FinalUseError> {
    let root = windows::prepare_directory(path)?;
    let initialized = windows::entry_exists(&root, "authority.lock")?;
    let lock = windows::open_private(&root, "authority.lock", Access::Create)?;
    lock.try_lock().map_err(|_| FinalUseError::StateLocked)?;
    Ok(LockedDirectory {
        root: Directory::Path(root),
        initialized,
        lock: Some(lock),
    })
}

impl LockedDirectory {
    pub(super) fn from_windows(input: PrivateStoreDirectory) -> Result<Self, FinalUseError> {
        let root = input
            .lock_original_marker("authority.lock")
            .map_err(|error| match error {
                OwnerLockError::StateLocked => FinalUseError::StateLocked,
                OwnerLockError::Rejected(_) => FinalUseError::UnsafeStateDirectory,
            })?;
        let initialized = root.origin() == &OwnerLockOrigin::Existing;
        Ok(Self {
            root: Directory::Held(root),
            initialized,
            lock: None,
        })
    }
}

pub(super) fn open_private<'owner>(
    directory: &'owner Directory,
    name: &str,
    access: Access,
) -> Result<StoreFile<'owner>, FinalUseError> {
    match directory {
        Directory::Path(root) => windows::open_private(root, name, access).map(StoreFile::Path),
        Directory::Held(root) => {
            let access = match access {
                Access::Read => OriginalFileAccess::Read,
                Access::Write => OriginalFileAccess::Write,
                Access::Create => OriginalFileAccess::Stage,
            };
            root.open_original_file(name, /*maximum*/ 64 * 1024 * 1024, access)
                .map(StoreFile::Held)
                .map_err(|_| FinalUseError::Unavailable)
        }
    }
}

pub(super) fn entry_exists(directory: &Directory, name: &str) -> Result<bool, FinalUseError> {
    match directory {
        Directory::Path(root) => windows::entry_exists(root, name),
        Directory::Held(root) => root
            .entry_exists(name)
            .map_err(|_| FinalUseError::Unavailable),
    }
}

pub(super) fn replace_state(
    directory: &Directory,
    stage: &StoreFile<'_>,
) -> Result<(), FinalUseError> {
    match (directory, stage) {
        (Directory::Path(root), StoreFile::Path(_)) => windows::replace_state(root),
        (Directory::Held(_), StoreFile::Held(stage)) => stage
            .replace_synced("authority.json")
            .map_err(|_| FinalUseError::Unavailable),
        _ => Err(FinalUseError::UnsafeStateDirectory),
    }
}

pub(super) fn replace_claims(
    directory: &Directory,
    stage: &StoreFile<'_>,
) -> Result<(), FinalUseError> {
    match (directory, stage) {
        (Directory::Path(root), StoreFile::Path(_)) => windows::replace_claims(root),
        (Directory::Held(_), StoreFile::Held(stage)) => stage
            .replace_synced("authority.claims")
            .map_err(|_| FinalUseError::Unavailable),
        _ => Err(FinalUseError::UnsafeStateDirectory),
    }
}

pub(super) fn validate_windows_prewrite(
    directory: &Directory,
    state: &super::State,
    initial: &super::FinalUseRevocations,
    signer_id: &str,
    frontier: Option<&dyn crate::AuthorityFrontierStore<super::super::FinalUseFrontier>>,
) -> Result<(), FinalUseError> {
    if matches!(directory, Directory::Path(_)) {
        // The ordinary constructor retains its original recovery semantics.
        // Only the explicit held-owner constructor makes the stronger promise.
        return Ok(());
    }
    if &state.head != initial {
        return Err(FinalUseError::InvalidTrust);
    }
    let trusted = frontier
        .ok_or(FinalUseError::Unavailable)?
        .load(signer_id)
        .map_err(super::super::map_trust_error)?;
    if trusted != super::super::frontier_for_state(state) {
        return Err(FinalUseError::AntiRollbackViolation);
    }
    Ok(())
}
