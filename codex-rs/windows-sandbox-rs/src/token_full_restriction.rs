//! Explicit OS restriction only; never prepared filesystem or launch authority.
#![deny(clippy::all)]
use super::LocalSid;
use super::token_query::TokenBytes;
use crate::winutil::to_wide;
use anyhow::Result;
use std::mem::offset_of;
use std::mem::size_of;
use std::os::windows::io::AsHandle;
use std::os::windows::io::AsRawHandle;
use std::os::windows::io::BorrowedHandle;
use std::os::windows::io::FromRawHandle;
use std::os::windows::io::OwnedHandle;
use windows_sys::Win32::Foundation::GetLastError;
use windows_sys::Win32::Foundation::HANDLE;
use windows_sys::Win32::Foundation::LUID;
use windows_sys::Win32::Security::CreateRestrictedToken;
use windows_sys::Win32::Security::GetLengthSid;
use windows_sys::Win32::Security::LUID_AND_ATTRIBUTES;
use windows_sys::Win32::Security::LookupPrivilegeValueW;
use windows_sys::Win32::Security::SE_PRIVILEGE_ENABLED;
use windows_sys::Win32::Security::SID_AND_ATTRIBUTES;
use windows_sys::Win32::Security::TOKEN_INFORMATION_CLASS;
use windows_sys::Win32::Security::TOKEN_PRIVILEGES;
use windows_sys::Win32::Security::TOKEN_STATISTICS;
use windows_sys::Win32::Security::TokenDefaultDacl;
use windows_sys::Win32::Security::TokenGroups;
use windows_sys::Win32::Security::TokenHasRestrictions;
use windows_sys::Win32::Security::TokenIsAppContainer;
use windows_sys::Win32::Security::TokenPrivileges;
use windows_sys::Win32::Security::TokenRestrictedSids;
use windows_sys::Win32::Security::TokenStatistics;
use windows_sys::Win32::Security::TokenType;
use windows_sys::Win32::Security::TokenUser;

/// An OS token with explicit restricting SIDs, without filesystem admission.
///
/// Construction checks an explicitly supplied, unfiltered primary token. It
/// does not prove managed credentials, prepared read/write ACLs, executable
/// loading, private desktop, stdio, containment or a production sandbox. No
/// ambient identity or network-route SID is added; the base default DACL stays
/// unchanged. The original qualified-launch guards remain mandatory.
pub struct UnqualifiedFullRestrictionToken {
    token: OwnedHandle,
}

impl UnqualifiedFullRestrictionToken {
    /// Apply at most 128 explicit nonambient limiting SIDs to this live base.
    /// Public SID selection and this result confer no role or launch authority.
    pub fn from_primary(base: BorrowedHandle<'_>, subjects: &[&LocalSid]) -> Result<Self> {
        anyhow::ensure!(!subjects.is_empty() && subjects.len() <= 128);
        Ok(Self {
            token: create_checked_full_restriction(base, subjects, /*capacity*/ 128)?,
        })
    }

    /// Transfer the same OS handle. It remains unqualified for sandbox launch.
    pub fn into_owned_handle(self) -> OwnedHandle {
        self.token
    }
}

impl AsHandle for UnqualifiedFullRestrictionToken {
    fn as_handle(&self) -> BorrowedHandle<'_> {
        self.token.as_handle()
    }
}

/// Native full restriction shared by qualified admission and the unchanged
/// diagnostic mechanism. Only the admission owner supplies filesystem roles.
pub(super) fn create_checked_full_restriction(
    base: BorrowedHandle<'_>,
    subjects: &[&LocalSid],
    capacity: usize,
) -> Result<OwnedHandle> {
    anyhow::ensure!(!subjects.is_empty() && subjects.len() <= capacity);
    let base = base.as_raw_handle() as HANDLE;
    let before = version(base)?;
    require_unfiltered_primary(base)?;
    let normal = TokenBytes::query(base, TokenGroups)?.group_entries()?;
    let original_privileges = enabled_privileges(base)?;
    let original_user = user(base)?;
    let original_dacl = TokenBytes::query(base, TokenDefaultDacl)?.default_dacl()?;
    let mut expected = Vec::with_capacity(subjects.len());
    for sid in subjects {
        // SAFETY: LocalSid retains a validated native SID during this call.
        let length = unsafe { GetLengthSid(sid.as_ptr()) } as usize;
        anyhow::ensure!((8..=68).contains(&length), "invalid limiting SID length");
        let bytes =
            unsafe { std::slice::from_raw_parts(sid.as_ptr().cast::<u8>(), length) }.to_vec();
        anyhow::ensure!(
            bytes != original_user
                && !normal.iter().any(|(sid, _)| sid == &bytes)
                && !expected.contains(&bytes),
            "limiting SID is ambient or duplicated"
        );
        expected.push(bytes);
    }
    let entries: Vec<_> = subjects
        .iter()
        .map(|sid| SID_AND_ATTRIBUTES {
            Sid: sid.as_ptr(),
            Attributes: 0,
        })
        .collect();
    let mut raw = 0;
    // SAFETY: the borrowed base and owned SID cohort stay live. This only
    // restricts; no WRITE_RESTRICTED, default-DACL repair or identity fallback.
    anyhow::ensure!(
        unsafe {
            CreateRestrictedToken(
                base,
                /*flags*/ 0x01 | 0x04,
                /*disablesidcount*/ 0,
                std::ptr::null(),
                /*deleteprivilegecount*/ 0,
                std::ptr::null(),
                entries.len() as u32,
                entries.as_ptr(),
                &mut raw,
            )
        } != 0,
        "full restriction failed: {}",
        unsafe { GetLastError() }
    );
    // SAFETY: successful native creation transferred exactly this handle.
    let token = unsafe { OwnedHandle::from_raw_handle(raw as _) };
    let output = token.as_raw_handle() as HANDLE;
    let mut actual = TokenBytes::query(output, TokenRestrictedSids)?.groups()?;
    actual.sort();
    expected.sort();
    anyhow::ensure!(actual == expected, "actual limiting SID cohort differs");
    anyhow::ensure!(scalar(output, TokenType)? == 1 && has_restrictions(output)?);
    let output_groups = TokenBytes::query(output, TokenGroups)?.group_entries()?;
    anyhow::ensure!(
        !output_groups.is_empty()
            && output_groups.iter().all(|(sid, attributes)| {
                normal.iter().any(|(base_sid, base_attributes)| {
                    sid == base_sid
                        && (attributes & 0x04 == 0 || base_attributes & 0x04 != 0)
                        && (base_attributes & 0x10 == 0 || attributes & 0x10 != 0)
                })
            })
            && expected
                .iter()
                .all(|sid| !output_groups.iter().any(|(group, _)| group == sid)),
        "full restriction introduced or enabled an ambient group"
    );
    anyhow::ensure!(
        user(output)? == original_user,
        "full restriction changed TokenUser"
    );
    anyhow::ensure!(
        TokenBytes::query(output, TokenDefaultDacl)?.default_dacl()? == original_dacl,
        "full restriction changed the original default DACL"
    );
    require_bounded_privileges(output, &original_privileges)?;
    require_unfiltered_primary(base)?;
    anyhow::ensure!(
        version(base)? == before,
        "base token changed during restriction"
    );
    Ok(token)
}

fn scalar(token: HANDLE, class: TOKEN_INFORMATION_CLASS) -> Result<u32> {
    let data = TokenBytes::query(token, class)?;
    anyhow::ensure!(
        data.length == size_of::<u32>(),
        "unexpected DWORD token field size"
    );
    data.value(/*offset*/ 0)
}

fn has_restrictions(token: HANDLE) -> Result<bool> {
    let data = TokenBytes::query(token, TokenHasRestrictions)?;
    // Native class21 returns BOOLEAN, not the DWORD stated in Learn's prose.
    // The backing allocation remains native-word aligned, including this byte.
    anyhow::ensure!(
        data.length == 1,
        "unexpected TokenHasRestrictions field size"
    );
    let value = data.value::<u8>(/*offset*/ 0)?;
    anyhow::ensure!(value <= 1, "invalid TokenHasRestrictions BOOLEAN");
    Ok(value != 0)
}

fn user(token: HANDLE) -> Result<Vec<u8>> {
    let data = TokenBytes::query(token, TokenUser)?;
    data.sid(data.value::<SID_AND_ATTRIBUTES>(/*offset*/ 0)?.Sid)
}

pub(super) fn version(token: HANDLE) -> Result<(u32, i32, u32, i32)> {
    let data = TokenBytes::query(token, TokenStatistics)?;
    let value = data.value::<TOKEN_STATISTICS>(/*offset*/ 0)?;
    Ok((
        value.TokenId.LowPart,
        value.TokenId.HighPart,
        value.ModifiedId.LowPart,
        value.ModifiedId.HighPart,
    ))
}

pub(super) fn require_unfiltered_primary(token: HANDLE) -> Result<()> {
    anyhow::ensure!(
        scalar(token, TokenType)? == 1,
        "base is not a primary token"
    );
    // IsTokenRestricted alone misses tokens filtered only by groups/privileges.
    anyhow::ensure!(!has_restrictions(token)?, "base has been filtered");
    anyhow::ensure!(
        scalar(token, TokenIsAppContainer)? == 0,
        "base is an AppContainer"
    );
    anyhow::ensure!(
        TokenBytes::query(token, TokenRestrictedSids)?
            .groups()?
            .is_empty(),
        "base already has restricting SIDs"
    );
    Ok(())
}

fn enabled_privileges(token: HANDLE) -> Result<Vec<(u32, i32)>> {
    let privileges = TokenBytes::query(token, TokenPrivileges)?;
    let count = privileges.value::<u32>(/*offset*/ 0)? as usize;
    let offset = offset_of!(TOKEN_PRIVILEGES, Privileges);
    anyhow::ensure!(
        count <= privileges.length.saturating_sub(offset) / size_of::<LUID_AND_ATTRIBUTES>()
    );
    let mut enabled = Vec::new();
    for index in 0..count {
        let entry = privileges
            .value::<LUID_AND_ATTRIBUTES>(offset + index * size_of::<LUID_AND_ATTRIBUTES>())?;
        if entry.Attributes & SE_PRIVILEGE_ENABLED != 0 {
            enabled.push((entry.Luid.LowPart, entry.Luid.HighPart));
        }
    }
    Ok(enabled)
}

fn require_bounded_privileges(token: HANDLE, base: &[(u32, i32)]) -> Result<()> {
    let mut traverse = LUID {
        LowPart: 0,
        HighPart: 0,
    };
    // SAFETY: valid NUL-terminated constant and complete native output.
    anyhow::ensure!(
        unsafe {
            LookupPrivilegeValueW(
                std::ptr::null(),
                to_wide("SeChangeNotifyPrivilege").as_ptr(),
                &mut traverse,
            )
        } != 0,
        "privilege identity query failed: {}",
        unsafe { GetLastError() }
    );
    for entry in enabled_privileges(token)? {
        anyhow::ensure!(
            entry == (traverse.LowPart, traverse.HighPart) && base.contains(&entry),
            "unexpected enabled privilege after full restriction"
        );
    }
    Ok(())
}
