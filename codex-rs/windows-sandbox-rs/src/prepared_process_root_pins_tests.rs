//! Continuous process-root ownership, separate from the query-only ACL reader.
use super::PreparedProcessContext;
use crate::desktop::DesktopCapability;
use crate::prepared_filesystem::PreparedFilesystemAclContext;
use crate::token::get_current_token_for_restriction;
use anyhow::Result;
use pretty_assertions::assert_eq;
use std::fs::OpenOptions;
use std::os::windows::fs::OpenOptionsExt;
use std::os::windows::io::AsHandle;
use std::os::windows::io::FromRawHandle;
use std::os::windows::io::OwnedHandle;
use std::path::PathBuf;
use windows_sys::Win32::Foundation::ERROR_SHARING_VIOLATION;
use windows_sys::Win32::Storage::FileSystem::DELETE;
use windows_sys::Win32::Storage::FileSystem::FILE_FLAG_BACKUP_SEMANTICS;
use windows_sys::Win32::Storage::FileSystem::FILE_FLAG_OPEN_REPARSE_POINT;
use windows_sys::Win32::Storage::FileSystem::FILE_READ_ATTRIBUTES;
use windows_sys::Win32::Storage::FileSystem::FILE_SHARE_DELETE;
use windows_sys::Win32::Storage::FileSystem::FILE_SHARE_READ;
use windows_sys::Win32::Storage::FileSystem::FILE_SHARE_WRITE;
use windows_sys::Win32::Storage::FileSystem::READ_CONTROL;
use windows_sys::Win32::Storage::FileSystem::SYNCHRONIZE;

struct PinFixture {
    tree: tempfile::TempDir,
    _home: tempfile::TempDir,
    read_root: PathBuf,
    workspace: PathBuf,
    base: OwnedHandle,
    filesystem: PreparedFilesystemAclContext,
}

impl PinFixture {
    fn new() -> Result<Self> {
        let tree = tempfile::tempdir()?;
        let home = tempfile::tempdir()?;
        let read_root = tree.path().join("read-root");
        let workspace = tree.path().join("write-root");
        std::fs::create_dir(&read_root)?;
        std::fs::create_dir(&workspace)?;
        // SAFETY: success transfers one owned handle to the actual source token.
        let base =
            unsafe { OwnedHandle::from_raw_handle(get_current_token_for_restriction()? as _) };
        let plan = crate::filesystem_capability_plan(
            home.path(),
            &workspace,
            std::slice::from_ref(&read_root),
            std::slice::from_ref(&workspace),
        )?;
        // Preparation iterates the read roots before the write roots. Distinct
        // siblings ensure a workspace handle cannot pin the read root indirectly.
        assert_eq!(
            (
                plan.read_root_sids().count(),
                plan.write_root_sids().count()
            ),
            (1, 1)
        );
        let filesystem =
            PreparedFilesystemAclContext::prepare(home.path(), &plan, base.as_handle())?;
        Ok(Self {
            tree,
            _home: home,
            read_root,
            workspace,
            base,
            filesystem,
        })
    }
}

#[test]
fn process_root_pins_reject_read_root_rename_until_the_exact_owner_is_dropped() -> Result<()> {
    let PinFixture {
        tree,
        _home,
        read_root,
        workspace: _,
        base,
        filesystem,
    } = PinFixture::new()?;
    let moved = tree.path().join("moved-read-root");
    let context = PreparedProcessContext::prepare(
        base.as_handle(),
        filesystem,
        DesktopCapability::create()?,
        /*logs_base_dir*/ None,
    )?;
    drop(base);
    let (mut owners, desktop, job) = context.into_parts()?;
    owners.revalidate()?;
    assert!(std::fs::rename(&read_root, &moved).is_err());
    assert_eq!((read_root.is_dir(), moved.exists()), (true, false));
    drop((owners, desktop, job));
    std::fs::rename(&read_root, &moved)?;
    assert_eq!((read_root.exists(), moved.is_dir()), (false, true));
    Ok(())
}

#[test]
fn process_root_pin_failure_releases_already_acquired_read_root() -> Result<()> {
    let PinFixture {
        tree,
        _home,
        read_root,
        workspace,
        base,
        filesystem,
    } = PinFixture::new()?;
    // An actual, pre-existing DELETE owner of the second, independent root
    // conflicts with the new pin's no-DELETE-share. This owner itself shares all.
    let delete_owner = OpenOptions::new()
        .access_mode(DELETE | READ_CONTROL | FILE_READ_ATTRIBUTES | SYNCHRONIZE)
        .share_mode(FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE)
        .custom_flags(FILE_FLAG_BACKUP_SEMANTICS | FILE_FLAG_OPEN_REPARSE_POINT)
        .open(&workspace)?;
    let error = match PreparedProcessContext::prepare(
        base.as_handle(),
        filesystem,
        DesktopCapability::create()?,
        /*logs_base_dir*/ None,
    ) {
        Ok(_) => anyhow::bail!("conflicting DELETE owner produced a launch context"),
        Err(error) => error,
    };
    assert_eq!(
        error
            .downcast_ref::<std::io::Error>()
            .and_then(std::io::Error::raw_os_error),
        Some(ERROR_SHARING_VIOLATION as i32)
    );
    let moved = tree.path().join("released-read-root");
    std::fs::rename(&read_root, &moved)?;
    assert_eq!((read_root.exists(), moved.is_dir()), (false, true));
    assert!(delete_owner.metadata()?.is_dir());
    assert!(workspace.is_dir());
    drop(delete_owner);
    Ok(())
}
