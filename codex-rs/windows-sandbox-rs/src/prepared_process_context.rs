//! Native launch resources, without filesystem or loader admission authority.
use crate::desktop::DesktopCapability;
use crate::desktop::LaunchDesktop;
use anyhow::Context;
use anyhow::Result;
use anyhow::ensure;
use codex_utils_pty::JobObject;
use std::os::windows::io::AsRawHandle;
use std::os::windows::io::BorrowedHandle;
use std::os::windows::io::FromRawHandle;
use std::os::windows::io::OwnedHandle;
use std::path::Path;
use std::sync::Arc;
use windows_sys::Win32::Foundation::DuplicateHandle;
use windows_sys::Win32::Foundation::HANDLE;
use windows_sys::Win32::Security::GetTokenInformation;
use windows_sys::Win32::Security::TOKEN_ASSIGN_PRIMARY;
use windows_sys::Win32::Security::TOKEN_DUPLICATE;
use windows_sys::Win32::Security::TOKEN_QUERY;
use windows_sys::Win32::Security::TOKEN_STATISTICS;
use windows_sys::Win32::Security::TokenStatistics;
use windows_sys::Win32::System::Threading::GetCurrentProcess;

/// A one-use private desktop, exact token instance, and non-breakaway owner.
/// This value is neither serializable nor constructible from setup wire fields.
pub struct PreparedProcessContext {
    token: OwnedHandle,
    version: [u32; 4],
    desktop: LaunchDesktop,
    job: Arc<JobObject>,
}

impl PreparedProcessContext {
    /// An internal mechanism, not production admission. Its eventual caller must
    /// supply the separate filesystem, loader and lifetime qualification first.
    pub(crate) fn prepare(
        token: BorrowedHandle<'_>,
        capability: &DesktopCapability,
        logs_base_dir: Option<&Path>,
    ) -> Result<Self> {
        let raw = token.as_raw_handle() as HANDLE;
        let version = token_version(raw)?;
        let desktop = LaunchDesktop::prepare_for_capability(raw, capability, logs_base_dir)?;
        let job = Arc::new(
            JobObject::create_without_breakaway().context("create controlled process job")?,
        );
        let mut duplicate = 0;
        ensure!(
            unsafe {
                DuplicateHandle(
                    GetCurrentProcess(),
                    raw,
                    GetCurrentProcess(),
                    &mut duplicate,
                    TOKEN_QUERY | TOKEN_ASSIGN_PRIMARY | TOKEN_DUPLICATE,
                    /*binherithandle*/ 0,
                    /*dwoptions*/ 0,
                )
            } != 0,
            "retain controlled process token: {}",
            std::io::Error::last_os_error()
        );
        let token = unsafe { OwnedHandle::from_raw_handle(duplicate as _) };
        ensure!(
            token_version(token.as_raw_handle() as HANDLE)? == version,
            "process token changed while preparing launch"
        );
        Ok(Self {
            token,
            version,
            desktop,
            job,
        })
    }

    pub(crate) fn into_parts(self) -> Result<(OwnedHandle, LaunchDesktop, Arc<JobObject>)> {
        ensure!(
            token_version(self.token.as_raw_handle() as HANDLE)? == self.version,
            "prepared process token changed before launch"
        );
        Ok((self.token, self.desktop, self.job))
    }
}

fn token_version(token: HANDLE) -> Result<[u32; 4]> {
    let mut statistics: TOKEN_STATISTICS = unsafe { std::mem::zeroed() };
    let mut length = 0;
    ensure!(
        unsafe {
            GetTokenInformation(
                token,
                TokenStatistics,
                std::ptr::addr_of_mut!(statistics).cast(),
                std::mem::size_of::<TOKEN_STATISTICS>() as u32,
                &mut length,
            )
        } != 0
            && length as usize == std::mem::size_of::<TOKEN_STATISTICS>(),
        "query exact process token identity: {}",
        std::io::Error::last_os_error()
    );
    Ok([
        statistics.TokenId.LowPart,
        statistics.TokenId.HighPart as u32,
        statistics.ModifiedId.LowPart,
        statistics.ModifiedId.HighPart as u32,
    ])
}
