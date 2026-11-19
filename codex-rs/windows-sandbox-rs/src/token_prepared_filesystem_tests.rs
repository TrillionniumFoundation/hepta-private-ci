//! Bounded prepared admission, in addition to both unchanged legacy failures.
use super::super::prepared_filesystem::create_full_filesystem_token_from;
use super::*;
use crate::desktop::DesktopCapability;
use crate::prepared_filesystem::PreparedFilesystemAclContext;
use pretty_assertions::assert_eq;
use std::io::ErrorKind;
use std::os::windows::io::AsHandle;
use std::os::windows::io::AsRawHandle;
use std::os::windows::io::BorrowedHandle;
use windows_sys::Win32::Storage::FileSystem::FILE_GENERIC_EXECUTE;
use windows_sys::Win32::Storage::FileSystem::FILE_GENERIC_READ;
use windows_sys::Win32::Storage::FileSystem::WRITE_DAC;
use windows_sys::Win32::Storage::FileSystem::WRITE_OWNER;

#[test]
fn prepared_full_token_preserves_bounded_reads_and_refuses_broad_parent_delete() -> Result<()> {
    let fixture = tempfile::tempdir()?;
    let home = tempfile::tempdir()?;
    let base = OwnedToken(unsafe { get_current_token_for_restriction()? });
    let base_handle = unsafe { BorrowedHandle::borrow_raw(base.0 as _) };
    let logon = unsafe { get_logon_sid_bytes(base.0)? };
    let everyone = LocalSid::from_string("S-1-1-0")?;
    // Preserve the attack precondition, including broad parent DELETE_CHILD.
    unsafe {
        ensure_allow_mask_aces(
            fixture.path(),
            &[logon.as_ptr().cast_mut().cast(), everyone.as_ptr()],
            FILE_ALL_ACCESS,
        )?;
    }
    let allowed = [
        fixture.path().join("workspace"),
        fixture.path().join("temp"),
    ];
    for path in &allowed {
        std::fs::create_dir(path)?;
        std::fs::write(path.join("delete.txt"), "inside")?;
        std::fs::create_dir(path.join("delete-dir"))?;
    }
    let outside = fixture.path().join("outside");
    std::fs::create_dir(&outside)?;
    let stale = LocalSid::from_string("S-1-5-21-121-232-343-454")?;
    unsafe { ensure_allow_write_aces(&outside, &[stale.as_ptr()])? };
    std::fs::write(outside.join("keep.txt"), "outside")?;
    std::fs::create_dir(outside.join("keep-dir"))?;
    let plan = crate::filesystem_capability_plan(
        home.path(),
        &allowed[0],
        &[dunce::canonicalize(fixture.path())?],
        &allowed,
    )?;
    let mut prepared = PreparedFilesystemAclContext::prepare(home.path(), &plan, base_handle)?;
    let desktop = DesktopCapability::create()?;
    let mut token = create_full_filesystem_token_from(base_handle, &mut prepared, &desktop)?;
    token.revalidate(&mut prepared)?;
    let token_handle = token.as_handle().as_raw_handle() as HANDLE;
    // First prove the same broad ACL admits parent-delete for the unfiltered
    // source, then prove the admitted token refuses that exact requested right.
    assert_eq!(
        (
            fixture_access_check(
                &outside,
                base.0,
                windows_sys::Win32::Storage::FileSystem::FILE_DELETE_CHILD
            )?
            .0,
            fixture_access_check(
                &outside,
                token_handle,
                windows_sys::Win32::Storage::FileSystem::FILE_DELETE_CHILD
            )?
            .0,
        ),
        (true, false)
    );
    for path in [
        &outside,
        &outside.join("keep.txt"),
        &outside.join("keep-dir"),
    ] {
        for access in [WRITE_DAC, WRITE_OWNER] {
            assert!(fixture_access_check(path, base.0, access)?.0);
            assert!(!fixture_access_check(path, token_handle, access)?.0);
        }
    }
    {
        let _impersonation = unsafe { Impersonation::enter(token_handle)? };
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
        assert_eq!(refused, [Some(ErrorKind::PermissionDenied); 4]);
        assert_eq!(outside_read, "outside");
    }
    assert_eq!(
        (
            std::fs::read_to_string(outside.join("keep.txt"))?,
            outside.join("created.txt").exists(),
            outside.join("keep-dir").is_dir(),
        ),
        ("outside".to_owned(), false, true)
    );
    for path in &allowed {
        assert_eq!(
            (
                std::fs::read_to_string(path.join("created.txt"))?,
                path.join("delete.txt").exists(),
                path.join("delete-dir").exists(),
            ),
            ("allowed".to_owned(), false, false)
        );
    }
    // A real changed root descriptor must poison both preparation and admission.
    let extra = LocalSid::from_string("S-1-5-21-881-882-883-884")?;
    unsafe { ensure_allow_mask_aces(&outside, &[extra.as_ptr()], FILE_GENERIC_READ)? };
    // The declared root is fixture, so mutate that held root, not only a child.
    unsafe {
        ensure_allow_mask_aces(
            fixture.path(),
            &[extra.as_ptr()],
            FILE_GENERIC_READ | FILE_GENERIC_EXECUTE,
        )?
    };
    assert!(token.revalidate(&mut prepared).is_err());
    assert!(token.revalidate(&mut prepared).is_err());
    Ok(())
}

#[test]
fn full_token_mutation_deny_keeps_native_reads_and_idempotence() -> Result<()> {
    let fixture = tempfile::tempdir()?;
    let read = LocalSid::from_string("S-1-5-21-971-972-973-974")?;
    let write = LocalSid::from_string("S-1-5-21-981-982-983-984")?;
    let base = OwnedToken(unsafe { get_current_token_for_restriction()? });
    unsafe {
        ensure_allow_mask_aces(
            fixture.path(),
            &[read.as_ptr()],
            FILE_GENERIC_READ | FILE_GENERIC_EXECUTE,
        )?;
        ensure_allow_write_aces(fixture.path(), &[write.as_ptr()])?;
    }
    let existing = fixture.path().join("existing.txt");
    let created = fixture.path().join("created.txt");
    std::fs::write(&existing, "original")?;
    let token = super::super::full_restriction::create_checked_full_restriction(
        unsafe { BorrowedHandle::borrow_raw(base.0 as _) },
        &[&read, &write],
        /*capacity*/ 128,
    )?;
    {
        let _impersonation = unsafe { Impersonation::enter(token.as_raw_handle() as _) }?;
        std::fs::write(&existing, "before repair")?;
    }
    let repaired =
        unsafe { crate::acl::ensure_filesystem_mutation_deny(fixture.path(), write.as_ptr())? };
    let repeated = unsafe {
        (
            crate::acl::ensure_filesystem_mutation_deny(fixture.path(), write.as_ptr())?,
            crate::acl::ensure_filesystem_mutation_deny(&existing, write.as_ptr())?,
            crate::acl::ensure_filesystem_mutation_deny(&existing, write.as_ptr())?,
        )
    };
    let (read, denied) = {
        let _impersonation = unsafe { Impersonation::enter(token.as_raw_handle() as _) }?;
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
        (true, [Some(ErrorKind::PermissionDenied); 2])
    );
    assert_eq!(repeated, (false, true, false));
    assert_eq!(read, "before repair");
    assert_eq!(
        (std::fs::read_to_string(&existing)?, created.exists()),
        ("before repair".to_owned(), false)
    );
    Ok(())
}
