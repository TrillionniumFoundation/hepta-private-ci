//! Read-only descriptor observations against a captured effective user.
//!
//! These observations grant no private-owner authority and establish no parent,
//! volume, prior-handle revocation, replay, sandbox or durability qualification.

use crate::mechanism;
use std::ffi::c_void;
use std::fmt;
use std::fs::File;
use std::io;
use std::mem::size_of;
use std::mem::size_of_val;
use std::os::windows::io::AsRawHandle;
use std::os::windows::io::FromRawHandle;
use std::os::windows::io::OwnedHandle;
use std::ptr;
use std::ptr::NonNull;
use windows_sys::Win32::Foundation::ERROR_INSUFFICIENT_BUFFER;
use windows_sys::Win32::Foundation::ERROR_NO_TOKEN;
use windows_sys::Win32::Foundation::HANDLE;
use windows_sys::Win32::Foundation::INVALID_HANDLE_VALUE;
use windows_sys::Win32::Foundation::LocalFree;
use windows_sys::Win32::Security::Authorization::GetSecurityInfo;
use windows_sys::Win32::Security::Authorization::SE_FILE_OBJECT;
use windows_sys::Win32::Security::DACL_SECURITY_INFORMATION;
use windows_sys::Win32::Security::GetLengthSid;
use windows_sys::Win32::Security::GetSecurityDescriptorLength;
use windows_sys::Win32::Security::GetTokenInformation;
use windows_sys::Win32::Security::IsValidSecurityDescriptor;
use windows_sys::Win32::Security::IsValidSid;
use windows_sys::Win32::Security::OWNER_SECURITY_INFORMATION;
use windows_sys::Win32::Security::SE_DACL_AUTO_INHERIT_REQ;
use windows_sys::Win32::Security::SE_DACL_AUTO_INHERITED;
use windows_sys::Win32::Security::SE_DACL_DEFAULTED;
use windows_sys::Win32::Security::SE_DACL_PRESENT;
use windows_sys::Win32::Security::SE_DACL_PROTECTED;
use windows_sys::Win32::Security::SE_SELF_RELATIVE;
use windows_sys::Win32::Security::TOKEN_QUERY;
use windows_sys::Win32::Security::TOKEN_USER;
use windows_sys::Win32::Security::TokenUser;
use windows_sys::Win32::Storage::FileSystem::FILE_ALL_ACCESS;
use windows_sys::Win32::Storage::FileSystem::FILE_ATTRIBUTE_DIRECTORY;
use windows_sys::Win32::Storage::FileSystem::FILE_ATTRIBUTE_REPARSE_POINT;
use windows_sys::Win32::System::Memory::LocalSize;
use windows_sys::Win32::System::Threading::GetCurrentProcess;
use windows_sys::Win32::System::Threading::GetCurrentThread;
use windows_sys::Win32::System::Threading::OpenProcessToken;
use windows_sys::Win32::System::Threading::OpenThreadToken;

/// A failed observation never repairs or authorizes the existing object.
#[derive(Debug)]
pub enum ValidationError {
    Os(io::Error),
    MalformedDescriptor,
    WrongOwner,
    UnprotectedDacl,
    NonCanonicalDacl,
    UnsafeObject,
}

impl From<io::Error> for ValidationError {
    fn from(error: io::Error) -> Self {
        Self::Os(error)
    }
}

impl fmt::Display for ValidationError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Os(error) => error.fmt(formatter),
            other => write!(
                formatter,
                "Windows descriptor observation rejected: {other:?}"
            ),
        }
    }
}

impl std::error::Error for ValidationError {}

#[derive(Eq, PartialEq)]
#[repr(C, align(4))]
struct Sid {
    bytes: [u8; 68],
    length: usize,
}

impl Sid {
    fn read(bytes: &[u8]) -> Result<Self, ValidationError> {
        let header = bytes.get(..8).ok_or(ValidationError::MalformedDescriptor)?;
        if header[0] != 1 || header[1] > 15 {
            return Err(ValidationError::MalformedDescriptor);
        }
        let length = 8 + usize::from(header[1]) * 4;
        let source = bytes
            .get(..length)
            .ok_or(ValidationError::MalformedDescriptor)?;
        let mut sid = Self {
            bytes: [0; 68],
            length,
        };
        sid.bytes[..length].copy_from_slice(source);
        // SAFETY: the complete bounded SID was copied into four-byte-aligned
        // owned storage; its revision/count cannot address beyond this buffer.
        let raw = sid.bytes.as_mut_ptr().cast();
        if unsafe { IsValidSid(raw) } == 0 || unsafe { GetLengthSid(raw) } as usize != length {
            return Err(ValidationError::MalformedDescriptor);
        }
        Ok(sid)
    }
}

/// Captured TokenUser SID, not TokenOwner, group membership or an owner guard.
pub struct CurrentUser {
    sid: Sid,
}

impl CurrentUser {
    /// Capture the thread token when impersonating; only NO_TOKEN falls back.
    pub fn capture_effective() -> Result<Self, ValidationError> {
        let mut raw = 0;
        // SAFETY: current-thread pseudo-handle is live, output is writable;
        // OpenAsSelf affects opening access, not which thread token is returned.
        if unsafe {
            OpenThreadToken(
                GetCurrentThread(),
                TOKEN_QUERY,
                /*openasself*/ 1,
                &mut raw,
            )
        } == 0
        {
            let error = io::Error::last_os_error();
            if error.raw_os_error() != Some(ERROR_NO_TOKEN as i32) {
                return Err(error.into());
            }
            // SAFETY: current-process pseudo-handle is live and output writable.
            if unsafe { OpenProcessToken(GetCurrentProcess(), TOKEN_QUERY, &mut raw) } == 0 {
                return Err(io::Error::last_os_error().into());
            }
        }
        if raw == 0 || raw == INVALID_HANDLE_VALUE {
            return Err(io::Error::other("token open returned an invalid handle").into());
        }
        // SAFETY: successful token open transfers one owned non-inherited handle.
        let token = unsafe { OwnedHandle::from_raw_handle(raw as *mut c_void) };
        let mut needed = 0;
        // SAFETY: the null/zero query writes only needed, while token stays live.
        let result = unsafe {
            GetTokenInformation(
                token.as_raw_handle() as HANDLE,
                TokenUser,
                ptr::null_mut(),
                /*tokeninformationlength*/ 0,
                &mut needed,
            )
        };
        if result != 0 {
            return Err(ValidationError::MalformedDescriptor);
        }
        let error = io::Error::last_os_error();
        if error.raw_os_error() != Some(ERROR_INSUFFICIENT_BUFFER as i32) {
            return Err(error.into());
        }
        // TokenUser is a fixed header plus a SID (at most 68 bytes). Bound the
        // kernel output, keeping TOKEN_USER pointer alignment without Vec<u8>.
        let mut buffer = [0_usize; 512 / size_of::<usize>()];
        if needed < size_of::<TOKEN_USER>() as u32 || needed as usize > size_of_val(&buffer) {
            return Err(ValidationError::MalformedDescriptor);
        }
        let supplied = needed;
        // SAFETY: aligned stack storage has the advertised writable byte size.
        if unsafe {
            GetTokenInformation(
                token.as_raw_handle() as HANDLE,
                TokenUser,
                buffer.as_mut_ptr().cast(),
                needed,
                &mut needed,
            )
        } == 0
        {
            return Err(io::Error::last_os_error().into());
        }
        if needed < size_of::<TOKEN_USER>() as u32 || needed > supplied {
            return Err(ValidationError::MalformedDescriptor);
        }
        // SAFETY: fixed header fits in the initialized, suitably aligned buffer.
        let user = unsafe { ptr::read(buffer.as_ptr().cast::<TOKEN_USER>()) };
        let offset = (user.User.Sid as usize)
            .checked_sub(buffer.as_ptr() as usize)
            .filter(|offset| *offset >= size_of::<TOKEN_USER>() && *offset < needed as usize)
            .ok_or(ValidationError::MalformedDescriptor)?;
        // SAFETY: range is within initialized live owned stack storage. Sid::read
        // bounds/copies the complete SID before calling any native SID function.
        let bytes = unsafe {
            std::slice::from_raw_parts(
                buffer.as_ptr().cast::<u8>().add(offset),
                needed as usize - offset,
            )
        };
        Ok(Self {
            sid: Sid::read(bytes)?,
        })
    }
}

struct LocalDescriptor(NonNull<c_void>);

impl Drop for LocalDescriptor {
    fn drop(&mut self) {
        // SAFETY: GetSecurityInfo allocated this descriptor once with LocalAlloc.
        unsafe {
            LocalFree(self.0.as_ptr());
        }
    }
}

impl LocalDescriptor {
    fn read(file: &File) -> Result<Self, ValidationError> {
        let mut raw = ptr::null_mut();
        // SAFETY: borrow the live File, request a single owned descriptor; no
        // borrowed component pointer or raw allocation escapes this module.
        let code = unsafe {
            GetSecurityInfo(
                file.as_raw_handle() as HANDLE,
                SE_FILE_OBJECT,
                OWNER_SECURITY_INFORMATION | DACL_SECURITY_INFORMATION,
                ptr::null_mut(),
                ptr::null_mut(),
                ptr::null_mut(),
                ptr::null_mut(),
                &mut raw,
            )
        };
        let owned = NonNull::new(raw).map(Self);
        if code != 0 {
            return Err(io::Error::from_raw_os_error(code as i32).into());
        }
        owned.ok_or(ValidationError::MalformedDescriptor)
    }

    fn bytes(&self) -> Result<&[u8], ValidationError> {
        // SAFETY: this is the still-live LocalAlloc allocation, not a component.
        let allocated = unsafe { LocalSize(self.0.as_ptr()) };
        if !(20..=1_048_576).contains(&allocated) {
            return Err(ValidationError::MalformedDescriptor);
        }
        // SAFETY: successful GetSecurityInfo returns a complete native descriptor.
        // Use its initialized length, not possibly uninitialized allocator padding.
        let length = unsafe { GetSecurityDescriptorLength(self.0.as_ptr()) } as usize;
        if !(20..=allocated).contains(&length)
            || unsafe { IsValidSecurityDescriptor(self.0.as_ptr()) } == 0
        {
            return Err(ValidationError::MalformedDescriptor);
        }
        // SAFETY: the initialized descriptor fits its still-live allocation.
        Ok(unsafe { std::slice::from_raw_parts(self.0.as_ptr().cast(), length) })
    }
}

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

fn validate_descriptor(bytes: &[u8], current: &CurrentUser) -> Result<(), ValidationError> {
    // GetSecurityInfo requested only owner/DACL: reject unexpected components
    // rather than dereferencing an unvalidated group or SACL offset.
    if bytes.get(..2) != Some(&[1, 0])
        || dword(bytes, /*offset*/ 8)? != 0
        || dword(bytes, /*offset*/ 12)? != 0
        || word(bytes, /*offset*/ 2)? & SE_SELF_RELATIVE == 0
    {
        return Err(ValidationError::MalformedDescriptor);
    }
    let control = word(bytes, /*offset*/ 2)?;
    if control & (SE_DACL_PRESENT | SE_DACL_PROTECTED) != SE_DACL_PRESENT | SE_DACL_PROTECTED {
        return Err(ValidationError::UnprotectedDacl);
    }
    if control & (SE_DACL_DEFAULTED | SE_DACL_AUTO_INHERITED | SE_DACL_AUTO_INHERIT_REQ) != 0 {
        return Err(ValidationError::NonCanonicalDacl);
    }
    let owner = Sid::read(component(bytes, dword(bytes, /*offset*/ 4)?)?)?;
    if owner != current.sid {
        return Err(ValidationError::WrongOwner);
    }
    let acl = component(bytes, dword(bytes, /*offset*/ 16)?)?;
    if acl.get(..2) != Some(&[2, 0])
        || word(acl, /*offset*/ 4)? != 1
        || word(acl, /*offset*/ 6)? != 0
    {
        return Err(ValidationError::NonCanonicalDacl);
    }
    let acl = acl
        .get(..usize::from(word(acl, /*offset*/ 2)?))
        .ok_or(ValidationError::MalformedDescriptor)?;
    let ace = acl.get(8..).ok_or(ValidationError::MalformedDescriptor)?;
    // Only one ordinary explicit owner allow ACE, with exact file full control.
    // No System/Admin/group exception, generic masks, inherited or special ACEs.
    if ace.get(..2) != Some(&[0, 0])
        || usize::from(word(ace, /*offset*/ 2)?) != ace.len()
        || dword(ace, /*offset*/ 4)? != FILE_ALL_ACCESS
    {
        return Err(ValidationError::NonCanonicalDacl);
    }
    let trustee = Sid::read(ace.get(8..).ok_or(ValidationError::MalformedDescriptor)?)?;
    if trustee != current.sid || ace.len() != 8 + trustee.length {
        return Err(ValidationError::NonCanonicalDacl);
    }
    Ok(())
}

/// Required held-object shape; this does not validate the parent or volume.
#[derive(Clone, Copy)]
pub enum ObjectKind {
    Directory,
    SingleLinkFile,
}

/// A point-in-time readback, never a private owner or persistent access grant.
pub struct DescriptorObservation {
    pub identity: mechanism::Identity,
}

/// Observe a sole-owner protected DACL against the captured effective user.
///
/// Reads only the held handle. It does not change ACLs, revoke earlier handles,
/// freeze future descriptor changes, validate ancestors, or admit an owner store.
pub fn validate_owner_descriptor(
    file: &File,
    current: &CurrentUser,
    kind: ObjectKind,
) -> Result<DescriptorObservation, ValidationError> {
    let identity = mechanism::identity(file)?;
    let directory = identity.attributes & FILE_ATTRIBUTE_DIRECTORY != 0;
    if identity.attributes & FILE_ATTRIBUTE_REPARSE_POINT != 0
        || match kind {
            ObjectKind::Directory => !directory,
            ObjectKind::SingleLinkFile => directory || identity.links != 1,
        }
    {
        return Err(ValidationError::UnsafeObject);
    }
    let descriptor = LocalDescriptor::read(file)?;
    validate_descriptor(descriptor.bytes()?, current)?;
    Ok(DescriptorObservation { identity })
}

#[cfg(test)]
#[path = "security_tests.rs"]
mod tests;
