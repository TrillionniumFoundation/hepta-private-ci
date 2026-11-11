use super::LaunchDesktop;
use crate::legacy_admission_tests::assert_unavailable;
use crate::token::LocalSid;
use crate::token::create_readonly_token_with_caps_from;
use crate::token::create_workspace_write_token_with_caps_from;
use crate::token::get_current_token_for_restriction;
use crate::token::mechanism_fixture;
use crate::winutil::to_wide;
use anyhow::Result;
use anyhow::bail;
use pretty_assertions::assert_eq;
use windows_sys::Win32::Foundation::CloseHandle;
use windows_sys::Win32::Foundation::ERROR_ACCESS_DENIED;
use windows_sys::Win32::Foundation::ERROR_SUCCESS;
use windows_sys::Win32::Foundation::GetLastError;
use windows_sys::Win32::Foundation::HANDLE;
use windows_sys::Win32::Foundation::INVALID_HANDLE_VALUE;
use windows_sys::Win32::Security::ImpersonateLoggedOnUser;
use windows_sys::Win32::Security::RevertToSelf;
use windows_sys::Win32::System::StationsAndDesktops::CloseDesktop;
use windows_sys::Win32::System::StationsAndDesktops::DESKTOP_CREATEWINDOW;
use windows_sys::Win32::System::StationsAndDesktops::DESKTOP_WRITEOBJECTS;
use windows_sys::Win32::System::StationsAndDesktops::OpenDesktopW;

struct TokenHandle(HANDLE);

impl Drop for TokenHandle {
    fn drop(&mut self) {
        unsafe { CloseHandle(self.0) };
    }
}

struct DesktopHandle(isize);

impl Drop for DesktopHandle {
    fn drop(&mut self) {
        if self.0 != 0 {
            unsafe { CloseDesktop(self.0) };
        }
    }
}

struct ImpersonationGuard;

impl Drop for ImpersonationGuard {
    fn drop(&mut self) {
        if unsafe { RevertToSelf() } == 0 {
            // Never return a still-impersonating thread to the test harness.
            std::process::abort();
        }
    }
}

fn desktop_write_access(token: HANDLE, name: &str) -> Result<u32> {
    let name = to_wide(name);
    if unsafe { ImpersonateLoggedOnUser(token) } == 0 {
        bail!("ImpersonateLoggedOnUser failed: {}", unsafe {
            GetLastError()
        });
    }
    let _impersonation = ImpersonationGuard;
    let desktop = DesktopHandle(unsafe {
        OpenDesktopW(
            name.as_ptr(),
            /*dwflags*/ 0,
            /*finherit*/ 0,
            DESKTOP_CREATEWINDOW | DESKTOP_WRITEOBJECTS,
        )
    });
    Ok(if desktop.0 == 0 {
        unsafe { GetLastError() }
    } else {
        ERROR_SUCCESS
    })
}

#[test]
fn legacy_refuses_before_workspace_desktop_mechanism_fixture() -> Result<()> {
    let base = TokenHandle(unsafe { get_current_token_for_restriction()? });
    let capability = LocalSid::from_string("S-1-5-21-101-202-303-404")?;
    let other_capability = LocalSid::from_string("S-1-5-21-101-202-303-405")?;
    for capability in [&capability, &other_capability] {
        assert_unavailable(unsafe {
            create_workspace_write_token_with_caps_from(base.0, &[capability.as_ptr()])
                .map(TokenHandle)
        });
    }
    // No process is launched: these test-only tokens exercise only the private
    // desktop created and owned below. Legacy admission remains unavailable.
    let workspace = TokenHandle(unsafe {
        mechanism_fixture::workspace_token_for_owned_objects(base.0, &[capability.as_ptr()])?
    });
    let other_workspace = TokenHandle(unsafe {
        mechanism_fixture::workspace_token_for_owned_objects(base.0, &[other_capability.as_ptr()])?
    });
    let desktop = LaunchDesktop::prepare(
        workspace.0,
        /*use_private_desktop*/ true,
        /*logs_base_dir*/ None,
    )?;
    let name = &desktop
        ._private_desktop
        .as_ref()
        .expect("private desktop")
        .name;
    assert_eq!(desktop_write_access(workspace.0, name)?, ERROR_SUCCESS);
    assert_eq!(
        desktop_write_access(other_workspace.0, name)?,
        ERROR_ACCESS_DENIED
    );
    assert!(
        LaunchDesktop::prepare(
            workspace.0,
            /*use_private_desktop*/ false,
            /*logs_base_dir*/ None,
        )
        .is_err()
    );
    Ok(())
}

#[test]
fn legacy_refuses_before_readonly_desktop_mechanism_fixture() -> Result<()> {
    let base = TokenHandle(unsafe { get_current_token_for_restriction()? });
    let capability = LocalSid::from_string("S-1-5-21-101-202-303-406")?;
    assert_unavailable(unsafe {
        create_readonly_token_with_caps_from(base.0, &[capability.as_ptr()]).map(TokenHandle)
    });
    // Private-desktop access and the default-desktop selector remain native
    // mechanism assertions; neither starts a process under this fixture token.
    let readonly = TokenHandle(unsafe {
        mechanism_fixture::readonly_token_for_owned_objects(base.0, &[capability.as_ptr()])?
    });
    let desktop = LaunchDesktop::prepare(
        readonly.0, /*use_private_desktop*/ true, /*logs_base_dir*/ None,
    )?;
    let name = &desktop
        ._private_desktop
        .as_ref()
        .expect("private desktop")
        .name;
    assert_eq!(desktop_write_access(readonly.0, name)?, ERROR_SUCCESS);
    let default = LaunchDesktop::prepare(
        readonly.0, /*use_private_desktop*/ false, /*logs_base_dir*/ None,
    )?;
    assert_eq!(default.startup_name, to_wide("Winsta0\\Default"));
    Ok(())
}

#[test]
fn desktop_rejects_unrestricted_and_invalid_tokens() -> Result<()> {
    let base = TokenHandle(unsafe { get_current_token_for_restriction()? });
    for token in [base.0, INVALID_HANDLE_VALUE] {
        for use_private_desktop in [true, false] {
            assert!(
                LaunchDesktop::prepare(token, use_private_desktop, /*logs_base_dir*/ None).is_err()
            );
        }
    }
    Ok(())
}
