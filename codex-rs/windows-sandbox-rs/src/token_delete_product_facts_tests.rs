//! Bounded, owned snapshots for the production-token observer.

use anyhow::Result;
use anyhow::anyhow;
use anyhow::ensure;
use std::ffi::c_void;
use std::fs::OpenOptions;
use std::mem::offset_of;
use std::os::windows::fs::OpenOptionsExt;
use std::os::windows::io::AsRawHandle;
use std::path::Path;
use windows_sys::Win32::Foundation::HANDLE;
use windows_sys::Win32::Foundation::LocalFree;
use windows_sys::Win32::Security::Authorization::GetSecurityInfo;
use windows_sys::Win32::Security::Authorization::SE_FILE_OBJECT;
use windows_sys::Win32::Security::DACL_SECURITY_INFORMATION;
use windows_sys::Win32::Security::GROUP_SECURITY_INFORMATION;
use windows_sys::Win32::Security::GetSecurityDescriptorControl;
use windows_sys::Win32::Security::GetSecurityDescriptorLength;
use windows_sys::Win32::Security::GetTokenInformation;
use windows_sys::Win32::Security::IsValidSecurityDescriptor;
use windows_sys::Win32::Security::IsValidSid;
use windows_sys::Win32::Security::LUID_AND_ATTRIBUTES;
use windows_sys::Win32::Security::OWNER_SECURITY_INFORMATION;
use windows_sys::Win32::Security::SE_SELF_RELATIVE;
use windows_sys::Win32::Security::SECURITY_IMPERSONATION_LEVEL;
use windows_sys::Win32::Security::SID_AND_ATTRIBUTES;
use windows_sys::Win32::Security::TOKEN_GROUPS;
use windows_sys::Win32::Security::TOKEN_INFORMATION_CLASS;
use windows_sys::Win32::Security::TOKEN_MANDATORY_LABEL;
use windows_sys::Win32::Security::TOKEN_MANDATORY_POLICY;
use windows_sys::Win32::Security::TOKEN_OWNER;
use windows_sys::Win32::Security::TOKEN_PRIVILEGES;
use windows_sys::Win32::Security::TOKEN_TYPE;
use windows_sys::Win32::Security::TOKEN_USER;
use windows_sys::Win32::Security::TokenGroups;
use windows_sys::Win32::Security::TokenImpersonationLevel;
use windows_sys::Win32::Security::TokenIntegrityLevel;
use windows_sys::Win32::Security::TokenMandatoryPolicy;
use windows_sys::Win32::Security::TokenOwner;
use windows_sys::Win32::Security::TokenPrivileges;
use windows_sys::Win32::Security::TokenRestrictedSids;
use windows_sys::Win32::Security::TokenType;
use windows_sys::Win32::Security::TokenUser;
use windows_sys::Win32::Storage::FileSystem::FILE_FLAG_BACKUP_SEMANTICS;
use windows_sys::Win32::Storage::FileSystem::FILE_FLAG_OPEN_REPARSE_POINT;
use windows_sys::Win32::Storage::FileSystem::FILE_SHARE_DELETE;
use windows_sys::Win32::Storage::FileSystem::FILE_SHARE_READ;
use windows_sys::Win32::Storage::FileSystem::FILE_SHARE_WRITE;
use windows_sys::Win32::Storage::FileSystem::READ_CONTROL;

pub(super) const MAX_BYTES: usize = 64 * 1024;
pub(super) const MAX_ENTRIES: usize = 256;

fn checked_sid(bytes: &[u8], pointer: *mut c_void) -> Result<Vec<u8>> {
    let offset = (pointer as usize)
        .checked_sub(bytes.as_ptr() as usize)
        .ok_or_else(|| anyhow!("SID before returned allocation"))?;
    ensure!(
        offset <= bytes.len(),
        "SID pointer outside returned allocation"
    );
    let header = bytes
        .get(offset..offset + 8)
        .ok_or_else(|| anyhow!("SID header outside allocation"))?;
    let length = 8 + usize::from(header[1]) * 4;
    let sid = bytes
        .get(offset..offset + length)
        .ok_or_else(|| anyhow!("SID body outside allocation"))?;
    ensure!(unsafe { IsValidSid(pointer) } != 0, "invalid returned SID");
    Ok(sid.to_vec())
}

pub(super) struct Descriptor {
    pub(super) pointer: *mut c_void,
    pub(super) original: Vec<u8>,
    pub(super) owner: Vec<u8>,
}

impl Drop for Descriptor {
    fn drop(&mut self) {
        unsafe { LocalFree(self.pointer as _) };
    }
}

impl Descriptor {
    pub(super) fn capture(path: &Path) -> Result<Self> {
        let file = OpenOptions::new()
            .access_mode(READ_CONTROL)
            .share_mode(FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE)
            .custom_flags(FILE_FLAG_BACKUP_SEMANTICS | FILE_FLAG_OPEN_REPARSE_POINT)
            .open(path)?;
        let (mut owner, mut group, mut pointer) = (
            std::ptr::null_mut(),
            std::ptr::null_mut(),
            std::ptr::null_mut(),
        );
        let status = unsafe {
            GetSecurityInfo(
                file.as_raw_handle() as _,
                SE_FILE_OBJECT,
                OWNER_SECURITY_INFORMATION | GROUP_SECURITY_INFORMATION | DACL_SECURITY_INFORMATION,
                &mut owner,
                &mut group,
                std::ptr::null_mut(),
                std::ptr::null_mut(),
                &mut pointer,
            )
        };
        ensure!(status == 0, "GetSecurityInfo returned {status}");
        let mut descriptor = Self {
            pointer,
            original: Vec::new(),
            owner: Vec::new(),
        };
        ensure!(
            unsafe { IsValidSecurityDescriptor(pointer) } != 0,
            "invalid descriptor"
        );
        let length = unsafe { GetSecurityDescriptorLength(pointer) } as usize;
        ensure!(
            length > 0 && length <= MAX_BYTES,
            "descriptor length out of bounds"
        );
        let mut control = 0;
        let mut revision = 0;
        ensure!(
            unsafe { GetSecurityDescriptorControl(pointer, &mut control, &mut revision) } != 0
                && control & SE_SELF_RELATIVE != 0,
            "descriptor is not self-relative"
        );
        let bytes = unsafe { std::slice::from_raw_parts(pointer.cast::<u8>(), length) };
        descriptor.owner = checked_sid(bytes, owner)?;
        let _group = checked_sid(bytes, group)?;
        descriptor.original = bytes.to_vec();
        drop(file);
        Ok(descriptor)
    }

    pub(super) fn memory_unchanged(&self) -> bool {
        let bytes =
            unsafe { std::slice::from_raw_parts(self.pointer.cast::<u8>(), self.original.len()) };
        bytes == self.original
    }
}

struct TokenBuffer {
    words: Vec<usize>,
    length: usize,
}

impl TokenBuffer {
    fn query(token: HANDLE, class: TOKEN_INFORMATION_CLASS) -> Result<Self> {
        let mut length = 0;
        unsafe {
            GetTokenInformation(
                token,
                class,
                std::ptr::null_mut(),
                /*tokeninformationlength*/ 0,
                &mut length,
            )
        };
        ensure!(
            length > 0 && length as usize <= MAX_BYTES,
            "token class {class} length out of bounds"
        );
        let mut words = vec![0usize; (length as usize).div_ceil(size_of::<usize>())];
        let capacity = length;
        ensure!(
            unsafe {
                GetTokenInformation(
                    token,
                    class,
                    words.as_mut_ptr().cast(),
                    capacity,
                    &mut length,
                )
            } != 0,
            "token class {class}: {}",
            std::io::Error::last_os_error()
        );
        ensure!(length <= capacity, "token length exceeded allocation");
        Ok(Self {
            words,
            length: length as usize,
        })
    }

    fn bytes(&self) -> &[u8] {
        unsafe { std::slice::from_raw_parts(self.words.as_ptr().cast(), self.length) }
    }

    fn header<T: Copy>(&self) -> Result<T> {
        ensure!(
            size_of::<T>() <= self.length && align_of::<T>() <= align_of::<usize>(),
            "token header out of bounds"
        );
        Ok(unsafe { self.words.as_ptr().cast::<T>().read() })
    }

    fn groups(&self) -> Result<Vec<(Vec<u8>, u32)>> {
        let count = self.header::<u32>()? as usize;
        let offset = offset_of!(TOKEN_GROUPS, Groups);
        ensure!(
            count <= MAX_ENTRIES && offset + count * size_of::<SID_AND_ATTRIBUTES>() <= self.length,
            "token groups out of bounds"
        );
        let mut entries = Vec::with_capacity(count);
        for index in 0..count {
            let entry = unsafe {
                self.bytes()
                    .as_ptr()
                    .add(offset + index * size_of::<SID_AND_ATTRIBUTES>())
                    .cast::<SID_AND_ATTRIBUTES>()
                    .read_unaligned()
            };
            entries.push((checked_sid(self.bytes(), entry.Sid)?, entry.Attributes));
        }
        entries.sort();
        Ok(entries)
    }
}

#[derive(PartialEq, Eq)]
pub(super) struct TokenFacts {
    pub(super) user: (Vec<u8>, u32),
    pub(super) owner: Vec<u8>,
    pub(super) groups: Vec<(Vec<u8>, u32)>,
    pub(super) restricting: Vec<(Vec<u8>, u32)>,
    pub(super) privileges: Vec<(i32, u32, u32)>,
    pub(super) integrity: (Vec<u8>, u32),
    pub(super) mandatory_policy: u32,
    pub(super) token_type: TOKEN_TYPE,
    pub(super) impersonation_level: SECURITY_IMPERSONATION_LEVEL,
}

impl TokenFacts {
    pub(super) fn capture(token: HANDLE) -> Result<Self> {
        let user = TokenBuffer::query(token, TokenUser)?;
        let user_header = user.header::<TOKEN_USER>()?;
        let owner = TokenBuffer::query(token, TokenOwner)?;
        let owner_header = owner.header::<TOKEN_OWNER>()?;
        let groups = TokenBuffer::query(token, TokenGroups)?.groups()?;
        let restricting = TokenBuffer::query(token, TokenRestrictedSids)?.groups()?;
        let privilege_data = TokenBuffer::query(token, TokenPrivileges)?;
        let count = privilege_data.header::<u32>()? as usize;
        let offset = offset_of!(TOKEN_PRIVILEGES, Privileges);
        ensure!(
            count <= MAX_ENTRIES
                && offset + count * size_of::<LUID_AND_ATTRIBUTES>() <= privilege_data.length,
            "privileges out of bounds"
        );
        let mut privileges = Vec::with_capacity(count);
        for index in 0..count {
            let entry = unsafe {
                privilege_data
                    .bytes()
                    .as_ptr()
                    .add(offset + index * size_of::<LUID_AND_ATTRIBUTES>())
                    .cast::<LUID_AND_ATTRIBUTES>()
                    .read_unaligned()
            };
            privileges.push((entry.Luid.HighPart, entry.Luid.LowPart, entry.Attributes));
        }
        privileges.sort();
        let integrity = TokenBuffer::query(token, TokenIntegrityLevel)?;
        let integrity_header = integrity.header::<TOKEN_MANDATORY_LABEL>()?;
        let mandatory =
            TokenBuffer::query(token, TokenMandatoryPolicy)?.header::<TOKEN_MANDATORY_POLICY>()?;
        Ok(Self {
            user: (
                checked_sid(user.bytes(), user_header.User.Sid)?,
                user_header.User.Attributes,
            ),
            owner: checked_sid(owner.bytes(), owner_header.Owner)?,
            groups,
            restricting,
            privileges,
            integrity: (
                checked_sid(integrity.bytes(), integrity_header.Label.Sid)?,
                integrity_header.Label.Attributes,
            ),
            mandatory_policy: mandatory.Policy,
            token_type: TokenBuffer::query(token, TokenType)?.header::<TOKEN_TYPE>()?,
            impersonation_level: TokenBuffer::query(token, TokenImpersonationLevel)?
                .header::<SECURITY_IMPERSONATION_LEVEL>()?,
        })
    }
}
