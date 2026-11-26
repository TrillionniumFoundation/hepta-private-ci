//! Read-only descriptor authorization, separate from path-based deletion results.

use super::support;
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
use windows_sys::Win32::Foundation::GetLastError;
use windows_sys::Win32::Foundation::LocalFree;
use windows_sys::Win32::Security::AccessCheck;
use windows_sys::Win32::Security::Authorization::GetSecurityInfo;
use windows_sys::Win32::Security::Authorization::SE_FILE_OBJECT;
use windows_sys::Win32::Security::DACL_SECURITY_INFORMATION;
use windows_sys::Win32::Security::GENERIC_MAPPING;
use windows_sys::Win32::Security::GROUP_SECURITY_INFORMATION;
use windows_sys::Win32::Security::GetSecurityDescriptorControl;
use windows_sys::Win32::Security::GetSecurityDescriptorDacl;
use windows_sys::Win32::Security::GetTokenInformation;
use windows_sys::Win32::Security::IsValidAcl;
use windows_sys::Win32::Security::IsValidSecurityDescriptor;
use windows_sys::Win32::Security::LUID_AND_ATTRIBUTES;
use windows_sys::Win32::Security::MapGenericMask;
use windows_sys::Win32::Security::OWNER_SECURITY_INFORMATION;
use windows_sys::Win32::Security::PRIVILEGE_SET;
use windows_sys::Win32::Security::TOKEN_PRIVILEGES;
use windows_sys::Win32::Security::TOKEN_QUERY;
use windows_sys::Win32::Security::TokenPrivileges;
use windows_sys::Win32::Storage::FileSystem::DELETE;
use windows_sys::Win32::Storage::FileSystem::FILE_ALL_ACCESS;
use windows_sys::Win32::Storage::FileSystem::FILE_FLAG_BACKUP_SEMANTICS;
use windows_sys::Win32::Storage::FileSystem::FILE_FLAG_OPEN_REPARSE_POINT;
use windows_sys::Win32::Storage::FileSystem::FILE_GENERIC_EXECUTE;
use windows_sys::Win32::Storage::FileSystem::FILE_GENERIC_READ;
use windows_sys::Win32::Storage::FileSystem::FILE_GENERIC_WRITE;
use windows_sys::Win32::Storage::FileSystem::FILE_SHARE_DELETE;
use windows_sys::Win32::Storage::FileSystem::FILE_SHARE_READ;
use windows_sys::Win32::Storage::FileSystem::FILE_SHARE_WRITE;
use windows_sys::Win32::Storage::FileSystem::READ_CONTROL;
use windows_sys::Win32::System::SystemServices::MAXIMUM_ALLOWED;
use windows_sys::Win32::System::Threading::GetCurrentThread;
use windows_sys::Win32::System::Threading::OpenThreadToken;

const BUFFER_WORDS: usize = 1024;
const MAX_PRIVILEGES: usize = 256;

struct Descriptor(*mut c_void);

impl Drop for Descriptor {
    fn drop(&mut self) {
        unsafe { LocalFree(self.0) };
    }
}

impl Descriptor {
    fn capture(path: &Path, object: &str, scenario: &str, phase: &str) -> Result<Self> {
        // Only query access, all sharing, and no retained filesystem handle.
        // OWNER and GROUP are needed by AccessCheck, but their SID bytes are not logged.
        let handle = OpenOptions::new()
            .access_mode(READ_CONTROL)
            .custom_flags(FILE_FLAG_BACKUP_SEMANTICS | FILE_FLAG_OPEN_REPARSE_POINT)
            .share_mode(FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE)
            .open(path)
            .with_context(|| {
                format!(
                    "open owned {object} for descriptor query: {}",
                    path.display()
                )
            })?;
        let (mut owner, mut group, mut sd) = (
            std::ptr::null_mut(),
            std::ptr::null_mut(),
            std::ptr::null_mut(),
        );
        let code = unsafe {
            GetSecurityInfo(
                handle.as_raw_handle() as _,
                SE_FILE_OBJECT,
                OWNER_SECURITY_INFORMATION | GROUP_SECURITY_INFORMATION | DACL_SECURITY_INFORMATION,
                &mut owner,
                &mut group,
                std::ptr::null_mut(),
                std::ptr::null_mut(),
                &mut sd,
            )
        };
        drop(handle);
        ensure!(code == ERROR_SUCCESS, "query {object} descriptor: {code}");
        let descriptor = Self(sd);
        ensure!(
            !sd.is_null()
                && !owner.is_null()
                && !group.is_null()
                && unsafe { IsValidSecurityDescriptor(sd) } != 0,
            "{object} descriptor must be valid and include owner and group"
        );
        let (mut control, mut revision) = (0, 0);
        let (mut present, mut defaulted, mut dacl) = (0, 0, std::ptr::null_mut());
        ensure!(
            unsafe { GetSecurityDescriptorControl(sd, &mut control, &mut revision) } != 0
                && unsafe {
                    GetSecurityDescriptorDacl(sd, &mut present, &mut dacl, &mut defaulted)
                } != 0,
            "inspect {object} descriptor: {}",
            std::io::Error::last_os_error()
        );
        let dacl_bytes = if dacl.is_null() {
            None
        } else {
            ensure!(unsafe { IsValidAcl(dacl) } != 0, "invalid {object} ACL");
            // Windows supplied and validated this ACL; AclSize is a bounded u16.
            Some(unsafe {
                std::slice::from_raw_parts(dacl.cast::<u8>(), (*dacl).AclSize as usize).to_vec()
            })
        };
        eprintln!(
            "HEPTA_DELETE_SD scenario={scenario} phase={phase} object={object} control=0x{control:04x} revision={revision} owner_present=true group_present=true dacl_present={present} dacl_defaulted={defaulted} dacl={dacl_bytes:02x?}"
        );
        Ok(descriptor)
    }

    fn check(
        &self,
        token: &OwnedHandle,
        requested: u32,
        object: &str,
        scenario: &str,
        phase: &str,
    ) -> Result<()> {
        let mapping = GENERIC_MAPPING {
            GenericRead: FILE_GENERIC_READ,
            GenericWrite: FILE_GENERIC_WRITE,
            GenericExecute: FILE_GENERIC_EXECUTE,
            GenericAll: FILE_ALL_ACCESS,
        };
        let mut desired = requested;
        unsafe { MapGenericMask(&mut desired, &mapping) };
        let mut buffer = [0usize; BUFFER_WORDS];
        let mut bytes = std::mem::size_of_val(&buffer) as u32;
        let (mut granted, mut access_status) = (0, 0);
        let api_ok = unsafe {
            AccessCheck(
                self.0,
                token.as_raw_handle() as _,
                desired,
                &mapping,
                buffer.as_mut_ptr().cast(),
                &mut bytes,
                &mut granted,
                &mut access_status,
            )
        };
        if api_ok == 0 {
            let error = unsafe { GetLastError() };
            // Output authorization fields are undefined when the API itself fails.
            eprintln!(
                "HEPTA_DELETE_ACCESS scenario={scenario} phase={phase} object={object} requested=0x{requested:08x} mapped=0x{desired:08x} api_error={error} allowed=unknown granted=unknown privilege_buffer_bytes={bytes}"
            );
            anyhow::bail!(
                "AccessCheck API failed: scenario={scenario} phase={phase} object={object} requested=0x{requested:08x} error={error}"
            );
        }
        let offset = std::mem::offset_of!(PRIVILEGE_SET, Privilege);
        ensure!(
            bytes as usize >= offset,
            "short AccessCheck privilege header"
        );
        let set = buffer.as_ptr().cast::<PRIVILEGE_SET>();
        let (count, control) = unsafe { ((*set).PrivilegeCount, (*set).Control) };
        let used = read_privileges(&buffer, bytes as usize, offset, count)?;
        let allowed = access_status != 0;
        eprintln!(
            "HEPTA_DELETE_ACCESS scenario={scenario} phase={phase} object={object} requested=0x{requested:08x} mapped=0x{desired:08x} api_error=none allowed={allowed} granted=0x{granted:08x} privilege_control=0x{control:08x} used_privileges={used:?}"
        );
        Ok(())
    }
}

// Each tuple is (LUID low part, LUID high part, attributes), never a SID.
fn read_privileges(
    buffer: &[usize],
    bytes: usize,
    offset: usize,
    count: u32,
) -> Result<Vec<(u32, i32, u32)>> {
    let count = count as usize;
    ensure!(
        count <= MAX_PRIVILEGES,
        "privilege count exceeds diagnostic bound"
    );
    let end = count
        .checked_mul(std::mem::size_of::<LUID_AND_ATTRIBUTES>())
        .and_then(|length| offset.checked_add(length))
        .context("privilege extent overflow")?;
    ensure!(
        end <= bytes && bytes <= std::mem::size_of_val(buffer),
        "privilege extent exceeds returned buffer"
    );
    // Both native structures place an aligned LUID_AND_ATTRIBUTES array at offset.
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
    Ok(entries
        .iter()
        .map(|entry| (entry.Luid.LowPart, entry.Luid.HighPart, entry.Attributes))
        .collect())
}

pub struct AuthorizationSnapshot {
    parent: Descriptor,
    target: Descriptor,
}

impl AuthorizationSnapshot {
    pub fn capture(parent: &Path, target: &Path, scenario: &str, phase: &str) -> Result<Self> {
        support::ensure_unimpersonated().context("query descriptors using original identity")?;
        Ok(Self {
            parent: Descriptor::capture(parent, "parent", scenario, phase)?,
            target: Descriptor::capture(target, "target", scenario, phase)?,
        })
    }

    pub fn observe_current_token(&self, scenario: &str, phase: &str) -> Result<()> {
        let mut raw = 0;
        // OpenAsSelf changes the access check for this query handle, not the token
        // it refers to. AccessCheck receives the current thread's impersonation token.
        ensure!(
            unsafe {
                OpenThreadToken(
                    GetCurrentThread(),
                    TOKEN_QUERY,
                    /*openasself*/ 1,
                    &mut raw,
                )
            } != 0,
            "query current impersonation token: {}",
            std::io::Error::last_os_error()
        );
        let token = unsafe { OwnedHandle::from_raw_handle(raw as _) };
        let mut buffer = [0usize; BUFFER_WORDS];
        let mut bytes = 0;
        ensure!(
            unsafe {
                GetTokenInformation(
                    token.as_raw_handle() as _,
                    TokenPrivileges,
                    buffer.as_mut_ptr().cast(),
                    std::mem::size_of_val(&buffer) as u32,
                    &mut bytes,
                )
            } != 0,
            "read current token privileges: {} (required bytes {bytes})",
            std::io::Error::last_os_error()
        );
        let offset = std::mem::offset_of!(TOKEN_PRIVILEGES, Privileges);
        ensure!(bytes as usize >= offset, "short token privilege header");
        let count = unsafe { (*buffer.as_ptr().cast::<TOKEN_PRIVILEGES>()).PrivilegeCount };
        let privileges = read_privileges(&buffer, bytes as usize, offset, count)?;
        eprintln!(
            "HEPTA_DELETE_TOKEN scenario={scenario} phase={phase} query_access=TOKEN_QUERY privileges={privileges:?}"
        );
        for (object, descriptor) in [("parent", &self.parent), ("target", &self.target)] {
            for requested in [DELETE, MAXIMUM_ALLOWED] {
                descriptor.check(&token, requested, object, scenario, phase)?;
            }
        }
        Ok(())
    }
}
