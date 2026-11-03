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

#[path = "token_delete_boundary_tests.rs"]
mod delete_boundary;

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
    native_write_deny_repair(DELETE)
}

#[test]
fn legacy_generic_write_deny_keeps_mutations_denied_without_blocking_reads() -> Result<()> {
    use windows_sys::Win32::Foundation::GENERIC_WRITE;
    use windows_sys::Win32::Storage::FileSystem::FILE_DELETE_CHILD;
    use windows_sys::Win32::Storage::FileSystem::FILE_GENERIC_WRITE;

    for write in [GENERIC_WRITE, FILE_GENERIC_WRITE] {
        native_write_deny_repair(write | DELETE | FILE_DELETE_CHILD)?;
    }
    Ok(())
}

fn native_write_deny_repair(seed_mask: u32) -> Result<()> {
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
        grfAccessPermissions: seed_mask,
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
        let write = std::fs::write(&existing, "before repair");
        if seed_mask == DELETE {
            write?;
        } else {
            assert_eq!(
                write.err().map(|error| error.kind()),
                Some(std::io::ErrorKind::PermissionDenied),
            );
            assert_eq!(
                std::fs::read_to_string(&existing)
                    .err()
                    .map(|error| error.kind()),
                Some(std::io::ErrorKind::PermissionDenied),
            );
        }
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
    let expected = if seed_mask == DELETE {
        "before repair"
    } else {
        "original"
    };
    assert_eq!(read, expected);
    assert_eq!(
        (std::fs::read_to_string(&existing)?, created.exists()),
        (expected.to_owned(), false),
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
    let read_cap = LocalSid::from_string("S-1-5-21-131-242-353-464")?;
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
        ensure_allow_mask_aces(
            &outside,
            &[read_cap.as_ptr()],
            windows_sys::Win32::Storage::FileSystem::FILE_GENERIC_READ
                | windows_sys::Win32::Storage::FileSystem::FILE_GENERIC_EXECUTE,
        )?;
    }
    std::fs::write(outside.join("keep.txt"), "outside")?;
    std::fs::create_dir(outside.join("keep-dir"))?;
    let token = OwnedToken(unsafe {
        create_workspace_write_token_with_read_caps_from(
            base.0,
            &[cap_a.as_ptr(), cap_b.as_ptr()],
            &[read_cap.as_ptr()],
        )?
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

struct OwnedEvent(HANDLE);

impl Drop for OwnedEvent {
    fn drop(&mut self) {
        unsafe { CloseHandle(self.0) };
    }
}

fn describe_actual_event_descriptor(label: &str, descriptor: *mut c_void) -> Result<()> {
    use windows_sys::Win32::Security::GetSecurityDescriptorControl;
    use windows_sys::Win32::Security::GetSecurityDescriptorGroup;
    use windows_sys::Win32::Security::GetSecurityDescriptorLength;
    use windows_sys::Win32::Security::GetSecurityDescriptorOwner;
    use windows_sys::Win32::Security::IsValidSecurityDescriptor;
    use windows_sys::Win32::Security::IsValidSid;

    let valid = unsafe { IsValidSecurityDescriptor(descriptor) } != 0;
    let mut control = 0;
    let mut revision = 0;
    let control_ok =
        unsafe { GetSecurityDescriptorControl(descriptor, &mut control, &mut revision) };
    let mut owner = std::ptr::null_mut();
    let mut group = std::ptr::null_mut();
    let mut owner_defaulted = 0;
    let mut group_defaulted = 0;
    let owner_ok =
        unsafe { GetSecurityDescriptorOwner(descriptor, &mut owner, &mut owner_defaulted) };
    let group_ok =
        unsafe { GetSecurityDescriptorGroup(descriptor, &mut group, &mut group_defaulted) };
    let owner_valid = !owner.is_null() && unsafe { IsValidSid(owner) } != 0;
    let group_valid = !group.is_null() && unsafe { IsValidSid(group) } != 0;
    let length = if valid {
        unsafe { GetSecurityDescriptorLength(descriptor) }
    } else {
        0
    };
    eprintln!(
        "actual Event SD {label}: valid={valid} length={length} control_ok={control_ok} control={control:#x} revision={revision} owner_ok={owner_ok} owner_present={} owner_valid={owner_valid} owner_defaulted={owner_defaulted} group_ok={group_ok} group_present={} group_valid={group_valid} group_defaulted={group_defaulted}",
        !owner.is_null(),
        !group.is_null(),
    );
    anyhow::ensure!(
        valid && control_ok != 0 && owner_ok != 0 && group_ok != 0,
        "actual Event descriptor inspection failed"
    );
    Ok(())
}

fn assert_event_access(descriptor: *mut c_void, token: HANDLE, expected: bool) -> Result<()> {
    use windows_sys::Win32::Security::AccessCheck;
    use windows_sys::Win32::Security::DuplicateToken;
    use windows_sys::Win32::Security::GENERIC_MAPPING;
    use windows_sys::Win32::Security::PRIVILEGE_SET;
    use windows_sys::Win32::Security::SecurityImpersonation;
    use windows_sys::Win32::Storage::FileSystem::READ_CONTROL;
    use windows_sys::Win32::Storage::FileSystem::SYNCHRONIZE;
    use windows_sys::Win32::System::Threading::EVENT_ALL_ACCESS;
    use windows_sys::Win32::System::Threading::EVENT_MODIFY_STATE;

    let mut impersonation = 0;
    anyhow::ensure!(
        unsafe { DuplicateToken(token, SecurityImpersonation, &mut impersonation) } != 0,
        "duplicate AccessCheck impersonation token: {}",
        unsafe { GetLastError() }
    );
    let impersonation = OwnedToken(impersonation);
    let desired = EVENT_MODIFY_STATE | SYNCHRONIZE;
    let mapping = GENERIC_MAPPING {
        GenericRead: READ_CONTROL | 0x0001,
        GenericWrite: READ_CONTROL | EVENT_MODIFY_STATE,
        GenericExecute: READ_CONTROL | SYNCHRONIZE,
        GenericAll: EVENT_ALL_ACCESS,
    };
    let mut privileges: PRIVILEGE_SET = unsafe { std::mem::zeroed() };
    let mut privilege_bytes = std::mem::size_of::<PRIVILEGE_SET>() as u32;
    let mut granted = 0;
    let mut allowed = 0;
    // This is the descriptor of an actual object created with the production
    // token's default DACL. API failure is never interpreted as access denial.
    let ok = unsafe {
        AccessCheck(
            descriptor,
            impersonation.0,
            desired,
            &mapping,
            &mut privileges,
            &mut privilege_bytes,
            &mut granted,
            &mut allowed,
        )
    };
    anyhow::ensure!(ok != 0, "Event AccessCheck API failed: {}", unsafe {
        GetLastError()
    });
    assert_eq!(
        (allowed != 0, granted),
        (expected, if expected { desired } else { 0 }),
    );
    Ok(())
}

#[test]
fn actual_unnamed_event_default_dacl_keeps_shared_read_capabilities_nonwriting() -> Result<()> {
    use windows_sys::Win32::Security::Authorization::GetSecurityInfo;
    use windows_sys::Win32::Security::Authorization::SE_KERNEL_OBJECT;
    use windows_sys::Win32::Security::GROUP_SECURITY_INFORMATION;
    use windows_sys::Win32::Security::OWNER_SECURITY_INFORMATION;
    use windows_sys::Win32::System::Threading::CreateEventW;
    use windows_sys::Win32::System::Threading::SetEvent;
    use windows_sys::Win32::System::Threading::WaitForSingleObject;

    struct Descriptor(*mut c_void);
    impl Drop for Descriptor {
        fn drop(&mut self) {
            unsafe { LocalFree(self.0 as HLOCAL) };
        }
    }

    let fixture = tempfile::tempdir()?;
    let caps = crate::cap::load_or_create_cap_sids(fixture.path())?;
    let first = LocalSid::from_string(&caps.workspace)?;
    let second = LocalSid::from_string(&caps.readonly)?;
    let read = LocalSid::from_string(&crate::cap::readable_root_cap_sid_for_path(
        fixture.path(),
        fixture.path(),
    )?)?;
    let base = OwnedToken(unsafe { get_current_token_for_restriction()? });
    let first_token = OwnedToken(unsafe {
        create_workspace_write_token_with_read_caps_from(
            base.0,
            &[first.as_ptr()],
            &[read.as_ptr()],
        )?
    });
    let second_token = OwnedToken(unsafe {
        create_workspace_write_token_with_read_caps_from(
            base.0,
            &[second.as_ptr()],
            &[read.as_ptr()],
        )?
    });
    // An access-check-only token isolates the shared read SID. It creates no
    // objects and receives neither workspace SID nor a default write grant.
    let mut read_entry = SID_AND_ATTRIBUTES {
        Sid: read.as_ptr(),
        Attributes: 0,
    };
    let mut read_token = 0;
    anyhow::ensure!(
        unsafe {
            CreateRestrictedToken(
                base.0,
                DISABLE_MAX_PRIVILEGE | LUA_TOKEN,
                0,
                std::ptr::null(),
                0,
                std::ptr::null(),
                1,
                &mut read_entry,
                &mut read_token,
            )
        } != 0,
        "create shared-read-only AccessCheck token: {}",
        unsafe { GetLastError() }
    );
    let read_token = OwnedToken(read_token);
    let event = {
        let _identity = unsafe { Impersonation::enter(first_token.0)? };
        let handle = unsafe { CreateEventW(std::ptr::null(), 1, 0, std::ptr::null()) };
        anyhow::ensure!(handle != 0, "create actual unnamed event: {}", unsafe {
            GetLastError()
        });
        let event = OwnedEvent(handle);
        anyhow::ensure!(
            unsafe { SetEvent(event.0) } != 0,
            "signal actual unnamed event"
        );
        assert_eq!(
            unsafe { WaitForSingleObject(event.0, 0) },
            windows_sys::Win32::Foundation::WAIT_OBJECT_0,
        );
        event
    };
    let mut descriptor = std::ptr::null_mut();
    let code = unsafe {
        GetSecurityInfo(
            event.0,
            SE_KERNEL_OBJECT,
            OWNER_SECURITY_INFORMATION | GROUP_SECURITY_INFORMATION | DACL_SECURITY_INFORMATION,
            std::ptr::null_mut(),
            std::ptr::null_mut(),
            std::ptr::null_mut(),
            std::ptr::null_mut(),
            &mut descriptor,
        )
    };
    anyhow::ensure!(
        code == ERROR_SUCCESS,
        "read actual Event descriptor: {code}"
    );
    anyhow::ensure!(!descriptor.is_null(), "missing actual Event descriptor");
    let descriptor = Descriptor(descriptor);
    describe_actual_event_descriptor("GetSecurityInfo", descriptor.0)?;

    // Independently inspect the same real object; do not add or synthesize a
    // missing owner/group to make AccessCheck accept a different descriptor.
    let information =
        OWNER_SECURITY_INFORMATION | GROUP_SECURITY_INFORMATION | DACL_SECURITY_INFORMATION;
    let mut required = 0;
    let first = unsafe {
        windows_sys::Win32::Security::GetKernelObjectSecurity(
            event.0,
            information,
            std::ptr::null_mut(),
            0,
            &mut required,
        )
    };
    anyhow::ensure!(
        first == 0
            && unsafe { GetLastError() }
                == windows_sys::Win32::Foundation::ERROR_INSUFFICIENT_BUFFER
            && (20..=1_048_576).contains(&required),
        "bound actual kernel Event descriptor: {} bytes={required}",
        unsafe { GetLastError() },
    );
    let mut kernel = vec![0_u64; (required as usize).div_ceil(8)];
    let ok = unsafe {
        windows_sys::Win32::Security::GetKernelObjectSecurity(
            event.0,
            information,
            kernel.as_mut_ptr().cast(),
            (kernel.len() * std::mem::size_of::<u64>()) as u32,
            &mut required,
        )
    };
    anyhow::ensure!(ok != 0, "read actual kernel Event descriptor: {}", unsafe {
        GetLastError()
    });
    let kernel_descriptor = kernel.as_mut_ptr().cast();
    describe_actual_event_descriptor("GetKernelObjectSecurity", kernel_descriptor)?;
    let info_check = assert_event_access(descriptor.0, first_token.0, true);
    let kernel_check = assert_event_access(kernel_descriptor, first_token.0, true);
    eprintln!(
        "same real Event AccessCheck: GetSecurityInfo={info_check:?}, GetKernelObjectSecurity={kernel_check:?}"
    );
    info_check?;
    kernel_check?;
    assert_event_access(descriptor.0, read_token.0, false)?;
    assert_event_access(descriptor.0, second_token.0, false)?;
    Ok(())
}

#[test]
fn strict_token_refuses_unprovisioned_local_named_event_namespace() -> Result<()> {
    use windows_sys::Win32::System::Threading::CreateEventW;

    let fixture = tempfile::tempdir()?;
    let caps = crate::cap::load_or_create_cap_sids(fixture.path())?;
    let write = LocalSid::from_string(&caps.workspace)?;
    let read = LocalSid::from_string(&crate::cap::readable_root_cap_sid_for_path(
        fixture.path(),
        fixture.path(),
    )?)?;
    let base = OwnedToken(unsafe { get_current_token_for_restriction()? });
    let token = OwnedToken(unsafe {
        create_workspace_write_token_with_read_caps_from(
            base.0,
            &[write.as_ptr()],
            &[read.as_ptr()],
        )?
    });
    let name = to_wide(format!("Local\\codex-read-cap-ipc-{}", caps.workspace));
    let (handle, error) = {
        let _identity = unsafe { Impersonation::enter(token.0)? };
        let handle = unsafe { CreateEventW(std::ptr::null(), 1, 0, name.as_ptr()) };
        let error = (handle == 0).then(|| unsafe { GetLastError() });
        (handle, error)
    };
    let _event = (handle != 0).then(|| OwnedEvent(handle));
    assert_eq!(
        (handle, error),
        (0, Some(windows_sys::Win32::Foundation::ERROR_ACCESS_DENIED)),
    );
    Ok(())
}
