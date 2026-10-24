//! Bounded reads under the actual original owner lock; no File escapes.

use super::OwnerLock;
use crate::mechanism;
use crate::mechanism::Identity;
use crate::parent_anchor::Continuity;
use crate::parent_anchor::fresh_private_directory::DirectoryContext;
use crate::parent_anchor::non_inherited;
use crate::security::ObjectKind;
use crate::security::ValidationError;
use crate::security::validate_owner_descriptor;
use crate::volume::inspect_local_ntfs;
use std::fs::File;
use std::io;
use std::io::Read;
use windows_sys::Win32::Storage::FileSystem::FILE_GENERIC_READ;
use windows_sys::Win32::Storage::FileSystem::FILE_SHARE_READ;
use windows_sys::Win32::Storage::FileSystem::FILE_SHARE_WRITE;

const MAX_OWNER_READ_BYTES: usize = 64 * 1024 * 1024;

fn inspect(file: &File, held: &mut DirectoryContext) -> Result<Identity, ValidationError> {
    non_inherited(file)?;
    let observed = validate_owner_descriptor(
        file,
        held.directory.parent.owner.current_user()?,
        ObjectKind::SingleLinkFile,
    )?;
    if observed.identity.volume != held.identity.volume
        || inspect_local_ntfs(file)?.object != observed.identity
    {
        return Err(ValidationError::UnsafeObject);
    }
    Ok(observed.identity)
}

fn open(
    held: &mut DirectoryContext,
    leaf: &str,
) -> Result<Option<(File, Identity)>, ValidationError> {
    if leaf.len() > 128 {
        return Err(ValidationError::UnsafeObject);
    }
    mechanism::leaf_name(leaf)?;
    let mut event = None;
    let result = mechanism::open_relative(
        &held.directory.file,
        leaf,
        FILE_GENERIC_READ,
        FILE_SHARE_READ | FILE_SHARE_WRITE,
        mechanism::FILE_OPEN,
        |value| event = Some(value),
    );
    let file = match (result, event) {
        // STATUS_OBJECT_NAME_NOT_FOUND, never sharing/ACL/I/O or an unsafe object.
        (Err(error), Some(event))
            if error.raw_os_error() == Some(2) && event.ntstatus == 0xC000_0034_u32 as i32 =>
        {
            return Ok(None);
        }
        (Ok(file), Some(event)) if event.ntstatus == 0 && event.information == 1 => file,
        (Err(error), _) => return Err(error.into()),
        (Ok(_), _) => return Err(ValidationError::UnsafeObject),
    };
    let identity = inspect(&file, held)?;
    Ok(Some((file, identity)))
}

impl OwnerLock {
    /// Inspect one existing private regular leaf; only an exact native missing
    /// name returns false. This never creates, follows, repairs or truncates.
    pub fn entry_exists(&self, leaf: &str) -> Result<bool, ValidationError> {
        let mut held = self
            .context
            .lock()
            .map_err(|_| ValidationError::UnsafeObject)?;
        self.validate_locked(&mut held)?;
        held.continuity = Continuity::Refused;
        let observed = open(&mut held, leaf)?;
        let exists = observed.is_some();
        drop(observed);
        held.continuity = Continuity::Live;
        self.validate_locked(&mut held)?;
        Ok(exists)
    }

    /// Read a bounded original snapshot/journal while retaining the OS lock.
    /// Consumer-specific original limits remain mandatory; this primitive also
    /// imposes a 64 MiB hard ceiling, including the original 40 MiB claim log.
    /// Any size/identity/descriptor/owner change permanently refuses the role.
    pub fn read_bounded(&self, leaf: &str, maximum: usize) -> Result<Vec<u8>, ValidationError> {
        if maximum == 0 || maximum > MAX_OWNER_READ_BYTES {
            return Err(ValidationError::UnsafeObject);
        }
        let mut held = self
            .context
            .lock()
            .map_err(|_| ValidationError::UnsafeObject)?;
        self.validate_locked(&mut held)?;
        held.continuity = Continuity::Refused;
        let (mut file, identity) = open(&mut held, leaf)?
            .ok_or_else(|| ValidationError::Os(io::Error::from_raw_os_error(2)))?;
        let before = file.metadata()?.len();
        if before > maximum as u64 {
            return Err(ValidationError::UnsafeObject);
        }
        let mut bytes = Vec::new();
        (&mut file)
            .take(maximum as u64 + 1)
            .read_to_end(&mut bytes)?;
        if bytes.len() > maximum
            || bytes.len() as u64 != before
            || file.metadata()?.len() != before
            || inspect(&file, &mut held)? != identity
        {
            return Err(ValidationError::UnsafeObject);
        }
        drop(file);
        held.continuity = Continuity::Live;
        self.validate_locked(&mut held)?;
        Ok(bytes)
    }
}

#[cfg(test)]
#[path = "owner_read_tests.rs"]
mod tests;
