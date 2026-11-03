use std::ffi::c_void;
use std::io;
use std::os::windows::io::AsRawHandle;
use std::os::windows::io::FromRawHandle;
use std::os::windows::io::OwnedHandle;
use std::ptr;

use windows_sys::Win32::Foundation::ERROR_INSUFFICIENT_BUFFER;
use windows_sys::Win32::Foundation::ERROR_NO_TOKEN;
use windows_sys::Win32::Foundation::HANDLE;
use windows_sys::Win32::Foundation::LocalFree;
use windows_sys::Win32::Security::ACCESS_ALLOWED_ACE;
use windows_sys::Win32::Security::ACE_HEADER;
use windows_sys::Win32::Security::Authorization::ConvertSidToStringSidW;
use windows_sys::Win32::Security::Authorization::ConvertStringSecurityDescriptorToSecurityDescriptorW;
use windows_sys::Win32::Security::Authorization::GetSecurityInfo;
use windows_sys::Win32::Security::Authorization::SE_KERNEL_OBJECT;
use windows_sys::Win32::Security::CopySid;
use windows_sys::Win32::Security::DACL_SECURITY_INFORMATION;
use windows_sys::Win32::Security::EqualSid;
use windows_sys::Win32::Security::GetAce;
use windows_sys::Win32::Security::GetLengthSid;
use windows_sys::Win32::Security::GetSecurityDescriptorControl;
use windows_sys::Win32::Security::GetTokenInformation;
use windows_sys::Win32::Security::IsValidSid;
use windows_sys::Win32::Security::OWNER_SECURITY_INFORMATION;
use windows_sys::Win32::Security::PSID;
use windows_sys::Win32::Security::RevertToSelf;
use windows_sys::Win32::Security::SE_DACL_PRESENT;
use windows_sys::Win32::Security::SE_DACL_PROTECTED;
use windows_sys::Win32::Security::SecurityIdentification;
use windows_sys::Win32::Security::TOKEN_QUERY;
use windows_sys::Win32::Security::TOKEN_USER;
use windows_sys::Win32::Security::TokenImpersonationLevel;
use windows_sys::Win32::Security::TokenUser;
use windows_sys::Win32::Storage::FileSystem::FILE_ALL_ACCESS;
use windows_sys::Win32::System::Pipes::ImpersonateNamedPipeClient;
use windows_sys::Win32::System::SystemServices::ACCESS_ALLOWED_ACE_TYPE;
use windows_sys::Win32::System::Threading::GetCurrentProcess;
use windows_sys::Win32::System::Threading::GetCurrentThread;
use windows_sys::Win32::System::Threading::OpenProcessToken;
use windows_sys::Win32::System::Threading::OpenThreadToken;

pub(super) fn denied() -> io::Error {
    io::Error::new(
        io::ErrorKind::PermissionDenied,
        "owner-local pipe identity or protected DACL rejected",
    )
}

/// Aligned, validated, complete native SID bytes; never compares SDDL aliases.
pub(super) struct Sid(Vec<u32>);

impl Sid {
    pub(super) fn current() -> io::Result<Self> {
        let mut handle = ptr::null_mut();
        if unsafe { OpenProcessToken(GetCurrentProcess(), TOKEN_QUERY, &mut handle) } == 0 {
            return Err(io::Error::last_os_error());
        }
        let token = unsafe { OwnedHandle::from_raw_handle(handle) };
        token_user(token.as_raw_handle())
    }

    fn as_ptr(&self) -> PSID {
        self.0.as_ptr().cast_mut().cast()
    }

    // The caller supplies a SID pointer owned by a live Windows API result.
    unsafe fn copy(sid: PSID) -> io::Result<Self> {
        if sid.is_null() || unsafe { IsValidSid(sid) } == 0 {
            return Err(denied());
        }
        let length = unsafe { GetLengthSid(sid) };
        if !(8..=68).contains(&length) || !length.is_multiple_of(4) {
            return Err(denied());
        }
        let mut bytes = vec![0u32; length as usize / 4];
        if unsafe { CopySid(length, bytes.as_mut_ptr().cast(), sid) } == 0 {
            return Err(io::Error::last_os_error());
        }
        Ok(Self(bytes))
    }

    pub(super) fn sddl(&self) -> io::Result<String> {
        let mut text = ptr::null_mut();
        if unsafe { ConvertSidToStringSidW(self.as_ptr(), &mut text) } == 0 {
            return Err(io::Error::last_os_error());
        }
        let _allocation = LocalAllocation(text.cast());
        let mut length = 0;
        while length < 256 && unsafe { *text.add(length) } != 0 {
            length += 1;
        }
        if length == 256 {
            return Err(denied());
        }
        String::from_utf16(unsafe { std::slice::from_raw_parts(text, length) })
            .map_err(|_| denied())
    }
}

struct LocalAllocation(*mut c_void);
impl Drop for LocalAllocation {
    fn drop(&mut self) {
        unsafe { LocalFree(self.0) };
    }
}

/// Self-relative descriptor in aligned owned memory, valid throughout creation.
pub(super) struct Descriptor(Vec<u64>);

impl Descriptor {
    pub(super) fn from_sddl(sddl: &str) -> io::Result<Self> {
        let wide: Vec<_> = sddl.encode_utf16().chain(Some(0)).collect();
        let mut descriptor = ptr::null_mut();
        let mut length = 0;
        if unsafe {
            ConvertStringSecurityDescriptorToSecurityDescriptorW(
                wide.as_ptr(),
                1,
                &mut descriptor,
                &mut length,
            )
        } == 0
        {
            return Err(io::Error::last_os_error());
        }
        let _allocation = LocalAllocation(descriptor);
        if length == 0 || length > 4096 {
            return Err(denied());
        }
        let mut owned = vec![0u64; (length as usize).div_ceil(8)];
        unsafe {
            ptr::copy_nonoverlapping(
                descriptor.cast::<u8>(),
                owned.as_mut_ptr().cast::<u8>(),
                length as usize,
            )
        };
        Ok(Self(owned))
    }

    pub(super) fn as_ptr(&self) -> *mut c_void {
        self.0.as_ptr().cast_mut().cast()
    }
}

/// Inspect the connected handle, never a PID lookup or a fresh pathname open.
pub(super) fn verify_handle(handle: HANDLE, owner: &Sid) -> io::Result<()> {
    let mut actual_owner = ptr::null_mut();
    let mut dacl = ptr::null_mut();
    let mut descriptor = ptr::null_mut();
    let status = unsafe {
        GetSecurityInfo(
            handle,
            SE_KERNEL_OBJECT,
            OWNER_SECURITY_INFORMATION | DACL_SECURITY_INFORMATION,
            &mut actual_owner,
            ptr::null_mut(),
            &mut dacl,
            ptr::null_mut(),
            &mut descriptor,
        )
    };
    if status != 0 {
        return Err(io::Error::from_raw_os_error(status as i32));
    }
    let _allocation = LocalAllocation(descriptor);
    let mut control = 0;
    let mut revision = 0;
    if unsafe { GetSecurityDescriptorControl(descriptor, &mut control, &mut revision) } == 0
        || control & (SE_DACL_PROTECTED | SE_DACL_PRESENT) != SE_DACL_PROTECTED | SE_DACL_PRESENT
        || actual_owner.is_null()
        || unsafe { EqualSid(actual_owner, owner.as_ptr()) } == 0
        || dacl.is_null()
        || unsafe { (*dacl).AceCount } != 1
    {
        return Err(denied());
    }
    let mut ace = ptr::null_mut();
    if unsafe { GetAce(dacl, 0, &mut ace) } == 0 {
        return Err(io::Error::last_os_error());
    }
    let header = unsafe { ptr::read_unaligned(ace.cast::<ACE_HEADER>()) };
    let sid_offset = std::mem::offset_of!(ACCESS_ALLOWED_ACE, SidStart);
    if header.AceType != ACCESS_ALLOWED_ACE_TYPE as u8
        || header.AceFlags != 0
        || usize::from(header.AceSize) < sid_offset + 8
    {
        return Err(denied());
    }
    let allowed = unsafe { ptr::read_unaligned(ace.cast::<ACCESS_ALLOWED_ACE>()) };
    let sid = unsafe { ace.cast::<u8>().add(sid_offset) };
    let sid_length = 8 + 4 * usize::from(unsafe { *sid.add(1) });
    if sid_length > 68
        || sid_offset + sid_length != usize::from(header.AceSize)
        || allowed.Mask != FILE_ALL_ACCESS
        || unsafe { IsValidSid(sid.cast()) } == 0
        || unsafe { EqualSid(sid.cast(), owner.as_ptr()) } == 0
    {
        return Err(denied());
    }
    Ok(())
}

fn token_user(token: HANDLE) -> io::Result<Sid> {
    let mut needed = 0;
    unsafe { GetTokenInformation(token, TokenUser, ptr::null_mut(), 0, &mut needed) };
    if io::Error::last_os_error().raw_os_error() != Some(ERROR_INSUFFICIENT_BUFFER as i32)
        || needed < std::mem::size_of::<TOKEN_USER>() as u32
        || needed > 4096
    {
        return Err(denied());
    }
    let mut buffer = vec![0usize; (needed as usize).div_ceil(std::mem::size_of::<usize>())];
    if unsafe {
        GetTokenInformation(
            token,
            TokenUser,
            buffer.as_mut_ptr().cast(),
            needed,
            &mut needed,
        )
    } == 0
    {
        return Err(io::Error::last_os_error());
    }
    let user = unsafe { ptr::read_unaligned(buffer.as_ptr().cast::<TOKEN_USER>()) };
    unsafe { Sid::copy(user.User.Sid) }
}

/// Restoring the thread identity is mandatory even during an early return/panic.
/// A failed RevertToSelf must never return a foreign token to an executor thread.
pub(super) struct RevertGuard;
impl Drop for RevertGuard {
    fn drop(&mut self) {
        if unsafe { RevertToSelf() } == 0 {
            std::process::abort();
        }
    }
}

/// Synchronous, no await or application operation while impersonating.
pub(super) fn authenticate_client(handle: HANDLE, owner: &Sid) -> io::Result<()> {
    let mut previous = ptr::null_mut();
    if unsafe { OpenThreadToken(GetCurrentThread(), TOKEN_QUERY, 1, &mut previous) } != 0 {
        let _previous = unsafe { OwnedHandle::from_raw_handle(previous) };
        return Err(denied());
    }
    if io::Error::last_os_error().raw_os_error() != Some(ERROR_NO_TOKEN as i32) {
        return Err(io::Error::last_os_error());
    }
    if unsafe { ImpersonateNamedPipeClient(handle) } == 0 {
        return Err(io::Error::last_os_error());
    }
    let _restore = RevertGuard;
    let mut handle = ptr::null_mut();
    if unsafe { OpenThreadToken(GetCurrentThread(), TOKEN_QUERY, 1, &mut handle) } == 0 {
        return Err(io::Error::last_os_error());
    }
    let token = unsafe { OwnedHandle::from_raw_handle(handle) };
    let mut level = 0i32;
    let mut returned = 0;
    if unsafe {
        GetTokenInformation(
            token.as_raw_handle(),
            TokenImpersonationLevel,
            ptr::addr_of_mut!(level).cast(),
            std::mem::size_of_val(&level) as u32,
            &mut returned,
        )
    } == 0
    {
        return Err(io::Error::last_os_error());
    }
    if level != SecurityIdentification || token_user(token.as_raw_handle())?.0 != owner.0 {
        return Err(denied());
    }
    Ok(())
}

#[cfg(test)]
#[path = "owner_local_windows_tests.rs"]
mod tests;
