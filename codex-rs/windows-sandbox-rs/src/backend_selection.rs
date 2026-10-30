use anyhow::Result;
use anyhow::bail;
use codex_protocol::config_types::WindowsSandboxLevel;

/// Configuration checks shared by every public broker launch entry point.
pub(crate) struct WindowsSandboxBrokerRequest<'a> {
    pub(crate) windows_sandbox_level: WindowsSandboxLevel,
    pub(crate) proxy_enforced: bool,
    pub(crate) network_proxy_restricting_sid: Option<&'a str>,
}

/// Require the broker without permitting a fallback to the direct token path.
///
/// A `WRITE_RESTRICTED` token limits ordinary write access through restricting
/// SIDs, but Windows can authorize deletion through a parent directory's
/// `FILE_DELETE_CHILD` right. That alternate authorization path means the
/// restricted-token backend cannot prove that deletion stays inside the
/// declared writable roots. Explicit filesystem overrides have the same
/// problem because their effective parent ACLs are not part of the token.
///
/// A read-only request still forbids deletion. Its former token also retained
/// Logon/Everyone as alternative restricting SID matches, so broad identity
/// grants cannot establish a no-write boundary. All public sandbox launches
/// therefore use the broker. This admission rule does not by itself qualify
/// the broker's filesystem enforcement; native boundary tests must still pass.
pub(crate) fn require_windows_sandbox_broker(
    request: &WindowsSandboxBrokerRequest<'_>,
) -> Result<()> {
    if matches!(request.windows_sandbox_level, WindowsSandboxLevel::Elevated) {
        return Ok(());
    }
    if request.proxy_enforced {
        bail!("managed networking requires the elevated Windows sandbox backend");
    }
    if request.network_proxy_restricting_sid.is_some() {
        bail!("network proxy restricting SID requires the elevated Windows sandbox backend");
    }

    Ok(())
}
