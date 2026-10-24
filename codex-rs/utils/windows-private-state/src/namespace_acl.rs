//! Internal ancestor policy. A descriptor observation alone grants no capability.

use crate::mechanism;
use crate::security::CurrentUser;
use crate::security::LocalDescriptor;
use crate::security::ValidationError;
use std::fs::File;
use windows_sys::Win32::Foundation::GENERIC_EXECUTE;
use windows_sys::Win32::Foundation::GENERIC_READ;
use windows_sys::Win32::Storage::FileSystem::FILE_ADD_SUBDIRECTORY;
use windows_sys::Win32::Storage::FileSystem::FILE_ATTRIBUTE_DIRECTORY;
use windows_sys::Win32::Storage::FileSystem::FILE_ATTRIBUTE_REPARSE_POINT;
use windows_sys::Win32::Storage::FileSystem::FILE_GENERIC_EXECUTE;
use windows_sys::Win32::Storage::FileSystem::FILE_GENERIC_READ;

const SYSTEM_SID: &[u8] = &[1, 1, 0, 0, 0, 0, 0, 5, 18, 0, 0, 0];
const ADMIN_SID: &[u8] = &[1, 2, 0, 0, 0, 0, 0, 5, 32, 0, 0, 0, 32, 2, 0, 0];
const INHERIT_ONLY: u8 = 8;
const SELF_RELATIVE_DACL_PRESENT: u16 = 0x8004;

fn word(bytes: &[u8], offset: usize) -> Result<u16, ValidationError> {
    let value = bytes
        .get(offset..offset + 2)
        .ok_or(ValidationError::MalformedDescriptor)?;
    Ok(u16::from_le_bytes([value[0], value[1]]))
}

fn dword(bytes: &[u8], offset: usize) -> Result<u32, ValidationError> {
    let value = bytes
        .get(offset..offset + 4)
        .ok_or(ValidationError::MalformedDescriptor)?;
    Ok(u32::from_le_bytes([value[0], value[1], value[2], value[3]]))
}

fn component(bytes: &[u8], offset: u32) -> Result<&[u8], ValidationError> {
    if offset < 20 || !offset.is_multiple_of(4) {
        return Err(ValidationError::MalformedDescriptor);
    }
    bytes
        .get(offset as usize..)
        .ok_or(ValidationError::MalformedDescriptor)
}

fn sid(bytes: &[u8]) -> Result<&[u8], ValidationError> {
    let header = bytes.get(..8).ok_or(ValidationError::MalformedDescriptor)?;
    if header[0] != 1 || header[1] > 15 {
        return Err(ValidationError::MalformedDescriptor);
    }
    bytes
        .get(..8 + 4 * usize::from(header[1]))
        .ok_or(ValidationError::MalformedDescriptor)
}

fn trusted(sid: &[u8], user: &CurrentUser) -> bool {
    sid == user.sid_bytes() || sid == SYSTEM_SID || sid == ADMIN_SID
}

fn validate(bytes: &[u8], user: &CurrentUser) -> Result<(), ValidationError> {
    if bytes.len() > 65_536
        || bytes.get(..2) != Some(&[1, 0])
        || word(bytes, /*offset*/ 2)? & SELF_RELATIVE_DACL_PRESENT != SELF_RELATIVE_DACL_PRESENT
        || dword(bytes, /*offset*/ 8)? != 0
        || dword(bytes, /*offset*/ 12)? != 0
    {
        return Err(ValidationError::MalformedDescriptor);
    }
    if !trusted(sid(component(bytes, dword(bytes, /*offset*/ 4)?)?)?, user) {
        return Err(ValidationError::WrongOwner);
    }
    let acl = component(bytes, dword(bytes, /*offset*/ 16)?)?;
    if !matches!(acl.first(), Some(2 | 4))
        || acl.get(1) != Some(&0)
        || word(acl, /*offset*/ 6)? != 0
    {
        return Err(ValidationError::NonCanonicalDacl);
    }
    let acl = acl
        .get(..usize::from(word(acl, /*offset*/ 2)?))
        .filter(|acl| acl.len() >= 8)
        .ok_or(ValidationError::MalformedDescriptor)?;
    let count = word(acl, /*offset*/ 4)?;
    if count > 256 {
        return Err(ValidationError::MalformedDescriptor);
    }
    let mut cursor = 8;
    for _ in 0..count {
        let tail = acl
            .get(cursor..)
            .ok_or(ValidationError::MalformedDescriptor)?;
        let length = usize::from(word(tail, /*offset*/ 2)?);
        if length < 16 || !length.is_multiple_of(4) {
            return Err(ValidationError::MalformedDescriptor);
        }
        let ace = tail
            .get(..length)
            .ok_or(ValidationError::MalformedDescriptor)?;
        if !matches!(ace[0], 0 | 1) || ace[1] & !0x1f != 0 {
            return Err(ValidationError::NonCanonicalDacl);
        }
        let trustee = sid(&ace[8..])?;
        if trustee.len() + 8 != ace.len() {
            return Err(ValidationError::MalformedDescriptor);
        }
        if ace[0] == 0 && ace[1] & INHERIT_ONLY == 0 && !trusted(trustee, user) {
            // Directory ADD_SUBDIRECTORY creates a different child; it cannot
            // replace an existing protected name. Consumers still must use
            // atomic protected CREATE_NEW and refuse pre-existing impostors.
            // DELETE_CHILD/DELETE, WRITE_DAC/OWNER, file creation, attribute/EA
            // changes, generic write/all and unknown rights remain refused.
            let allowed = FILE_GENERIC_READ
                | FILE_GENERIC_EXECUTE
                | FILE_ADD_SUBDIRECTORY
                | GENERIC_READ
                | GENERIC_EXECUTE;
            if dword(ace, /*offset*/ 4)? & !allowed != 0 {
                return Err(ValidationError::NonCanonicalDacl);
            }
        }
        cursor += length;
    }
    Ok(())
}

pub(crate) fn observe_directory(
    file: &File,
    user: &CurrentUser,
) -> Result<mechanism::Identity, ValidationError> {
    let before = mechanism::identity(file)?;
    if before.attributes & FILE_ATTRIBUTE_DIRECTORY == 0
        || before.attributes & FILE_ATTRIBUTE_REPARSE_POINT != 0
    {
        return Err(ValidationError::UnsafeObject);
    }
    validate(LocalDescriptor::read(file)?.bytes()?, user)?;
    if mechanism::identity(file)? != before {
        return Err(ValidationError::UnsafeObject);
    }
    Ok(before)
}

#[cfg(test)]
#[path = "namespace_acl_tests.rs"]
mod tests;
