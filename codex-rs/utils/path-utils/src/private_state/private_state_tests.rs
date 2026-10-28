use super::Access;
use super::entry_exists;
use super::open_private;
use super::prepare_directory;
use super::replace;
use super::security::Descriptor;
use super::wide_path;
use pretty_assertions::assert_eq;
use std::fs;
use std::io;
use std::io::Read;
use std::io::Write;
use std::path::Path;
use std::process::Command;
use std::ptr;
use windows_sys::Win32::Security::Authorization::SE_FILE_OBJECT;
use windows_sys::Win32::Security::Authorization::SetNamedSecurityInfoW;
use windows_sys::Win32::Security::DACL_SECURITY_INFORMATION;
use windows_sys::Win32::Security::GetSecurityDescriptorDacl;
use windows_sys::Win32::Security::PROTECTED_DACL_SECURITY_INFORMATION;

#[test]
fn replacement_reopens_exact_bytes_and_preserves_predecessor_on_failure() -> io::Result<()> {
    let temp = tempfile::tempdir()?;
    let root = temp.path().join("private");
    let directory = prepare_directory(&root)?;
    let mut next = open_private(&directory, "state.next", Access::Create)?;
    next.write_all(b"first durable generation")?;
    next.sync_all()?;
    replace(&directory, "state.next", "state.json")?;
    directory.sync_all()?;
    drop(next);
    assert!(!entry_exists(&directory, "state.next")?);
    assert!(entry_exists(&directory, "state.json")?);
    let before = fs::read(root.join("state.json"))?;
    assert!(replace(&directory, "absent.next", "state.json").is_err());
    assert_eq!(fs::read(root.join("state.json"))?, before);

    let mut next = open_private(&directory, "state.next", Access::Create)?;
    next.write_all(b"second")?;
    next.sync_all()?;
    replace(&directory, "state.next", "state.json")?;
    directory.sync_all()?;
    drop(next);
    drop(directory);
    let reopened = prepare_directory(&root)?;
    let mut state = open_private(&reopened, "state.json", Access::Read)?;
    let mut bytes = Vec::new();
    state.read_to_end(&mut bytes)?;
    assert_eq!(bytes, b"second");
    Ok(())
}

#[test]
fn pinned_directory_survives_path_replacement_without_redirecting_writes() -> io::Result<()> {
    let temp = tempfile::tempdir()?;
    let root = temp.path().join("private");
    let moved = temp.path().join("moved");
    let pinned = prepare_directory(&root)?;
    fs::rename(&root, &moved)?;
    let substitute = prepare_directory(&root)?;
    let mut file = open_private(&pinned, "state.next", Access::Create)?;
    file.write_all(b"original directory identity")?;
    file.sync_all()?;
    replace(&pinned, "state.next", "state.json")?;
    pinned.sync_all()?;
    assert_eq!(
        fs::read(moved.join("state.json"))?,
        b"original directory identity"
    );
    assert!(!entry_exists(&substitute, "state.json")?);
    Ok(())
}

#[test]
fn exclusive_owner_lock_contends_and_releases() -> io::Result<()> {
    let temp = tempfile::tempdir()?;
    let directory = prepare_directory(&temp.path().join("private"))?;
    let first = open_private(&directory, "owner.lock", Access::Create)?;
    let second = open_private(&directory, "owner.lock", Access::Create)?;
    first.try_lock().map_err(io::Error::from)?;
    assert!(second.try_lock().is_err());
    drop(first);
    second.try_lock().map_err(io::Error::from)?;
    Ok(())
}

#[test]
fn hard_links_are_rejected_without_truncating_the_external_name() -> io::Result<()> {
    let temp = tempfile::tempdir()?;
    let root = temp.path().join("private");
    let directory = prepare_directory(&root)?;
    let mut state = open_private(&directory, "state.next", Access::Create)?;
    state.write_all(b"must remain unchanged")?;
    state.sync_all()?;
    drop(state);
    let external = temp.path().join("external");
    fs::hard_link(root.join("state.next"), &external)?;
    assert!(open_private(&directory, "state.next", Access::Create).is_err());
    assert!(entry_exists(&directory, "state.next").is_err());
    assert!(replace(&directory, "state.next", "state.json").is_err());
    assert_eq!(fs::read(external)?, b"must remain unchanged");
    Ok(())
}

#[test]
fn path_traversal_and_alternate_streams_never_create_entries() -> io::Result<()> {
    let temp = tempfile::tempdir()?;
    let root = temp.path().join("private");
    let directory = prepare_directory(&root)?;
    for name in [
        "",
        ".",
        "..",
        "../escape",
        "\\escape",
        "C:escape",
        "data:stream",
        "data.",
        "data ",
    ] {
        assert!(
            open_private(&directory, name, Access::Create).is_err(),
            "{name:?}"
        );
        assert!(entry_exists(&directory, name).is_err(), "{name:?}");
    }
    assert_eq!(fs::read_dir(root)?.count(), 0);
    Ok(())
}

#[test]
fn permissive_or_null_dacl_is_rejected_without_repair_or_data_loss() -> io::Result<()> {
    let temp = tempfile::tempdir()?;
    let root = temp.path().join("private");
    let directory = prepare_directory(&root)?;
    for (name, sddl) in [
        ("world.json", "D:P(A;;FA;;;WD)"),
        ("null.json", "D:NO_ACCESS_CONTROL"),
    ] {
        let mut file = open_private(&directory, name, Access::Create)?;
        file.write_all(b"unmodified")?;
        file.sync_all()?;
        drop(file);
        set_dacl(&root.join(name), sddl)?;
        assert!(open_private(&directory, name, Access::Create).is_err());
        assert!(entry_exists(&directory, name).is_err());
        assert_eq!(fs::read(root.join(name))?, b"unmodified");
        // A second refusal ensures the first call did not silently repair ACLs.
        assert!(open_private(&directory, name, Access::Read).is_err());
    }
    set_dacl(&root, "D:P(A;;FA;;;WD)")?;
    assert!(prepare_directory(&root).is_err());
    assert!(open_private(&directory, "new.json", Access::Create).is_err());
    assert!(!root.join("new.json").exists());
    Ok(())
}

#[test]
fn default_directory_acl_and_foreign_owner_descriptors_fail_closed() -> io::Result<()> {
    let temp = tempfile::tempdir()?;
    let root = temp.path().join("inherited");
    fs::create_dir(&root)?;
    assert!(prepare_directory(&root).is_err());
    // Everyone is never a token user SID. This exercises the same validator
    // used on GetSecurityInfo output without requiring takeover privileges.
    let foreign = Descriptor::from_sddl("O:WDD:P(A;;FA;;;WD)")?;
    assert!(foreign.validate_current_user().is_err());
    Descriptor::current_user()?.validate_current_user()?;
    Ok(())
}

#[test]
fn junctions_are_rejected_at_the_root_and_under_the_pinned_handle() -> io::Result<()> {
    let temp = tempfile::tempdir()?;
    let target = temp.path().join("target");
    let _target = prepare_directory(&target)?;
    let root = temp.path().join("private");
    let directory = prepare_directory(&root)?;
    let link = root.join("redirect");
    // Directory junctions require no symlink privilege or developer mode.
    let output = Command::new("cmd.exe")
        .args(["/d", "/c", "mklink", "/J"])
        .arg(&link)
        .arg(&target)
        .output()?;
    assert!(output.status.success(), "junction creation: {output:?}");
    assert!(prepare_directory(&link).is_err());
    assert!(open_private(&directory, "redirect", Access::Create).is_err());
    assert!(entry_exists(&directory, "redirect").is_err());
    Ok(())
}

fn set_dacl(path: &Path, sddl: &str) -> io::Result<()> {
    let descriptor = Descriptor::from_sddl(sddl)?;
    let mut dacl = ptr::null_mut();
    let mut present = 0;
    let mut defaulted = 0;
    // SAFETY: descriptor owns the output ACL for the duration of both calls.
    if unsafe {
        GetSecurityDescriptorDacl(descriptor.as_ptr(), &mut present, &mut dacl, &mut defaulted)
    } == 0
    {
        return Err(io::Error::last_os_error());
    }
    let path = wide_path(path)?;
    // SAFETY: path is NUL terminated and the live descriptor owns `dacl`. Tests
    // deliberately change only this temporary object's DACL, never its owner.
    let status = unsafe {
        SetNamedSecurityInfoW(
            path.as_ptr(),
            SE_FILE_OBJECT,
            DACL_SECURITY_INFORMATION | PROTECTED_DACL_SECURITY_INFORMATION,
            ptr::null_mut(),
            ptr::null_mut(),
            dacl,
            ptr::null(),
        )
    };
    if status != 0 {
        return Err(io::Error::from_raw_os_error(status as i32));
    }
    Ok(())
}

#[test]
fn configured_refs_volume_is_rejected_before_authoritative_writes() -> io::Result<()> {
    let Some(volume) = std::env::var_os("CODEX_TEST_REFS_VOLUME") else {
        eprintln!("ReFS runtime rejection was not exercised: CODEX_TEST_REFS_VOLUME is unset");
        return Ok(());
    };
    let temp = tempfile::tempdir_in(volume)?;
    let root = temp.path().join("private");
    let error = prepare_directory(&root).expect_err("ReFS cannot satisfy directory durability");
    assert_eq!(error.kind(), io::ErrorKind::PermissionDenied);
    assert_eq!(
        error.to_string(),
        "private durable state requires local NTFS"
    );
    assert_eq!(fs::read_dir(root)?.count(), 0);
    Ok(())
}
