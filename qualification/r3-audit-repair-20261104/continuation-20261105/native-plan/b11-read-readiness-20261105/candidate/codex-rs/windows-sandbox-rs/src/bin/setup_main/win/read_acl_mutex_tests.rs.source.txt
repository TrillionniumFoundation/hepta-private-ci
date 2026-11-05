use super::acquire_named_read_acl_mutex;
use anyhow::Context;
use anyhow::Result;
use codex_windows_sandbox::to_wide;
use pretty_assertions::assert_eq;
use std::ffi::OsStr;
use std::os::windows::io::FromRawHandle;
use std::os::windows::io::OwnedHandle;
use std::os::windows::io::RawHandle;
use windows_sys::Win32::Foundation::ERROR_ALREADY_EXISTS;
use windows_sys::Win32::System::Threading::MUTEX_ALL_ACCESS;
use windows_sys::Win32::System::Threading::OpenMutexW;

#[test]
fn existing_read_acl_mutex_is_not_a_completion_receipt() -> Result<()> {
    let temp = tempfile::tempdir()?;
    let unique = temp.path().file_name().expect("owned temporary directory");
    let name = format!("Local\\CodexSandboxReadAclTest-{}", unique.to_string_lossy());
    let name = OsStr::new(&name);
    let first = acquire_named_read_acl_mutex(name)?;

    let competing = acquire_named_read_acl_mutex(name)
        .err()
        .expect("an existing mutex must not report readiness");
    assert_eq!(
        competing
            .downcast_ref::<std::io::Error>()
            .and_then(std::io::Error::raw_os_error),
        Some(ERROR_ALREADY_EXISTS as i32)
    );
    assert_eq!(
        competing.to_string(),
        "read ACL preparation mutex already exists; current request is not ready"
    );

    let wide_name = to_wide(name);
    // SAFETY: the live owner's name is NUL-terminated and valid for the call.
    let retained =
        unsafe { OpenMutexW(MUTEX_ALL_ACCESS, /*binherithandle*/ 0, wide_name.as_ptr()) };
    if retained == 0 {
        return Err(std::io::Error::last_os_error()).context("retain owned test mutex");
    }
    // SAFETY: OpenMutexW returned a new valid handle owned solely by this value.
    let retained = unsafe { OwnedHandle::from_raw_handle(retained as RawHandle) };
    drop(first);

    let released_but_retained = acquire_named_read_acl_mutex(name)
        .err()
        .expect("an unowned existing object still is not a completion receipt");
    assert_eq!(
        released_but_retained
            .downcast_ref::<std::io::Error>()
            .and_then(std::io::Error::raw_os_error),
        Some(ERROR_ALREADY_EXISTS as i32)
    );
    assert_eq!(
        released_but_retained.to_string(),
        "read ACL preparation mutex already exists; current request is not ready"
    );

    drop(retained);
    let _after_last_handle_closes = acquire_named_read_acl_mutex(name)?;
    Ok(())
}
