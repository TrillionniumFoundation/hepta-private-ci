use anyhow::Result;
use codex_windows_sandbox::LocalSid;
use codex_windows_sandbox::grant_read_capability_for_root;
use codex_windows_sandbox::read_cap_sid_for_root;
use std::ffi::c_void;
use std::path::PathBuf;

/// Completes normal-account and restricting-SID root grants before launch.
pub(super) fn apply(read_roots: &[PathBuf], sandbox_group: *mut c_void) -> Result<()> {
    for root in read_roots {
        let sid = LocalSid::from_string(&read_cap_sid_for_root(root)?)?;
        // SAFETY: setup retains the group allocation and LocalSid through the call.
        unsafe { grant_read_capability_for_root(root, sandbox_group, sid.as_ptr()) }?;
    }
    Ok(())
}
