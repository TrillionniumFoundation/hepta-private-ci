use super::*;
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
fn legacy_readonly_restrictions_use_the_capability_not_broad_identity_sids() -> Result<()> {
    let capability = LocalSid::from_string("S-1-5-21-10-20-30-40")?;
    let everyone = LocalSid::from_string("S-1-1-0")?;
    // SAFETY: the primary and restricted token handles are owned until the
    // native queries complete; SID allocations outlive those calls.
    unsafe {
        let base = OwnedToken(get_current_token_for_restriction()?);
        let mut logon_sid = get_logon_sid_bytes(base.0)?;
        let (token, _) = create_readonly_token_with_cap_from(base.0, capability.as_ptr())?;
        let token = OwnedToken(token);
        assert!(token_has_restricting_sid(token.0, capability.as_ptr())?);
        assert!(!token_has_restricting_sid(token.0, everyone.as_ptr())?);
        assert!(!token_has_restricting_sid(
            token.0,
            logon_sid.as_mut_ptr().cast(),
        )?);
    }
    Ok(())
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
fn workspace_capability_token_has_no_broad_restricting_identity() -> Result<()> {
    let capability = LocalSid::from_string("S-1-5-21-51-61-71-81")?;
    let everyone = LocalSid::from_string("S-1-1-0")?;
    // SAFETY: token lifetime and SID allocations cover native metadata queries.
    unsafe {
        let base = OwnedToken(get_current_token_for_restriction()?);
        let mut logon_sid = get_logon_sid_bytes(base.0)?;
        let token = OwnedToken(create_workspace_write_token_with_caps_from(
            base.0,
            &[capability.as_ptr()],
        )?);
        assert!(token_has_restricting_sid(token.0, capability.as_ptr())?);
        assert!(!token_has_restricting_sid(token.0, everyone.as_ptr())?);
        assert!(!token_has_restricting_sid(
            token.0,
            logon_sid.as_mut_ptr().cast(),
        )?);
    }
    Ok(())
}
