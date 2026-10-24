//! Compatibility I/O for the existing journals; no new store or authority.

use super::ExistingPrivateDirectoryCandidate;
use super::FreshPrivateDirectory;
use super::OwnerLock;
use super::OwnerLockError;
use super::StageReplaceError;
use super::owner_file::LockedPrivateFile;
use super::owner_file::PrivateFileAccess;
use super::owner_stage::LockedStateStage;
use crate::security::ValidationError;
use std::fs::Metadata;
use std::io;
use std::io::Read;
use std::io::Seek;
use std::io::SeekFrom;
use std::io::Write;

/// Explicit actual namespace inputs; paths, receipts and booleans cannot enter.
/// Neither variant grants marker/schema/journal/frontier recovery authority.
pub enum PrivateStoreDirectory {
    Fresh(FreshPrivateDirectory),
    Existing(ExistingPrivateDirectoryCandidate),
}
impl PrivateStoreDirectory {
    /// Preserve the original marker distinction and real OS-lock contention.
    /// Fresh provisioning flushes its actual namespace before state creation.
    pub fn lock_original_marker(self, leaf: &str) -> Result<OwnerLock, OwnerLockError> {
        match self {
            Self::Fresh(mut directory) => {
                directory.sync_all()?;
                directory.sync_parent_namespace()?;
                directory.lock_owner(leaf)
            }
            Self::Existing(mut candidate) => candidate.lock_existing_owner(leaf),
        }
    }
}

/// The original store's explicit file purpose, never a permission grant.
#[derive(Clone, Copy)]
pub enum OriginalFileAccess {
    Read,
    Write,
    Create,
    Stage,
}
enum Role<'owner> {
    File(LockedPrivateFile<'owner>),
    Stage(LockedStateStage<'owner>),
}

/// One opaque existing-format I/O object borrowing its genuine original lock.
pub struct OriginalStoreFile<'owner> {
    role: Role<'owner>,
}
impl OwnerLock {
    pub fn open_original_file(
        &self,
        leaf: &str,
        maximum: usize,
        access: OriginalFileAccess,
    ) -> Result<OriginalStoreFile<'_>, ValidationError> {
        let role = match access {
            OriginalFileAccess::Read => {
                Role::File(self.open_existing_file(leaf, maximum, PrivateFileAccess::Read)?)
            }
            OriginalFileAccess::Write => {
                Role::File(self.open_existing_file(leaf, maximum, PrivateFileAccess::ReadWrite)?)
            }
            OriginalFileAccess::Create => Role::File(self.create_private_file(leaf, maximum)?),
            OriginalFileAccess::Stage => Role::Stage(self.create_state_stage(leaf, maximum)?),
        };
        Ok(OriginalStoreFile { role })
    }
}
impl OriginalStoreFile<'_> {
    pub fn metadata(&self) -> io::Result<Metadata> {
        match &self.role {
            Role::File(file) => file.metadata(),
            Role::Stage(stage) => stage.metadata(),
        }
    }
    pub fn set_len(&self, length: u64) -> io::Result<()> {
        match &self.role {
            Role::File(file) => file.set_len(length),
            Role::Stage(stage) => stage.set_len(length),
        }
    }
    pub fn sync_all(&self) -> io::Result<()> {
        match &self.role {
            Role::File(file) => file.sync_all(),
            Role::Stage(stage) => stage.sync_all(),
        }
    }
    pub fn replace_synced(&self, leaf: &str) -> Result<(), StageReplaceError> {
        match &self.role {
            Role::Stage(stage) => stage.replace_synced(leaf),
            Role::File(_) => Err(StageReplaceError::BeforePublication(
                ValidationError::UnsafeObject,
            )),
        }
    }
}
impl Read for OriginalStoreFile<'_> {
    fn read(&mut self, bytes: &mut [u8]) -> io::Result<usize> {
        match &mut self.role {
            Role::File(file) => file.read(bytes),
            Role::Stage(_) => Err(io::Error::new(
                io::ErrorKind::Unsupported,
                "stage is write-only",
            )),
        }
    }
}
impl Write for OriginalStoreFile<'_> {
    fn write(&mut self, bytes: &[u8]) -> io::Result<usize> {
        match &mut self.role {
            Role::File(file) => file.write(bytes),
            Role::Stage(stage) => stage.write(bytes),
        }
    }
    fn flush(&mut self) -> io::Result<()> {
        match &mut self.role {
            Role::File(file) => file.flush(),
            Role::Stage(stage) => stage.flush(),
        }
    }
}
impl Seek for OriginalStoreFile<'_> {
    fn seek(&mut self, position: SeekFrom) -> io::Result<u64> {
        match &mut self.role {
            Role::File(file) => file.seek(position),
            Role::Stage(_) => Err(io::Error::new(
                io::ErrorKind::Unsupported,
                "stage is sequential",
            )),
        }
    }
}

#[cfg(test)]
#[path = "original_store_file_tests.rs"]
mod tests;
