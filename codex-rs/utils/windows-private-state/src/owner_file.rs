//! Bounded file mechanisms borrowing the original exclusive OS lock.

use super::OwnerLock;
use super::owner_read;
use crate::mechanism;
use crate::mechanism::Identity;
use crate::parent_anchor::Continuity;
use crate::parent_anchor::fresh_private_directory::DirectoryContext;
use crate::protected_descriptor::ProtectedDescriptor;
use crate::security::ValidationError;
use std::fs::File;
use std::io;
use std::io::Read;
use std::io::Seek;
use std::io::SeekFrom;
use std::io::Write;
use windows_sys::Win32::Storage::FileSystem::FILE_GENERIC_READ;
use windows_sys::Win32::Storage::FileSystem::FILE_GENERIC_WRITE;

/// Explicit access for one original file; this is not store authority.
#[derive(Clone, Copy)]
pub enum PrivateFileAccess {
    Read,
    ReadWrite,
}
impl PrivateFileAccess {
    fn rights(self) -> u32 {
        match self {
            Self::Read => FILE_GENERIC_READ,
            Self::ReadWrite => FILE_GENERIC_READ | FILE_GENERIC_WRITE,
        }
    }
}

/// One exact private file borrowing, and therefore retaining, the real OS lock.
/// No raw File, cloned handle or deserialization is available. Store consumers
/// must finish their original recovery/trust/frontier checks before writing.
pub struct LockedPrivateFile<'owner> {
    pub(super) file: File,
    pub(super) owner: &'owner OwnerLock,
    identity: Identity,
    maximum: u64,
    access: PrivateFileAccess,
}

impl OwnerLock {
    /// Open an existing original private file. Missing files are never created.
    pub fn open_existing_file(
        &self,
        leaf: &str,
        maximum: usize,
        access: PrivateFileAccess,
    ) -> Result<LockedPrivateFile<'_>, ValidationError> {
        self.open_file(leaf, maximum, access, None)
    }

    /// Atomically create a protected private file, or strictly inspect the exact
    /// existing leaf on native collision. No repair, OPEN_IF or truncation.
    /// This namespace mechanism does not qualify a cold store for writes.
    pub fn create_private_file(
        &self,
        leaf: &str,
        maximum: usize,
    ) -> Result<LockedPrivateFile<'_>, ValidationError> {
        self.open_file(
            leaf,
            maximum,
            PrivateFileAccess::ReadWrite,
            Some(PrivateCreation::Ordinary),
        )
    }

    pub(super) fn open_file(
        &self,
        leaf: &str,
        maximum: usize,
        access: PrivateFileAccess,
        creation: Option<PrivateCreation>,
    ) -> Result<LockedPrivateFile<'_>, ValidationError> {
        if maximum == 0 || maximum > owner_read::MAX_OWNER_READ_BYTES || leaf.len() > 128 {
            return Err(ValidationError::UnsafeObject);
        }
        mechanism::leaf_name(leaf)?;
        let mut held = self
            .context
            .lock()
            .map_err(|_| ValidationError::UnsafeObject)?;
        self.validate_locked(&mut held)?;
        held.continuity = Continuity::Refused;
        let extra_access = match creation {
            Some(PrivateCreation::Stage) => 0x0001_0000,
            Some(PrivateCreation::Ordinary) | None => 0,
        };
        let created = match creation {
            None => None,
            Some(kind) => {
                let descriptor =
                    ProtectedDescriptor::for_user(held.directory.parent.owner.current_user()?)?;
                let mut event = None;
                let result = match kind {
                    PrivateCreation::Ordinary => mechanism::create_protected_file(
                        &held.directory.file,
                        leaf,
                        &descriptor,
                        |value| event = Some(value),
                    ),
                    PrivateCreation::Stage => mechanism::create_protected_stage(
                        &held.directory.file,
                        leaf,
                        &descriptor,
                        |value| event = Some(value),
                    ),
                };
                match (result, event) {
                    (Ok(file), Some(event)) if event.ntstatus == 0 && event.information == 2 => {
                        let identity = owner_read::inspect(&file, &mut held)?;
                        Some((file, identity))
                    }
                    (Err(_), Some(event)) if event.ntstatus == 0xC000_0035_u32 as i32 => None,
                    (Err(error), _) => return Err(error.into()),
                    (Ok(_), _) => return Err(ValidationError::UnsafeObject),
                }
            }
        };
        let (file, identity) = match created {
            Some(value) => value,
            None => owner_read::open(&mut held, leaf, access.rights() | extra_access)?
                .ok_or_else(|| ValidationError::Os(io::Error::from_raw_os_error(2)))?,
        };
        if file.metadata()?.len() > maximum as u64 {
            return Err(ValidationError::UnsafeObject);
        }
        held.continuity = Continuity::Live;
        self.validate_locked(&mut held)?;
        Ok(LockedPrivateFile {
            file,
            owner: self,
            identity,
            maximum: maximum as u64,
            access,
        })
    }
}
pub(super) enum PrivateCreation {
    Ordinary,
    Stage,
}

impl LockedPrivateFile<'_> {
    // Only internal synchronous bounded filesystem operations run while held.
    // No caller callback is accepted by any public method or trait operation.
    fn operate<T>(&mut self, action: impl FnOnce(&mut File) -> io::Result<T>) -> io::Result<T> {
        let mut held = self
            .owner
            .context
            .lock()
            .map_err(|_| io::Error::other("poisoned private owner"))?;
        self.owner
            .validate_locked(&mut held)
            .map_err(io::Error::other)?;
        held.continuity = Continuity::Refused;
        self.inspect(&mut held).map_err(io::Error::other)?;
        let result = action(&mut self.file)?;
        self.inspect(&mut held).map_err(io::Error::other)?;
        held.continuity = Continuity::Live;
        self.owner
            .validate_locked(&mut held)
            .map_err(io::Error::other)?;
        Ok(result)
    }
    pub(super) fn inspect(&self, held: &mut DirectoryContext) -> Result<(), ValidationError> {
        if owner_read::inspect(&self.file, held)? != self.identity
            || self.file.metadata()?.len() > self.maximum
        {
            return Err(ValidationError::UnsafeObject);
        }
        Ok(())
    }
    fn operate_shared<T>(&self, action: impl FnOnce(&File) -> io::Result<T>) -> io::Result<T> {
        let mut held = self
            .owner
            .context
            .lock()
            .map_err(|_| io::Error::other("poisoned private owner"))?;
        self.owner
            .validate_locked(&mut held)
            .map_err(io::Error::other)?;
        held.continuity = Continuity::Refused;
        self.inspect(&mut held).map_err(io::Error::other)?;
        let result = action(&self.file)?;
        self.inspect(&mut held).map_err(io::Error::other)?;
        held.continuity = Continuity::Live;
        self.owner
            .validate_locked(&mut held)
            .map_err(io::Error::other)?;
        Ok(result)
    }
    pub fn metadata(&self) -> io::Result<std::fs::Metadata> {
        self.operate_shared(File::metadata)
    }
    pub fn len(&self) -> io::Result<u64> {
        self.metadata().map(|value| value.len())
    }
    pub fn is_empty(&self) -> io::Result<bool> {
        self.len().map(|length| length == 0)
    }
    pub fn sync_all(&self) -> io::Result<()> {
        self.operate_shared(File::sync_all)
    }
    pub fn set_len(&self, length: u64) -> io::Result<()> {
        if matches!(self.access, PrivateFileAccess::Read) || length > self.maximum {
            return Err(io::Error::new(
                io::ErrorKind::InvalidInput,
                "private file write bound/access",
            ));
        }
        self.operate_shared(|file| file.set_len(length))
    }
}
impl Read for LockedPrivateFile<'_> {
    fn read(&mut self, bytes: &mut [u8]) -> io::Result<usize> {
        let maximum = self.maximum;
        self.operate(|file| {
            let remaining = maximum.saturating_sub(file.stream_position()?);
            let count = bytes.len().min(remaining as usize);
            file.read(&mut bytes[..count])
        })
    }
}
impl Write for LockedPrivateFile<'_> {
    fn write(&mut self, bytes: &[u8]) -> io::Result<usize> {
        if matches!(self.access, PrivateFileAccess::Read) {
            return Err(io::Error::new(
                io::ErrorKind::PermissionDenied,
                "read-only private file",
            ));
        }
        let maximum = self.maximum;
        self.operate(|file| {
            let remaining = maximum.saturating_sub(file.stream_position()?);
            if bytes.len() as u64 > remaining {
                return Err(io::Error::new(
                    io::ErrorKind::InvalidInput,
                    "private file extent bound",
                ));
            }
            file.write(bytes)
        })
    }
    fn flush(&mut self) -> io::Result<()> {
        self.operate(std::io::Write::flush)
    }
}
impl Seek for LockedPrivateFile<'_> {
    fn seek(&mut self, position: SeekFrom) -> io::Result<u64> {
        let maximum = self.maximum;
        self.operate(|file| {
            let target = match position {
                SeekFrom::Start(value) => Some(value),
                SeekFrom::End(offset) => file.metadata()?.len().checked_add_signed(offset),
                SeekFrom::Current(offset) => file.stream_position()?.checked_add_signed(offset),
            }
            .filter(|value| *value <= maximum)
            .ok_or_else(|| {
                io::Error::new(io::ErrorKind::InvalidInput, "private file seek bound")
            })?;
            file.seek(SeekFrom::Start(target))
        })
    }
}

#[cfg(test)]
#[path = "owner_file_tests.rs"]
mod tests;
