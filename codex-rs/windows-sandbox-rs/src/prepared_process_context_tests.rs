//! Native preparation and retained-owner checks, without a child-launch claim.
use super::PreparedProcessContext;
use crate::desktop::DesktopCapability;
use crate::prepared_filesystem::PreparedFilesystemAclContext;
use crate::token::LocalSid;
use crate::token::get_current_token_for_restriction;
use anyhow::Result;
use pretty_assertions::assert_eq;
use std::os::windows::io::AsHandle;
use std::os::windows::io::FromRawHandle;
use std::os::windows::io::OwnedHandle;
use std::path::Path;
use std::path::PathBuf;
use windows_sys::Win32::Storage::FileSystem::FILE_GENERIC_READ;

struct Fixture {
    tree: tempfile::TempDir,
    _home: tempfile::TempDir,
    workspace: PathBuf,
    base: OwnedHandle,
    filesystem: PreparedFilesystemAclContext,
}

impl Fixture {
    fn new() -> Result<Self> {
        let tree = tempfile::tempdir()?;
        let home = tempfile::tempdir()?;
        let workspace = tree.path().join("workspace");
        std::fs::create_dir(&workspace)?;
        // SAFETY: success returns one owned handle to the actual source token.
        let base =
            unsafe { OwnedHandle::from_raw_handle(get_current_token_for_restriction()? as _) };
        let plan = crate::filesystem_capability_plan(
            home.path(),
            &workspace,
            &[dunce::canonicalize(tree.path())?],
            std::slice::from_ref(&workspace),
        )?;
        let filesystem =
            PreparedFilesystemAclContext::prepare(home.path(), &plan, base.as_handle())?;
        Ok(Self {
            tree,
            _home: home,
            workspace,
            base,
            filesystem,
        })
    }
}

fn change_fixture_acl(path: &Path) -> Result<()> {
    let other = LocalSid::from_string("S-1-5-21-881-882-883-885")?;
    // SAFETY: only the owned temporary directory is changed. The retained root
    // descriptor must observe this real native mutation; no system ACL changes.
    unsafe {
        crate::acl::ensure_allow_mask_aces(path, &[other.as_ptr()], FILE_GENERIC_READ)?;
    }
    Ok(())
}

#[test]
fn prepared_process_owner_retains_source_and_root_handles_after_original_base_closes() -> Result<()>
{
    let Fixture {
        tree,
        _home,
        workspace,
        base,
        filesystem,
    } = Fixture::new()?;
    let context = PreparedProcessContext::prepare(
        base.as_handle(),
        filesystem,
        DesktopCapability::create()?,
        /*logs_base_dir*/ None,
    )?;
    drop(base);
    let (mut owners, desktop, job) = context.into_parts()?;
    owners.revalidate()?;
    let moved = tree.path().join("moved-workspace");
    assert!(std::fs::rename(&workspace, &moved).is_err());
    assert_eq!((workspace.is_dir(), moved.exists()), (true, false));
    drop((owners, desktop, job));
    std::fs::rename(&workspace, &moved)?;
    assert_eq!((workspace.exists(), moved.is_dir()), (false, true));
    Ok(())
}

#[test]
fn prepared_process_owner_refuses_changed_acl_before_creating_launch_resources() -> Result<()> {
    let Fixture {
        tree,
        _home,
        workspace,
        base,
        filesystem,
    } = Fixture::new()?;
    change_fixture_acl(&workspace)?;
    let error = match PreparedProcessContext::prepare(
        base.as_handle(),
        filesystem,
        DesktopCapability::create()?,
        /*logs_base_dir*/ None,
    ) {
        Ok(_) => anyhow::bail!("changed root descriptor produced a launch context"),
        Err(error) => error,
    };
    assert!(
        error
            .to_string()
            .contains("prepared root identity or descriptor changed")
    );
    // Refusal consumed the prepared context; no retained root handle leaks.
    std::fs::rename(&workspace, tree.path().join("moved-after-refusal"))?;
    Ok(())
}

#[test]
fn prepared_process_owner_refuses_acl_drift_at_the_one_use_handoff() -> Result<()> {
    let Fixture {
        tree,
        _home,
        workspace,
        base,
        filesystem,
    } = Fixture::new()?;
    let context = PreparedProcessContext::prepare(
        base.as_handle(),
        filesystem,
        DesktopCapability::create()?,
        /*logs_base_dir*/ None,
    )?;
    change_fixture_acl(&workspace)?;
    let error = match context.into_parts() {
        Ok(_) => anyhow::bail!("changed root descriptor passed the one-use handoff"),
        Err(error) => error,
    };
    assert!(
        error
            .to_string()
            .contains("prepared root identity or descriptor changed")
    );
    std::fs::rename(&workspace, tree.path().join("moved-after-handoff-refusal"))?;
    Ok(())
}
