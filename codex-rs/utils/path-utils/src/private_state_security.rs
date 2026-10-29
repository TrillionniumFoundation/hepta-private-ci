//! Current-owner security descriptors and handle-based ACL verification.

use std::ffi::c_void;
use std::fs::File;
use std::io;
use std::mem::offset_of;
use std::mem::size_of;
use std::os::windows::io::AsRawHandle;
use std::os::windows::io::FromRawHandle;
use std::os::windows::io::OwnedHandle;
use std::ptr;
use windows_sys::Win32::Foundation::HANDLE;
use windows_sys::Win32::Foundation::LocalFree;
use windows_sys::Win32::Foundation::PSID;
use windows_sys::Win32::Security::ACCESS_ALLOWED_ACE;
use windows_sys::Win32::Security::ACL;
use windows_sys::Win32::Security::Authorization::ConvertSidToStringSidW;
use windows_sys::Win32::Security::Authorization::ConvertStringSecurityDescriptorToSecurityDescriptorW;
use windows_sys::Win32::Security::Authorization::GetSecurityInfo;
use windows_sys::Win32::Security::Authorization::SDDL_REVISION_1;
use windows_sys::Win32::Security::Authorization::SE_FILE_OBJECT;
use windows_sys::Win32::Security::DACL_SECURITY_INFORMATION;
use windows_sys::Win32::Security::EqualSid;
use windows_sys::Win32::Security::GetAce;
use windows_sys::Win32::Security::GetSecurityDescriptorControl;
use windows_sys::Win32::Security::GetTokenInformation;
use windows_sys::Win32::Security::IsValidAcl;
use windows_sys::Win32::Security::IsValidSid;
use windows_sys::Win32::Security::OWNER_SECURITY_INFORMATION;
use windows_sys::Win32::Security::SE_DACL_PROTECTED;
use windows_sys::Win32::Security::TOKEN_QUERY;
use windows_sys::Win32::Security::TOKEN_USER;
use windows_sys::Win32::Security::TokenUser;
use windows_sys::Win32::Storage::FileSystem::FILE_ALL_ACCESS;
use windows_sys::Win32::System::Threading::GetCurrentProcess;
use windows_sys::Win32::System::Threading::OpenProcessToken;

const ACCESS_ALLOWED_ACE_TYPE: u8 = 0;

struct LocalAllocation(*mut c_void);

impl Drop for LocalAllocation {
    fn drop(&mut self) {
        // SAFETY: Each non-null pointer comes from one LocalAlloc-family API
        // and has exactly one owner. LocalFree accepts null as well.
        unsafe { LocalFree(self.0) };
    }
}

pub(super) struct OwnerSecurity {
    token_user: Vec<usize>,
    descriptor: LocalAllocation,
}

impl OwnerSecurity {
    pub(super) fn current() -> io::Result<Self> {
        let mut raw_token = 0;
        // SAFETY: The current-process pseudo handle is valid and output is writable.
        if unsafe { OpenProcessToken(GetCurrentProcess(), TOKEN_QUERY, &mut raw_token) } == 0 {
            return Err(io::Error::last_os_error());
        }
        // SAFETY: OpenProcessToken transferred one owned token handle.
        let token = unsafe { OwnedHandle::from_raw_handle(raw_token as *mut c_void) };
        let mut needed = 0;
        // SAFETY: A zero-sized null output asks only for the required buffer size.
        unsafe {
            GetTokenInformation(
                token.as_raw_handle() as HANDLE,
                TokenUser,
                ptr::null_mut(),
                /*tokeninformationlength*/ 0,
                &mut needed,
            )
        };
        if needed < size_of::<TOKEN_USER>() as u32 || needed > 4096 {
            return Err(io::Error::last_os_error());
        }
        let mut token_user = vec![0_usize; (needed as usize).div_ceil(size_of::<usize>())];
        // SAFETY: The aligned allocation has at least the requested byte count.
        if unsafe {
            GetTokenInformation(
                token.as_raw_handle() as HANDLE,
                TokenUser,
                token_user.as_mut_ptr().cast(),
                needed,
                &mut needed,
            )
        } == 0
        {
            return Err(io::Error::last_os_error());
        }
        // SAFETY: Successful TokenUser retrieval initialized a TOKEN_USER and its SID.
        let sid = unsafe { (*token_user.as_ptr().cast::<TOKEN_USER>()).User.Sid };
        if unsafe { IsValidSid(sid) } == 0 {
            return Err(unsafe_owner());
        }
        let mut text = ptr::null_mut();
        // SAFETY: The validated SID is backed by token_user through this call.
        if unsafe { ConvertSidToStringSidW(sid, &mut text) } == 0 {
            return Err(io::Error::last_os_error());
        }
        let text_owner = LocalAllocation(text.cast());
        let mut count = 0;
        // SAFETY: This API returns a NUL-terminated string; SID text is bounded.
        while count < 256 && unsafe { *text.add(count) } != 0 {
            count += 1;
        }
        if count == 256 {
            return Err(unsafe_owner());
        }
        // SAFETY: The counted range lies within the valid returned SID string.
        let sid_text = String::from_utf16(unsafe { std::slice::from_raw_parts(text, count) })
            .map_err(|_| unsafe_owner())?;
        drop(text_owner);
        let descriptor_text: Vec<u16> = format!("O:{sid_text}D:P(A;;FA;;;{sid_text})")
            .encode_utf16()
            .chain(std::iter::once(0))
            .collect();
        let mut descriptor = ptr::null_mut();
        // SAFETY: The immutable input is NUL terminated and the output pointer is valid.
        if unsafe {
            ConvertStringSecurityDescriptorToSecurityDescriptorW(
                descriptor_text.as_ptr(),
                SDDL_REVISION_1,
                &mut descriptor,
                ptr::null_mut(),
            )
        } == 0
        {
            return Err(io::Error::last_os_error());
        }
        Ok(Self {
            token_user,
            descriptor: LocalAllocation(descriptor),
        })
    }

    pub(super) fn descriptor(&self) -> *const c_void {
        self.descriptor.0
    }

    pub(super) fn validate(&self, file: &File) -> io::Result<()> {
        let mut owner: PSID = ptr::null_mut();
        let mut acl: *mut ACL = ptr::null_mut();
        let mut descriptor = ptr::null_mut();
        // SAFETY: The file is live and all output pointers remain writable.
        let status = unsafe {
            GetSecurityInfo(
                file.as_raw_handle() as HANDLE,
                SE_FILE_OBJECT,
                OWNER_SECURITY_INFORMATION | DACL_SECURITY_INFORMATION,
                &mut owner,
                ptr::null_mut(),
                &mut acl,
                ptr::null_mut(),
                &mut descriptor,
            )
        };
        if status != 0 {
            return Err(io::Error::from_raw_os_error(status as i32));
        }
        let descriptor_owner = LocalAllocation(descriptor);
        // SAFETY: The token SID and returned security descriptor remain allocated.
        let expected = unsafe { (*self.token_user.as_ptr().cast::<TOKEN_USER>()).User.Sid };
        let mut control = 0;
        let mut revision = 0;
        // SAFETY: Every queried pointer belongs to the still-live descriptor.
        let valid = unsafe {
            !owner.is_null()
                && EqualSid(owner, expected) != 0
                && !acl.is_null()
                && IsValidAcl(acl) != 0
                && GetSecurityDescriptorControl(descriptor, &mut control, &mut revision) != 0
                && control & SE_DACL_PROTECTED != 0
                && (*acl).AceCount == 1
        };
        if !valid {
            return Err(unsafe_owner());
        }
        let mut ace = ptr::null_mut();
        // SAFETY: The validated ACL contains exactly one ACE.
        if unsafe {
            GetAce(acl, /*dwaceindex*/ 0, &mut ace)
        } == 0
            || ace.is_null()
        {
            return Err(unsafe_owner());
        }
        let ace = ace.cast::<ACCESS_ALLOWED_ACE>();
        // SAFETY: IsValidAcl verified the ACE header. Read only the header until
        // its length proves that the remaining ACCESS_ALLOWED_ACE fields fit.
        let header = unsafe { (*ace).Header };
        let sid_offset = offset_of!(ACCESS_ALLOWED_ACE, SidStart);
        if header.AceType != ACCESS_ALLOWED_ACE_TYPE
            || header.AceFlags != 0
            || usize::from(header.AceSize) < sid_offset + 8
        {
            return Err(unsafe_owner());
        }
        // SAFETY: The ACE length checked above contains the SID's fixed header.
        let sid = unsafe { ace.cast::<u8>().add(sid_offset) };
        let sid_bytes = 8 + 4 * usize::from(unsafe { *sid.add(1) });
        if sid_bytes > usize::from(header.AceSize) - sid_offset {
            return Err(unsafe_owner());
        }
        // SAFETY: The full SID is bounded by the validated ACE, and both SIDs
        // remain allocated until the equality check returns.
        let valid = unsafe {
            IsValidSid(sid.cast()) != 0
                && EqualSid(sid.cast(), expected) != 0
                && (*ace).Mask == FILE_ALL_ACCESS
        };
        drop(descriptor_owner);
        if valid { Ok(()) } else { Err(unsafe_owner()) }
    }
}

fn unsafe_owner() -> io::Error {
    io::Error::new(
        io::ErrorKind::PermissionDenied,
        "state object lacks a protected current-owner-only ACL",
    )
}
