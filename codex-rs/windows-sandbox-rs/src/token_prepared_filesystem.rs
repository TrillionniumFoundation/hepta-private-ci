//! Full-restriction mechanism bound to retained, same-plan root ACL readback.
use super::full_restriction::create_checked_full_restriction;
use super::full_restriction::require_unfiltered_primary;
use super::full_restriction::version;
use crate::desktop::DesktopCapability;
use crate::prepared_filesystem::PreparedFilesystemAclContext;
use anyhow::Result;
use anyhow::ensure;
use std::mem::offset_of;
use std::mem::size_of;
use std::os::windows::io::AsHandle;
use std::os::windows::io::AsRawHandle;
use std::os::windows::io::BorrowedHandle;
use std::os::windows::io::FromRawHandle;
use std::os::windows::io::OwnedHandle;
use windows_sys::Win32::Foundation::DuplicateHandle;
use windows_sys::Win32::Foundation::GetHandleInformation;
use windows_sys::Win32::Foundation::HANDLE;
use windows_sys::Win32::Foundation::HANDLE_FLAG_INHERIT;
use windows_sys::Win32::Foundation::LUID;
use windows_sys::Win32::Security::LUID_AND_ATTRIBUTES;
use windows_sys::Win32::Security::LookupPrivilegeValueW;
use windows_sys::Win32::Security::TOKEN_DUPLICATE;
use windows_sys::Win32::Security::TOKEN_PRIVILEGES;
use windows_sys::Win32::Security::TOKEN_QUERY;
use windows_sys::Win32::Security::TokenPrivileges;
use windows_sys::Win32::System::Threading::GetCurrentProcess;

type TokenVersion = (u32, i32, u32, i32);

/// The original full-restriction token and its retained, non-adjustable source.
///
/// No public constructor, deserialization, cloning or diagnostic-token adapter
/// can produce this value. It does not by itself prove image loading, private
/// desktop, explicit inherited handles or suspended Job containment.
pub(crate) struct PreparedFilesystemToken {
    token: OwnedHandle,
    source: OwnedHandle,
    source_version: TokenVersion,
    token_version: TokenVersion,
    refused: bool,
}

fn require_noninheritable(handle: BorrowedHandle<'_>) -> Result<()> {
    let mut flags = 0;
    // SAFETY: the borrowed handle stays owned and flags is an initialized DWORD.
    ensure!(
        unsafe { GetHandleInformation(handle.as_raw_handle() as HANDLE, &mut flags) } != 0
            && flags & HANDLE_FLAG_INHERIT == 0,
        "filesystem token handle is unavailable or inheritable"
    );
    Ok(())
}

/// Retain query and impersonation-duplication authority for AccessCheck only.
/// No adjustment, assignment or inheritance authority is retained.
fn retain_source(base: BorrowedHandle<'_>) -> Result<OwnedHandle> {
    let mut raw = 0;
    // SAFETY: source and target are the current live process. DuplicateHandle
    // creates one independently owned, non-inheritable query/duplicate handle.
    ensure!(
        unsafe {
            DuplicateHandle(
                GetCurrentProcess(),
                base.as_raw_handle() as HANDLE,
                GetCurrentProcess(),
                &mut raw,
                TOKEN_QUERY | TOKEN_DUPLICATE,
                /*binherithandle*/ 0,
                /*dwoptions*/ 0,
            )
        } != 0,
        "cannot retain the filesystem token source: {}",
        std::io::Error::last_os_error()
    );
    // SAFETY: successful DuplicateHandle transferred exactly this handle.
    let source = unsafe { OwnedHandle::from_raw_handle(raw as _) };
    require_noninheritable(source.as_handle())?;
    Ok(source)
}

fn require_no_reenableable_privileges(token: BorrowedHandle<'_>) -> Result<()> {
    let privileges =
        super::token_query::TokenBytes::query(token.as_raw_handle() as HANDLE, TokenPrivileges)?;
    let count = privileges.value::<u32>(/*offset*/ 0)? as usize;
    let offset = offset_of!(TOKEN_PRIVILEGES, Privileges);
    ensure!(count <= privileges.length.saturating_sub(offset) / size_of::<LUID_AND_ATTRIBUTES>());
    let mut traverse = LUID {
        LowPart: 0,
        HighPart: 0,
    };
    // SAFETY: live output and an owned NUL-terminated constant privilege name.
    ensure!(
        unsafe {
            LookupPrivilegeValueW(
                std::ptr::null(),
                crate::winutil::to_wide("SeChangeNotifyPrivilege").as_ptr(),
                &mut traverse,
            )
        } != 0,
        "cannot identify traversal privilege"
    );
    for index in 0..count {
        let privilege = privileges
            .value::<LUID_AND_ATTRIBUTES>(offset + index * size_of::<LUID_AND_ATTRIBUTES>())?;
        ensure!(
            (privilege.Luid.LowPart, privilege.Luid.HighPart)
                == (traverse.LowPart, traverse.HighPart),
            "filesystem token retained a privilege that a child could reenable"
        );
    }
    Ok(())
}

pub(crate) fn create_full_filesystem_token_from(
    base: BorrowedHandle<'_>,
    prepared: &mut PreparedFilesystemAclContext,
    desktop: &DesktopCapability,
) -> Result<PreparedFilesystemToken> {
    let source_version = version(base.as_raw_handle() as HANDLE)?;
    require_unfiltered_primary(base.as_raw_handle() as HANDLE)?;
    prepared.validate_for_token(base)?;
    let filesystem = prepared.filesystem_sids()?;
    // Read/write declarations are separately bounded to 64. The complete native
    // cohort retains the 128-subject launch bound, including one desktop role.
    // Refuse an overfull union instead of truncating the declaration.
    ensure!(
        !filesystem.is_empty() && filesystem.len() < 128,
        "filesystem restricting cohort exceeds its declared bound"
    );
    let mut subjects = filesystem.iter().collect::<Vec<_>>();
    subjects.push(desktop.as_sid());
    let source = retain_source(base)?;
    let token = create_checked_full_restriction(base, &subjects, /*capacity*/ 128)?;
    require_noninheritable(token.as_handle())?;
    require_no_reenableable_privileges(token.as_handle())?;
    prepared.require_token_access(token.as_handle())?;
    let token_version = version(token.as_raw_handle() as HANDLE)?;
    let mut output = PreparedFilesystemToken {
        token,
        source,
        source_version,
        token_version,
        refused: false,
    };
    output.revalidate(prepared)?;
    Ok(output)
}

impl PreparedFilesystemToken {
    /// Any source-token, ACL, identity or output-token change permanently refuses
    /// this admission, including after an intervening caller restores old state.
    pub(crate) fn revalidate(&mut self, prepared: &mut PreparedFilesystemAclContext) -> Result<()> {
        ensure!(!self.refused, "filesystem token admission remains refused");
        self.refused = true;
        let source = self.source.as_raw_handle() as HANDLE;
        ensure!(
            version(source)? == self.source_version
                && version(self.token.as_raw_handle() as HANDLE)? == self.token_version,
            "filesystem source or admitted token changed"
        );
        require_unfiltered_primary(source)?;
        prepared.validate_for_token(self.source.as_handle())?;
        prepared.revalidate()?;
        prepared.require_token_access(self.token.as_handle())?;
        require_noninheritable(self.source.as_handle())?;
        require_noninheritable(self.token.as_handle())?;
        require_no_reenableable_privileges(self.token.as_handle())?;
        ensure!(
            version(source)? == self.source_version
                && version(self.token.as_raw_handle() as HANDLE)? == self.token_version,
            "filesystem token changed during admission readback"
        );
        self.refused = false;
        Ok(())
    }
}

impl AsHandle for PreparedFilesystemToken {
    fn as_handle(&self) -> BorrowedHandle<'_> {
        self.token.as_handle()
    }
}
