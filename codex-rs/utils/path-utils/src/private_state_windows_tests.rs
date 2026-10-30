use super::PrivateStateDirectory;
use super::StateFileAccess;
use pretty_assertions::assert_eq;
use std::io;
use std::io::Read;
use std::io::Write;
use std::os::windows::io::AsRawHandle;
use std::path::PathBuf;
use std::ptr;
use tempfile::TempDir;
use windows_sys::Win32::Foundation::HANDLE;
use windows_sys::Win32::Security::Authorization::SE_FILE_OBJECT;
use windows_sys::Win32::Security::Authorization::SetSecurityInfo;
use windows_sys::Win32::Security::DACL_SECURITY_INFORMATION;
use windows_sys::Win32::Security::PROTECTED_DACL_SECURITY_INFORMATION;

fn fixture() -> io::Result<(TempDir, PathBuf, PrivateStateDirectory)> {
    let temporary = tempfile::tempdir()?;
    let path = temporary.path().join("owner");
    let directory = PrivateStateDirectory::open_or_create(&path)?;
    Ok((temporary, path, directory))
}

#[test]
fn publish_flush_and_reopen_preserve_exact_bytes() -> io::Result<()> {
    let (_temporary, path, directory) = fixture()?;
    for contents in [
        b"first".as_slice(),
        b"replacement with a longer payload".as_slice(),
    ] {
        let mut staging = directory.open_file("state.next", StateFileAccess::Create)?;
        staging.set_len(0)?;
        staging.write_all(contents)?;
        staging.sync_all()?;
        directory.replace_file("state.next", "state.json")?;
        directory.sync_all()?;
        let mut recovered = Vec::new();
        directory
            .open_file("state.json", StateFileAccess::Read)?
            .read_to_end(&mut recovered)?;
        assert_eq!(recovered, contents);
        assert!(!directory.entry_exists("state.next")?);
    }
    drop(directory);
    let reopened = PrivateStateDirectory::open_or_create(&path)?;
    let mut recovered = String::new();
    reopened
        .open_file("state.json", StateFileAccess::Read)?
        .read_to_string(&mut recovered)?;
    assert_eq!(recovered, "replacement with a longer payload");
    Ok(())
}

#[test]
fn exclusive_owner_lock_is_observed_across_directory_handles() -> io::Result<()> {
    let (_temporary, path, directory) = fixture()?;
    let first = directory.open_file("owner.lock", StateFileAccess::Create)?;
    first.try_lock().expect("first owner locks state");
    let other_directory = PrivateStateDirectory::open_or_create(&path)?;
    let second = other_directory.open_file("owner.lock", StateFileAccess::Create)?;
    assert!(second.try_lock().is_err());
    drop(first);
    second.try_lock().expect("released owner permits recovery");
    Ok(())
}

#[test]
fn open_root_cannot_be_renamed_or_rebound() -> io::Result<()> {
    let (temporary, path, directory) = fixture()?;
    let replacement = temporary.path().join("moved");
    assert!(std::fs::rename(&path, &replacement).is_err());
    let mut file = directory.open_file("state.json", StateFileAccess::Create)?;
    file.write_all(b"pinned")?;
    drop(file);
    drop(directory);
    std::fs::rename(path, &replacement)?;
    let reopened = PrivateStateDirectory::open_or_create(&replacement)?;
    assert!(reopened.entry_exists("state.json")?);
    Ok(())
}

#[test]
fn hard_links_and_non_component_names_are_rejected() -> io::Result<()> {
    let (_temporary, path, directory) = fixture()?;
    drop(directory.open_file("state.json", StateFileAccess::Create)?);
    std::fs::hard_link(path.join("state.json"), path.join("alias"))?;
    for name in ["state.json", "alias"] {
        assert_eq!(
            directory
                .open_file(name, StateFileAccess::Read)
                .expect_err("hard-linked state must not be admitted")
                .kind(),
            io::ErrorKind::PermissionDenied
        );
    }
    for name in [
        "",
        ".",
        "..",
        "../outside",
        "state:alternate",
        "child\\state",
    ] {
        assert_eq!(
            directory
                .open_file(name, StateFileAccess::Create)
                .expect_err("only one bounded component is legal")
                .kind(),
            io::ErrorKind::InvalidInput
        );
    }
    Ok(())
}

#[test]
fn existing_permissive_acl_is_rejected_without_repair() -> io::Result<()> {
    let (_temporary, path, directory) = fixture()?;
    // A null DACL grants everyone access. Mutate only this test-owned object;
    // opening it afterward must refuse it rather than silently repairing it.
    let status = unsafe {
        // SAFETY: The live fixture handle grants WRITE_DAC. Null SID/DACL inputs
        // have the documented SetSecurityInfo meaning; no pointer is borrowed.
        SetSecurityInfo(
            directory.file.as_raw_handle() as HANDLE,
            SE_FILE_OBJECT,
            DACL_SECURITY_INFORMATION | PROTECTED_DACL_SECURITY_INFORMATION,
            ptr::null_mut(),
            ptr::null_mut(),
            ptr::null_mut(),
            ptr::null_mut(),
        )
    };
    assert_eq!(status, 0);
    assert_eq!(
        directory
            .open_file("state.json", StateFileAccess::Create)
            .expect_err("changed owner ACL must fence further writes")
            .kind(),
        io::ErrorKind::PermissionDenied
    );
    drop(directory);
    assert_eq!(
        PrivateStateDirectory::open_or_create(&path)
            .expect_err("unsafe existing directory must stay rejected")
            .kind(),
        io::ErrorKind::PermissionDenied
    );
    Ok(())
}

#[test]
fn directory_junctions_are_rejected_at_final_and_intermediate_components() -> io::Result<()> {
    let (temporary, path, directory) = fixture()?;
    let junction = temporary.path().join("junction");
    let result = std::process::Command::new("cmd.exe")
        .args(["/d", "/c", "mklink", "/J"])
        .arg(&junction)
        .arg(&path)
        .output()?;
    assert!(result.status.success(), "junction fixture: {result:?}");
    assert!(PrivateStateDirectory::open_or_create(&junction).is_err());
    assert!(PrivateStateDirectory::open_or_create(&junction.join("nested")).is_err());
    assert!(!path.join("nested").exists());
    std::fs::remove_dir(&junction)?;
    drop(directory);
    Ok(())
}
