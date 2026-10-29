//! Security descriptor ownership and validation. No inherited/default DACLs.

use super::unsafe_state;
use std::ffi::c_void;
use std::fs::File;
use std::io;
use std::mem::offset_of;
use std::mem::size_of;
use std::os::windows::io::AsRawHandle;
use std::os::windows::io::FromRawHandle;
use std::os::windows::io::OwnedHandle;
use std::ptr;
use windows_sys::Win32::Foundation::ERROR_INSUFFICIENT_BUFFER;
use windows_sys::Win32::Foundation::ERROR_NO_TOKEN;
use windows_sys::Win32::Foundation::LocalFree;
use windows_sys::Win32::Security::ACCESS_ALLOWED_ACE;
use windows_sys::Win32::Security::ACE_HEADER;
use windows_sys::Win32::Security::Authorization::ConvertSidToStringSidW;
use windows_sys::Win32::Security::Authorization::ConvertStringSecurityDescriptorToSecurityDescriptorW;
use windows_sys::Win32::Security::Authorization::GetSecurityInfo;
use windows_sys::Win32::Security::Authorization::SDDL_REVISION_1;
use windows_sys::Win32::Security::Authorization::SE_FILE_OBJECT;
use windows_sys::Win32::Security::DACL_SECURITY_INFORMATION;
use windows_sys::Win32::Security::EqualSid;
use windows_sys::Win32::Security::GetAce;
use windows_sys::Win32::Security::GetSecurityDescriptorControl;
use windows_sys::Win32::Security::GetSecurityDescriptorDacl;
use windows_sys::Win32::Security::GetSecurityDescriptorOwner;
use windows_sys::Win32::Security::GetTokenInformation;
use windows_sys::Win32::Security::IsValidAcl;
use windows_sys::Win32::Security::IsValidSid;
use windows_sys::Win32::Security::OWNER_SECURITY_INFORMATION;
use windows_sys::Win32::Security::PSID;
use windows_sys::Win32::Security::SE_DACL_PROTECTED;
use windows_sys::Win32::Security::SECURITY_ATTRIBUTES;
use windows_sys::Win32::Security::TOKEN_QUERY;
use windows_sys::Win32::Security::TOKEN_USER;
use windows_sys::Win32::Security::TokenUser;
use windows_sys::Win32::Storage::FileSystem::FILE_ALL_ACCESS;
use windows_sys::Win32::System::SystemServices::ACCESS_ALLOWED_ACE_TYPE;
use windows_sys::Win32::System::Threading::GetCurrentProcess;
use windows_sys::Win32::System::Threading::GetCurrentThread;
use windows_sys::Win32::System::Threading::OpenProcessToken;
use windows_sys::Win32::System::Threading::OpenThreadToken;

struct LocalMemory(*mut c_void);

impl Drop for LocalMemory {
    fn drop(&mut self) {
        // SAFETY: the pointer was allocated by a documented LocalAlloc-family
        // API and this object owns it uniquely; LocalFree also accepts NULL.
        unsafe { LocalFree(self.0) };
    }
}

pub(super) struct Descriptor(LocalMemory);

impl Descriptor {
    pub(super) fn current_user() -> io::Result<Self> {
        let user = User::current()?;
        let sid = user.text()?;
        Self::from_sddl(&format!("O:{sid}D:P(A;;FA;;;{sid})"))
    }

    pub(super) fn from_sddl(sddl: &str) -> io::Result<Self> {
        if sddl.contains('\0') {
            return Err(unsafe_state("embedded NUL in security descriptor"));
        }
        let sddl: Vec<u16> = sddl.encode_utf16().chain([0]).collect();
        let mut descriptor = ptr::null_mut();
        // SAFETY: the input is NUL terminated; the API allocates the output.
        if unsafe {
            ConvertStringSecurityDescriptorToSecurityDescriptorW(
                sddl.as_ptr(),
                SDDL_REVISION_1,
                &mut descriptor,
                ptr::null_mut(),
            )
        } == 0
        {
            return Err(io::Error::last_os_error());
        }
        Ok(Self(LocalMemory(descriptor)))
    }

    pub(super) fn as_ptr(&self) -> *mut c_void {
        self.0.0
    }

    pub(super) fn attributes(&self) -> SECURITY_ATTRIBUTES {
        SECURITY_ATTRIBUTES {
            nLength: size_of::<SECURITY_ATTRIBUTES>() as u32,
            lpSecurityDescriptor: self.as_ptr(),
            bInheritHandle: 0,
        }
    }

    pub(super) fn validate_current_user(&self) -> io::Result<()> {
        let user = User::current()?;
        let mut owner = ptr::null_mut();
        let mut dacl = ptr::null_mut();
        let mut defaulted = 0;
        let mut present = 0;
        let mut control = 0;
        let mut revision = 0;
        // SAFETY: this live descriptor came from a successful Windows API;
        // returned pointers borrow its allocation and are never retained.
        unsafe {
            if GetSecurityDescriptorOwner(self.as_ptr(), &mut owner, &mut defaulted) == 0
                || GetSecurityDescriptorDacl(self.as_ptr(), &mut present, &mut dacl, &mut defaulted)
                    == 0
                || GetSecurityDescriptorControl(self.as_ptr(), &mut control, &mut revision) == 0
            {
                return Err(io::Error::last_os_error());
            }
            if owner.is_null() || IsValidSid(owner) == 0 || EqualSid(owner, user.sid()) == 0 {
                return Err(unsafe_state("state is not owned by the current user"));
            }
            if present == 0
                || dacl.is_null()
                || control & SE_DACL_PROTECTED == 0
                || IsValidAcl(dacl) == 0
                || (*dacl).AceCount != 1
            {
                return Err(unsafe_state(
                    "state DACL is absent, inherited or not exclusive",
                ));
            }
            let mut ace = ptr::null_mut();
            if GetAce(dacl, /*dwaceindex*/ 0, &mut ace) == 0 || ace.is_null() {
                return Err(io::Error::last_os_error());
            }
            let header = &*ace.cast::<ACE_HEADER>();
            let sid_offset = offset_of!(ACCESS_ALLOWED_ACE, SidStart);
            if u32::from(header.AceType) != ACCESS_ALLOWED_ACE_TYPE
                || header.AceFlags != 0
                || usize::from(header.AceSize) < sid_offset + 8
            {
                return Err(unsafe_state("state DACL has an unexpected ACE"));
            }
            let allowed = &*ace.cast::<ACCESS_ALLOWED_ACE>();
            let sid_bytes = ace.cast::<u8>().add(sid_offset);
            let sid_length = 8 + usize::from(*sid_bytes.add(1)) * size_of::<u32>();
            if allowed.Mask != FILE_ALL_ACCESS
                || sid_offset + sid_length > usize::from(header.AceSize)
                || IsValidSid(sid_bytes.cast()) == 0
                || EqualSid(sid_bytes.cast(), user.sid()) == 0
            {
                return Err(unsafe_state("state DACL grants access outside its owner"));
            }
        }
        Ok(())
    }
}

pub(super) fn validate_private(file: &File) -> io::Result<()> {
    let mut descriptor = ptr::null_mut();
    // SAFETY: optional component outputs are NULL. GetSecurityInfo allocates
    // one self-relative descriptor and the borrowed file handle remains live.
    let status = unsafe {
        GetSecurityInfo(
            file.as_raw_handle(),
            SE_FILE_OBJECT,
            OWNER_SECURITY_INFORMATION | DACL_SECURITY_INFORMATION,
            ptr::null_mut(),
            ptr::null_mut(),
            ptr::null_mut(),
            ptr::null_mut(),
            &mut descriptor,
        )
    };
    if status != 0 {
        return Err(io::Error::from_raw_os_error(status as i32));
    }
    if descriptor.is_null() {
        return Err(unsafe_state("missing handle security descriptor"));
    }
    Descriptor(LocalMemory(descriptor)).validate_current_user()
}

struct User(Vec<usize>);

impl User {
    fn current() -> io::Result<Self> {
        let mut raw_token = ptr::null_mut();
        // SAFETY: pseudo-handles are borrowed, output is newly owned. An active
        // impersonation token, if any, defines the effective filesystem user.
        if unsafe {
            OpenThreadToken(
                GetCurrentThread(),
                TOKEN_QUERY,
                /*openasself*/ 1,
                &mut raw_token,
            )
        } == 0
        {
            let error = io::Error::last_os_error();
            if error.raw_os_error() != Some(ERROR_NO_TOKEN as i32) {
                return Err(error);
            }
            // SAFETY: same ownership contract as OpenThreadToken above.
            if unsafe { OpenProcessToken(GetCurrentProcess(), TOKEN_QUERY, &mut raw_token) } == 0 {
                return Err(io::Error::last_os_error());
            }
        }
        // SAFETY: a successful token-open call transferred this handle to us.
        let token = unsafe { OwnedHandle::from_raw_handle(raw_token) };
        let mut length = 0;
        // SAFETY: a NULL, zero-length buffer requests the required output size.
        unsafe {
            GetTokenInformation(
                token.as_raw_handle(),
                TokenUser,
                ptr::null_mut(),
                /*tokeninformationlength*/ 0,
                &mut length,
            )
        };
        let error = io::Error::last_os_error();
        if error.raw_os_error() != Some(ERROR_INSUFFICIENT_BUFFER as i32) {
            return Err(error);
        }
        if length < size_of::<TOKEN_USER>() as u32 || length > 65536 {
            return Err(unsafe_state("invalid token user buffer length"));
        }
        let mut buffer = vec![0usize; (length as usize).div_ceil(size_of::<usize>())];
        // SAFETY: the correctly aligned allocation is at least `length` bytes.
        if unsafe {
            GetTokenInformation(
                token.as_raw_handle(),
                TokenUser,
                buffer.as_mut_ptr().cast(),
                length,
                &mut length,
            )
        } == 0
        {
            return Err(io::Error::last_os_error());
        }
        Ok(Self(buffer))
    }

    fn sid(&self) -> PSID {
        // SAFETY: GetTokenInformation initialized TOKEN_USER and its SID in
        // this stable, aligned allocation; only its immutable pointer is read.
        unsafe { (*self.0.as_ptr().cast::<TOKEN_USER>()).User.Sid }
    }

    fn text(&self) -> io::Result<String> {
        let mut text = ptr::null_mut();
        // SAFETY: the user SID remains live; the API allocates a NUL-terminated
        // SID string that is released by LocalMemory even on conversion errors.
        if unsafe { ConvertSidToStringSidW(self.sid(), &mut text) } == 0 {
            return Err(io::Error::last_os_error());
        }
        let allocation = LocalMemory(text.cast());
        let mut length = 0;
        // SAFETY: ConvertSidToStringSidW guarantees a NUL-terminated string.
        while unsafe { *text.add(length) } != 0 {
            length += 1;
        }
        // SAFETY: the loop bounded this slice within the API-owned allocation.
        let result = String::from_utf16(unsafe { std::slice::from_raw_parts(text, length) })
            .map_err(|_| unsafe_state("invalid textual user SID"));
        drop(allocation);
        result
    }
}
