use super::LaunchDesktop;
use crate::legacy_admission_tests::assert_unavailable;
use crate::token::LocalSid;
use crate::token::create_readonly_token_with_caps_from;
use crate::token::create_workspace_write_token_with_caps_from;
use crate::token::get_current_token_for_restriction;
use anyhow::Result;
use windows_sys::Win32::Foundation::CloseHandle;
use windows_sys::Win32::Foundation::HANDLE;
use windows_sys::Win32::Foundation::INVALID_HANDLE_VALUE;

struct TokenHandle(HANDLE);

impl Drop for TokenHandle {
    fn drop(&mut self) {
        unsafe { CloseHandle(self.0) };
    }
}

#[test]
fn workspace_private_desktop_requires_a_qualified_token_backend() -> Result<()> {
    let base = TokenHandle(unsafe { get_current_token_for_restriction()? });
    let capability = LocalSid::from_string("S-1-5-21-101-202-303-404")?;
    let other_capability = LocalSid::from_string("S-1-5-21-101-202-303-405")?;
    for capability in [&capability, &other_capability] {
        // Keep the valid base and capability alive; admission must refuse before
        // a legacy token can be used for any desktop access.
        assert_unavailable(unsafe {
            create_workspace_write_token_with_caps_from(base.0, &[capability.as_ptr()])
                .map(TokenHandle)
        });
    }
    Ok(())
}

#[test]
fn readonly_desktop_requires_a_qualified_token_backend() -> Result<()> {
    let base = TokenHandle(unsafe { get_current_token_for_restriction()? });
    let capability = LocalSid::from_string("S-1-5-21-101-202-303-406")?;
    assert_unavailable(unsafe {
        create_readonly_token_with_caps_from(base.0, &[capability.as_ptr()]).map(TokenHandle)
    });
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
