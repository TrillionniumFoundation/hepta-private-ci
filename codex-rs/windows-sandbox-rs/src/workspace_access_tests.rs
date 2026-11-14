//! Native authorization checks against owned, in-memory fixture descriptors.
//! The independent broker integration fixture still checks actual file operations.

use super::create_workspace_token;
use crate::WindowsSandboxReadScope;
use crate::token::LocalSid;
use crate::token::get_current_token_for_restriction;
use crate::token::get_user_sid_bytes;
use crate::winutil::string_from_sid_bytes;
use anyhow::Result;
use pretty_assertions::assert_eq;
use windows_sys::Win32::Foundation::CloseHandle;
use windows_sys::Win32::Foundation::GetLastError;
use windows_sys::Win32::Foundation::HANDLE;
use windows_sys::Win32::Foundation::HLOCAL;
use windows_sys::Win32::Foundation::LocalFree;
use windows_sys::Win32::Security::AccessCheck;
use windows_sys::Win32::Security::Authorization::ConvertStringSecurityDescriptorToSecurityDescriptorW;
use windows_sys::Win32::Security::Authorization::SDDL_REVISION_1;
use windows_sys::Win32::Security::DuplicateToken;
use windows_sys::Win32::Security::GENERIC_MAPPING;
use windows_sys::Win32::Security::SecurityImpersonation;
use windows_sys::Win32::Storage::FileSystem::DELETE;
use windows_sys::Win32::Storage::FileSystem::FILE_ALL_ACCESS;
use windows_sys::Win32::Storage::FileSystem::FILE_APPEND_DATA;
use windows_sys::Win32::Storage::FileSystem::FILE_DELETE_CHILD;
use windows_sys::Win32::Storage::FileSystem::FILE_GENERIC_EXECUTE;
use windows_sys::Win32::Storage::FileSystem::FILE_GENERIC_READ;
use windows_sys::Win32::Storage::FileSystem::FILE_GENERIC_WRITE;
use windows_sys::Win32::Storage::FileSystem::FILE_READ_DATA;
use windows_sys::Win32::Storage::FileSystem::FILE_WRITE_ATTRIBUTES;
use windows_sys::Win32::Storage::FileSystem::FILE_WRITE_DATA;
use windows_sys::Win32::Storage::FileSystem::FILE_WRITE_EA;
use windows_sys::Win32::Storage::FileSystem::SYNCHRONIZE;
use windows_sys::Win32::Storage::FileSystem::WRITE_DAC;
use windows_sys::Win32::Storage::FileSystem::WRITE_OWNER;

const MAXIMUM_ALLOWED: u32 = 0x0200_0000;
const WRITE_RIGHTS: u32 = FILE_WRITE_DATA
    | FILE_APPEND_DATA
    | FILE_WRITE_EA
    | FILE_WRITE_ATTRIBUTES
    | FILE_DELETE_CHILD
    | DELETE
    | WRITE_DAC
    | WRITE_OWNER;
const ROOT_CAPABILITY_RIGHTS: u32 =
    FILE_GENERIC_READ | FILE_GENERIC_WRITE | FILE_GENERIC_EXECUTE | DELETE;

struct Token(HANDLE);

impl Drop for Token {
    fn drop(&mut self) {
        unsafe { CloseHandle(self.0) };
    }
}

struct Descriptor(*mut std::ffi::c_void);

impl Drop for Descriptor {
    fn drop(&mut self) {
        unsafe { LocalFree(self.0 as HLOCAL) };
    }
}

fn checked_access(descriptor: &Descriptor, token: &Token, desired: u32) -> Result<(bool, u32)> {
    let mapping = GENERIC_MAPPING {
        GenericRead: FILE_GENERIC_READ,
        GenericWrite: FILE_GENERIC_WRITE,
        GenericExecute: FILE_GENERIC_EXECUTE,
        GenericAll: FILE_ALL_ACCESS,
    };
    let mut privilege_storage = [0_u64; 32];
    let mut privilege_bytes = std::mem::size_of_val(&privilege_storage).try_into()?;
    let mut granted = 0;
    let mut allowed = 0;
    let checked = unsafe {
        AccessCheck(
            descriptor.0,
            token.0,
            desired,
            &mapping,
            privilege_storage.as_mut_ptr().cast(),
            &mut privilege_bytes,
            &mut granted,
            &mut allowed,
        )
    };
    anyhow::ensure!(checked != 0, "AccessCheck failed: {}", unsafe {
        GetLastError()
    });
    Ok((allowed != 0, granted))
}

#[test]
fn native_read_scopes_preserve_the_complete_file_write_rights_boundary() -> Result<()> {
    let base = Token(unsafe { get_current_token_for_restriction()? });
    let user_sid = unsafe { get_user_sid_bytes(base.0)? };
    let user_sid = string_from_sid_bytes(&user_sid).map_err(anyhow::Error::msg)?;
    let sid_text = "S-1-5-21-211-322-433-544";
    let write_capability = LocalSid::from_string(sid_text)?;
    let masks = [
        FILE_READ_DATA,
        FILE_GENERIC_READ,
        FILE_GENERIC_EXECUTE,
        FILE_WRITE_DATA,
        FILE_APPEND_DATA,
        FILE_WRITE_EA,
        FILE_WRITE_ATTRIBUTES,
        FILE_DELETE_CHILD,
        DELETE,
        WRITE_DAC,
        WRITE_OWNER,
        FILE_READ_DATA | FILE_WRITE_DATA,
        FILE_WRITE_ATTRIBUTES | SYNCHRONIZE,
        FILE_GENERIC_READ | DELETE,
        DELETE | WRITE_DAC,
        FILE_GENERIC_READ | WRITE_OWNER,
    ];
    // Cover caller-owned input and an object still owned by a worker from a
    // previous run. Ownership must not restore out-of-scope WRITE_DAC access.
    for owner in ["SY", user_sid.as_str()] {
        for scope in [
            WindowsSandboxReadScope::CapabilityRoots,
            WindowsSandboxReadScope::FullDisk,
        ] {
            let token = Token(unsafe {
                create_workspace_token(base.0, &[write_capability.as_ptr()], &[], scope)?
            });
            let mut impersonation = 0;
            anyhow::ensure!(
                unsafe { DuplicateToken(token.0, SecurityImpersonation, &mut impersonation) } != 0,
                "DuplicateToken failed: {}",
                unsafe { GetLastError() }
            );
            let impersonation = Token(impersonation);
            for cap_grant in [0, ROOT_CAPABILITY_RIGHTS] {
                let capability_ace = if cap_grant == 0 {
                    String::new()
                } else {
                    format!("(A;;0x{cap_grant:x};;;{sid_text})")
                };
                let sddl = format!("O:{owner}G:SYD:(A;;FA;;;WD){capability_ace}");
                let wide = crate::winutil::to_wide(&sddl);
                let mut raw = std::ptr::null_mut();
                anyhow::ensure!(
                    unsafe {
                        ConvertStringSecurityDescriptorToSecurityDescriptorW(
                            wide.as_ptr(),
                            SDDL_REVISION_1,
                            &mut raw,
                            std::ptr::null_mut(),
                        )
                    } != 0,
                    "parse fixture descriptor failed: {}",
                    unsafe { GetLastError() }
                );
                let descriptor = Descriptor(raw);
                let actual = masks
                    .iter()
                    .map(|mask| checked_access(&descriptor, &impersonation, *mask).map(|r| r.0))
                    .collect::<Result<Vec<_>>>()?;
                let expected = masks
                    .iter()
                    .map(|mask| {
                        (scope == WindowsSandboxReadScope::FullDisk && mask & WRITE_RIGHTS == 0)
                            || mask & !cap_grant == 0
                    })
                    .collect::<Vec<_>>();
                assert_eq!(
                    actual, expected,
                    "owner={owner}, scope={scope:?}, cap_grant={cap_grant:#x}"
                );
                let (allowed, maximum) =
                    checked_access(&descriptor, &impersonation, MAXIMUM_ALLOWED)?;
                assert_eq!(
                    maximum & WRITE_RIGHTS,
                    cap_grant & WRITE_RIGHTS,
                    "maximum access owner={owner}, scope={scope:?}, cap_grant={cap_grant:#x}"
                );
                if cap_grant != 0 {
                    assert!(allowed, "maximum access to the granted root was rejected");
                }
            }
        }
    }
    Ok(())
}
