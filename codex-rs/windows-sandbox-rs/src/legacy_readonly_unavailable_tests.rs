use anyhow::Result;
use codex_protocol::models::PermissionProfile;
use codex_utils_absolute_path::AbsolutePathBuf;
use pretty_assertions::assert_eq;
use std::collections::HashMap;
use std::ffi::c_void;
use std::io::ErrorKind;
use std::os::windows::io::FromRawHandle;
use std::os::windows::io::OwnedHandle;

fn require_unsupported(error: &anyhow::Error) {
    assert_eq!(
        error
            .downcast_ref::<std::io::Error>()
            .map(std::io::Error::kind),
        Some(ErrorKind::Unsupported),
    );
    assert!(error.to_string().contains("ambient identity writes"));
}

#[test]
fn legacy_ambient_readonly_returns_no_token() -> Result<()> {
    // SAFETY: this call returns one newly owned process-token handle.
    let raw = unsafe { crate::token::get_current_token_for_restriction()? };
    // SAFETY: immediately take sole ownership of that live handle.
    let _base = unsafe { OwnedHandle::from_raw_handle(raw as *mut c_void) };
    let cap = crate::token::LocalSid::from_string("S-1-5-21-101-202-303-404")?;
    // SAFETY: the original base and capability allocations remain live. Each
    // unexpected success is immediately owned, including unvisited results.
    let results = unsafe {
        [
            crate::token::create_readonly_token_with_caps_from(raw, &[cap.as_ptr()]),
            crate::token::create_readonly_token_with_cap_from(raw, cap.as_ptr())
                .map(|(token, _)| token),
            crate::token::create_readonly_token_with_cap(cap.as_ptr()).map(|(token, _)| token),
        ]
        .map(|result| result.map(|token| OwnedHandle::from_raw_handle(token as *mut c_void)))
    };
    for result in results {
        match result {
            Err(error) => require_unsupported(&error),
            Ok(_unexpected_token) => {
                anyhow::bail!("legacy ambient readonly returned an unsafe token")
            }
        }
    }
    Ok(())
}

#[test]
fn legacy_ambient_readonly_capture_never_reaches_process_creation() -> Result<()> {
    let temporary = tempfile::tempdir()?;
    let root = temporary.path().canonicalize()?;
    let workspace = root.join("workspace");
    std::fs::create_dir(&workspace)?;
    let outside = root.join("outside.txt");
    std::fs::write(&outside, b"retained outside bytes")?;
    let marker = workspace.join("child-started.txt");
    let home = root.join("codex-home");
    let roots = [AbsolutePathBuf::from_absolute_path(&workspace)?];
    let profile = PermissionProfile::read_only();
    let system_root = std::env::var("SystemRoot")?;
    let command = vec![
        std::path::Path::new(&system_root)
            .join("System32/cmd.exe")
            .to_string_lossy()
            .into_owned(),
        "/d".into(),
        "/c".into(),
        format!(
            "echo started>\"{}\" & del /q \"{}\"",
            marker.display(),
            outside.display()
        ),
    ];
    let attempts = crate::process::launch_attempts_on_current_thread();
    let result = crate::run_windows_sandbox_capture(
        &profile,
        &roots,
        &home,
        command,
        &workspace,
        HashMap::from([("SystemRoot".into(), system_root)]),
        /*timeout_ms*/ Some(10_000),
        /*cancellation*/ None,
        /*use_private_desktop*/ true,
    );
    let error = match result {
        Err(error) => error,
        Ok(_) => anyhow::bail!("legacy ambient readonly launched instead of refusing"),
    };
    require_unsupported(&error);
    assert_eq!(
        (
            crate::process::launch_attempts_on_current_thread() - attempts,
            marker.exists(),
            std::fs::read(&outside)?,
        ),
        (0, false, b"retained outside bytes".to_vec()),
    );
    Ok(())
}

#[test]
fn legacy_ambient_readonly_preflight_refuses_before_acl_setup() -> Result<()> {
    let temporary = tempfile::tempdir()?;
    let workspace = temporary.path().canonicalize()?;
    let home = workspace.join("must-not-be-created");
    let roots = [AbsolutePathBuf::from_absolute_path(&workspace)?];
    let profile = PermissionProfile::read_only();
    let result = crate::run_windows_sandbox_legacy_preflight(
        &profile,
        &roots,
        &home,
        &workspace,
        &HashMap::new(),
    );
    let error = match result {
        Err(error) => error,
        Ok(()) => anyhow::bail!("unsupported legacy readonly preflight succeeded"),
    };
    require_unsupported(&error);
    assert!(!home.exists());
    Ok(())
}
