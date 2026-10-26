//! Native existing-root readback only; no production or descendant qualification.
use super::*;
use pretty_assertions::assert_eq;
use std::os::windows::io::AsHandle;
use windows_sys::Win32::Foundation::GetHandleInformation;
use windows_sys::Win32::Foundation::HANDLE_FLAG_INHERIT;
use windows_sys::Win32::Security::Authorization::SET_ACCESS;

fn fixture() -> Result<(
    tempfile::TempDir,
    PathBuf,
    FilesystemCapabilityPlan,
    OwnedHandle,
)> {
    let temporary = tempfile::tempdir()?;
    let home = temporary.path().join("home");
    let writable = temporary.path().join("writable");
    let readonly = temporary.path().join("readonly");
    std::fs::create_dir(&writable)?;
    std::fs::create_dir(&readonly)?;
    let writable = dunce::canonicalize(writable)?;
    let readonly = dunce::canonicalize(readonly)?;
    let plan = crate::filesystem_capability_plan(
        &home,
        &writable,
        &[writable.clone(), readonly],
        std::slice::from_ref(&writable),
    )?;
    // SAFETY: successful capture transfers one actual current primary handle.
    let base =
        unsafe { OwnedHandle::from_raw_handle(crate::get_current_token_for_restriction()? as _) };
    Ok((temporary, home, plan, base))
}

fn snapshots(plan: &FilesystemCapabilityPlan) -> Result<Vec<Vec<u8>>> {
    plan.read_root_sids()
        .chain(plan.write_root_sids())
        .map(|(path, _)| {
            descriptor(&read_acl_query::open(Path::new(path))?).map(|(_, bytes)| bytes)
        })
        .collect()
}

fn set_role(path: &str, sid: &str, mask: u32, flags: u32) -> Result<()> {
    let file = read_acl_query::open_with_access(Path::new(path), QUERY | WRITE_DAC)?;
    let subject = LocalSid::from_string(sid)?;
    let mut raw = std::ptr::null_mut();
    let mut old = std::ptr::null_mut();
    let code = unsafe {
        GetSecurityInfo(
            file.as_raw_handle() as _,
            SE_FILE_OBJECT,
            DACL_SECURITY_INFORMATION,
            std::ptr::null_mut(),
            std::ptr::null_mut(),
            &mut old,
            std::ptr::null_mut(),
            &mut raw,
        )
    };
    let _original = Allocation(raw);
    ensure!(code == 0 && !old.is_null());
    let entry = EXPLICIT_ACCESS_W {
        grfAccessPermissions: mask,
        grfAccessMode: SET_ACCESS,
        grfInheritance: flags,
        Trustee: TRUSTEE_W {
            TrusteeForm: TRUSTEE_IS_SID,
            ptstrName: subject.as_ptr() as _,
            ..unsafe { std::mem::zeroed() }
        },
    };
    let mut updated = std::ptr::null_mut();
    ensure!(
        unsafe {
            SetEntriesInAclW(
                /*ccountofexplicitentries*/ 1,
                &entry,
                old,
                &mut updated,
            )
        } == 0
    );
    let _updated = Allocation(updated.cast());
    ensure!(!updated.is_null());
    ensure!(
        unsafe {
            SetSecurityInfo(
                file.as_raw_handle() as _,
                SE_FILE_OBJECT,
                DACL_SECURITY_INFORMATION,
                std::ptr::null_mut(),
                std::ptr::null_mut(),
                updated,
                std::ptr::null_mut(),
            )
        } == 0
    );
    Ok(())
}

#[test]
fn existing_readv3_grants_keep_query_handles_and_same_path_read_write_roles() -> Result<()> {
    let (_temporary, home, plan, base) = fixture()?;
    assert!(
        PreparedFilesystemAclContext::observe_existing(&home, &plan, base.as_handle()).is_err()
    );
    drop(PreparedFilesystemAclContext::prepare(
        &home,
        &plan,
        base.as_handle(),
    )?);
    let before = snapshots(&plan)?;
    let mut observed =
        PreparedFilesystemAclContext::observe_existing(&home, &plan, base.as_handle())?;
    assert_eq!(
        observed.roots.len(),
        plan.read_sids().count() + plan.write_sids().count()
    );
    for root in &observed.roots {
        let mut flags = 0;
        assert_ne!(
            unsafe { GetHandleInformation(root.file.as_raw_handle() as _, &mut flags) },
            0
        );
        assert_eq!(flags & HANDLE_FLAG_INHERIT, 0);
        let (security, _) = descriptor(&root.file)?;
        let mut old = std::ptr::null_mut();
        let mut present = 0;
        let mut defaulted = 0;
        assert_ne!(
            unsafe {
                windows_sys::Win32::Security::GetSecurityDescriptorDacl(
                    security.0,
                    &mut present,
                    &mut old,
                    &mut defaulted,
                )
            },
            0
        );
        assert_eq!(present, 1);
        // A real query-only handle cannot be used even to reinstall its same DACL.
        assert_eq!(
            unsafe {
                SetSecurityInfo(
                    root.file.as_raw_handle() as _,
                    SE_FILE_OBJECT,
                    DACL_SECURITY_INFORMATION,
                    std::ptr::null_mut(),
                    std::ptr::null_mut(),
                    old,
                    std::ptr::null_mut(),
                )
            },
            5
        );
    }
    let subjects = observed.filesystem_sids()?;
    let refs = subjects.iter().collect::<Vec<_>>();
    let token = crate::UnqualifiedFullRestrictionToken::from_primary(base.as_handle(), &refs)?;
    observed.require_token_access(token.as_handle())?;
    observed.validate_for_token(base.as_handle())?;
    assert_eq!(snapshots(&plan)?, before);
    Ok(())
}

#[test]
fn existing_read_ancestor_and_write_descendants_keep_their_original_role_masks() -> Result<()> {
    let temporary = tempfile::tempdir()?;
    let home = tempfile::tempdir()?;
    let children = [
        temporary.path().join("workspace"),
        temporary.path().join("temp"),
    ];
    for child in &children {
        std::fs::create_dir(child)?;
    }
    let plan = crate::filesystem_capability_plan(
        home.path(),
        &children[0],
        &[dunce::canonicalize(temporary.path())?],
        &children,
    )?;
    // SAFETY: successful capture transfers one actual current primary handle.
    let base =
        unsafe { OwnedHandle::from_raw_handle(crate::get_current_token_for_restriction()? as _) };
    drop(PreparedFilesystemAclContext::prepare(
        home.path(),
        &plan,
        base.as_handle(),
    )?);
    let before = snapshots(&plan)?;
    let mut observed =
        PreparedFilesystemAclContext::observe_existing(home.path(), &plan, base.as_handle())?;
    let subjects = observed.filesystem_sids()?;
    let refs = subjects.iter().collect::<Vec<_>>();
    let token = crate::UnqualifiedFullRestrictionToken::from_primary(base.as_handle(), &refs)?;
    observed.require_token_access(token.as_handle())?;
    assert_eq!(snapshots(&plan)?, before);
    Ok(())
}

#[test]
fn existing_write_role_requires_effective_complete_root_grant_without_repair() -> Result<()> {
    let (_temporary, home, plan, base) = fixture()?;
    drop(PreparedFilesystemAclContext::prepare(
        &home,
        &plan,
        base.as_handle(),
    )?);
    let (path, sid) = plan
        .write_root_sids()
        .next()
        .ok_or_else(|| anyhow::anyhow!("write role"))?;
    for (mask, flags) in [(0, 3), (RX, 3), (WRITE, 3 | 8)] {
        set_role(path, sid, mask, flags)?;
        let before = snapshots(&plan)?;
        assert!(
            PreparedFilesystemAclContext::observe_existing(&home, &plan, base.as_handle()).is_err()
        );
        assert_eq!(snapshots(&plan)?, before);
    }
    set_role(path, sid, WRITE, /*flags*/ 3)?;
    PreparedFilesystemAclContext::observe_existing(&home, &plan, base.as_handle())?;
    Ok(())
}
