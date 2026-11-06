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

fn observe_fixture_metadata(label: &str, path: &std::path::Path) {
    let state = std::fs::metadata(path)
        .map(|metadata| (metadata.is_file(), metadata.is_dir(), metadata.len()))
        .map_err(|error| (error.kind(), error.raw_os_error()));
    record_windows_boundary_diagnostic(format_args!(
        "metadata={label} path={path:?} state={state:?}"
    ));
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
    for (label, sid) in [
        ("allowed_cap_a", cap_a.as_ptr()),
        ("allowed_cap_b", cap_b.as_ptr()),
        ("unrelated_cap", other_cap.as_ptr()),
        ("logon_identity", logon.as_mut_ptr().cast()),
        ("everyone_identity", everyone.as_mut_ptr().cast()),
    ] {
        // SAFETY: the owned token and each fixture/identity SID remain live.
        let member = unsafe { token_has_restricting_sid(token.0, sid) };
        record_windows_boundary_diagnostic(format_args!(
            "restricted_sid={label} member={member:?}"
        ));
    }
    observe_fixture_dacl("broad_parent", fixture.path());
    observe_fixture_dacl("outside_parent_before", &outside);
    observe_fixture_dacl("outside_file_before", &outside.join("keep.txt"));
    observe_fixture_dacl("outside_directory_before", &outside.join("keep-dir"));
    let (outside_read, refused, native_errors) = {
        let _impersonation = unsafe { Impersonation::enter(token.0)? };
        for path in &allowed {
            std::fs::write(path.join("created.txt"), "allowed")?;
            std::fs::remove_file(path.join("delete.txt"))?;
            std::fs::remove_dir(path.join("delete-dir"))?;
        }
        let outside_read = std::fs::read_to_string(outside.join("keep.txt"))?;
        let results = [
            std::fs::write(outside.join("keep.txt"), "overwritten"),
            std::fs::write(outside.join("created.txt"), "outside"),
            std::fs::remove_file(outside.join("keep.txt")),
            std::fs::remove_dir(outside.join("keep-dir")),
        ];
        let native_errors = results.each_ref().map(|result| {
            result
                .as_ref()
                .err()
                .map(|error| (error.kind(), error.raw_os_error()))
        });
        let refused = results.map(|result| result.err().map(|error| error.kind()));
        (outside_read, refused, native_errors)
    };
    // Impersonation has ended before any diagnostic output or metadata query.
    record_windows_boundary_diagnostic(format_args!(
        "outside_operations=[overwrite,create,remove_file,remove_dir] native_errors={native_errors:?}"
    ));
    observe_fixture_metadata("outside_file_after", &outside.join("keep.txt"));
    observe_fixture_metadata("outside_directory_after", &outside.join("keep-dir"));
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

#[test]
fn workspace_capability_delete_routes_require_the_capability_in_all_four_cells() -> Result<()> {
    use crate::delete_permission_matrix::DeleteMatrix;
    use crate::delete_permission_matrix::DeleteOutcome;
    use crate::delete_permission_matrix::DeleteRoute;

    let fixture = tempfile::tempdir()?;
    let host = DeleteMatrix::new(&fixture.path().join("host"))?;
    let restricted = DeleteMatrix::new(&fixture.path().join("restricted"))?;
    host.assert_same_acls(&restricted);
    // Elevated host privileges can bypass the Neither ACL. Use the same
    // identity with only DISABLE_MAX_PRIVILEGE for this ordinary ACL control.
    let acl_control = crate::acl_control_test_support::AclControl::new()?;
    let host_errors: Vec<_> = {
        let _impersonation = acl_control.impersonate()?;
        host
            .paths()
            .map(|(file, directory)| {
                [std::fs::remove_file(file), std::fs::remove_dir(directory)].map(|result| {
                    result
                        .err()
                        .map(|error| (error.kind(), error.raw_os_error()))
                })
            })
            .collect()
    };
    acl_control.ensure_restored()?;
    let host_outcomes = host.finish("nonprivileged-acl-control")?;
    eprintln!("delete_matrix host_native_errors={host_errors:?}");
    assert_eq!(
        host_errors,
        vec![
            [Some((std::io::ErrorKind::PermissionDenied, Some(5))); 2],
            [None; 2],
            [None; 2],
            [None; 2],
        ]
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
        })
    );

    let base = OwnedToken(unsafe { get_current_token_for_restriction()? });
    let capability = LocalSid::from_string("S-1-5-21-101-202-303-404")?;
    let second_capability = LocalSid::from_string("S-1-5-21-111-222-333-444")?;
    let allowed = fixture.path().join("allowed");
    std::fs::create_dir(&allowed)?;
    unsafe { ensure_allow_write_aces(&allowed, &[capability.as_ptr()])? };
    std::fs::write(allowed.join("file"), "allowed")?;
    std::fs::create_dir(allowed.join("directory"))?;
    // This is the unchanged product constructor and flags, not a diagnostic token variant.
    let token = OwnedToken(unsafe {
        create_workspace_write_token_with_caps_from(
            base.0,
            &[capability.as_ptr(), second_capability.as_ptr()],
        )?
    });
    let mut logon = unsafe { get_logon_sid_bytes(base.0)? };
    let mut everyone = unsafe { world_sid()? };
    let membership: Vec<_> = [
        capability.as_ptr(),
        second_capability.as_ptr(),
        logon.as_mut_ptr().cast(),
        everyone.as_mut_ptr().cast(),
    ]
    .into_iter()
    .map(|sid| unsafe { token_has_restricting_sid(token.0, sid) })
    .collect::<Result<_>>()?;
    assert_eq!(membership, [true, true, false, false]);
    eprintln!(
        "delete_matrix restricting_membership=[cap_a,cap_b,logon,everyone] values={membership:?}"
    );
    let mut reads = Vec::new();
    let mut errors = Vec::new();
    {
        let _impersonation = unsafe { Impersonation::enter(token.0)? };
        std::fs::remove_file(allowed.join("file"))?;
        std::fs::remove_dir(allowed.join("directory"))?;
        for (file, directory) in restricted.paths() {
            reads.push(std::fs::read_to_string(file)?);
            errors.push(
                [std::fs::remove_file(file), std::fs::remove_dir(directory)].map(|result| {
                    result
                        .err()
                        .map(|error| (error.kind(), error.raw_os_error()))
                }),
            );
        }
    }
    // All four observations are taken before asserting, after RevertToSelf.
    eprintln!("delete_matrix restricted_native_errors={errors:?}");
    let outcomes = restricted.finish("after-revert")?;
    assert_eq!(reads, vec!["matrix-original"; 4]);
    assert_eq!(
        std::fs::symlink_metadata(allowed.join("file"))
            .unwrap_err()
            .kind(),
        std::io::ErrorKind::NotFound
    );
    assert_eq!(
        std::fs::symlink_metadata(allowed.join("directory"))
            .unwrap_err()
            .kind(),
        std::io::ErrorKind::NotFound
    );
    assert_eq!(
        errors,
        vec![[Some((std::io::ErrorKind::PermissionDenied, Some(5))); 2]; 4]
    );
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
