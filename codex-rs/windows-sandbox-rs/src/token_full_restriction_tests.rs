//! Native diagnostic candidate only; no production launch or isolation admission.
#![deny(clippy::all)]

use super::*;
use pretty_assertions::assert_eq;
use std::io::ErrorKind;
use std::mem::offset_of;
use std::mem::size_of;
use std::os::windows::io::AsRawHandle;
use std::os::windows::io::FromRawHandle;
use std::os::windows::io::OwnedHandle;
use std::path::Path;
use windows_sys::Win32::Foundation::ERROR_ACCESS_DENIED;
use windows_sys::Win32::Security::Authorization::GetSecurityInfo;
use windows_sys::Win32::Security::LUID_AND_ATTRIBUTES;
use windows_sys::Win32::Security::OWNER_SECURITY_INFORMATION;
use windows_sys::Win32::Security::SE_PRIVILEGE_ENABLED;
use windows_sys::Win32::Security::TokenPrivileges;
use windows_sys::Win32::Storage::FileSystem::CreateFileW;
use windows_sys::Win32::Storage::FileSystem::FILE_FLAG_BACKUP_SEMANTICS;
use windows_sys::Win32::Storage::FileSystem::FILE_GENERIC_EXECUTE;
use windows_sys::Win32::Storage::FileSystem::FILE_GENERIC_READ;
use windows_sys::Win32::Storage::FileSystem::FILE_SHARE_DELETE;
use windows_sys::Win32::Storage::FileSystem::FILE_SHARE_READ;
use windows_sys::Win32::Storage::FileSystem::FILE_SHARE_WRITE;
use windows_sys::Win32::Storage::FileSystem::OPEN_EXISTING;
use windows_sys::Win32::Storage::FileSystem::READ_CONTROL;
use windows_sys::Win32::Storage::FileSystem::WRITE_DAC;
use windows_sys::Win32::Storage::FileSystem::WRITE_OWNER;

use crate::token::token_query::TokenBytes;

// Explicit subjects, not a boolean that silently changes a production token.
// The inherited default DACL is left unchanged: IPC/process compatibility is unqualified.
fn candidate(base: &OwnedToken, subjects: &[&LocalSid]) -> Result<OwnedToken> {
    let raw = super::super::UnqualifiedFullRestrictionToken::from_primary(
        // SAFETY: the original OwnedToken keeps this explicit base alive.
        unsafe { std::os::windows::io::BorrowedHandle::borrow_raw(base.0 as _) },
        subjects,
    )?;
    let token = OwnedToken(std::os::windows::io::IntoRawHandle::into_raw_handle(
        raw.into_owned_handle(),
    ) as _);
    let actual = TokenBytes::query(token.0, TokenRestrictedSids)?.groups()?;
    let mut expected = subjects
        .iter()
        .map(|sid| {
            // SAFETY: LocalSid owns a validated converted SID throughout this copy.
            unsafe {
                std::slice::from_raw_parts(
                    sid.as_ptr().cast::<u8>(),
                    GetLengthSid(sid.as_ptr()) as usize,
                )
            }
            .to_vec()
        })
        .collect::<Vec<_>>();
    expected.sort();
    assert!(actual == expected, "unexpected actual restricting SID set");
    let normal = TokenBytes::query(token.0, TokenGroups)?.groups()?;
    let base_groups = TokenBytes::query(base.0, TokenGroups)?.groups()?;
    assert!(!normal.is_empty() && normal.iter().all(|sid| base_groups.contains(sid)));
    assert!(
        expected.iter().all(|sid| !normal.contains(sid)),
        "capabilities became ambient groups"
    );
    let original = TokenBytes::query(base.0, TokenUser)?;
    let restricted = TokenBytes::query(token.0, TokenUser)?;
    assert!(
        original.sid(original.value::<SID_AND_ATTRIBUTES>(/*offset*/ 0)?.Sid)?
            == restricted.sid(restricted.value::<SID_AND_ATTRIBUTES>(/*offset*/ 0)?.Sid)?
    );
    assert!(
        TokenBytes::query(base.0, TokenDefaultDacl)?.default_dacl()?
            == TokenBytes::query(token.0, TokenDefaultDacl)?.default_dacl()?
    );
    let privileges = TokenBytes::query(token.0, TokenPrivileges)?;
    let count = privileges.value::<u32>(/*offset*/ 0)? as usize;
    let offset = offset_of!(TOKEN_PRIVILEGES, Privileges);
    anyhow::ensure!(
        count <= privileges.length.saturating_sub(offset) / size_of::<LUID_AND_ATTRIBUTES>()
    );
    let mut traverse = LUID {
        LowPart: 0,
        HighPart: 0,
    };
    // SAFETY: valid NUL-terminated privilege name and live output.
    anyhow::ensure!(
        unsafe {
            LookupPrivilegeValueW(
                std::ptr::null(),
                to_wide("SeChangeNotifyPrivilege").as_ptr(),
                &mut traverse,
            )
        } != 0
    );
    for index in 0..count {
        let entry = privileges
            .value::<LUID_AND_ATTRIBUTES>(offset + index * size_of::<LUID_AND_ATTRIBUTES>())?;
        assert!(
            entry.Attributes & SE_PRIVILEGE_ENABLED == 0
                || (entry.Luid.LowPart, entry.Luid.HighPart)
                    == (traverse.LowPart, traverse.HighPart)
        );
    }
    Ok(token)
}

#[test]
fn raw_full_restriction_refuses_filtered_impersonation_and_ambient_inputs() -> Result<()> {
    use std::os::windows::io::AsHandle;
    use windows_sys::Win32::Security::DuplicateTokenEx;
    use windows_sys::Win32::Security::IsTokenRestricted;
    use windows_sys::Win32::Security::SecurityImpersonation;
    use windows_sys::Win32::Security::TOKEN_DUPLICATE;
    use windows_sys::Win32::Security::TOKEN_QUERY;
    use windows_sys::Win32::Security::TokenImpersonation;

    let base = OwnedToken(unsafe { get_current_token_for_restriction()? });
    // SAFETY: the original owned base is retained through every native query.
    let borrowed = unsafe { std::os::windows::io::BorrowedHandle::borrow_raw(base.0 as _) };
    let subject = LocalSid::from_string("S-1-5-21-161-262-363-464")?;
    let everyone = LocalSid::from_string("S-1-1-0")?;
    assert!(super::super::UnqualifiedFullRestrictionToken::from_primary(borrowed, &[]).is_err());
    assert!(
        super::super::UnqualifiedFullRestrictionToken::from_primary(
            borrowed,
            &[&subject, &subject]
        )
        .is_err()
    );
    assert!(
        super::super::UnqualifiedFullRestrictionToken::from_primary(borrowed, &[&everyone])
            .is_err()
    );
    let maximum = (0..128)
        .map(|index| LocalSid::from_string(&format!("S-1-5-21-171-272-373-{}", 1_000 + index)))
        .collect::<Result<Vec<_>>>()?;
    let mut maximum_refs = maximum.iter().collect::<Vec<_>>();
    drop(candidate(&base, &maximum_refs)?);
    maximum_refs.push(&subject);
    assert!(
        super::super::UnqualifiedFullRestrictionToken::from_primary(borrowed, &maximum_refs)
            .is_err()
    );
    let raw = candidate(&base, &[&subject])?;
    assert!(
        super::super::UnqualifiedFullRestrictionToken::from_primary(
            // SAFETY: raw remains owned during this refusal observation.
            unsafe { std::os::windows::io::BorrowedHandle::borrow_raw(raw.0 as _) },
            &[&subject]
        )
        .is_err()
    );

    let mut filtered = 0;
    // Filtering privileges without any restricting SID must not pass the new
    // fresh-input check merely because IsTokenRestricted reports zero.
    anyhow::ensure!(
        unsafe {
            CreateRestrictedToken(
                base.0,
                DISABLE_MAX_PRIVILEGE,
                /*disablesidcount*/ 0,
                std::ptr::null(),
                /*deleteprivilegecount*/ 0,
                std::ptr::null(),
                /*restrictedsidcount*/ 0,
                std::ptr::null(),
                &mut filtered,
            )
        } != 0
    );
    let filtered = unsafe { OwnedHandle::from_raw_handle(filtered as _) };
    assert_eq!(
        unsafe { IsTokenRestricted(filtered.as_raw_handle() as _) },
        0
    );
    assert!(
        super::super::UnqualifiedFullRestrictionToken::from_primary(
            filtered.as_handle(),
            &[&subject]
        )
        .is_err()
    );
    let mut impersonation = 0;
    anyhow::ensure!(
        unsafe {
            DuplicateTokenEx(
                base.0,
                TOKEN_QUERY | TOKEN_DUPLICATE,
                std::ptr::null(),
                SecurityImpersonation,
                TokenImpersonation,
                &mut impersonation,
            )
        } != 0
    );
    let impersonation = unsafe { OwnedHandle::from_raw_handle(impersonation as _) };
    assert!(
        super::super::UnqualifiedFullRestrictionToken::from_primary(
            impersonation.as_handle(),
            &[&subject]
        )
        .is_err()
    );
    Ok(())
}

fn open_execute(path: &Path) -> std::io::Result<OwnedHandle> {
    // SAFETY: this existing owned fixture and counted wide path remain live.
    let raw = unsafe {
        CreateFileW(
            to_wide(path).as_ptr(),
            FILE_GENERIC_EXECUTE,
            /*dwsharemode*/ 0,
            std::ptr::null(),
            OPEN_EXISTING,
            /*dwflagsandattributes*/ 0,
            /*htemplatefile*/ 0,
        )
    };
    if raw == 0 || raw == windows_sys::Win32::Foundation::INVALID_HANDLE_VALUE {
        return Err(std::io::Error::last_os_error());
    }
    // SAFETY: successful CreateFileW transferred one live handle.
    Ok(unsafe { OwnedHandle::from_raw_handle(raw as *mut c_void) })
}

fn open_fixture_security(path: &Path, access: u32) -> std::io::Result<OwnedHandle> {
    // SAFETY: this fresh owned fixture stays live; directories need backup semantics.
    let raw = unsafe {
        CreateFileW(
            to_wide(path).as_ptr(),
            access,
            FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
            std::ptr::null(),
            OPEN_EXISTING,
            FILE_FLAG_BACKUP_SEMANTICS,
            /*htemplatefile*/ 0,
        )
    };
    if raw == 0 || raw == windows_sys::Win32::Foundation::INVALID_HANDLE_VALUE {
        return Err(std::io::Error::last_os_error());
    }
    // SAFETY: successful CreateFileW transferred this one live handle.
    Ok(unsafe { OwnedHandle::from_raw_handle(raw as *mut c_void) })
}

fn require_fixture_owned_by_user(path: &Path, user: &[u8]) -> Result<()> {
    let held = open_fixture_security(path, READ_CONTROL)?;
    let mut owner = std::ptr::null_mut();
    let mut descriptor = std::ptr::null_mut();
    // SAFETY: the held fixture and output pointers remain live; no ACL or owner is changed.
    let code = unsafe {
        GetSecurityInfo(
            held.as_raw_handle() as HANDLE,
            SE_FILE_OBJECT,
            OWNER_SECURITY_INFORMATION,
            &mut owner,
            std::ptr::null_mut(),
            std::ptr::null_mut(),
            std::ptr::null_mut(),
            &mut descriptor,
        )
    };
    let same_owner = code == ERROR_SUCCESS
        && !owner.is_null()
        && unsafe {
            // SAFETY: success returned a SID in descriptor; user is a validated queried SID.
            EqualSid(owner, user.as_ptr().cast_mut().cast()) != 0
        };
    if !descriptor.is_null() {
        // SAFETY: GetSecurityInfo allocated this descriptor; all borrowed SID use ended.
        unsafe { LocalFree(descriptor as HLOCAL) };
    }
    anyhow::ensure!(code == ERROR_SUCCESS, "fixture owner query failed: {code}");
    anyhow::ensure!(same_owner, "fresh fixture owner is not the base TokenUser");
    Ok(())
}

#[test]
fn native_full_restriction_preserves_reads_and_refuses_parent_delete() -> Result<()> {
    let fixture = tempfile::tempdir()?;
    let base = OwnedToken(unsafe { get_current_token_for_restriction()? });
    let read = LocalSid::from_string("S-1-5-21-151-252-353-454")?;
    let cap_a = LocalSid::from_string("S-1-5-21-101-202-303-404")?;
    let cap_b = LocalSid::from_string("S-1-5-21-111-222-333-444")?;
    let other = LocalSid::from_string("S-1-5-21-121-232-343-454")?;
    let mut logon = unsafe { get_logon_sid_bytes(base.0)? };
    let mut everyone = unsafe { world_sid()? };
    // SAFETY: change only this fresh owned fixture. Preserve the original broad parent attack.
    unsafe {
        ensure_allow_mask_aces(
            fixture.path(),
            &[logon.as_mut_ptr().cast(), everyone.as_mut_ptr().cast()],
            FILE_ALL_ACCESS,
        )?;
        ensure_allow_mask_aces(
            fixture.path(),
            &[read.as_ptr()],
            FILE_GENERIC_READ | FILE_GENERIC_EXECUTE,
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
    unsafe {
        ensure_allow_write_aces(&outside, &[other.as_ptr()])?;
    }
    std::fs::write(outside.join("keep.txt"), "outside")?;
    std::fs::create_dir(outside.join("keep-dir"))?;
    let security_targets = [
        outside.clone(),
        outside.join("keep.txt"),
        outside.join("keep-dir"),
    ];
    let queried_user = TokenBytes::query(base.0, TokenUser)?;
    let user = queried_user.sid(queried_user.value::<SID_AND_ATTRIBUTES>(/*offset*/ 0)?.Sid)?;
    for path in &security_targets {
        require_fixture_owned_by_user(path, &user)?;
        // Unrestricted positive controls prove each exact request is valid on this fixture.
        drop(open_fixture_security(path, WRITE_DAC)?);
        drop(open_fixture_security(path, WRITE_OWNER)?);
    }
    let no_read = candidate(&base, &[&cap_a, &cap_b])?;
    {
        let _impersonation = unsafe { Impersonation::enter(no_read.0)? };
        assert_eq!(
            std::fs::read(outside.join("keep.txt")).unwrap_err().kind(),
            ErrorKind::PermissionDenied
        );
        assert_eq!(
            open_execute(&outside.join("keep.txt")).unwrap_err().kind(),
            ErrorKind::PermissionDenied
        );
    }
    let readonly = candidate(&base, &[&read])?;
    {
        let _impersonation = unsafe { Impersonation::enter(readonly.0)? };
        for path in &allowed {
            assert_eq!(std::fs::read_to_string(path.join("delete.txt"))?, "inside");
            drop(open_execute(&path.join("delete.txt"))?);
            let refused = [
                std::fs::write(path.join("delete.txt"), "bad"),
                std::fs::write(path.join("created.txt"), "bad"),
                std::fs::remove_file(path.join("delete.txt")),
                std::fs::remove_dir(path.join("delete-dir")),
            ]
            .map(|result| result.err().map(|error| error.kind()));
            assert_eq!(refused, [Some(ErrorKind::PermissionDenied); 4]);
        }
    }
    for path in &allowed {
        assert_eq!(
            (
                std::fs::read_to_string(path.join("delete.txt"))?,
                path.join("created.txt").exists(),
                path.join("delete-dir").is_dir()
            ),
            ("inside".to_owned(), false, true)
        );
    }
    let full = candidate(&base, &[&read, &cap_a, &cap_b])?;
    {
        let _impersonation = unsafe { Impersonation::enter(full.0)? };
        for path in &allowed {
            std::fs::write(path.join("created.txt"), "allowed")?;
            std::fs::remove_file(path.join("delete.txt"))?;
            std::fs::remove_dir(path.join("delete-dir"))?;
        }
        let outside_read = std::fs::read_to_string(outside.join("keep.txt"))?;
        drop(open_execute(&outside.join("keep.txt"))?);
        let refused = [
            std::fs::write(outside.join("keep.txt"), "overwritten"),
            std::fs::write(outside.join("created.txt"), "outside"),
            std::fs::remove_file(outside.join("keep.txt")),
            std::fs::remove_dir(outside.join("keep-dir")),
        ]
        .map(|result| result.err().map(|error| error.kind()));
        assert_eq!(refused, [Some(ErrorKind::PermissionDenied); 4]);
        assert_eq!(outside_read, "outside");
    }
    {
        let _impersonation = unsafe { Impersonation::enter(full.0)? };
        for path in &security_targets {
            let refused = [
                open_fixture_security(path, WRITE_DAC),
                open_fixture_security(path, WRITE_OWNER),
            ]
            .map(|result| {
                result
                    .err()
                    .map(|error| (error.kind(), error.raw_os_error()))
            });
            assert_eq!(
                refused,
                [Some((
                    ErrorKind::PermissionDenied,
                    Some(ERROR_ACCESS_DENIED as i32)
                )); 2],
                "outside fixture security access: {}",
                path.display()
            );
        }
    }
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
    println!(
        "HEPTA_FULL_RESTRICTION_CANDIDATE {{\"stage\":\"original_operations_complete\",\"readonly_controls\":true,\"explicit_read_execute\":true,\"production_admitted\":false}}"
    );
    Ok(())
}
