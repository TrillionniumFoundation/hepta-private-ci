//! Read-only metadata for independent, owned directory-factor fixtures.

use super::super::support;
use anyhow::Context;
use anyhow::Result;
use anyhow::ensure;
use std::ffi::c_void;
use std::fs::OpenOptions;
use std::os::windows::fs::OpenOptionsExt;
use std::os::windows::io::AsRawHandle;
use std::os::windows::io::FromRawHandle;
use std::os::windows::io::OwnedHandle;
use std::path::Path;
use windows_sys::Win32::Foundation::ERROR_SUCCESS;
use windows_sys::Win32::Foundation::LocalFree;
use windows_sys::Win32::Security::Authorization::GetSecurityInfo;
use windows_sys::Win32::Security::Authorization::SE_FILE_OBJECT;
use windows_sys::Win32::Security::GetTokenInformation;
use windows_sys::Win32::Security::IsValidAcl;
use windows_sys::Win32::Security::IsValidSid;
use windows_sys::Win32::Security::LABEL_SECURITY_INFORMATION;
use windows_sys::Win32::Security::TOKEN_MANDATORY_LABEL;
use windows_sys::Win32::Security::TOKEN_MANDATORY_POLICY;
use windows_sys::Win32::Security::TOKEN_QUERY;
use windows_sys::Win32::Security::TokenIntegrityLevel;
use windows_sys::Win32::Security::TokenMandatoryPolicy;
use windows_sys::Win32::Storage::FileSystem::FILE_ATTRIBUTE_DIRECTORY;
use windows_sys::Win32::Storage::FileSystem::FILE_ATTRIBUTE_READONLY;
use windows_sys::Win32::Storage::FileSystem::FILE_ATTRIBUTE_REPARSE_POINT;
use windows_sys::Win32::Storage::FileSystem::FILE_ATTRIBUTE_TAG_INFO;
use windows_sys::Win32::Storage::FileSystem::FILE_FLAG_BACKUP_SEMANTICS;
use windows_sys::Win32::Storage::FileSystem::FILE_FLAG_OPEN_REPARSE_POINT;
use windows_sys::Win32::Storage::FileSystem::FILE_READ_ATTRIBUTES;
use windows_sys::Win32::Storage::FileSystem::FILE_SHARE_DELETE;
use windows_sys::Win32::Storage::FileSystem::FILE_SHARE_READ;
use windows_sys::Win32::Storage::FileSystem::FILE_SHARE_WRITE;
use windows_sys::Win32::Storage::FileSystem::FileAttributeTagInfo;
use windows_sys::Win32::Storage::FileSystem::GetFileInformationByHandleEx;
use windows_sys::Win32::Storage::FileSystem::READ_CONTROL;
use windows_sys::Win32::System::Threading::GetCurrentThread;
use windows_sys::Win32::System::Threading::OpenThreadToken;

struct Allocation(*mut c_void);
impl Drop for Allocation {
    fn drop(&mut self) {
        unsafe { LocalFree(self.0) };
    }
}

#[derive(Debug, PartialEq, Eq)]
pub(super) struct ObjectFacts {
    attributes: u32,
    reparse_tag: u32,
    label_acl: Option<Vec<u8>>,
}

pub(super) fn object_facts(path: &Path) -> Result<ObjectFacts> {
    support::ensure_unimpersonated()?;
    // Only this observer's original-identity query handle requests attributes.
    // No restricted-token requested access, DACL or label is changed.
    let file = OpenOptions::new()
        .access_mode(READ_CONTROL | FILE_READ_ATTRIBUTES)
        .custom_flags(FILE_FLAG_BACKUP_SEMANTICS | FILE_FLAG_OPEN_REPARSE_POINT)
        .share_mode(FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE)
        .open(path)
        .with_context(|| format!("open owned directory metadata: {}", path.display()))?;
    let mut info = FILE_ATTRIBUTE_TAG_INFO {
        FileAttributes: 0,
        ReparseTag: 0,
    };
    ensure!(
        unsafe {
            GetFileInformationByHandleEx(
                file.as_raw_handle() as _,
                FileAttributeTagInfo,
                std::ptr::addr_of_mut!(info).cast(),
                std::mem::size_of_val(&info) as u32,
            )
        } != 0,
        "query attributes: {}",
        std::io::Error::last_os_error()
    );
    ensure!(
        info.FileAttributes & FILE_ATTRIBUTE_DIRECTORY != 0
            && info.FileAttributes & (FILE_ATTRIBUTE_READONLY | FILE_ATTRIBUTE_REPARSE_POINT) == 0
            && info.ReparseTag == 0,
        "fixture must be a writable ordinary directory"
    );
    let (mut sd, mut label) = (std::ptr::null_mut(), std::ptr::null_mut());
    let code = unsafe {
        GetSecurityInfo(
            file.as_raw_handle() as _,
            SE_FILE_OBJECT,
            LABEL_SECURITY_INFORMATION,
            std::ptr::null_mut(),
            std::ptr::null_mut(),
            std::ptr::null_mut(),
            &mut label,
            &mut sd,
        )
    };
    ensure!(
        code == ERROR_SUCCESS,
        "read label: {}: {code}",
        path.display()
    );
    let _allocation = Allocation(sd);
    let label_acl = if label.is_null() {
        None
    } else {
        ensure!(unsafe { IsValidAcl(label) } != 0, "invalid label ACL");
        Some(
            unsafe { std::slice::from_raw_parts(label.cast::<u8>(), (*label).AclSize as usize) }
                .to_vec(),
        )
    };
    Ok(ObjectFacts {
        attributes: info.FileAttributes,
        reparse_tag: info.ReparseTag,
        label_acl,
    })
}

#[derive(Debug, PartialEq, Eq)]
pub(super) struct TokenFacts {
    integrity_rid: u32,
    mandatory_policy: u32,
}

pub(super) fn current_token_facts() -> Result<TokenFacts> {
    let mut raw = 0;
    ensure!(
        unsafe {
            OpenThreadToken(
                GetCurrentThread(),
                TOKEN_QUERY,
                /*openasself*/ 1,
                &mut raw,
            )
        } != 0,
        "open actual impersonation token: {}",
        std::io::Error::last_os_error()
    );
    let token = unsafe { OwnedHandle::from_raw_handle(raw as _) };
    let mut buffer = [0usize; 128];
    let mut bytes = 0;
    ensure!(
        unsafe {
            GetTokenInformation(
                token.as_raw_handle() as _,
                TokenIntegrityLevel,
                buffer.as_mut_ptr().cast(),
                std::mem::size_of_val(&buffer) as u32,
                &mut bytes,
            )
        } != 0,
        "query token integrity: {}",
        std::io::Error::last_os_error()
    );
    ensure!(
        (bytes as usize) >= std::mem::size_of::<TOKEN_MANDATORY_LABEL>()
            && bytes as usize <= std::mem::size_of_val(&buffer),
        "invalid integrity buffer extent"
    );
    let sid = unsafe { (*buffer.as_ptr().cast::<TOKEN_MANDATORY_LABEL>()).Label.Sid };
    let start = buffer.as_ptr().addr();
    let end = start
        .checked_add(bytes as usize)
        .context("integrity extent overflow")?;
    ensure!(
        sid.addr() >= start
            && sid
                .addr()
                .checked_add(/*rhs*/ 12)
                .is_some_and(|bound| bound <= end),
        "integrity SID outside returned buffer"
    );
    let data = unsafe {
        std::slice::from_raw_parts(sid.cast::<u8>(), /*len*/ 12)
    };
    ensure!(
        data[1] == 1 && data[2..8] == [0, 0, 0, 0, 0, 16] && unsafe { IsValidSid(sid) } != 0,
        "unexpected integrity SID shape"
    );
    let integrity_rid = u32::from_le_bytes([data[8], data[9], data[10], data[11]]);
    let mut policy = TOKEN_MANDATORY_POLICY { Policy: 0 };
    let mut returned = 0;
    ensure!(
        unsafe {
            GetTokenInformation(
                token.as_raw_handle() as _,
                TokenMandatoryPolicy,
                std::ptr::addr_of_mut!(policy).cast(),
                std::mem::size_of_val(&policy) as u32,
                &mut returned,
            )
        } != 0,
        "query token mandatory policy: {}",
        std::io::Error::last_os_error()
    );
    ensure!(
        returned as usize == std::mem::size_of_val(&policy),
        "invalid token mandatory-policy extent {returned}"
    );
    Ok(TokenFacts {
        integrity_rid,
        mandatory_policy: policy.Policy,
    })
}
