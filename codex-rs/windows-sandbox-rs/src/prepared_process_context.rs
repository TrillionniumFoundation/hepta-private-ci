//! Native launch resources, without filesystem or loader admission authority.
use crate::desktop::DesktopCapability;
use crate::desktop::LaunchDesktop;
use crate::prepared_filesystem::PreparedFilesystemAclContext;
use crate::token::PreparedFilesystemToken;
use anyhow::Context;
use anyhow::Result;
use anyhow::ensure;
use codex_utils_pty::JobObject;
use std::os::windows::io::AsHandle;
use std::os::windows::io::AsRawHandle;
use std::os::windows::io::BorrowedHandle;
use std::path::Path;
use std::sync::Arc;
use windows_sys::Win32::Foundation::HANDLE;
use windows_sys::Win32::Security::GetTokenInformation;
use windows_sys::Win32::Security::TOKEN_STATISTICS;
use windows_sys::Win32::Security::TokenStatistics;

/// Retains the original source token, output token, root handles and session role.
/// It grants no loader, production-launch or terminal-reconciliation authority.
pub(crate) struct PreparedFilesystemOwners {
    token: PreparedFilesystemToken,
    filesystem: PreparedFilesystemAclContext,
    capability: DesktopCapability,
}

impl PreparedFilesystemOwners {
    fn revalidate(&mut self) -> Result<()> {
        self.token.revalidate(&mut self.filesystem)
    }
}

impl AsHandle for PreparedFilesystemOwners {
    fn as_handle(&self) -> BorrowedHandle<'_> {
        self.token.as_handle()
    }
}

/// A one-use private desktop, exact token instance, and non-breakaway owner.
/// This value is neither serializable nor constructible from setup wire fields.
pub struct PreparedProcessContext {
    owners: Box<PreparedFilesystemOwners>,
    version: [u32; 4],
    desktop: LaunchDesktop,
    job: Arc<JobObject>,
}

impl PreparedProcessContext {
    /// An internal mechanism, not production admission. Its eventual caller must
    /// supply the separate loader and lifetime qualification first. Consuming
    /// these owners does not itself provide that production admission.
    pub(crate) fn prepare(
        token: PreparedFilesystemToken,
        filesystem: PreparedFilesystemAclContext,
        capability: DesktopCapability,
        logs_base_dir: Option<&Path>,
    ) -> Result<Self> {
        let mut owners = PreparedFilesystemOwners {
            token,
            filesystem,
            capability,
        };
        owners.revalidate()?;
        let raw = owners.token.as_handle().as_raw_handle() as HANDLE;
        let version = token_version(raw)?;
        let desktop =
            LaunchDesktop::prepare_for_capability(raw, &owners.capability, logs_base_dir)?;
        let job = Arc::new(
            JobObject::create_without_breakaway().context("create controlled process job")?,
        );
        owners.revalidate()?;
        ensure!(
            token_version(raw)? == version,
            "process token changed while preparing launch"
        );
        Ok(Self {
            owners: Box::new(owners),
            version,
            desktop,
            job,
        })
    }

    pub(crate) fn into_parts(
        mut self,
    ) -> Result<(Box<PreparedFilesystemOwners>, LaunchDesktop, Arc<JobObject>)> {
        self.owners.revalidate()?;
        ensure!(
            token_version(self.owners.token.as_handle().as_raw_handle() as HANDLE)? == self.version,
            "prepared process token changed before launch"
        );
        Ok((self.owners, self.desktop, self.job))
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
