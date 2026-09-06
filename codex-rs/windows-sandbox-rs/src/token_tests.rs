use super::*;
use crate::acl::ensure_allow_mask_aces;
use crate::acl::ensure_allow_write_aces;
use pretty_assertions::assert_eq;
use windows_sys::Win32::Security::EqualSid;
use windows_sys::Win32::Security::ImpersonateLoggedOnUser;
use windows_sys::Win32::Security::RevertToSelf;
use windows_sys::Win32::Security::TokenRestrictedSids;
use windows_sys::Win32::Storage::FileSystem::FILE_ALL_ACCESS;

struct OwnedToken(HANDLE);

impl Drop for OwnedToken {
    fn drop(&mut self) {
        unsafe {
            CloseHandle(self.0);
        }
    }
}

struct Impersonation;

impl Impersonation {
    unsafe fn enter(token: HANDLE) -> Result<Self> {
        if ImpersonateLoggedOnUser(token) == 0 {
            return Err(anyhow!(
                "ImpersonateLoggedOnUser failed: {}",
                GetLastError()
            ));
        }
        Ok(Self)
    }
}

impl Drop for Impersonation {
    fn drop(&mut self) {
        if unsafe { RevertToSelf() } == 0 {
            // Continuing on a reused test thread with the wrong token is unsafe.
            std::process::abort();
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
fn workspace_capabilities_deny_writes_and_deletes_under_broad_identity_aces() -> Result<()> {
    let fixture = tempfile::tempdir()?;
    let base = OwnedToken(unsafe { get_current_token_for_restriction()? });
    let cap_a = LocalSid::from_string("S-1-5-21-101-202-303-404")?;
    let cap_b = LocalSid::from_string("S-1-5-21-111-222-333-444")?;
    let other_cap = LocalSid::from_string("S-1-5-21-121-232-343-454")?;
    let mut logon = unsafe { get_logon_sid_bytes(base.0)? };
    let mut everyone = unsafe { world_sid()? };
    // Deliberately grant broad inherited DELETE and parent DELETE_CHILD inside
    // this owned fixture. Neither identity may substitute for a workspace cap.
    unsafe {
        ensure_allow_mask_aces(
            fixture.path(),
            &[logon.as_mut_ptr().cast(), everyone.as_mut_ptr().cast()],
            FILE_ALL_ACCESS,
        )?;
    }
    let allowed = [
        fixture.path().join("workspace"),
        fixture.path().join("temp"),
    ];
    for (path, cap) in allowed.iter().zip([&cap_a, &cap_b]) {
        std::fs::create_dir(path)?;
        unsafe {
            ensure_allow_write_aces(path, &[cap.as_ptr()])?;
        }
        std::fs::write(path.join("delete.txt"), "inside")?;
        std::fs::create_dir(path.join("delete-dir"))?;
    }
    let outside = fixture.path().join("outside");
    std::fs::create_dir(&outside)?;
    // A stale capability for another root must not authorize this token either.
    unsafe {
        ensure_allow_write_aces(&outside, &[other_cap.as_ptr()])?;
    }
    std::fs::write(outside.join("keep.txt"), "outside")?;
    std::fs::create_dir(outside.join("keep-dir"))?;
    let token = OwnedToken(unsafe {
        create_workspace_write_token_with_caps_from(base.0, &[cap_a.as_ptr(), cap_b.as_ptr()])?
    });
    let (outside_read, refused) = {
        let _impersonation = unsafe { Impersonation::enter(token.0)? };
        for path in &allowed {
            std::fs::write(path.join("created.txt"), "allowed")?;
            std::fs::remove_file(path.join("delete.txt"))?;
            std::fs::remove_dir(path.join("delete-dir"))?;
        }
        let outside_read = std::fs::read_to_string(outside.join("keep.txt"))?;
        let refused = [
            std::fs::write(outside.join("keep.txt"), "overwritten"),
            std::fs::write(outside.join("created.txt"), "outside"),
            std::fs::remove_file(outside.join("keep.txt")),
            std::fs::remove_dir(outside.join("keep-dir")),
        ]
        .map(|result| result.err().map(|error| error.kind()));
        (outside_read, refused)
    };
    assert_eq!(refused, [Some(std::io::ErrorKind::PermissionDenied); 4]);
    assert_eq!(outside_read, "outside");
    assert_eq!(
        (
            std::fs::read_to_string(outside.join("keep.txt"))?,
            outside.join("created.txt").exists(),
            outside.join("keep-dir").is_dir()
        ),
        ("outside".to_owned(), false, true)
    );
    for path in &allowed {
        assert_eq!(
            (
                std::fs::read_to_string(path.join("created.txt"))?,
                path.join("delete.txt").exists(),
                path.join("delete-dir").exists()
            ),
            ("allowed".to_owned(), false, false)
        );
    }
    Ok(())
}
