use super::*;
use crate::acl::add_deny_write_ace;
use crate::acl::ensure_allow_mask_aces;
use crate::acl::ensure_allow_write_aces;
use crate::acl::fetch_dacl_handle;
use pretty_assertions::assert_eq;
use windows_sys::Win32::Security::Authorization::DENY_ACCESS;
use windows_sys::Win32::Security::Authorization::SE_FILE_OBJECT;
use windows_sys::Win32::Security::Authorization::SetNamedSecurityInfoW;
use windows_sys::Win32::Security::CONTAINER_INHERIT_ACE;
use windows_sys::Win32::Security::DACL_SECURITY_INFORMATION;
use windows_sys::Win32::Security::EqualSid;
use windows_sys::Win32::Security::ImpersonateLoggedOnUser;
use windows_sys::Win32::Security::OBJECT_INHERIT_ACE;
use windows_sys::Win32::Security::RevertToSelf;
use windows_sys::Win32::Security::TokenRestrictedSids;
use windows_sys::Win32::Storage::FileSystem::DELETE;
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
fn partial_delete_deny_is_repaired_before_native_workspace_writes() -> Result<()> {
    let fixture = tempfile::tempdir()?;
    let capability = LocalSid::from_string("S-1-5-21-171-272-373-474")?;
    let everyone = LocalSid::from_string("S-1-1-0")?;
    // SAFETY: the existing fixture and validated SIDs remain live for both grants.
    unsafe {
        ensure_allow_mask_aces(fixture.path(), &[everyone.as_ptr()], FILE_ALL_ACCESS)?;
        ensure_allow_write_aces(fixture.path(), &[capability.as_ptr()])?;
    }
    let existing = fixture.path().join("existing.txt");
    let created = fixture.path().join("created.txt");
    std::fs::write(&existing, "original")?;
    let entry = EXPLICIT_ACCESS_W {
        grfAccessPermissions: DELETE,
        grfAccessMode: DENY_ACCESS,
        grfInheritance: OBJECT_INHERIT_ACE | CONTAINER_INHERIT_ACE,
        Trustee: TRUSTEE_W {
            pMultipleTrustee: std::ptr::null_mut(),
            MultipleTrusteeOperation: 0,
            TrusteeForm: TRUSTEE_IS_SID,
            TrusteeType: TRUSTEE_IS_UNKNOWN,
            ptstrName: capability.as_ptr().cast(),
        },
    };
    // SAFETY: the fixture exists and all SID/ACL allocations live through their
    // calls. Both returned allocations are freed after the named setter copies.
    let code = unsafe {
        let (dacl, descriptor) = fetch_dacl_handle(fixture.path())?;
        let mut partial_dacl = std::ptr::null_mut();
        let code = SetEntriesInAclW(
            /*ccountofexplicitentries*/ 1,
            &entry,
            dacl,
            &mut partial_dacl,
        );
        let code = if code == ERROR_SUCCESS {
            SetNamedSecurityInfoW(
                to_wide(fixture.path()).as_ptr() as *mut u16,
                SE_FILE_OBJECT,
                DACL_SECURITY_INFORMATION,
                std::ptr::null_mut(),
                std::ptr::null_mut(),
                partial_dacl,
                std::ptr::null_mut(),
            )
        } else {
            code
        };
        if !partial_dacl.is_null() {
            LocalFree(partial_dacl as HLOCAL);
        }
        LocalFree(descriptor as HLOCAL);
        code
    };
    anyhow::ensure!(code == ERROR_SUCCESS, "seed partial delete deny: {code}");
    // SAFETY: the base token stays owned until restricted-token creation completes.
    let base = OwnedToken(unsafe { get_current_token_for_restriction()? });
    // SAFETY: the owned base token and validated capability SID are live; the
    // resulting token is immediately owned and closed after both impersonations.
    let token = OwnedToken(unsafe {
        create_workspace_write_token_with_caps_from(base.0, &[capability.as_ptr()])?
    });
    {
        // SAFETY: token remains owned throughout this impersonation scope.
        let _impersonation = unsafe { Impersonation::enter(token.0)? };
        std::fs::write(&existing, "before repair")?;
    }
    // SAFETY: the fixture and validated capability SID are live for the repair.
    let repaired = unsafe { add_deny_write_ace(fixture.path(), capability.as_ptr())? };
    // SAFETY: the same objects remain live. Check native directory and file
    // storage retains the constructor's complete mask and inheritance scope.
    let repeated_repairs = unsafe {
        (
            add_deny_write_ace(fixture.path(), capability.as_ptr())?,
            add_deny_write_ace(&existing, capability.as_ptr())?,
            add_deny_write_ace(&existing, capability.as_ptr())?,
        )
    };
    let (read, denied) = {
        // SAFETY: token remains owned throughout this impersonation scope.
        let _impersonation = unsafe { Impersonation::enter(token.0)? };
        let read = std::fs::read_to_string(&existing)?;
        let denied = [
            std::fs::write(&existing, "after repair"),
            std::fs::write(&created, "created"),
        ]
        .map(|result| result.err().map(|error| error.kind()));
        (read, denied)
    };
    assert_eq!(
        (repaired, denied),
        (true, [Some(std::io::ErrorKind::PermissionDenied); 2]),
    );
    assert_eq!(repeated_repairs, (false, true, false));
    assert_eq!(read, "before repair");
    assert_eq!(
        (std::fs::read_to_string(&existing)?, created.exists()),
        ("before repair".to_owned(), false),
    );
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

/// Measure the two independent Windows deletion grants with actual file objects.
/// This is diagnostic evidence, not a replacement for the original refusal tests.
#[test]
fn record_native_write_restricted_delete_routes() -> Result<()> {
    use std::os::windows::fs::OpenOptionsExt;

    #[derive(Clone, Copy)]
    enum Grant {
        None,
        Own,
        Other,
    }

    unsafe fn token_integrity_sid(token: HANDLE) -> Result<String> {
        use windows_sys::Win32::Security::TOKEN_MANDATORY_LABEL;
        use windows_sys::Win32::Security::TokenIntegrityLevel;
        let mut needed = 0;
        GetTokenInformation(
            token,
            TokenIntegrityLevel,
            std::ptr::null_mut(),
            0,
            &mut needed,
        );
        anyhow::ensure!(needed as usize >= std::mem::size_of::<TOKEN_MANDATORY_LABEL>());
        let mut buffer = vec![0u8; needed as usize];
        let ok = GetTokenInformation(
            token,
            TokenIntegrityLevel,
            buffer.as_mut_ptr().cast(),
            needed,
            &mut needed,
        );
        anyhow::ensure!(
            ok != 0,
            "query diagnostic token integrity: {}",
            GetLastError()
        );
        let label = std::ptr::read_unaligned(buffer.as_ptr().cast::<TOKEN_MANDATORY_LABEL>());
        let mut text: *mut u16 = std::ptr::null_mut();
        let ok = windows_sys::Win32::Security::Authorization::ConvertSidToStringSidW(
            label.Label.Sid,
            &mut text,
        );
        anyhow::ensure!(
            ok != 0,
            "format diagnostic integrity SID: {}",
            GetLastError()
        );
        let mut length = 0;
        while *text.add(length) != 0 {
            length += 1;
        }
        let result = String::from_utf16_lossy(std::slice::from_raw_parts(text, length));
        LocalFree(text as HLOCAL);
        Ok(result)
    }

    unsafe fn low_label(path: &std::path::Path) -> Result<()> {
        use windows_sys::Win32::Security::LABEL_SECURITY_INFORMATION;
        let mut descriptor = std::ptr::null_mut();
        let ok = windows_sys::Win32::Security::Authorization::ConvertStringSecurityDescriptorToSecurityDescriptorW(
            to_wide("S:(ML;OICI;NW;;;LW)").as_ptr(), 1, &mut descriptor, std::ptr::null_mut(),
        );
        anyhow::ensure!(
            ok != 0,
            "parse diagnostic mandatory label: {}",
            GetLastError()
        );
        let result = (|| -> Result<()> {
            let mut present = 0;
            let mut defaulted = 0;
            let mut sacl = std::ptr::null_mut();
            let ok = windows_sys::Win32::Security::GetSecurityDescriptorSacl(
                descriptor,
                &mut present,
                &mut sacl,
                &mut defaulted,
            );
            anyhow::ensure!(ok != 0 && present != 0 && !sacl.is_null());
            let code = SetNamedSecurityInfoW(
                to_wide(path).as_ptr() as *mut u16,
                SE_FILE_OBJECT,
                LABEL_SECURITY_INFORMATION,
                std::ptr::null_mut(),
                std::ptr::null_mut(),
                std::ptr::null_mut(),
                sacl,
            );
            anyhow::ensure!(code == ERROR_SUCCESS, "set diagnostic Low label: {code}");
            Ok(())
        })();
        LocalFree(descriptor as HLOCAL);
        result
    }

    unsafe fn actual_label(path: &std::path::Path) -> Result<String> {
        use windows_sys::Win32::Security::LABEL_SECURITY_INFORMATION;
        let mut descriptor = std::ptr::null_mut();
        let code = windows_sys::Win32::Security::Authorization::GetNamedSecurityInfoW(
            to_wide(path).as_ptr(),
            SE_FILE_OBJECT,
            LABEL_SECURITY_INFORMATION,
            std::ptr::null_mut(),
            std::ptr::null_mut(),
            std::ptr::null_mut(),
            std::ptr::null_mut(),
            &mut descriptor,
        );
        anyhow::ensure!(
            code == ERROR_SUCCESS,
            "read diagnostic mandatory label: {code}"
        );
        let mut text: *mut u16 = std::ptr::null_mut();
        let ok = windows_sys::Win32::Security::Authorization::ConvertSecurityDescriptorToStringSecurityDescriptorW(
            descriptor, 1, LABEL_SECURITY_INFORMATION, &mut text, std::ptr::null_mut(),
        );
        let error = GetLastError();
        LocalFree(descriptor as HLOCAL);
        anyhow::ensure!(ok != 0, "format actual mandatory label: {error}");
        let mut length = 0;
        while *text.add(length) != 0 {
            length += 1;
        }
        let result = String::from_utf16_lossy(std::slice::from_raw_parts(text, length));
        LocalFree(text as HLOCAL);
        Ok(result)
    }

    unsafe fn deny_parent_delete(path: &std::path::Path, everyone: *mut c_void) -> Result<()> {
        let (old_acl, descriptor) = fetch_dacl_handle(path)?;
        let entry = EXPLICIT_ACCESS_W {
            grfAccessPermissions: windows_sys::Win32::Storage::FileSystem::FILE_DELETE_CHILD,
            grfAccessMode: DENY_ACCESS,
            grfInheritance: CONTAINER_INHERIT_ACE,
            Trustee: TRUSTEE_W {
                pMultipleTrustee: std::ptr::null_mut(),
                MultipleTrusteeOperation: 0,
                TrusteeForm: TRUSTEE_IS_SID,
                TrusteeType: TRUSTEE_IS_UNKNOWN,
                ptstrName: everyone.cast(),
            },
        };
        let mut acl = std::ptr::null_mut();
        let code = SetEntriesInAclW(1, &entry, old_acl, &mut acl);
        let applied = if code == ERROR_SUCCESS {
            SetNamedSecurityInfoW(
                to_wide(path).as_ptr() as *mut u16,
                SE_FILE_OBJECT,
                DACL_SECURITY_INFORMATION,
                std::ptr::null_mut(),
                std::ptr::null_mut(),
                acl,
                std::ptr::null_mut(),
            )
        } else {
            code
        };
        if !acl.is_null() {
            LocalFree(acl as HLOCAL);
        }
        if !descriptor.is_null() {
            LocalFree(descriptor as HLOCAL);
        }
        anyhow::ensure!(
            applied == ERROR_SUCCESS,
            "set diagnostic parent delete deny: {applied}"
        );
        Ok(())
    }

    fn result<T>(value: std::io::Result<T>) -> serde_json::Value {
        match value {
            Ok(_) => serde_json::json!({"allowed": true, "error": null}),
            Err(error) => serde_json::json!({
                "allowed": false,
                "error": error.raw_os_error(),
                "kind": format!("{:?}", error.kind()),
            }),
        }
    }

    unsafe fn replace_dacl(path: &std::path::Path, grants: &[(*mut c_void, u32)]) -> Result<()> {
        let entries: Vec<EXPLICIT_ACCESS_W> = grants
            .iter()
            .map(|(sid, mask)| EXPLICIT_ACCESS_W {
                grfAccessPermissions: *mask,
                grfAccessMode: GRANT_ACCESS,
                grfInheritance: 0,
                Trustee: TRUSTEE_W {
                    pMultipleTrustee: std::ptr::null_mut(),
                    MultipleTrusteeOperation: 0,
                    TrusteeForm: TRUSTEE_IS_SID,
                    TrusteeType: TRUSTEE_IS_UNKNOWN,
                    ptstrName: sid.cast(),
                },
            })
            .collect();
        let mut acl = std::ptr::null_mut();
        let code = SetEntriesInAclW(
            entries.len() as u32,
            entries.as_ptr(),
            std::ptr::null_mut(),
            &mut acl,
        );
        anyhow::ensure!(code == ERROR_SUCCESS, "create diagnostic DACL: {code}");
        let code = SetNamedSecurityInfoW(
            to_wide(path).as_ptr() as *mut u16,
            SE_FILE_OBJECT,
            DACL_SECURITY_INFORMATION
                | windows_sys::Win32::Security::PROTECTED_DACL_SECURITY_INFORMATION,
            std::ptr::null_mut(),
            std::ptr::null_mut(),
            acl,
            std::ptr::null_mut(),
        );
        if !acl.is_null() {
            LocalFree(acl as HLOCAL);
        }
        anyhow::ensure!(code == ERROR_SUCCESS, "set diagnostic DACL: {code}");
        Ok(())
    }

    let fixture = tempfile::tempdir()?;
    let base = OwnedToken(unsafe { get_current_token_for_restriction()? });
    let capability = LocalSid::from_string("S-1-5-21-151-252-353-454")?;
    let other_capability = LocalSid::from_string("S-1-5-21-161-262-363-464")?;
    let everyone = LocalSid::from_string("S-1-1-0")?;
    let write_restricted = OwnedToken(unsafe {
        create_workspace_write_token_with_caps_from(base.0, &[capability.as_ptr()])?
    });
    let full_restricted = OwnedToken(unsafe {
        let mut token = 0;
        let entry = SID_AND_ATTRIBUTES {
            Sid: capability.as_ptr(),
            Attributes: 0,
        };
        let ok = CreateRestrictedToken(
            base.0,
            DISABLE_MAX_PRIVILEGE | LUA_TOKEN,
            0,
            std::ptr::null(),
            0,
            std::ptr::null(),
            1,
            &entry,
            &mut token,
        );
        anyhow::ensure!(
            ok != 0,
            "create all-access restricted control: {}",
            GetLastError()
        );
        token
    });
    let low_restricted = OwnedToken(unsafe {
        let token = create_workspace_write_token_with_caps_from(base.0, &[capability.as_ptr()])?;
        let low = LocalSid::from_string("S-1-16-4096")?;
        let label = windows_sys::Win32::Security::TOKEN_MANDATORY_LABEL {
            Label: SID_AND_ATTRIBUTES {
                Sid: low.as_ptr(),
                Attributes: windows_sys::Win32::System::SystemServices::SE_GROUP_INTEGRITY as u32,
            },
        };
        let ok = SetTokenInformation(
            token,
            windows_sys::Win32::Security::TokenIntegrityLevel,
            (&label as *const windows_sys::Win32::Security::TOKEN_MANDATORY_LABEL).cast(),
            std::mem::size_of_val(&label) as u32 + GetLengthSid(low.as_ptr()),
        );
        if ok == 0 {
            let error = GetLastError();
            CloseHandle(token);
            return Err(anyhow!("lower diagnostic token integrity: {error}"));
        }
        token
    });
    assert_eq!(
        unsafe { token_integrity_sid(low_restricted.0)? },
        "S-1-16-4096"
    );
    for token in [write_restricted.0, full_restricted.0, low_restricted.0] {
        assert!(unsafe { token_has_restricting_sid(token, capability.as_ptr())? });
        assert!(!unsafe { token_has_restricting_sid(token, everyone.as_ptr())? });
    }

    let read_mask = windows_sys::Win32::Storage::FileSystem::FILE_GENERIC_READ
        | windows_sys::Win32::Storage::FileSystem::FILE_GENERIC_EXECUTE;
    let capability_mask =
        read_mask | windows_sys::Win32::Storage::FileSystem::FILE_GENERIC_WRITE | DELETE;
    let delete_child = windows_sys::Win32::Storage::FileSystem::FILE_DELETE_CHILD;
    let mut observations = Vec::new();
    for (mode, token, lowered, protect_low_roots) in [
        (
            "actual-production-write-restricted",
            write_restricted.0,
            false,
            false,
        ),
        (
            "independent-control-all-access-restricted",
            full_restricted.0,
            false,
            false,
        ),
        ("independent-low-integrity", low_restricted.0, true, false),
        (
            "independent-low-integrity-parent-deny",
            low_restricted.0,
            true,
            true,
        ),
    ] {
        let actual_token_integrity = unsafe { token_integrity_sid(token)? };
        for (label, child_delete, parent_delete, grant) in [
            ("file-delete-only", true, false, Grant::None),
            ("parent-delete-child-only", false, true, Grant::None),
            ("neither-delete-grant", false, false, Grant::None),
            ("explicit-workspace-capability", true, false, Grant::Own),
            ("other-workspace-capability", true, true, Grant::Other),
        ] {
            let parent = fixture.path().join(format!("{mode}-{label}"));
            std::fs::create_dir(&parent)?;
            let file = parent.join("file.txt");
            let directory = parent.join("empty-directory");
            std::fs::write(&file, "original")?;
            std::fs::create_dir(&directory)?;
            let cap_grant = matches!(grant, Grant::Own);
            let granted_sid = match grant {
                Grant::None => None,
                Grant::Own => Some(capability.as_ptr()),
                Grant::Other => Some(other_capability.as_ptr()),
            };
            // This diagnostic changes only its own objects, before replacing
            // their DACLs. Production grant and token construction stay unchanged.
            if lowered && granted_sid.is_some() {
                for path in [&parent, &file, &directory] {
                    unsafe { low_label(path)? };
                }
            }
            let parent_mask = read_mask | if parent_delete { delete_child } else { 0 };
            let child_mask = read_mask | if child_delete { DELETE } else { 0 };
            let parent_grants = match granted_sid {
                Some(sid) => vec![(everyone.as_ptr(), FILE_ALL_ACCESS), (sid, capability_mask)],
                None => vec![(everyone.as_ptr(), parent_mask)],
            };
            let child_grants = match granted_sid {
                Some(sid) => vec![(everyone.as_ptr(), FILE_ALL_ACCESS), (sid, capability_mask)],
                None => vec![(everyone.as_ptr(), child_mask)],
            };
            unsafe {
                replace_dacl(&parent, &parent_grants)?;
                replace_dacl(&file, &child_grants)?;
                replace_dacl(&directory, &child_grants)?;
                if protect_low_roots && granted_sid.is_some() {
                    deny_parent_delete(&parent, everyone.as_ptr())?;
                }
            }
            let labels = unsafe {
                [
                    actual_label(&parent)?,
                    actual_label(&file)?,
                    actual_label(&directory)?,
                ]
            };
            let mut observation = {
                let _impersonation = unsafe { Impersonation::enter(token)? };
                let probe = |path: &std::path::Path, mask| {
                    result(
                        std::fs::OpenOptions::new()
                            .access_mode(mask)
                            .share_mode(7)
                            .custom_flags(
                                windows_sys::Win32::Storage::FileSystem::FILE_FLAG_BACKUP_SEMANTICS,
                            )
                            .open(path),
                    )
                };
                serde_json::json!({
                    "mode": mode,
                    "case": label,
                    "parent_everyone_mask": parent_grants[0].1,
                    "child_everyone_mask": child_grants[0].1,
                    "capability_granted": cap_grant,
                    "other_capability_granted": matches!(grant, Grant::Other),
                    "actual_token_integrity_sid": actual_token_integrity,
                    "actual_parent_file_directory_labels": labels,
                    "parent_delete_child_deny": protect_low_roots && granted_sid.is_some(),
                    "read": result(std::fs::read(&file)),
                    "write": result(std::fs::write(&file, "rewritten")),
                    "file_delete_handle": probe(&file, DELETE),
                    "parent_delete_child_handle": probe(&parent, delete_child),
                    "write_dac_handle": probe(
                        &file, windows_sys::Win32::Storage::FileSystem::WRITE_DAC),
                    "write_owner_handle": probe(
                        &file, windows_sys::Win32::Storage::FileSystem::WRITE_OWNER),
                    "remove_file": result(std::fs::remove_file(&file)),
                    "remove_directory": result(std::fs::remove_dir(&directory)),
                })
            };
            observation["file_exists_after"] = file.exists().into();
            observation["directory_exists_after"] = directory.exists().into();
            // Restore only this test's own surviving objects after impersonation.
            // Their creator remains owner and can restore their original cleanup access.
            unsafe {
                replace_dacl(&parent, &[(everyone.as_ptr(), FILE_ALL_ACCESS)])?;
                for path in [&file, &directory] {
                    if path.exists() {
                        replace_dacl(path, &[(everyone.as_ptr(), FILE_ALL_ACCESS)])?;
                    }
                }
            }
            eprintln!("HIA_WINDOWS_DELETE_CASE {observation}");
            observations.push(observation);
        }
    }
    assert_eq!(observations.len(), 20);
    eprintln!(
        "HIA_WINDOWS_DELETE_DIAGNOSTIC {}",
        serde_json::json!({
            "schema": "hia.windows-restricted-token-delete-diagnostic.v2",
            "diagnostic_only": true,
            "production_qualification": false,
            "original_refusal_tests_unchanged": true,
            "observations": observations,
        }),
    );
    Ok(())
}
