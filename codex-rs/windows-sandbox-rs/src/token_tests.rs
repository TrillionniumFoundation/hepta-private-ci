use super::*;
use crate::acl::add_deny_write_ace;
use crate::acl::ensure_allow_mask_aces;
use crate::acl::ensure_allow_mask_aces_with_inheritance;
use crate::acl::ensure_allow_write_aces;
use crate::acl::ensure_filesystem_mutation_deny;
use crate::acl::fetch_dacl_handle;
use crate::legacy_admission_tests::assert_unavailable;
use crate::legacy_admission_tests::snapshot;
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

#[path = "token_full_restriction_tests.rs"]
mod full_restriction;
use windows_sys::Win32::Storage::FileSystem::FILE_GENERIC_EXECUTE;
use windows_sys::Win32::Storage::FileSystem::FILE_GENERIC_READ;

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

// Diagnostics are restricted to this test's owned fixture objects. They do not
// change ACLs, token rights, impersonation, operation order or acceptance checks.
fn record_windows_boundary_diagnostic(detail: std::fmt::Arguments<'_>) {
    use std::io::Write;

    let _ = writeln!(std::io::stderr().lock(), "windows_boundary_diag {detail}");
}

fn observe_fixture_dacl(label: &str, path: &std::path::Path) {
    use windows_sys::Win32::Security::ACE_HEADER;
    use windows_sys::Win32::Security::GetAce;

    struct Descriptor(*mut c_void);
    impl Drop for Descriptor {
        fn drop(&mut self) {
            // SAFETY: fetch_dacl_handle returns this LocalAlloc-owned descriptor.
            unsafe {
                LocalFree(self.0 as HLOCAL);
            }
        }
    }

    let observed_at = std::time::Instant::now();
    // SAFETY: callers supply only live paths within their owned temporary fixture.
    let result = unsafe { fetch_dacl_handle(path) };
    let (acl, descriptor) = match result {
        Ok(value) => value,
        Err(error) => {
            record_windows_boundary_diagnostic(format_args!(
                "dacl={label} path={path:?} read_error={error:#}"
            ));
            return;
        }
    };
    let _descriptor = Descriptor(descriptor);
    if acl.is_null() {
        record_windows_boundary_diagnostic(format_args!("dacl={label} null_dacl=true"));
        return;
    }
    // SAFETY: the OS-returned ACL remains inside the live descriptor above.
    let (bytes, count) = unsafe { ((*acl).AclSize as usize, (*acl).AceCount as usize) };
    record_windows_boundary_diagnostic(format_args!(
        "dacl={label} path={path:?} bytes={bytes} ace_count={count} truncated={}",
        count > 64,
    ));
    let acl_start = acl as usize;
    let Some(acl_end) = acl_start.checked_add(bytes) else {
        return;
    };
    for index in 0..count.min(64) {
        let mut ace = std::ptr::null_mut();
        // SAFETY: GetAce receives the live OS ACL and an in-range ACE index.
        if unsafe { GetAce(acl, index as u32, &mut ace) } == 0 {
            record_windows_boundary_diagnostic(format_args!(
                "dacl={label} ace={index} get_ace_error={}",
                unsafe { GetLastError() },
            ));
            continue;
        }
        let ace_start = ace as usize;
        if ace.is_null()
            || ace_start < acl_start
            || ace_start
                .checked_add(std::mem::size_of::<ACE_HEADER>())
                .is_none_or(|end| end > acl_end)
        {
            record_windows_boundary_diagnostic(format_args!(
                "dacl={label} ace={index} invalid_header_bounds=true"
            ));
            continue;
        }
        // SAFETY: the header bounds are inside the owned OS ACL; unaligned read
        // avoids making a stronger alignment assumption than the byte bounds.
        let header = unsafe { std::ptr::read_unaligned(ace.cast::<ACE_HEADER>()) };
        let size = header.AceSize as usize;
        if size < std::mem::size_of::<ACE_HEADER>()
            || ace_start.checked_add(size).is_none_or(|end| end > acl_end)
        {
            record_windows_boundary_diagnostic(format_args!(
                "dacl={label} ace={index} invalid_ace_bounds=true"
            ));
            continue;
        }
        // SAFETY: the complete ACE lies within the live descriptor. Observe at
        // most 512 bytes; this includes the native mask and SID for normal ACEs.
        let raw = unsafe { std::slice::from_raw_parts(ace.cast::<u8>(), size.min(512)) };
        let mask = (raw.len() >= 8).then(|| u32::from_le_bytes([raw[4], raw[5], raw[6], raw[7]]));
        record_windows_boundary_diagnostic(format_args!(
            "dacl={label} ace={index} type={} flags={:#04x} size={size} mask={mask:?} truncated={} raw={raw:02x?}",
            header.AceType,
            header.AceFlags,
            size > raw.len(),
        ));
    }
    record_windows_boundary_diagnostic(format_args!(
        "dacl={label} observation_us={}",
        observed_at.elapsed().as_micros(),
    ));
}

#[test]
fn elevated_token_includes_network_proxy_restricting_sid() -> Result<()> {
    let capability_sid = LocalSid::from_string("S-1-5-21-10-20-30-40")?;
    let network_proxy_sid = LocalSid::from_string("S-1-5-21-50-60-70-80")?;
    let everyone = LocalSid::from_string("S-1-1-0")?;
    let base_token = OwnedToken(unsafe { get_current_token_for_restriction()? });
    let mut user = unsafe { get_user_sid_bytes(base_token.0)? };
    let mut logon = unsafe { get_logon_sid_bytes(base_token.0)? };
    let restricted_token = OwnedToken(unsafe {
        create_readonly_token_with_caps_and_user_from(
            base_token.0,
            &[capability_sid.as_ptr()],
            &[network_proxy_sid.as_ptr()],
        )?
    });

    let has_network_proxy_sid =
        unsafe { token_has_restricting_sid(restricted_token.0, network_proxy_sid.as_ptr()) };

    assert!(has_network_proxy_sid?);
    assert!(unsafe { token_has_restricting_sid(restricted_token.0, capability_sid.as_ptr())? });
    assert!(unsafe { token_has_restricting_sid(restricted_token.0, user.as_mut_ptr().cast())? });
    assert!(!unsafe { token_has_restricting_sid(restricted_token.0, logon.as_mut_ptr().cast())? });
    assert!(!unsafe { token_has_restricting_sid(restricted_token.0, everyone.as_ptr())? });
    Ok(())
}

#[test]
fn legacy_refuses_before_partial_delete_deny_repair_mechanism_fixture() -> Result<()> {
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
    let before = crate::legacy_admission_tests::snapshot(fixture.path())?;
    crate::legacy_admission_tests::assert_unavailable(unsafe {
        create_workspace_write_token_with_caps_from(base.0, &[capability.as_ptr()]).map(OwnedToken)
    });
    assert_eq!(
        crate::legacy_admission_tests::snapshot(fixture.path())?,
        before
    );
    // SAFETY: this cfg(test) token is used only for the owned fixture below.
    // It preserves the native ACL-repair assertions without admitting a legacy
    // sandbox or launching any process under the token.
    let token = OwnedToken(unsafe {
        mechanism_fixture::workspace_token_for_owned_objects(base.0, &[capability.as_ptr()])?
    });
    {
        // SAFETY: token remains owned throughout this impersonation scope.
        let _impersonation = unsafe { Impersonation::enter(token.0)? };
        std::fs::write(&existing, "before repair")?;
    }
    observe_fixture_dacl("partial_directory_before_repair", fixture.path());
    observe_fixture_dacl("partial_file_before_repair", &existing);
    // SAFETY: the fixture and validated capability SID are live for the repair.
    let repaired = unsafe { add_deny_write_ace(fixture.path(), capability.as_ptr())? };
    observe_fixture_dacl("partial_directory_after_first_repair", fixture.path());
    observe_fixture_dacl("partial_file_after_directory_repair", &existing);
    // SAFETY: the same objects remain live. Check native directory and file
    // storage retains the constructor's complete mask and inheritance scope.
    let repeated_repairs = unsafe {
        (
            {
                let result = add_deny_write_ace(fixture.path(), capability.as_ptr())?;
                observe_fixture_dacl("partial_directory_after_repeat", fixture.path());
                result
            },
            {
                let result = add_deny_write_ace(&existing, capability.as_ptr())?;
                observe_fixture_dacl("partial_file_after_first_direct_repair", &existing);
                result
            },
            {
                let result = add_deny_write_ace(&existing, capability.as_ptr())?;
                observe_fixture_dacl("partial_file_after_repeat", &existing);
                result
            },
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
fn legacy_workspace_capabilities_refuse_broad_identity_delete_routes() -> Result<()> {
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
    // The ordinary caller really has the dangerous ambient rights. Keep this
    // positive control separate from the subsequent unchanged-fixture check.
    std::fs::write(outside.join("keep.txt"), "host-overwrite")?;
    assert_eq!(
        std::fs::read_to_string(outside.join("keep.txt"))?,
        "host-overwrite"
    );
    std::fs::write(outside.join("keep.txt"), "outside")?;
    let host_file = outside.join("host-delete-control.txt");
    let host_directory = outside.join("host-delete-control");
    std::fs::write(&host_file, "host")?;
    std::fs::create_dir(&host_directory)?;
    std::fs::remove_file(&host_file)?;
    std::fs::remove_dir(&host_directory)?;
    let before = snapshot(fixture.path())?;
    // This remains the real same-user constructor. A dedicated-account test
    // must never be simulated by passing the current user's SID to its API.
    assert_unavailable(unsafe {
        create_workspace_write_token_with_caps_from(base.0, &[cap_a.as_ptr(), cap_b.as_ptr()])
            .map(OwnedToken)
    });
    assert_eq!(snapshot(fixture.path())?, before);
    assert_eq!(
        std::fs::read_to_string(outside.join("keep.txt"))?,
        "outside"
    );
    assert!(outside.join("keep-dir").is_dir());
    for path in &allowed {
        assert_eq!(std::fs::read_to_string(path.join("delete.txt"))?, "inside");
        assert!(path.join("delete-dir").is_dir());
    }
    Ok(())
}

#[test]
fn legacy_workspace_capability_refuses_all_four_native_delete_routes() -> Result<()> {
    use crate::delete_permission_matrix::DeleteMatrix;
    use crate::delete_permission_matrix::DeleteOutcome;
    use crate::delete_permission_matrix::DeleteRoute;

    let fixture = tempfile::tempdir()?;
    let host = DeleteMatrix::new(&fixture.path().join("host"))?;
    let restricted = DeleteMatrix::new(&fixture.path().join("restricted"))?;
    host.assert_same_acls(&restricted);
    let host_access_context = host.access_diagnostics();
    let host_errors = crate::delete_permission_control::native(&host)?;
    let host_outcomes = host.finish("ordinary-host")?;
    eprintln!("delete_matrix host_native_errors={host_errors:?}");
    assert_eq!(
        host_errors,
        vec![
            [Some((std::io::ErrorKind::PermissionDenied, Some(5))); 2],
            [None; 2],
            [None; 2],
            [None; 2],
        ],
        "{host_access_context}"
    );
    assert_eq!(
        host_outcomes,
        [
            DeleteRoute::Neither,
            DeleteRoute::TargetOnly,
            DeleteRoute::ParentOnly,
            DeleteRoute::Both
        ]
        .map(|route| DeleteOutcome {
            route,
            file_deleted: route != DeleteRoute::Neither,
            directory_deleted: route != DeleteRoute::Neither
        }),
        "{host_access_context}"
    );

    let base = OwnedToken(unsafe { get_current_token_for_restriction()? });
    let capability = LocalSid::from_string("S-1-5-21-101-202-303-404")?;
    let second_capability = LocalSid::from_string("S-1-5-21-111-222-333-444")?;
    let allowed = fixture.path().join("allowed");
    std::fs::create_dir(&allowed)?;
    unsafe { ensure_allow_write_aces(&allowed, &[capability.as_ptr()])? };
    std::fs::write(allowed.join("file"), "allowed")?;
    std::fs::create_dir(allowed.join("directory"))?;
    let before = snapshot(fixture.path())?;
    assert_unavailable(unsafe {
        create_workspace_write_token_with_caps_from(
            base.0,
            &[capability.as_ptr(), second_capability.as_ptr()],
        )
        .map(OwnedToken)
    });
    assert_eq!(snapshot(fixture.path())?, before);
    // finish checks original object identity and exact four-cell native DACLs.
    let outcomes = restricted.finish("legacy-refused-before-impersonation")?;
    assert_eq!(std::fs::read_to_string(allowed.join("file"))?, "allowed");
    assert!(allowed.join("directory").is_dir());
    assert_eq!(
        outcomes,
        [
            DeleteRoute::Neither,
            DeleteRoute::TargetOnly,
            DeleteRoute::ParentOnly,
            DeleteRoute::Both
        ]
        .map(|route| DeleteOutcome {
            route,
            file_deleted: false,
            directory_deleted: false
        })
    );
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
        create_workspace_write_token_with_caps_from(base.0, &[capability.as_ptr()]).map(OwnedToken)
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

#[path = "token_probe_support.rs"]
mod probe_support;

#[path = "token_read_authority_tests.rs"]
mod read_authority_probe;

#[path = "token_mic_probe_tests.rs"]
mod mic_probe;

#[path = "token_prepared_filesystem_tests.rs"]
mod prepared_filesystem;

fn fixture_acl_snapshot(
    path: &std::path::Path,
    capability: &LocalSid,
) -> Result<Vec<(u8, u8, Option<u32>, bool)>> {
    use windows_sys::Win32::Security::ACCESS_ALLOWED_ACE;
    use windows_sys::Win32::Security::ACE_HEADER;
    use windows_sys::Win32::Security::ACL_SIZE_INFORMATION;
    use windows_sys::Win32::Security::AclSizeInformation;
    use windows_sys::Win32::Security::GetAce;
    use windows_sys::Win32::Security::GetAclInformation;

    // SAFETY: the fixture exists; the descriptor owns its ACL until it is freed
    // after the closure, including every early error path.
    unsafe {
        let (acl, descriptor) = fetch_dacl_handle(path)?;
        let result = (|| {
            anyhow::ensure!(!acl.is_null(), "fixture has a null DACL");
            let mut information: ACL_SIZE_INFORMATION = std::mem::zeroed();
            anyhow::ensure!(
                GetAclInformation(
                    acl,
                    (&raw mut information).cast(),
                    std::mem::size_of::<ACL_SIZE_INFORMATION>() as u32,
                    AclSizeInformation,
                ) != 0,
                "GetAclInformation failed: {}",
                GetLastError(),
            );
            let mut entries = Vec::new();
            for index in 0..information.AceCount {
                let mut ace = std::ptr::null_mut();
                anyhow::ensure!(
                    GetAce(acl, index, &mut ace) != 0,
                    "GetAce failed: {}",
                    GetLastError(),
                );
                let header = &*ace.cast::<ACE_HEADER>();
                let (mask, matching) = if matches!(header.AceType, 0 | 1) {
                    let ordinary = &*ace.cast::<ACCESS_ALLOWED_ACE>();
                    (
                        Some(ordinary.Mask),
                        EqualSid(
                            (&raw const ordinary.SidStart).cast_mut().cast(),
                            capability.as_ptr(),
                        ) != 0,
                    )
                } else {
                    (None, false)
                };
                entries.push((header.AceType, header.AceFlags, mask, matching));
            }
            Ok(entries)
        })();
        if !descriptor.is_null() {
            LocalFree(descriptor as HLOCAL);
        }
        result
    }
}

fn fixture_access_check(
    path: &std::path::Path,
    token: HANDLE,
    mut desired: u32,
) -> Result<(bool, u32, u32)> {
    use windows_sys::Win32::Security::AccessCheck;
    use windows_sys::Win32::Security::Authorization::GetNamedSecurityInfoW;
    use windows_sys::Win32::Security::DuplicateToken;
    use windows_sys::Win32::Security::GENERIC_MAPPING;
    use windows_sys::Win32::Security::GROUP_SECURITY_INFORMATION;
    use windows_sys::Win32::Security::MapGenericMask;
    use windows_sys::Win32::Security::OWNER_SECURITY_INFORMATION;
    use windows_sys::Win32::Security::PRIVILEGE_SET;
    use windows_sys::Win32::Security::SecurityImpersonation;
    use windows_sys::Win32::Storage::FileSystem::FILE_GENERIC_EXECUTE;
    use windows_sys::Win32::Storage::FileSystem::FILE_GENERIC_READ;
    use windows_sys::Win32::Storage::FileSystem::FILE_GENERIC_WRITE;

    // SAFETY: the fixture and input token remain live. The returned descriptor
    // owns its embedded owner/group/DACL until LocalFree after every result;
    // the duplicated impersonation token is independently closed by OwnedToken.
    unsafe {
        let mut descriptor = std::ptr::null_mut();
        let code = GetNamedSecurityInfoW(
            to_wide(path).as_ptr(),
            SE_FILE_OBJECT,
            OWNER_SECURITY_INFORMATION | GROUP_SECURITY_INFORMATION | DACL_SECURITY_INFORMATION,
            std::ptr::null_mut(),
            std::ptr::null_mut(),
            std::ptr::null_mut(),
            std::ptr::null_mut(),
            &mut descriptor,
        );
        let result = (|| {
            anyhow::ensure!(
                code == ERROR_SUCCESS,
                "GetNamedSecurityInfoW failed: {code}"
            );
            anyhow::ensure!(!descriptor.is_null(), "fixture has no security descriptor");
            let mut impersonation = 0;
            anyhow::ensure!(
                DuplicateToken(token, SecurityImpersonation, &mut impersonation) != 0,
                "DuplicateToken failed: {}",
                GetLastError(),
            );
            let impersonation = OwnedToken(impersonation);
            let mapping = GENERIC_MAPPING {
                GenericRead: FILE_GENERIC_READ,
                GenericWrite: FILE_GENERIC_WRITE,
                GenericExecute: FILE_GENERIC_EXECUTE,
                GenericAll: FILE_ALL_ACCESS,
            };
            MapGenericMask(&mut desired, &mapping);
            let mut privileges: PRIVILEGE_SET = std::mem::zeroed();
            let mut privilege_bytes = std::mem::size_of::<PRIVILEGE_SET>() as u32;
            let mut granted = 0;
            let mut allowed = 0;
            anyhow::ensure!(
                AccessCheck(
                    descriptor,
                    impersonation.0,
                    desired,
                    &mapping,
                    &mut privileges,
                    &mut privilege_bytes,
                    &mut granted,
                    &mut allowed,
                ) != 0,
                "AccessCheck failed: {} (privilege bytes {privilege_bytes})",
                GetLastError(),
            );
            Ok((allowed != 0, granted, privileges.PrivilegeCount))
        })();
        if !descriptor.is_null() {
            LocalFree(descriptor as HLOCAL);
        }
        result
    }
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
        create_workspace_write_token_with_caps_and_read_sids_from(
            base.0,
            &[capability.as_ptr()],
            &[],
        )?
    });
    {
        // SAFETY: token remains owned throughout this impersonation scope.
        let _impersonation = unsafe { Impersonation::enter(token.0)? };
        std::fs::write(&existing, "before repair")
            .map_err(|error| anyhow!("pre-repair capability write failed: {error}"))?;
    }
    // The strict restricting-SID token checks reads as well as writes. Use the
    // mutation-only deny so DELETE/FILE_DELETE_CHILD and data writes are denied
    // without also denying READ_CONTROL/SYNCHRONIZE needed by the read control.
    let repaired = unsafe { ensure_filesystem_mutation_deny(fixture.path(), capability.as_ptr())? };
    // SAFETY: the same objects remain live. Check native directory and file
    // storage retains the constructor's complete mask and inheritance scope.
    let repeated_repairs = unsafe {
        (
            ensure_filesystem_mutation_deny(fixture.path(), capability.as_ptr())?,
            ensure_filesystem_mutation_deny(&existing, capability.as_ptr())?,
            ensure_filesystem_mutation_deny(&existing, capability.as_ptr())?,
        )
    };
    let (read, denied) = {
        // SAFETY: token remains owned throughout this impersonation scope.
        let _impersonation = unsafe { Impersonation::enter(token.0)? };
        let read = std::fs::read_to_string(&existing)
            .map_err(|error| anyhow!("post-repair capability read failed: {error}"))?;
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
    assert_eq!(
        repeated_repairs,
        (false, true, false),
        "actual directory ACL={:?}; actual file ACL={:?}",
        fixture_acl_snapshot(fixture.path(), &capability)?,
        fixture_acl_snapshot(&existing, &capability)?,
    );
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
    let read_only = LocalSid::from_string("S-1-5-21-131-242-353-464")?;
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
        ensure_allow_mask_aces_with_inheritance(
            &outside,
            &[read_only.as_ptr()],
            FILE_GENERIC_READ | FILE_GENERIC_EXECUTE,
            CONTAINER_INHERIT_ACE | OBJECT_INHERIT_ACE,
        )?;
    }
    std::fs::write(outside.join("keep.txt"), "outside")?;
    std::fs::create_dir(outside.join("keep-dir"))?;
    let token = OwnedToken(unsafe {
        create_workspace_write_token_with_caps_and_read_sids_from(
            base.0,
            &[cap_a.as_ptr(), cap_b.as_ptr()],
            &[read_only.as_ptr()],
        )?
    });
    let outside_acl = (
        fixture_acl_snapshot(&outside, &cap_a)?,
        fixture_acl_snapshot(&outside.join("keep.txt"), &cap_a)?,
        fixture_acl_snapshot(&outside.join("keep-dir"), &cap_a)?,
    );
    // SAFETY: token and every SID buffer remain owned throughout these native
    // observations, before any impersonation or deletion can alter the fixture.
    let restricting_sids = unsafe {
        (
            token_has_restricting_sid(token.0, cap_a.as_ptr())?,
            token_has_restricting_sid(token.0, cap_b.as_ptr())?,
            token_has_restricting_sid(token.0, read_only.as_ptr())?,
            token_has_restricting_sid(token.0, logon.as_mut_ptr().cast())?,
            token_has_restricting_sid(token.0, everyone.as_mut_ptr().cast())?,
        )
    };
    // Read each descriptor before the original destructive attempts. Include
    // known read/write and authorized-root controls; do not turn an API error
    // into an apparent denial or short-circuit the real deletion assertions.
    let access_checks = [
        ("outside file DELETE", outside.join("keep.txt"), DELETE),
        ("outside directory DELETE", outside.join("keep-dir"), DELETE),
        (
            "outside parent FILE_DELETE_CHILD",
            outside.clone(),
            windows_sys::Win32::Storage::FileSystem::FILE_DELETE_CHILD,
        ),
        (
            "outside file FILE_WRITE_DATA",
            outside.join("keep.txt"),
            windows_sys::Win32::Storage::FileSystem::FILE_WRITE_DATA,
        ),
        (
            "outside file FILE_READ_DATA",
            outside.join("keep.txt"),
            windows_sys::Win32::Storage::FileSystem::FILE_READ_DATA,
        ),
        (
            "authorized file DELETE",
            allowed[0].join("delete.txt"),
            DELETE,
        ),
    ]
    .map(|(label, path, desired)| {
        (
            label,
            desired,
            fixture_access_check(&path, token.0, desired).map_err(|error| error.to_string()),
        )
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
    assert_eq!(
        refused,
        [Some(std::io::ErrorKind::PermissionDenied); 4],
        "restricting (cap_a, cap_b, logon, everyone)={restricting_sids:?}; \
         actual outside (parent, file, directory) ACL={outside_acl:?}; \
         per-descriptor AccessCheck (label, desired, result(allowed, granted, privileges))={access_checks:?}",
    );
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

#[path = "token_full_restriction_candidate_tests.rs"]
mod full_restriction_candidate;
