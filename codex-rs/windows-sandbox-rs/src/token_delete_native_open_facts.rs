//! Read-only evidence; query handles never cross into a filesystem probe.

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
use windows_sys::Win32::Security::DACL_SECURITY_INFORMATION;
use windows_sys::Win32::Security::GROUP_SECURITY_INFORMATION;
use windows_sys::Win32::Security::GetSecurityDescriptorControl;
use windows_sys::Win32::Security::GetSecurityDescriptorLength;
use windows_sys::Win32::Security::GetTokenInformation;
use windows_sys::Win32::Security::IsValidSecurityDescriptor;
use windows_sys::Win32::Security::LABEL_SECURITY_INFORMATION;
use windows_sys::Win32::Security::LUID_AND_ATTRIBUTES;
use windows_sys::Win32::Security::OWNER_SECURITY_INFORMATION;
use windows_sys::Win32::Security::SE_PRIVILEGE_USED_FOR_ACCESS;
use windows_sys::Win32::Security::SE_SELF_RELATIVE;
use windows_sys::Win32::Security::TOKEN_PRIVILEGES;
use windows_sys::Win32::Security::TOKEN_QUERY;
use windows_sys::Win32::Security::TOKEN_STATISTICS;
use windows_sys::Win32::Security::TokenImpersonation;
use windows_sys::Win32::Security::TokenPrivileges;
use windows_sys::Win32::Security::TokenStatistics;
use windows_sys::Win32::Storage::FileSystem::FILE_FLAG_BACKUP_SEMANTICS;
use windows_sys::Win32::Storage::FileSystem::FILE_FLAG_OPEN_REPARSE_POINT;
use windows_sys::Win32::Storage::FileSystem::FILE_SHARE_DELETE;
use windows_sys::Win32::Storage::FileSystem::FILE_SHARE_READ;
use windows_sys::Win32::Storage::FileSystem::FILE_SHARE_WRITE;
use windows_sys::Win32::Storage::FileSystem::READ_CONTROL;
use windows_sys::Win32::System::Threading::GetCurrentThread;
use windows_sys::Win32::System::Threading::OpenThreadToken;

struct Allocation(*mut c_void);
impl Drop for Allocation {
    fn drop(&mut self) {
        unsafe { LocalFree(self.0) };
    }
}

pub(super) fn descriptor_bytes(path: &Path) -> Result<Vec<u8>> {
    support::ensure_unimpersonated()?;
    let file = OpenOptions::new()
        .access_mode(READ_CONTROL)
        .custom_flags(FILE_FLAG_BACKUP_SEMANTICS | FILE_FLAG_OPEN_REPARSE_POINT)
        .share_mode(FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE)
        .open(path)
        .with_context(|| format!("open owned descriptor observer: {}", path.display()))?;
    let mut raw = std::ptr::null_mut();
    let code = unsafe {
        GetSecurityInfo(
            file.as_raw_handle() as _,
            SE_FILE_OBJECT,
            OWNER_SECURITY_INFORMATION
                | GROUP_SECURITY_INFORMATION
                | DACL_SECURITY_INFORMATION
                | LABEL_SECURITY_INFORMATION,
            std::ptr::null_mut(),
            std::ptr::null_mut(),
            std::ptr::null_mut(),
            std::ptr::null_mut(),
            &mut raw,
        )
    };
    drop(file);
    ensure!(code == ERROR_SUCCESS, "query owned descriptor: {code}");
    let _allocation = Allocation(raw);
    ensure!(
        !raw.is_null() && unsafe { IsValidSecurityDescriptor(raw) } != 0,
        "invalid owned descriptor"
    );
    let (mut control, mut revision) = (0, 0);
    ensure!(
        unsafe { GetSecurityDescriptorControl(raw, &mut control, &mut revision) } != 0
            && control & SE_SELF_RELATIVE != 0,
        "descriptor must be self-relative"
    );
    let length = unsafe { GetSecurityDescriptorLength(raw) } as usize;
    ensure!(
        (20..=64 * 1024).contains(&length),
        "descriptor extent is out of bounds"
    );
    // Full returned OWNER/GROUP/DACL/LABEL bytes are compared, never printed.
    Ok(unsafe { std::slice::from_raw_parts(raw.cast::<u8>(), length) }.to_vec())
}

#[derive(PartialEq, Eq)]
pub(super) struct SemanticToken {
    token_id: (u32, i32),
    modified_id: (u32, i32),
    token_type: i32,
    impersonation_level: i32,
    privileges: Vec<(u32, i32, u32)>,
}

pub(super) fn current_token(scenario: &str, phase: &str) -> Result<SemanticToken> {
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
        "query actual impersonation token: {}",
        std::io::Error::last_os_error()
    );
    let token = unsafe { OwnedHandle::from_raw_handle(raw as _) };
    let mut statistics = std::mem::MaybeUninit::<TOKEN_STATISTICS>::zeroed();
    let mut length = 0;
    ensure!(
        unsafe {
            GetTokenInformation(
                token.as_raw_handle() as _,
                TokenStatistics,
                statistics.as_mut_ptr().cast(),
                std::mem::size_of::<TOKEN_STATISTICS>() as u32,
                &mut length,
            )
        } != 0,
        "read token statistics: {}",
        std::io::Error::last_os_error()
    );
    ensure!(
        length as usize == std::mem::size_of::<TOKEN_STATISTICS>(),
        "unexpected token statistics extent"
    );
    let statistics = unsafe { statistics.assume_init() };
    ensure!(
        statistics.TokenType == TokenImpersonation,
        "observer did not receive an impersonation token"
    );
    let mut buffer = [0usize; 1024];
    ensure!(
        unsafe {
            GetTokenInformation(
                token.as_raw_handle() as _,
                TokenPrivileges,
                buffer.as_mut_ptr().cast(),
                std::mem::size_of_val(&buffer) as u32,
                &mut length,
            )
        } != 0,
        "read token privileges: {}",
        std::io::Error::last_os_error()
    );
    let offset = std::mem::offset_of!(TOKEN_PRIVILEGES, Privileges);
    ensure!(
        length as usize >= offset && length as usize <= std::mem::size_of_val(&buffer),
        "invalid privilege buffer extent"
    );
    let count = unsafe { (*buffer.as_ptr().cast::<TOKEN_PRIVILEGES>()).PrivilegeCount } as usize;
    ensure!(count <= 256, "privilege count out of bounds");
    let end = offset
        .checked_add(
            count
                .checked_mul(std::mem::size_of::<LUID_AND_ATTRIBUTES>())
                .context("privilege count overflow")?,
        )
        .context("privilege extent overflow")?;
    ensure!(
        end <= length as usize,
        "privilege entries exceed returned buffer"
    );
    let entries = unsafe {
        std::slice::from_raw_parts(
            buffer
                .as_ptr()
                .cast::<u8>()
                .add(offset)
                .cast::<LUID_AND_ATTRIBUTES>(),
            count,
        )
    };
    let raw_entries: Vec<_> = entries
        .iter()
        .map(|entry| (entry.Luid.LowPart, entry.Luid.HighPart, entry.Attributes))
        .collect();
    eprintln!("HEPTA_NATIVE_TOKEN scenario={scenario} phase={phase} privileges={raw_entries:?}");
    // USED_FOR_ACCESS is an observation bit, not an enabled/disabled right.
    // DynamicCharged/Available, counts and structure padding are not compared.
    let privileges = raw_entries
        .into_iter()
        .map(|(low, high, attributes)| (low, high, attributes & !SE_PRIVILEGE_USED_FOR_ACCESS))
        .collect();
    Ok(SemanticToken {
        token_id: (statistics.TokenId.LowPart, statistics.TokenId.HighPart),
        modified_id: (
            statistics.ModifiedId.LowPart,
            statistics.ModifiedId.HighPart,
        ),
        token_type: statistics.TokenType,
        impersonation_level: statistics.ImpersonationLevel,
        privileges,
    })
}
