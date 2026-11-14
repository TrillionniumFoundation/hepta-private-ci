use anyhow::Result;
use codex_windows_sandbox::LocalSid;
use codex_windows_sandbox::grant_read_capability_for_root;
use codex_windows_sandbox::read_cap_sid_for_root;
use std::ffi::c_void;
use std::path::PathBuf;

/// Completes normal-account and restricting-SID root grants before launch.
pub(super) fn apply(read_roots: &[PathBuf], sandbox_group: *mut c_void) -> Result<()> {
    for root in read_roots {
        let started = std::time::Instant::now();
        codex_windows_sandbox::trace_sandbox_phase(
            &format!("read-cap root grant begin: {}", root.display()),
            None,
        );
        let sid = LocalSid::from_string(&read_cap_sid_for_root(root)?)?;
        // SAFETY: setup retains the group allocation and LocalSid through the call.
        let result = unsafe { grant_read_capability_for_root(root, sandbox_group, sid.as_ptr()) };
        codex_windows_sandbox::trace_sandbox_phase(
            &format!(
                "read-cap root grant end: {} elapsed_ms={} success={}",
                root.display(),
                started.elapsed().as_millis(),
                result.is_ok()
            ),
            None,
        );
        result?;
    }
    Ok(())
}
