//! Same-object managed runner base observation, not filesystem or child-launch authority.
use super::token_query::TokenBytes;
use crate::identity::ManagedAccountSource;
use crate::managed_token_policy::ManagedTokenSnapshot;
use crate::runner_client::OriginalManagedRunnerProcess;
use anyhow::Result;
use std::mem::offset_of;
use std::mem::size_of;
use windows_sys::Win32::Foundation::HANDLE;
use windows_sys::Win32::Security::LUID_AND_ATTRIBUTES;
use windows_sys::Win32::Security::LookupPrivilegeNameW;
use windows_sys::Win32::Security::SID_AND_ATTRIBUTES;
use windows_sys::Win32::Security::TOKEN_INFORMATION_CLASS;
use windows_sys::Win32::Security::TOKEN_PRIVILEGES;
use windows_sys::Win32::Security::TOKEN_STATISTICS;
use windows_sys::Win32::Security::TokenDefaultDacl;
use windows_sys::Win32::Security::TokenElevation;
use windows_sys::Win32::Security::TokenElevationType;
use windows_sys::Win32::Security::TokenGroups;
use windows_sys::Win32::Security::TokenHasRestrictions;
use windows_sys::Win32::Security::TokenIsAppContainer;
use windows_sys::Win32::Security::TokenPrivileges;
use windows_sys::Win32::Security::TokenRestrictedSids;
use windows_sys::Win32::Security::TokenStatistics;
use windows_sys::Win32::Security::TokenType;
use windows_sys::Win32::Security::TokenUser;

/// Only the original CreateProcessWithLogonW owner can create this witness.
/// No Clone, wire format, raw handle export or conversion into launch authority.
pub(crate) struct FreshManagedRunnerBase {
    source: ManagedAccountSource,
    birth: OriginalManagedRunnerProcess,
    initial: ManagedTokenSnapshot,
    continuity: Continuity,
}

enum Continuity {
    Current,
    Refused,
}

impl FreshManagedRunnerBase {
    /// The original birth owner transfers an opaque same-object process capability.
    pub(crate) fn capture(
        mut source: ManagedAccountSource,
        mut birth: OriginalManagedRunnerProcess,
    ) -> Result<Self> {
        source.revalidate()?;
        let [initial, current] = birth.readback()?;
        initial.validate(source.user_sid(), source.group_sid())?;
        current.validate_continuity(&initial, source.user_sid(), source.group_sid())?;
        let mut result = Self {
            source,
            birth,
            initial,
            continuity: Continuity::Current,
        };
        result.revalidate()?;
        Ok(result)
    }

    pub(crate) fn revalidate(&mut self) -> Result<()> {
        anyhow::ensure!(
            matches!(self.continuity, Continuity::Current),
            "managed base continuity was refused"
        );
        // Every failed or incomplete readback permanently refuses this instance.
        self.continuity = Continuity::Refused;
        self.source.revalidate()?;
        for actual in self.birth.readback()? {
            actual.validate_continuity(
                &self.initial,
                self.source.user_sid(),
                self.source.group_sid(),
            )?;
        }
        self.continuity = Continuity::Current;
        Ok(())
    }
}

fn scalar(token: HANDLE, class: TOKEN_INFORMATION_CLASS) -> Result<u32> {
    let value = TokenBytes::query(token, class)?;
    anyhow::ensure!(value.length == size_of::<u32>());
    value.value(/*offset*/ 0)
}

fn version(token: HANDLE) -> Result<[u32; 6]> {
    let data = TokenBytes::query(token, TokenStatistics)?;
    anyhow::ensure!(
        data.length == size_of::<TOKEN_STATISTICS>(),
        "unexpected TokenStatistics size"
    );
    let value = data.value::<TOKEN_STATISTICS>(/*offset*/ 0)?;
    Ok([
        value.TokenId.LowPart,
        value.TokenId.HighPart as u32,
        value.AuthenticationId.LowPart,
        value.AuthenticationId.HighPart as u32,
        value.ModifiedId.LowPart,
        value.ModifiedId.HighPart as u32,
    ])
}

/// Bounded query data only; arbitrary readback cannot construct a birth capability.
pub(crate) fn read_snapshot(token: HANDLE) -> Result<ManagedTokenSnapshot> {
    let before = version(token)?;
    let user = TokenBytes::query(token, TokenUser)?;
    let user = user.sid(user.value::<SID_AND_ATTRIBUTES>(/*offset*/ 0)?.Sid)?;
    let groups = TokenBytes::query(token, TokenGroups)?.group_entries()?;
    anyhow::ensure!(groups.len() <= 128);
    let raw = TokenBytes::query(token, TokenPrivileges)?;
    let count = raw.value::<u32>(/*offset*/ 0)? as usize;
    let offset = offset_of!(TOKEN_PRIVILEGES, Privileges);
    anyhow::ensure!(
        count <= 5 && count <= raw.length.saturating_sub(offset) / size_of::<LUID_AND_ATTRIBUTES>()
    );
    let mut privileges = Vec::new();
    for index in 0..count {
        let entry =
            raw.value::<LUID_AND_ATTRIBUTES>(offset + index * size_of::<LUID_AND_ATTRIBUTES>())?;
        let mut name = [0u16; 128];
        let mut length = name.len() as u32;
        anyhow::ensure!(
            unsafe {
                LookupPrivilegeNameW(
                    std::ptr::null(),
                    &entry.Luid,
                    name.as_mut_ptr(),
                    &mut length,
                )
            } != 0
                && (1..128).contains(&length)
        );
        privileges.push((
            String::from_utf16(&name[..length as usize])?,
            entry.Attributes,
        ));
    }
    privileges.sort();
    let filtered = TokenBytes::query(token, TokenHasRestrictions)?;
    // Class21 is BOOLEAN with aligned backing storage, not a DWORD.
    anyhow::ensure!(filtered.length == 1);
    let filtered = filtered.value::<u8>(/*offset*/ 0)?;
    anyhow::ensure!(filtered <= 1);
    let snapshot = ManagedTokenSnapshot {
        version: before,
        user,
        groups,
        privileges,
        default_dacl: TokenBytes::query(token, TokenDefaultDacl)?.default_dacl()?,
        primary: scalar(token, TokenType)?,
        filtered,
        app_container: scalar(token, TokenIsAppContainer)?,
        elevated: scalar(token, TokenElevation)?,
        elevation_type: scalar(token, TokenElevationType)?,
        restricting_count: TokenBytes::query(token, TokenRestrictedSids)?
            .groups()?
            .len(),
    };
    anyhow::ensure!(
        version(token)? == before,
        "managed token changed during kernel readback"
    );
    Ok(snapshot)
}
