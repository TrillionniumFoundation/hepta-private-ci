//! Handle-based Windows identities and owner-only creation descriptors.

mod acl;

pub(crate) use acl::SecuritySnapshot;
pub(crate) use acl::private_security;

use std::ffi::c_void;
use std::io;
use std::mem::size_of;
use std::os::windows::io::AsHandle;
use std::os::windows::io::AsRawHandle;
use std::os::windows::io::BorrowedHandle;
use std::os::windows::io::FromRawHandle;
use std::os::windows::io::OwnedHandle;
use std::ptr;
use std::ptr::NonNull;

use windows_sys::Win32::Foundation::ERROR_INSUFFICIENT_BUFFER;
use windows_sys::Win32::Foundation::ERROR_NO_TOKEN;
use windows_sys::Win32::Foundation::LocalFree;
use windows_sys::Win32::Security::Authorization::ConvertStringSecurityDescriptorToSecurityDescriptorW;
use windows_sys::Win32::Security::Authorization::GetSecurityInfo;
use windows_sys::Win32::Security::Authorization::SDDL_REVISION_1;
use windows_sys::Win32::Security::Authorization::SE_FILE_OBJECT;
use windows_sys::Win32::Security::GetLengthSid;
use windows_sys::Win32::Security::GetSecurityDescriptorLength;
use windows_sys::Win32::Security::GetSecurityDescriptorOwner;
use windows_sys::Win32::Security::GetTokenInformation;
use windows_sys::Win32::Security::IsValidSecurityDescriptor;
use windows_sys::Win32::Security::IsValidSid;
use windows_sys::Win32::Security::OWNER_SECURITY_INFORMATION;
use windows_sys::Win32::Security::PSID;
use windows_sys::Win32::Security::SECURITY_MAX_SID_SIZE;
use windows_sys::Win32::Security::TOKEN_INFORMATION_CLASS;
use windows_sys::Win32::Security::TOKEN_OWNER;
use windows_sys::Win32::Security::TOKEN_QUERY;
use windows_sys::Win32::Security::TOKEN_USER;
use windows_sys::Win32::Security::TokenOwner as TOKEN_OWNER_CLASS;
use windows_sys::Win32::Security::TokenUser as TOKEN_USER_CLASS;
use windows_sys::Win32::System::Threading::GetCurrentProcess;
use windows_sys::Win32::System::Threading::GetCurrentThread;
use windows_sys::Win32::System::Threading::OpenProcessToken;
use windows_sys::Win32::System::Threading::OpenThreadToken;

/// An owned, validated SID. Equality compares the complete binary identity.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct Sid {
    words: Vec<u32>,
    length: usize,
}

impl Sid {
    fn from_bytes(bytes: &[u8]) -> io::Result<Self> {
        if bytes.len() < 8
            || bytes[0] != 1
            || bytes[1] > 15
            || bytes.len() != 8 + usize::from(bytes[1]) * 4
        {
            return Err(invalid_security("invalid SID encoding"));
        }
        let mut sid = Self {
            words: vec![0; bytes.len().div_ceil(size_of::<u32>())],
            length: bytes.len(),
        };
        // SAFETY: the u32 allocation has enough initialized bytes and is
        // disjoint from the input. Its alignment also satisfies SID alignment.
        unsafe {
            ptr::copy_nonoverlapping(bytes.as_ptr(), sid.words.as_mut_ptr().cast(), bytes.len());
        }
        Ok(sid)
    }

    /// Returns the SID bytes without exposing an OS-owned allocation.
    pub fn as_bytes(&self) -> &[u8] {
        // SAFETY: length is bounded by the initialized, immutable allocation.
        unsafe { std::slice::from_raw_parts(self.words.as_ptr().cast(), self.length) }
    }

    /// Formats this identity for Windows security descriptor strings.
    pub fn to_sddl(&self) -> String {
        let bytes = self.as_bytes();
        let authority = bytes[2..8]
            .iter()
            .fold(0_u64, |value, byte| (value << 8) | u64::from(*byte));
        let mut value = format!("S-1-{authority}");
        for part in bytes[8..].chunks_exact(4) {
            let number = u32::from_le_bytes([part[0], part[1], part[2], part[3]]);
            value.push_str(&format!("-{number}"));
        }
        value
    }

    pub(crate) fn privileged(&self) -> bool {
        self.as_bytes() == [1, 1, 0, 0, 0, 0, 0, 5, 18, 0, 0, 0]
            || self.as_bytes() == [1, 2, 0, 0, 0, 0, 0, 5, 32, 0, 0, 0, 32, 2, 0, 0]
    }
}

/// Whether an owner-only descriptor also protects newly inherited children.
#[derive(Clone, Copy, Debug)]
pub enum DescriptorInheritance {
    ObjectOnly,
    ContainersAndObjects,
}

/// A protected DACL and explicit owner, both bound to one exact user SID.
///
/// Keep this value alive while a synchronous creation API uses `as_ptr()`.
/// Existing objects must be validated separately; this descriptor does not
/// authorize repairing an unsafe pre-existing object.
pub struct OwnerSecurityDescriptor(LocalDescriptor);

impl OwnerSecurityDescriptor {
    pub fn new(user: &Sid, inheritance: DescriptorInheritance) -> io::Result<Self> {
        let user = user.to_sddl();
        let flags = match inheritance {
            DescriptorInheritance::ObjectOnly => "",
            DescriptorInheritance::ContainersAndObjects => "OICI",
        };
        let sddl = format!("O:{user}D:P(A;{flags};FA;;;{user})");
        Ok(Self(LocalDescriptor::from_sddl(&sddl)?))
    }

    /// Borrows the immutable descriptor for an OS creation call.
    pub fn as_ptr(&self) -> *const c_void {
        self.0.pointer.as_ptr()
    }
}

/// Reads the effective thread user, falling back only when no thread token exists.
pub fn current_user_sid() -> io::Result<Sid> {
    token_user_sid(effective_token()?.as_handle())
}

/// Reads exactly the supplied token's user SID. The handle needs `TOKEN_QUERY`.
/// This never opens a fallback token, including during named-pipe impersonation.
pub fn token_user_sid(token: BorrowedHandle<'_>) -> io::Result<Sid> {
    token_sid(token, TOKEN_USER_CLASS)
}

/// Reads a file, directory, or named-pipe owner from its retained handle.
/// The handle must have `READ_CONTROL`; no path or peer PID is consulted.
pub fn owner_sid(handle: BorrowedHandle<'_>) -> io::Result<Sid> {
    LocalDescriptor::from_handle(handle, OWNER_SECURITY_INFORMATION)?.owner()
}

pub(crate) struct CurrentIdentity {
    pub user: Sid,
    pub default_owner: Sid,
}

impl CurrentIdentity {
    pub fn read() -> io::Result<Self> {
        let token = effective_token()?;
        Ok(Self {
            user: token_user_sid(token.as_handle())?,
            default_owner: token_sid(token.as_handle(), TOKEN_OWNER_CLASS)?,
        })
    }
}

fn effective_token() -> io::Result<OwnedHandle> {
    let mut token = ptr::null_mut();
    // SAFETY: the pseudo thread handle is valid and the output pointer lives
    // through the call. OpenAsSelf changes access checking, not token identity.
    let opened = unsafe {
        OpenThreadToken(
            GetCurrentThread(),
            TOKEN_QUERY,
            /*openasself*/ 1,
            &mut token,
        )
    };
    if opened == 0 {
        let error = io::Error::last_os_error();
        if error.raw_os_error() != Some(ERROR_NO_TOKEN as i32) {
            return Err(error);
        }
        // SAFETY: no impersonation token exists; query the process token.
        if unsafe { OpenProcessToken(GetCurrentProcess(), TOKEN_QUERY, &mut token) } == 0 {
            return Err(io::Error::last_os_error());
        }
    }
    if token.is_null() {
        return Err(invalid_security("token query returned no handle"));
    }
    // SAFETY: the successful open transferred one owned token handle.
    Ok(unsafe { OwnedHandle::from_raw_handle(token) })
}

fn token_sid(token: BorrowedHandle<'_>, class: TOKEN_INFORMATION_CLASS) -> io::Result<Sid> {
    let mut needed = 0;
    // SAFETY: the first call only obtains the required buffer size.
    let result = unsafe {
        GetTokenInformation(
            token.as_raw_handle(),
            class,
            ptr::null_mut(),
            /*tokeninformationlength*/ 0,
            &mut needed,
        )
    };
    if result != 0
        || io::Error::last_os_error().raw_os_error() != Some(ERROR_INSUFFICIENT_BUFFER as i32)
        || needed as usize > 16 * 1024
        || (needed as usize) < size_of::<TOKEN_USER>()
    {
        return Err(invalid_security("invalid token information size"));
    }
    let mut buffer = vec![0_usize; (needed as usize).div_ceil(size_of::<usize>())];
    // SAFETY: this aligned allocation spans at least the requested byte count.
    if unsafe {
        GetTokenInformation(
            token.as_raw_handle(),
            class,
            buffer.as_mut_ptr().cast(),
            needed,
            &mut needed,
        )
    } == 0
    {
        return Err(io::Error::last_os_error());
    }
    // SAFETY: successful TokenUser/TokenOwner queries initialized the matching
    // header and its SID points inside this live OS-filled allocation.
    let sid = unsafe {
        match class {
            TOKEN_USER_CLASS => (*(buffer.as_ptr().cast::<TOKEN_USER>())).User.Sid,
            TOKEN_OWNER_CLASS => (*(buffer.as_ptr().cast::<TOKEN_OWNER>())).Owner,
            _ => return Err(invalid_security("unsupported token identity class")),
        }
    };
    // SAFETY: the token query above supplies a valid SID in the live buffer.
    unsafe { copy_sid(sid) }
}

pub(crate) struct LocalDescriptor {
    pointer: NonNull<c_void>,
}

impl LocalDescriptor {
    fn from_sddl(sddl: &str) -> io::Result<Self> {
        let sddl: Vec<u16> = sddl.encode_utf16().chain(Some(0)).collect();
        let mut pointer = ptr::null_mut();
        // SAFETY: input is NUL terminated and the output remains live.
        if unsafe {
            ConvertStringSecurityDescriptorToSecurityDescriptorW(
                sddl.as_ptr(),
                SDDL_REVISION_1,
                &mut pointer,
                ptr::null_mut(),
            )
        } == 0
        {
            return Err(io::Error::last_os_error());
        }
        Self::checked(pointer)
    }

    pub(crate) fn from_handle(handle: BorrowedHandle<'_>, information: u32) -> io::Result<Self> {
        let mut pointer = ptr::null_mut();
        // SAFETY: the borrowed file-object handle is live; GetSecurityInfo owns
        // the returned LocalAlloc allocation until this wrapper frees it.
        let result = unsafe {
            GetSecurityInfo(
                handle.as_raw_handle(),
                SE_FILE_OBJECT,
                information,
                ptr::null_mut(),
                ptr::null_mut(),
                ptr::null_mut(),
                ptr::null_mut(),
                &mut pointer,
            )
        };
        if result != 0 {
            return Err(io::Error::from_raw_os_error(result as i32));
        }
        Self::checked(pointer)
    }

    fn checked(pointer: *mut c_void) -> io::Result<Self> {
        let descriptor = Self {
            pointer: NonNull::new(pointer)
                .ok_or_else(|| invalid_security("missing security descriptor"))?,
        };
        // SAFETY: only successful allocating Windows APIs reach this function.
        if unsafe { IsValidSecurityDescriptor(pointer) } == 0
            || unsafe { GetSecurityDescriptorLength(pointer) } > 128 * 1024
        {
            return Err(invalid_security("invalid security descriptor"));
        }
        Ok(descriptor)
    }

    pub(crate) fn as_ptr(&self) -> *mut c_void {
        self.pointer.as_ptr()
    }

    pub(crate) fn owner(&self) -> io::Result<Sid> {
        let mut owner = ptr::null_mut();
        let mut defaulted = 0;
        // SAFETY: the validated descriptor owns the returned SID allocation.
        if unsafe { GetSecurityDescriptorOwner(self.as_ptr(), &mut owner, &mut defaulted) } == 0 {
            return Err(io::Error::last_os_error());
        }
        // SAFETY: owner is valid for the lifetime of this descriptor.
        unsafe { copy_sid(owner) }
    }
}

impl Drop for LocalDescriptor {
    fn drop(&mut self) {
        // SAFETY: Windows allocated this live descriptor with LocalAlloc.
        unsafe { LocalFree(self.pointer.as_ptr()) };
    }
}

unsafe fn copy_sid(pointer: PSID) -> io::Result<Sid> {
    // SAFETY: callers supply an OS-produced pointer in a live owning buffer.
    if pointer.is_null() || unsafe { IsValidSid(pointer) } == 0 {
        return Err(invalid_security("missing or invalid owner SID"));
    }
    // SAFETY: the OS validated this SID; its length remains within its owner.
    let length = unsafe { GetLengthSid(pointer) };
    if !(8..=SECURITY_MAX_SID_SIZE).contains(&length) {
        return Err(invalid_security("owner SID exceeds its bounds"));
    }
    // SAFETY: the validated SID has this many initialized bytes.
    Sid::from_bytes(unsafe { std::slice::from_raw_parts(pointer.cast(), length as usize) })
}

pub(crate) fn invalid_security(message: &'static str) -> io::Error {
    io::Error::new(io::ErrorKind::PermissionDenied, message)
}

#[cfg(test)]
#[path = "windows_security_tests.rs"]
mod tests;
