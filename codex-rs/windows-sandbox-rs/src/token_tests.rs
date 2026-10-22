use super::*;
use crate::acl::add_deny_write_ace;
use crate::acl::ensure_allow_mask_aces;
use crate::acl::ensure_allow_write_aces;
use crate::acl::fetch_dacl_handle;
use pretty_assertions::assert_eq;
use windows_sys::Win32::Foundation::ERROR_INSUFFICIENT_BUFFER;
use windows_sys::Win32::Security::AccessCheck;
use windows_sys::Win32::Security::Authorization::ConvertSecurityDescriptorToStringSecurityDescriptorW;
use windows_sys::Win32::Security::Authorization::DENY_ACCESS;
use windows_sys::Win32::Security::Authorization::GetNamedSecurityInfoW;
use windows_sys::Win32::Security::Authorization::SDDL_REVISION_1;
use windows_sys::Win32::Security::Authorization::SE_FILE_OBJECT;
use windows_sys::Win32::Security::Authorization::SetNamedSecurityInfoW;
use windows_sys::Win32::Security::CONTAINER_INHERIT_ACE;
use windows_sys::Win32::Security::DACL_SECURITY_INFORMATION;
use windows_sys::Win32::Security::DuplicateToken;
use windows_sys::Win32::Security::EqualSid;
use windows_sys::Win32::Security::GENERIC_MAPPING;
use windows_sys::Win32::Security::GROUP_SECURITY_INFORMATION;
use windows_sys::Win32::Security::ImpersonateLoggedOnUser;
use windows_sys::Win32::Security::OBJECT_INHERIT_ACE;
use windows_sys::Win32::Security::OWNER_SECURITY_INFORMATION;
use windows_sys::Win32::Security::PRIVILEGE_SET;
use windows_sys::Win32::Security::RevertToSelf;
use windows_sys::Win32::Security::SecurityImpersonation;
use windows_sys::Win32::Security::TokenImpersonationLevel;
use windows_sys::Win32::Security::TokenRestrictedSids;
use windows_sys::Win32::Storage::FileSystem::DELETE;
use windows_sys::Win32::Storage::FileSystem::FILE_ALL_ACCESS;
use windows_sys::Win32::Storage::FileSystem::FILE_DELETE_CHILD;
use windows_sys::Win32::Storage::FileSystem::FILE_GENERIC_EXECUTE;
use windows_sys::Win32::Storage::FileSystem::FILE_GENERIC_READ;
use windows_sys::Win32::Storage::FileSystem::FILE_GENERIC_WRITE;

struct OwnedToken(HANDLE);

impl Drop for OwnedToken {
    fn drop(&mut self) {
        unsafe {
            CloseHandle(self.0);
        }
    }
}

struct Impersonation;

fn trace_fixture_dacl(label: &str, path: &std::path::Path) {
    let snapshot = (|| -> Result<String> {
        // Query only the owned fixture. Keep the native DACL's order, masks and
        // inheritance flags so failures distinguish storage normalization from an
        // ineffective deny. This helper never changes an ACL or impersonates.
        // SAFETY: the descriptor owns its DACL until the conversion has copied it.
        let (_, descriptor) = unsafe { fetch_dacl_handle(path)? };
        let mut encoded = std::ptr::null_mut();
        let mut encoded_len = 0;
        // SAFETY: the descriptor and output pointers stay live for conversion. Each
        // returned allocation is freed exactly once, including the failure path.
        let (ok, error) = unsafe {
            let ok = ConvertSecurityDescriptorToStringSecurityDescriptorW(
                descriptor,
                SDDL_REVISION_1,
                DACL_SECURITY_INFORMATION,
                &mut encoded,
                &mut encoded_len,
            );
            let error = if ok == 0 { GetLastError() } else { 0 };
            LocalFree(descriptor as HLOCAL);
            (ok, error)
        };
        if ok == 0 || encoded.is_null() || encoded_len == 0 {
            if !encoded.is_null() {
                // SAFETY: encoded is the conversion's still-owned allocation.
                unsafe { LocalFree(encoded as HLOCAL) };
            }
            return Err(anyhow!("fixture DACL conversion failed ({label}): {error}"));
        }
        // SAFETY: Windows returned the allocation's UTF-16 capacity. Read only
        // through the first NUL, within that bound, and copy before freeing it.
        let sddl = unsafe {
            let mut len = 0;
            while len < encoded_len as usize && *encoded.add(len) != 0 {
                len += 1;
            }
            if len == encoded_len as usize {
                LocalFree(encoded as HLOCAL);
                return Err(anyhow!("fixture DACL string has no terminator ({label})"));
            }
            let units = std::slice::from_raw_parts(encoded, len);
            let value = String::from_utf16_lossy(units);
            LocalFree(encoded as HLOCAL);
            value
        };
        Ok(sddl)
    })();
    match snapshot {
        Ok(sddl) => eprintln!(
            "fixture DACL {label}: path={} directory={} sddl={sddl}",
            path.display(),
            path.is_dir()
        ),
        Err(error) => eprintln!("fixture DACL {label}: unavailable: {error:#}"),
    }
}

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
    trace_fixture_dacl("partial directory deny", fixture.path());
    trace_fixture_dacl("partial inherited file deny", &existing);
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
    trace_fixture_dacl("first directory repair", fixture.path());
    trace_fixture_dacl("file after directory repair", &existing);
    // SAFETY: the same objects remain live. Check native directory and file
    // storage retains the constructor's complete mask and inheritance scope.
    let repeated_repairs = unsafe {
        (
            add_deny_write_ace(fixture.path(), capability.as_ptr())?,
            add_deny_write_ace(&existing, capability.as_ptr())?,
            add_deny_write_ace(&existing, capability.as_ptr())?,
        )
    };
    trace_fixture_dacl("repeated directory repair", fixture.path());
    trace_fixture_dacl("repeated file repair", &existing);
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
    trace_fixture_dacl("broad parent", fixture.path());
    trace_fixture_dacl("allowed workspace", &allowed[0]);
    trace_fixture_dacl("allowed temp", &allowed[1]);
    trace_fixture_dacl("outside parent", &outside);
    trace_fixture_dacl("outside file", &outside.join("keep.txt"));
    trace_fixture_dacl("outside directory", &outside.join("keep-dir"));
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
    trace_parent_delete_child_authority(&base, &token, [&cap_a, &cap_b], &other_cap);
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

fn seed_fixture_object_deny(path: &std::path::Path, sid: &LocalSid, mask: u32) -> Result<()> {
    let entry = EXPLICIT_ACCESS_W {
        grfAccessPermissions: mask,
        grfAccessMode: DENY_ACCESS,
        grfInheritance: 0,
        Trustee: TRUSTEE_W {
            pMultipleTrustee: std::ptr::null_mut(),
            MultipleTrusteeOperation: 0,
            TrusteeForm: TRUSTEE_IS_SID,
            TrusteeType: TRUSTEE_IS_UNKNOWN,
            ptstrName: sid.as_ptr().cast(),
        },
    };
    // SAFETY: callers pass only a newly owned diagnostic fixture and a live SID.
    // The zero inheritance flags keep a parent DELETE_CHILD deny on that object.
    let code = unsafe {
        let (dacl, descriptor) = fetch_dacl_handle(path)?;
        let mut updated = std::ptr::null_mut();
        let code = SetEntriesInAclW(
            /*ccountofexplicitentries*/ 1,
            &entry,
            dacl,
            &mut updated,
        );
        let code = if code == ERROR_SUCCESS {
            SetNamedSecurityInfoW(
                to_wide(path).as_ptr() as *mut u16,
                SE_FILE_OBJECT,
                DACL_SECURITY_INFORMATION,
                std::ptr::null_mut(),
                std::ptr::null_mut(),
                updated,
                std::ptr::null_mut(),
            )
        } else {
            code
        };
        if !updated.is_null() {
            LocalFree(updated as HLOCAL);
        }
        LocalFree(descriptor as HLOCAL);
        code
    };
    anyhow::ensure!(code == ERROR_SUCCESS, "seed diagnostic object deny: {code}");
    Ok(())
}

fn fixture_access_check(
    path: &std::path::Path,
    token: &OwnedToken,
    requested_access: u32,
) -> Result<serde_json::Value> {
    let mut descriptor = std::ptr::null_mut();
    // SAFETY: the fixture path exists. AccessCheck requires owner and group in
    // addition to the DACL; the descriptor is freed after the final native call.
    let code = unsafe {
        GetNamedSecurityInfoW(
            to_wide(path).as_ptr(),
            SE_FILE_OBJECT,
            OWNER_SECURITY_INFORMATION | GROUP_SECURITY_INFORMATION | DACL_SECURITY_INFORMATION,
            std::ptr::null_mut(),
            std::ptr::null_mut(),
            std::ptr::null_mut(),
            std::ptr::null_mut(),
            &mut descriptor,
        )
    };
    if code != ERROR_SUCCESS {
        if !descriptor.is_null() {
            unsafe { LocalFree(descriptor as HLOCAL) };
        }
        return Err(anyhow!("diagnostic GetNamedSecurityInfoW: {code}"));
    }
    let mapping = GENERIC_MAPPING {
        GenericRead: FILE_GENERIC_READ,
        GenericWrite: FILE_GENERIC_WRITE,
        GenericExecute: FILE_GENERIC_EXECUTE,
        GenericAll: FILE_ALL_ACCESS,
    };
    let mut privileges =
        vec![0_u64; std::mem::size_of::<PRIVILEGE_SET>().div_ceil(std::mem::size_of::<u64>())];
    let mut granted_access = 0;
    let mut access_status = 0;
    let mut api_success = 0;
    let mut error = 0;
    let mut privilege_bytes = (privileges.len() * std::mem::size_of::<u64>()) as u32;
    let mut attempts = Vec::new();
    for attempt in 0..2 {
        let provided_bytes = privilege_bytes;
        // SAFETY: descriptor and impersonation token are live, requested rights
        // are already specific, and the u64 buffer is suitably aligned and sized.
        api_success = unsafe {
            AccessCheck(
                descriptor,
                token.0,
                requested_access,
                &mapping,
                privileges.as_mut_ptr().cast(),
                &mut privilege_bytes,
                &mut granted_access,
                &mut access_status,
            )
        };
        error = if api_success == 0 || access_status == 0 {
            unsafe { GetLastError() }
        } else {
            0
        };
        attempts.push(serde_json::json!({
            "api_success": api_success != 0,
            "error": error,
            "provided_privilege_bytes": provided_bytes,
            "returned_privilege_bytes": privilege_bytes,
            "access_status": (api_success != 0).then_some(access_status != 0),
            "granted_access": (api_success != 0).then_some(granted_access),
        }));
        if api_success == 0 && error == ERROR_INSUFFICIENT_BUFFER && attempt == 0 {
            privileges.resize(
                (privilege_bytes as usize).div_ceil(std::mem::size_of::<u64>()),
                /*value*/ 0,
            );
        } else {
            break;
        }
    }
    // SAFETY: no remaining reference uses the allocated descriptor.
    unsafe { LocalFree(descriptor as HLOCAL) };
    Ok(serde_json::json!({
        "requested_access": requested_access,
        "generic_mapping": {
            "read": mapping.GenericRead,
            "write": mapping.GenericWrite,
            "execute": mapping.GenericExecute,
            "all": mapping.GenericAll,
        },
        "api_success": api_success != 0,
        "api_error": (api_success == 0).then_some(error),
        "access_status": (api_success != 0).then_some(access_status != 0),
        "granted_access": (api_success != 0).then_some(granted_access),
        "access_denial_error": (api_success != 0 && access_status == 0).then_some(error),
        "privilege_set_bytes": privilege_bytes,
        "attempts": attempts,
    }))
}

fn trace_parent_delete_child_authority(
    base: &OwnedToken,
    token: &OwnedToken,
    capabilities: [&LocalSid; 2],
    outside_capability: &LocalSid,
) {
    // This probe runs after the original negative operations, on separate owned
    // tempdirs. Errors are observations and cannot bypass the original assertions.
    let mut duplicate = 0;
    let duplicated = unsafe { DuplicateToken(token.0, SecurityImpersonation, &mut duplicate) };
    let access_token = if duplicated == 0 {
        eprintln!("DELETE_CHILD probe DuplicateToken error={}", unsafe {
            GetLastError()
        });
        None
    } else {
        Some(OwnedToken(duplicate))
    };
    if let Some(access_token) = &access_token {
        let mut level = 0;
        let mut returned = 0;
        let ok = unsafe {
            GetTokenInformation(
                access_token.0,
                TokenImpersonationLevel,
                (&mut level as *mut i32).cast(),
                std::mem::size_of::<i32>() as u32,
                &mut returned,
            )
        };
        let error = if ok == 0 {
            unsafe { GetLastError() }
        } else {
            0
        };
        let identities = [
            ("capability_a", capabilities[0]),
            ("capability_b", capabilities[1]),
            ("outside_capability", outside_capability),
        ]
        .map(|(name, sid)| {
            serde_json::json!({
                "name": name,
                "original_restricting_sid": unsafe {
                    token_has_restricting_sid(token.0, sid.as_ptr())
                }.map_err(|error| error.to_string()),
                "duplicate_restricting_sid": unsafe {
                    token_has_restricting_sid(access_token.0, sid.as_ptr())
                }.map_err(|error| error.to_string()),
            })
        });
        eprintln!(
            "DELETE_CHILD probe token {}",
            serde_json::json!({
                "requested_impersonation_level": SecurityImpersonation,
                "level_query_success": ok != 0,
                "level_query_error": (ok == 0).then_some(error),
                "actual_impersonation_level": (ok != 0).then_some(level),
                "level_query_bytes": returned,
                "identities": identities,
            })
        );
    }
    for parent_delete_child_denied in [false, true] {
        for child_capability_delete_denied in [false, true] {
            let case = format!(
                "parent_delete_child_denied={parent_delete_child_denied} child_capability_delete_denied={child_capability_delete_denied}"
            );
            let result = (|| -> Result<serde_json::Value> {
                let fixture = tempfile::tempdir()?;
                let everyone = LocalSid::from_string("S-1-1-0")?;
                let mut logon = unsafe { get_logon_sid_bytes(base.0)? };
                unsafe {
                    ensure_allow_mask_aces(
                        fixture.path(),
                        &[logon.as_mut_ptr().cast(), everyone.as_ptr()],
                        FILE_ALL_ACCESS,
                    )?;
                }
                let parent = fixture.path().join("outside");
                std::fs::create_dir(&parent)?;
                unsafe { ensure_allow_write_aces(&parent, &[outside_capability.as_ptr()])? };
                let file = parent.join("keep.txt");
                let directory = parent.join("keep-dir");
                std::fs::write(&file, "outside")?;
                std::fs::create_dir(&directory)?;
                if parent_delete_child_denied {
                    seed_fixture_object_deny(&parent, &everyone, FILE_DELETE_CHILD)?;
                }
                if child_capability_delete_denied {
                    seed_fixture_object_deny(&file, capabilities[0], DELETE)?;
                    seed_fixture_object_deny(&directory, capabilities[0], DELETE)?;
                }
                for (name, path) in [
                    ("parent", &parent),
                    ("file", &file),
                    ("directory", &directory),
                ] {
                    trace_fixture_dacl(&format!("DELETE_CHILD probe {case} {name}"), path);
                }
                let access_checks = access_token.as_ref().map(|access_token| {
                    [
                        ("parent_delete_child", &parent, FILE_DELETE_CHILD),
                        ("file_delete", &file, DELETE),
                        ("directory_delete", &directory, DELETE),
                    ]
                    .map(|(name, path, requested)| {
                        serde_json::json!({
                            "name": name,
                            "result": fixture_access_check(path, access_token, requested)
                                .map_err(|error| error.to_string()),
                        })
                    })
                });
                let operations = {
                    let _impersonation = unsafe { Impersonation::enter(token.0)? };
                    [
                        ("write_existing", std::fs::write(&file, "overwritten")),
                        (
                            "create_outside",
                            std::fs::write(parent.join("created.txt"), "outside"),
                        ),
                        ("remove_file", std::fs::remove_file(&file)),
                        ("remove_directory", std::fs::remove_dir(&directory)),
                    ]
                    .map(|(name, result)| {
                        serde_json::json!({
                            "name": name,
                            "success": result.is_ok(),
                            "error": result.err().map(|error| serde_json::json!({
                                "kind": format!("{:?}", error.kind()),
                                "raw_os_error": error.raw_os_error(),
                                "message": error.to_string(),
                            })),
                        })
                    })
                };
                let cleanup = fixture.close().map_err(|error| error.to_string());
                Ok(serde_json::json!({
                    "parent_delete_child_denied": parent_delete_child_denied,
                    "parent_deny_sid": "S-1-1-0",
                    "parent_deny_inheritance_flags": 0,
                    "child_capability_delete_denied": child_capability_delete_denied,
                    "child_deny_sid": "capability_a",
                    "child_deny_inheritance_flags": 0,
                    "access_checks": access_checks,
                    "operations": operations,
                    "cleanup": cleanup,
                }))
            })();
            match result {
                Ok(value) => eprintln!("DELETE_CHILD probe result {value}"),
                Err(error) => eprintln!("DELETE_CHILD probe unavailable {case}: {error:#}"),
            }
        }
    }
}
