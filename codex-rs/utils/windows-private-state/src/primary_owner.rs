//! Live primary-administrator context, without private-namespace authority.

use crate::principal::CapturedPrincipal;
use crate::security::CurrentUser;
use crate::security::ValidationError;
use std::io;
use std::mem::offset_of;
use std::mem::size_of;
use std::os::windows::io::AsRawHandle;
use std::os::windows::io::OwnedHandle;
use std::ptr;
use windows_sys::Win32::Foundation::ERROR_INSUFFICIENT_BUFFER;
use windows_sys::Win32::Foundation::GetHandleInformation;
use windows_sys::Win32::Foundation::HANDLE;
use windows_sys::Win32::Security::GetTokenInformation;
use windows_sys::Win32::Security::SID_AND_ATTRIBUTES;
use windows_sys::Win32::Security::TOKEN_GROUPS;
use windows_sys::Win32::Security::TOKEN_INFORMATION_CLASS;
use windows_sys::Win32::Security::TokenElevation;
use windows_sys::Win32::Security::TokenGroups;
use windows_sys::Win32::Security::TokenHasRestrictions;
use windows_sys::Win32::Security::TokenIsAppContainer;
use windows_sys::Win32::Security::TokenPrimary;
use windows_sys::Win32::Security::TokenType;

const ADMIN_SID: &[u8] = &[1, 2, 0, 0, 0, 0, 0, 5, 32, 0, 0, 0, 32, 2, 0, 0];
const GROUP_ENABLED: u32 = 4;
const GROUP_DENY_ONLY: u32 = 16;
const GROUP_BYTES: usize = 65_536;
const GROUP_COUNT: usize = 256;

fn field(token: HANDLE, class: TOKEN_INFORMATION_CLASS) -> Result<u32, ValidationError> {
    let mut value = u32::MAX;
    let mut returned = 0;
    // SAFETY: only native DWORD fields are requested; the initialized output
    // and exact fixed length remain valid for this synchronous query.
    if unsafe {
        GetTokenInformation(
            token,
            class,
            ptr::from_mut(&mut value).cast(),
            size_of::<u32>() as u32,
            &mut returned,
        )
    } == 0
    {
        return Err(io::Error::last_os_error().into());
    }
    if returned as usize != size_of::<u32>() {
        return Err(ValidationError::MalformedDescriptor);
    }
    Ok(value)
}

fn enabled_administrator(token: HANDLE) -> Result<(), ValidationError> {
    let mut needed = 0;
    // SAFETY: the zero-capacity size query can write only needed.
    if unsafe {
        GetTokenInformation(
            token,
            TokenGroups,
            ptr::null_mut(),
            /*tokeninformationlength*/ 0,
            &mut needed,
        )
    } != 0
    {
        return Err(ValidationError::MalformedDescriptor);
    }
    let error = io::Error::last_os_error();
    if error.raw_os_error() != Some(ERROR_INSUFFICIENT_BUFFER as i32) {
        return Err(error.into());
    }
    let supplied = needed as usize;
    if !(size_of::<TOKEN_GROUPS>()..=GROUP_BYTES).contains(&supplied) {
        return Err(ValidationError::MalformedDescriptor);
    }
    let mut storage = vec![0_usize; supplied.div_ceil(size_of::<usize>())];
    // SAFETY: aligned, initialized owned storage has at least supplied bytes.
    if unsafe {
        GetTokenInformation(
            token,
            TokenGroups,
            storage.as_mut_ptr().cast(),
            needed,
            &mut needed,
        )
    } == 0
    {
        return Err(io::Error::last_os_error().into());
    }
    if needed as usize > supplied || (needed as usize) < size_of::<TOKEN_GROUPS>() {
        return Err(ValidationError::MalformedDescriptor);
    }
    // SAFETY: the fixed header fits and storage has native pointer alignment.
    let count = unsafe { ptr::read(storage.as_ptr().cast::<u32>()) } as usize;
    let start = offset_of!(TOKEN_GROUPS, Groups);
    if count > GROUP_COUNT || start + count * size_of::<SID_AND_ATTRIBUTES>() > needed as usize {
        return Err(ValidationError::MalformedDescriptor);
    }
    // SAFETY: only the initialized, reported token-buffer extent is exposed.
    let bytes =
        unsafe { std::slice::from_raw_parts(storage.as_ptr().cast::<u8>(), needed as usize) };
    let mut administrator = None;
    for index in 0..count {
        // SAFETY: the complete group array was bounded above, and its native
        // base/stride have SID_AND_ATTRIBUTES alignment.
        let group = unsafe {
            ptr::read(
                bytes
                    .as_ptr()
                    .add(start + index * size_of::<SID_AND_ATTRIBUTES>())
                    .cast::<SID_AND_ATTRIBUTES>(),
            )
        };
        let offset = (group.Sid as usize)
            .checked_sub(bytes.as_ptr() as usize)
            .ok_or(ValidationError::MalformedDescriptor)?;
        let tail = bytes
            .get(offset..)
            .ok_or(ValidationError::MalformedDescriptor)?;
        let header = tail.get(..8).ok_or(ValidationError::MalformedDescriptor)?;
        if header[0] != 1 || header[1] > 15 {
            return Err(ValidationError::MalformedDescriptor);
        }
        let sid = tail
            .get(..8 + 4 * usize::from(header[1]))
            .ok_or(ValidationError::MalformedDescriptor)?;
        if sid == ADMIN_SID {
            if administrator.is_some() {
                return Err(ValidationError::MalformedDescriptor);
            }
            administrator =
                Some(group.Attributes & (GROUP_ENABLED | GROUP_DENY_ONLY) == GROUP_ENABLED);
        }
    }
    if administrator != Some(true) {
        return Err(ValidationError::PrincipalChanged);
    }
    Ok(())
}

pub(crate) fn validate_primary(token: &OwnedHandle) -> Result<(), ValidationError> {
    let raw = token.as_raw_handle() as HANDLE;
    let mut flags = u32::MAX;
    // SAFETY: raw is borrowed from the retained query-only token.
    if unsafe { GetHandleInformation(raw, &mut flags) } == 0 {
        return Err(io::Error::last_os_error().into());
    }
    if flags != 0
        || field(raw, TokenType)? != TokenPrimary as u32
        || field(raw, TokenElevation)? != 1
        || field(raw, TokenHasRestrictions)? != 0
        || field(raw, TokenIsAppContainer)? != 0
    {
        return Err(ValidationError::PrincipalChanged);
    }
    enabled_administrator(raw)
}

enum Continuity {
    Live,
    Refused,
}

/// Captures only the actual elevated, unrestricted primary administrator.
///
/// Every impersonation token is refused. No handle, caller-supplied identity,
/// clone, deserialization, directory, or persistent namespace grant is exposed.
/// This is a prerequisite for protected-parent provisioning, never that proof.
pub struct CapturedPrimaryOwner {
    principal: CapturedPrincipal,
    user: CurrentUser,
    continuity: Continuity,
}

impl CapturedPrimaryOwner {
    pub(crate) fn current_user(&mut self) -> Result<&CurrentUser, ValidationError> {
        self.revalidate()?;
        Ok(&self.user)
    }

    /// Query the effective context, requiring it to be the process primary token.
    pub fn capture() -> Result<Self, ValidationError> {
        let mut principal = CapturedPrincipal::capture_effective()?;
        let user = principal.primary_owner_user()?;
        Ok(Self {
            principal,
            user,
            continuity: Continuity::Live,
        })
    }

    /// Recheck the held/current token identities and primary-admin policy.
    /// A query error or any drift permanently refuses this capture.
    pub fn revalidate(&mut self) -> Result<(), ValidationError> {
        if let Continuity::Refused = self.continuity {
            return Err(ValidationError::PrincipalChanged);
        }
        self.continuity = Continuity::Refused;
        if self.principal.primary_owner_user()? != self.user {
            return Err(ValidationError::PrincipalChanged);
        }
        self.continuity = Continuity::Live;
        Ok(())
    }
}

#[cfg(test)]
#[path = "primary_owner_tests.rs"]
mod tests;
