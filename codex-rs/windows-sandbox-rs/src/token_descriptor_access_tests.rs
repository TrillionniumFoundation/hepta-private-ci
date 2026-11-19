//! Descriptor-only checks under the existing owned fixture's actual thread token.

use super::Descriptor;
use super::get_user_sid_bytes;
use super::to_wide;
use super::token_information;
use anyhow::Result;
use std::ffi::c_void;
use std::path::Path;
use windows_sys::Win32::Foundation::CloseHandle;
use windows_sys::Win32::Foundation::ERROR_SUCCESS;
use windows_sys::Win32::Foundation::GetLastError;
use windows_sys::Win32::Foundation::HANDLE;
use windows_sys::Win32::Security::AccessCheck;
use windows_sys::Win32::Security::Authorization::GetNamedSecurityInfoW;
use windows_sys::Win32::Security::Authorization::SE_FILE_OBJECT;
use windows_sys::Win32::Security::DACL_SECURITY_INFORMATION;
use windows_sys::Win32::Security::EqualSid;
use windows_sys::Win32::Security::GENERIC_MAPPING;
use windows_sys::Win32::Security::GROUP_SECURITY_INFORMATION;
use windows_sys::Win32::Security::IsValidSecurityDescriptor;
use windows_sys::Win32::Security::IsValidSid;
use windows_sys::Win32::Security::LUID_AND_ATTRIBUTES;
use windows_sys::Win32::Security::OWNER_SECURITY_INFORMATION;
use windows_sys::Win32::Security::PRIVILEGE_SET;
use windows_sys::Win32::Security::SID_AND_ATTRIBUTES;
use windows_sys::Win32::Security::SecurityDelegation;
use windows_sys::Win32::Security::SecurityIdentification;
use windows_sys::Win32::Security::TOKEN_GROUPS;
use windows_sys::Win32::Security::TOKEN_QUERY;
use windows_sys::Win32::Security::TokenImpersonation;
use windows_sys::Win32::Security::TokenImpersonationLevel;
use windows_sys::Win32::Security::TokenRestrictedSids;
use windows_sys::Win32::Security::TokenType;
use windows_sys::Win32::Storage::FileSystem::DELETE;
use windows_sys::Win32::Storage::FileSystem::FILE_ALL_ACCESS;
use windows_sys::Win32::Storage::FileSystem::FILE_DELETE_CHILD;
use windows_sys::Win32::Storage::FileSystem::FILE_GENERIC_EXECUTE;
use windows_sys::Win32::Storage::FileSystem::FILE_GENERIC_READ;
use windows_sys::Win32::Storage::FileSystem::FILE_GENERIC_WRITE;
use windows_sys::Win32::Storage::FileSystem::SYNCHRONIZE;
use windows_sys::Win32::System::SystemServices::SE_GROUP_ENABLED;
use windows_sys::Win32::System::SystemServices::SE_GROUP_USE_FOR_DENY_ONLY;
use windows_sys::Win32::System::Threading::GetCurrentThread;
use windows_sys::Win32::System::Threading::OpenThreadToken;

pub(super) struct Snapshots {
    case: u8,
    descriptors: [Descriptor; 2],
}

fn descriptor(path: &Path) -> Result<Descriptor> {
    let mut raw = std::ptr::null_mut();
    let mut owner = std::ptr::null_mut();
    let mut group = std::ptr::null_mut();
    let mut dacl = std::ptr::null_mut();
    // SAFETY: only an existing owned fixture path is queried. The returned
    // descriptor owns all three inner pointers and is retained through checking.
    let status = unsafe {
        GetNamedSecurityInfoW(
            to_wide(path).as_ptr(),
            SE_FILE_OBJECT,
            OWNER_SECURITY_INFORMATION | GROUP_SECURITY_INFORMATION | DACL_SECURITY_INFORMATION,
            &mut owner,
            &mut group,
            &mut dacl,
            std::ptr::null_mut(),
            &mut raw,
        )
    };
    anyhow::ensure!(
        status == ERROR_SUCCESS,
        "FULL_SETUP dac_descriptor os={status}"
    );
    let allocation = Descriptor(raw);
    anyhow::ensure!(
        !raw.is_null()
            && !owner.is_null()
            && !group.is_null()
            && !dacl.is_null()
            && unsafe { IsValidSecurityDescriptor(raw) } != 0
            && unsafe { IsValidSid(owner) } != 0
            && unsafe { IsValidSid(group) } != 0,
        "FULL_SETUP dac_descriptor_shape"
    );
    Ok(allocation)
}

pub(super) fn capture(case: u8, parent: &Path, child: &Path) -> Result<Option<Snapshots>> {
    if !matches!(case, 0 | 3) {
        return Ok(None);
    }
    let descriptors = [descriptor(parent)?, descriptor(child)?];
    println!("FULL_DAC_SOURCE case={case} owner_group_dacl=true");
    Ok(Some(Snapshots { case, descriptors }))
}

struct QueryToken(HANDLE);

impl QueryToken {
    fn close(&mut self) -> std::io::Result<()> {
        // SAFETY: this wrapper owns exactly the query-only token handle.
        if unsafe { CloseHandle(self.0) } == 0 {
            Err(std::io::Error::last_os_error())
        } else {
            self.0 = 0;
            Ok(())
        }
    }
}

impl Drop for QueryToken {
    fn drop(&mut self) {
        if self.0 != 0 {
            // SAFETY: an unsuccessful explicit close leaves ownership here.
            // This cleanup fallback is not reported as a successful close.
            unsafe { CloseHandle(self.0) };
        }
    }
}

fn token_scalar(token: HANDLE, class: i32) -> Result<i32> {
    let buffer = token_information(token, class, std::mem::size_of::<i32>())?;
    // SAFETY: token_information checked the bounded, aligned result's minimum.
    Ok(unsafe { std::ptr::read(buffer.as_ptr().cast::<i32>()) })
}

fn direct_check(
    case: u8,
    slot: u8,
    descriptor: &Descriptor,
    token: HANDLE,
    requested: u32,
) -> bool {
    let mapping = GENERIC_MAPPING {
        GenericRead: FILE_GENERIC_READ,
        GenericWrite: FILE_GENERIC_WRITE,
        GenericExecute: FILE_GENERIC_EXECUTE,
        GenericAll: FILE_ALL_ACCESS,
    };
    let mut buffer = [0_u64; 512];
    let capacity = std::mem::size_of_val(&buffer) as u32;
    let mut length = capacity;
    let mut granted = 0;
    let mut status = 0;
    // SAFETY: descriptor and query-only impersonation token are live. The fixed
    // concrete masks contain no generic bits; the bounded buffer is aligned for
    // PRIVILEGE_SET. No filesystem access, mutation or privilege change occurs.
    let api_ok = unsafe {
        AccessCheck(
            descriptor.0,
            token,
            requested,
            &mapping,
            buffer.as_mut_ptr().cast(),
            &mut length,
            &mut granted,
            &mut status,
        )
    } != 0;
    let error = if !api_ok || status == 0 {
        Some(unsafe { GetLastError() })
    } else {
        None
    };
    let offset = std::mem::offset_of!(PRIVILEGE_SET, Privilege);
    let privileges = if api_ok && (offset as u32..=capacity).contains(&length) {
        // SAFETY: the initialized aligned prefix contains PrivilegeCount.
        Some(unsafe { (*buffer.as_ptr().cast::<PRIVILEGE_SET>()).PrivilegeCount })
    } else {
        None
    };
    let buffer_ok = api_ok.then_some(privileges.is_some_and(|count| {
        count as usize <= (length as usize - offset) / std::mem::size_of::<LUID_AND_ATTRIBUTES>()
    }));
    let access = api_ok.then_some(status != 0);
    let granted_mask = api_ok.then_some(granted);
    println!(
        "FULL_DAC_CHECK case={case} slot={slot} requested={requested} api_ok={api_ok} access={access:?} granted={granted_mask:?} error={error:?} buffer_ok={buffer_ok:?} privileges={privileges:?}"
    );
    api_ok && buffer_ok == Some(true) && (status != 0 || granted == 0)
}

impl Snapshots {
    pub(super) fn observe(
        &self,
        expected_token: HANDLE,
        expected_roles: [*mut c_void; 3],
    ) -> Result<()> {
        let case = self.case;
        let mut raw = 0;
        // SAFETY: query the token already installed by the existing guard.
        // OpenAsSelf affects this token-handle authorization only; no token is
        // duplicated, adjusted or installed by this diagnostic.
        let ok = unsafe {
            OpenThreadToken(
                GetCurrentThread(),
                TOKEN_QUERY,
                /*openasself*/ 1,
                &mut raw,
            )
        };
        anyhow::ensure!(ok != 0, "FULL_SETUP dac_thread_token os={}", unsafe {
            GetLastError()
        });
        let mut token = QueryToken(raw);
        let checked = (|| -> Result<()> {
            let kind = token_scalar(token.0, TokenType)?;
            let level = token_scalar(token.0, TokenImpersonationLevel)?;
            anyhow::ensure!(
                kind == TokenImpersonation
                    && (SecurityIdentification..=SecurityDelegation).contains(&level),
                "FULL_SETUP dac_token_type"
            );
            let actual_user = unsafe { get_user_sid_bytes(token.0)? };
            let expected_user = unsafe { get_user_sid_bytes(expected_token)? };
            anyhow::ensure!(actual_user == expected_user, "FULL_SETUP dac_token_user");
            let offset = std::mem::offset_of!(TOKEN_GROUPS, Groups);
            let buffer = token_information(token.0, TokenRestrictedSids, offset)?;
            let start = buffer.as_ptr().cast::<u8>();
            let count = unsafe { std::ptr::read(start.cast::<u32>()) } as usize;
            anyhow::ensure!(
                count == expected_roles.len()
                    && offset + count * std::mem::size_of::<SID_AND_ATTRIBUTES>()
                        <= std::mem::size_of_val(buffer.as_slice()),
                "FULL_SETUP dac_restricting_count"
            );
            // SAFETY: the returned count and complete aligned array were bounded.
            let rows = unsafe {
                std::slice::from_raw_parts(start.add(offset).cast::<SID_AND_ATTRIBUTES>(), count)
            };
            let mut seen = [false; 3];
            for row in rows {
                anyhow::ensure!(unsafe { IsValidSid(row.Sid) } != 0, "FULL_SETUP dac_sid");
                let role = expected_roles
                    .iter()
                    .position(|expected| unsafe { EqualSid(row.Sid, *expected) } != 0)
                    .ok_or_else(|| anyhow::anyhow!("FULL_SETUP dac_role"))?;
                anyhow::ensure!(
                    !seen[role]
                        && row.Attributes & SE_GROUP_ENABLED as u32 != 0
                        && row.Attributes & SE_GROUP_USE_FOR_DENY_ONLY as u32 == 0,
                    "FULL_SETUP dac_role_attributes"
                );
                println!(
                    "FULL_DAC_RESTRICT case={case} role={role} attributes={}",
                    row.Attributes
                );
                seen[role] = true;
            }
            anyhow::ensure!(seen == [true; 3], "FULL_SETUP dac_role_set");
            println!(
                "FULL_DAC_TOKEN case={case} type={kind} level={level} user_same=true restricting_set_same=true"
            );
            let requests = [
                (0_u8, &self.descriptors[0], FILE_DELETE_CHILD),
                (1, &self.descriptors[1], DELETE),
                (2, &self.descriptors[1], DELETE | SYNCHRONIZE),
            ];
            let mut complete = true;
            for (slot, descriptor, requested) in requests {
                complete &= direct_check(case, slot, descriptor, token.0, requested);
            }
            anyhow::ensure!(complete, "FULL_SETUP dac_check_unavailable");
            Ok(())
        })();
        let closed = token.close();
        let close_os = closed.as_ref().err().and_then(std::io::Error::raw_os_error);
        println!(
            "FULL_DAC_CLOSE case={case} success={} os={close_os:?}",
            closed.is_ok()
        );
        closed.map_err(|_| anyhow::anyhow!("FULL_SETUP dac_token_close os={close_os:?}"))?;
        checked
    }
}
