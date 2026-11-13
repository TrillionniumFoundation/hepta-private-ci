use super::*;
use crate::legacy_admission_tests::assert_unavailable;
use pretty_assertions::assert_eq;
use windows_sys::Win32::Security::EqualSid;
use windows_sys::Win32::Security::TokenRestrictedSids;

struct OwnedToken(HANDLE);

impl Drop for OwnedToken {
    fn drop(&mut self) {
        unsafe {
            CloseHandle(self.0);
        }
    }
}

unsafe fn token_has_restricting_sid(token: HANDLE, expected_sid: *mut c_void) -> Result<bool> {
    let mut needed = 0;
    GetTokenInformation(
        token,
        TokenRestrictedSids,
        std::ptr::null_mut(),
        0,
        &mut needed,
    );
    if needed == 0 {
        return Err(anyhow!(
            "GetTokenInformation(TokenRestrictedSids) size query failed: {}",
            GetLastError()
        ));
    }

    let mut buffer = vec![0_u8; needed as usize];
    if GetTokenInformation(
        token,
        TokenRestrictedSids,
        buffer.as_mut_ptr().cast(),
        needed,
        &mut needed,
    ) == 0
    {
        return Err(anyhow!(
            "GetTokenInformation(TokenRestrictedSids) failed: {}",
            GetLastError()
        ));
    }

    let group_count = std::ptr::read_unaligned(buffer.as_ptr().cast::<u32>()) as usize;
    let after_count = buffer.as_ptr().add(std::mem::size_of::<u32>()) as usize;
    let align = std::mem::align_of::<SID_AND_ATTRIBUTES>();
    let entries_addr = (after_count + (align - 1)) & !(align - 1);
    let restricting_sids =
        std::slice::from_raw_parts(entries_addr as *const SID_AND_ATTRIBUTES, group_count);
    Ok(restricting_sids
        .iter()
        .any(|entry| EqualSid(entry.Sid, expected_sid) != 0))
}

#[test]
fn elevated_token_includes_network_proxy_restricting_sid() -> Result<()> {
    let capability_sid = LocalSid::from_string("S-1-5-21-10-20-30-40")?;
    let network_proxy_sid = LocalSid::from_string("S-1-5-21-50-60-70-80")?;
    let base_token = unsafe { get_current_token_for_restriction()? };
    let restricted_token = unsafe {
        create_readonly_token_with_caps_and_user_from(
            base_token,
            &[capability_sid.as_ptr()],
            &[network_proxy_sid.as_ptr()],
        )?
    };

    let has_network_proxy_sid =
        unsafe { token_has_restricting_sid(restricted_token, network_proxy_sid.as_ptr()) };
    unsafe {
        CloseHandle(restricted_token);
        CloseHandle(base_token);
    }

    assert!(has_network_proxy_sid?);
    Ok(())
}

#[test]
fn workspace_token_refusal_leaves_existing_files_unchanged() -> Result<()> {
    let fixture = tempfile::tempdir()?;
    let existing = fixture.path().join("existing.txt");
    std::fs::write(&existing, "original")?;
    let capability = LocalSid::from_string("S-1-5-21-171-272-373-474")?;
    let base = OwnedToken(unsafe { get_current_token_for_restriction()? });
    assert_unavailable(unsafe {
        create_workspace_write_token_with_caps_from(base.0, &[capability.as_ptr()])
            .map(OwnedToken)
    });
    assert_eq!(std::fs::read_to_string(&existing)?, "original");
    assert_eq!(std::fs::read_dir(fixture.path())?.count(), 1);
    Ok(())
}

#[test]
fn workspace_token_refuses_multiple_capabilities_before_native_access() -> Result<()> {
    let first = LocalSid::from_string("S-1-5-21-101-202-303-404")?;
    let second = LocalSid::from_string("S-1-5-21-101-202-303-405")?;
    let base = OwnedToken(unsafe { get_current_token_for_restriction()? });
    assert_unavailable(unsafe {
        create_workspace_write_token_with_caps_from(base.0, &[first.as_ptr(), second.as_ptr()])
            .map(OwnedToken)
    });
    Ok(())
}

#[test]
fn workspace_token_refuses_empty_and_unrelated_capability_sets() -> Result<()> {
    let other = LocalSid::from_string("S-1-5-21-111-222-333-444")?;
    let unrelated = [other.as_ptr()];
    let base = OwnedToken(unsafe { get_current_token_for_restriction()? });
    for capabilities in [&[][..], unrelated.as_slice()] {
        assert_unavailable(unsafe {
            create_workspace_write_token_with_caps_from(base.0, capabilities).map(OwnedToken)
        });
    }
    Ok(())
}
