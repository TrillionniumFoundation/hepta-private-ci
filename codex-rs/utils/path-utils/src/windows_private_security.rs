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
use windows_sys::Win32::Foundation::PSID;
use windows_sys::Win32::Security::ACCESS_ALLOWED_ACE;
use windows_sys::Win32::Security::ACE_HEADER;
use windows_sys::Win32::Security::ACL;
use windows_sys::Win32::Security::Authorization::ConvertSidToStringSidW;
use windows_sys::Win32::Security::Authorization::ConvertStringSecurityDescriptorToSecurityDescriptorW;
use windows_sys::Win32::Security::Authorization::GetSecurityInfo;
use windows_sys::Win32::Security::Authorization::SDDL_REVISION_1;
use windows_sys::Win32::Security::Authorization::SE_FILE_OBJECT;
use windows_sys::Win32::Security::CONTAINER_INHERIT_ACE;
use windows_sys::Win32::Security::DACL_SECURITY_INFORMATION;
use windows_sys::Win32::Security::EqualSid;
use windows_sys::Win32::Security::GetAce;
use windows_sys::Win32::Security::GetSecurityDescriptorControl;
use windows_sys::Win32::Security::GetTokenInformation;
use windows_sys::Win32::Security::INHERITED_ACE;
use windows_sys::Win32::Security::IsValidAcl;
use windows_sys::Win32::Security::IsValidSid;
use windows_sys::Win32::Security::OBJECT_INHERIT_ACE;
use windows_sys::Win32::Security::OWNER_SECURITY_INFORMATION;
use windows_sys::Win32::Security::SE_DACL_PROTECTED;
use windows_sys::Win32::Security::TOKEN_QUERY;
use windows_sys::Win32::Security::TOKEN_USER;
use windows_sys::Win32::Security::TokenUser;
use windows_sys::Win32::Storage::FileSystem::FILE_ALL_ACCESS;
use windows_sys::Win32::System::Threading::GetCurrentProcess;
use windows_sys::Win32::System::Threading::GetCurrentThread;
use windows_sys::Win32::System::Threading::OpenProcessToken;
use windows_sys::Win32::System::Threading::OpenThreadToken;

/// Owns an aligned TOKEN_USER buffer, including its referenced SID.
pub(super) struct Identity(Vec<usize>);

pub(super) struct Descriptor(*mut c_void);

#[derive(Clone, Copy)]
pub(super) enum AclShape {
    Strict,
    SqliteDirectory,
    InspectDirectory,
    SqliteFile,
}

impl Drop for Descriptor {
    fn drop(&mut self) {
        // SAFETY: This pointer was allocated by a LocalAlloc-based Windows API.
        unsafe { LocalFree(self.0) };
    }
}

impl Descriptor {
    pub(super) fn as_ptr(&self) -> *const c_void {
        self.0
    }
}

impl Identity {
    pub(super) fn current() -> io::Result<Self> {
        let mut token = 0;
        // SAFETY: Pseudo thread handle is valid; output storage is live. Prefer
        // the effective impersonation identity, falling back only on NO_TOKEN.
        if unsafe {
            OpenThreadToken(
                GetCurrentThread(),
                TOKEN_QUERY,
                /*openasself*/ 1,
                &mut token,
            )
        } == 0
        {
            let error = io::Error::last_os_error();
            if error.raw_os_error() != Some(ERROR_NO_TOKEN as i32) {
                return Err(error);
            }
            // SAFETY: Same lifetime guarantees as the thread-token call.
            if unsafe { OpenProcessToken(GetCurrentProcess(), TOKEN_QUERY, &mut token) } == 0 {
                return Err(io::Error::last_os_error());
            }
        }
        // SAFETY: A successful token open returns a new owned handle.
        let token = unsafe { OwnedHandle::from_raw_handle(token as _) };
        let mut size = 0;
        // SAFETY: Null/zero asks for the required size without writing a buffer.
        let result = unsafe {
            GetTokenInformation(
                token.as_raw_handle() as _,
                TokenUser,
                ptr::null_mut(),
                /*tokeninformationlength*/ 0,
                &mut size,
            )
        };
        if result != 0
            || io::Error::last_os_error().raw_os_error() != Some(ERROR_INSUFFICIENT_BUFFER as i32)
            || size < size_of::<TOKEN_USER>() as u32
            || size > 65_536
        {
            return Err(super::unsafe_object());
        }
        let mut storage = vec![0_usize; (size as usize).div_ceil(size_of::<usize>())];
        // SAFETY: The aligned allocation has at least `size` writable bytes.
        if unsafe {
            GetTokenInformation(
                token.as_raw_handle() as _,
                TokenUser,
                storage.as_mut_ptr().cast(),
                size,
                &mut size,
            )
        } == 0
        {
            return Err(io::Error::last_os_error());
        }
        Ok(Self(storage))
    }

    fn sid(&self) -> PSID {
        // SAFETY: TOKEN_USER is initialized by GetTokenInformation and its SID
        // points within this retained, aligned buffer.
        unsafe { (*self.0.as_ptr().cast::<TOKEN_USER>()).User.Sid }
    }

    pub(super) fn descriptor(&self) -> io::Result<Descriptor> {
        self.descriptor_with_inheritance("")
    }

    pub(super) fn sqlite_descriptor(&self) -> io::Result<Descriptor> {
        self.descriptor_with_inheritance("OICI")
    }

    fn descriptor_with_inheritance(&self, inheritance: &str) -> io::Result<Descriptor> {
        let mut string_sid = ptr::null_mut();
        // SAFETY: The SID is from the retained token buffer; output is live.
        if unsafe { ConvertSidToStringSidW(self.sid(), &mut string_sid) } == 0 {
            return Err(io::Error::last_os_error());
        }
        let allocation = Descriptor(string_sid.cast());
        // A Windows SID has at most 15 subauthorities; its string is bounded.
        let mut length = 0;
        // SAFETY: ConvertSidToStringSidW returned a terminated UTF-16 string.
        while unsafe { *string_sid.add(length) } != 0 {
            length += 1;
        }
        // SAFETY: `length` was measured before the owned terminator.
        let sid = String::from_utf16(unsafe { std::slice::from_raw_parts(string_sid, length) })
            .map_err(|_| super::unsafe_object())?;
        drop(allocation);
        // Only the current owner is granted access. The SQLite-specific
        // directory explicitly propagates that same SID, never CREATOR_OWNER
        // or a generic group, to files created by SQLite's own VFS.
        let sddl: Vec<u16> = format!("O:{sid}D:P(A;{inheritance};FA;;;{sid})\0")
            .encode_utf16()
            .collect();
        let mut descriptor = ptr::null_mut();
        // SAFETY: SDDL is terminated and live; Windows owns the returned buffer.
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
        Ok(Descriptor(descriptor))
    }

    pub(super) fn validate(&self, file: &File) -> io::Result<()> {
        self.validate_shape(file, AclShape::Strict)
    }

    pub(super) fn validate_shape(&self, file: &File, shape: AclShape) -> io::Result<()> {
        let mut owner = ptr::null_mut();
        let mut acl: *mut ACL = ptr::null_mut();
        let mut descriptor = ptr::null_mut();
        // SAFETY: Security is read from the exact live filesystem handle. The
        // returned owner and ACL remain owned by the returned descriptor.
        let status = unsafe {
            GetSecurityInfo(
                file.as_raw_handle() as _,
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
        let descriptor = Descriptor(descriptor);
        let mut control = 0;
        let mut revision = 0;
        // SAFETY: All security pointers are supplied by GetSecurityInfo; null
        // pointers are rejected before dereferencing. The allocation is live.
        unsafe {
            if owner.is_null()
                || acl.is_null()
                || descriptor.0.is_null()
                || IsValidSid(owner) == 0
                || IsValidAcl(acl) == 0
            {
                return Err(super::unsafe_object());
            }
            if EqualSid(owner, self.sid()) == 0 {
                return Err(io::Error::new(
                    io::ErrorKind::PermissionDenied,
                    "storage object owner differs from the effective token user",
                ));
            }
            if (*acl).AceCount != 1 {
                return Err(io::Error::new(
                    io::ErrorKind::PermissionDenied,
                    format!(
                        "private storage requires one owner ACE, found {}",
                        (*acl).AceCount
                    ),
                ));
            }
            if GetSecurityDescriptorControl(descriptor.0, &mut control, &mut revision) == 0 {
                return Err(io::Error::last_os_error());
            }
            let mut ace = ptr::null_mut();
            if GetAce(acl, /*dwaceindex*/ 0, &mut ace) == 0 || ace.is_null() {
                return Err(super::unsafe_object());
            }
            let sid_offset = offset_of!(ACCESS_ALLOWED_ACE, SidStart);
            let header = &*ace.cast::<ACE_HEADER>();
            let protected = control & SE_DACL_PROTECTED != 0;
            let inheritable = (OBJECT_INHERIT_ACE | CONTAINER_INHERIT_ACE) as u8;
            let shape_matches = match shape {
                AclShape::Strict => protected && header.AceFlags == 0,
                AclShape::SqliteDirectory => protected && header.AceFlags == inheritable,
                AclShape::InspectDirectory => {
                    protected && (header.AceFlags == 0 || header.AceFlags == inheritable)
                }
                AclShape::SqliteFile => {
                    (protected && header.AceFlags == 0)
                        || (!protected && header.AceFlags == INHERITED_ACE as u8)
                }
            };
            if header.AceType != 0 || (header.AceSize as usize) < sid_offset + 8 {
                return Err(super::unsafe_object());
            }
            if !shape_matches {
                return Err(io::Error::new(
                    io::ErrorKind::PermissionDenied,
                    format!(
                        "private storage ACL shape mismatch: protected={protected}, ACE flags={:#04x}",
                        header.AceFlags
                    ),
                ));
            }
            let ace = &*ace.cast::<ACCESS_ALLOWED_ACE>();
            let sid = ptr::addr_of!(ace.SidStart).cast::<u8>();
            let sid_size = 8 + usize::from(*sid.add(1)) * 4;
            if sid_offset + sid_size > ace.Header.AceSize as usize
                || IsValidSid(sid.cast_mut().cast()) == 0
            {
                return Err(super::unsafe_object());
            }
            if EqualSid(sid.cast_mut().cast(), self.sid()) == 0 {
                return Err(io::Error::new(
                    io::ErrorKind::PermissionDenied,
                    "private storage ACE trustee differs from the effective token user",
                ));
            }
            if ace.Mask != FILE_ALL_ACCESS {
                return Err(io::Error::new(
                    io::ErrorKind::PermissionDenied,
                    format!(
                        "private storage owner ACE has unexpected mask {:#010x}",
                        ace.Mask
                    ),
                ));
            }
        }
        Ok(())
    }
}
