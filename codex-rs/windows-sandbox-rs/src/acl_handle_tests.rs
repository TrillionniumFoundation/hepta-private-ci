use super::DenyAceKind;
use super::DenyAceScope;
use super::add_deny_write_ace_to_file;
use super::dacl_mask_allows;
use super::ensure_allow_write_aces;
use super::fetch_dacl_handle;
use crate::token::LocalSid;
use anyhow::Result;
use pretty_assertions::assert_eq;
use std::fs;
use std::fs::OpenOptions;
use std::os::windows::fs::OpenOptionsExt;
use windows_sys::Win32::Foundation::HLOCAL;
use windows_sys::Win32::Foundation::LocalFree;
use windows_sys::Win32::Storage::FileSystem::FILE_FLAG_BACKUP_SEMANTICS;
use windows_sys::Win32::Storage::FileSystem::FILE_GENERIC_WRITE;
use windows_sys::Win32::Storage::FileSystem::READ_CONTROL;

#[test]
fn retained_deny_update_changes_only_the_original_file_object() -> Result<()> {
    let fixture = tempfile::tempdir()?;
    let original_name = fixture.path().join("protected.txt");
    let retained_name = fixture.path().join("retained.txt");
    fs::write(&original_name, "retained")?;
    let retained = OpenOptions::new()
        .access_mode(READ_CONTROL)
        .open(&original_name)?;
    fs::rename(&original_name, &retained_name)?;
    fs::write(&original_name, "replacement")?;
    let sid = LocalSid::from_string("S-1-5-21-173-281-397-419")?;
    // SAFETY: the descriptor operation is bound to the retained handle; the
    // pathname is only an error label and intentionally names a different file.
    assert!(unsafe { add_deny_write_ace_to_file(&original_name, &retained, sid.as_ptr())? });
    let mut observed = Vec::new();
    for path in [&retained_name, &original_name] {
        // SAFETY: the live descriptor owns the DACL through the recognizer call.
        let present = unsafe {
            let (dacl, descriptor) = fetch_dacl_handle(path)?;
            let present =
                DenyAceKind::Write.already_present(dacl, sid.as_ptr(), DenyAceScope::File);
            LocalFree(descriptor as HLOCAL);
            present
        };
        observed.push((fs::read_to_string(path)?, present));
    }
    assert_eq!(
        observed,
        vec![
            ("retained".to_owned(), true),
            ("replacement".to_owned(), false)
        ]
    );
    Ok(())
}

#[test]
fn retained_deny_update_changes_only_the_original_directory_object() -> Result<()> {
    let fixture = tempfile::tempdir()?;
    let original_name = fixture.path().join("protected");
    let retained_name = fixture.path().join("retained");
    fs::create_dir(&original_name)?;
    fs::write(original_name.join("marker.txt"), "retained")?;
    let retained = OpenOptions::new()
        .access_mode(READ_CONTROL)
        .custom_flags(FILE_FLAG_BACKUP_SEMANTICS)
        .open(&original_name)?;
    fs::rename(&original_name, &retained_name)?;
    fs::create_dir(&original_name)?;
    fs::write(original_name.join("marker.txt"), "replacement")?;
    let sid = LocalSid::from_string("S-1-5-21-173-281-397-423")?;
    // The retained directory has been renamed, and the diagnostic pathname now
    // names another object. The ACL change must still affect only the original.
    assert!(unsafe { add_deny_write_ace_to_file(&original_name, &retained, sid.as_ptr())? });
    let mut observed = Vec::new();
    for path in [&retained_name, &original_name] {
        let present = unsafe {
            let (dacl, descriptor) = fetch_dacl_handle(path)?;
            let present =
                DenyAceKind::Write.already_present(dacl, sid.as_ptr(), DenyAceScope::Directory);
            LocalFree(descriptor as HLOCAL);
            present
        };
        observed.push((fs::read_to_string(path.join("marker.txt"))?, present));
    }
    assert_eq!(
        observed,
        vec![
            ("retained".to_owned(), true),
            ("replacement".to_owned(), false)
        ]
    );
    Ok(())
}

#[test]
fn grant_rejects_a_reparse_target_and_ancestor_without_changing_the_destination() -> Result<()> {
    let fixture = tempfile::tempdir()?;
    let destination = fixture.path().join("destination");
    let alias = fixture.path().join("alias");
    fs::create_dir(&destination)?;
    let child = destination.join("child.txt");
    fs::write(&child, "unchanged")?;
    std::os::windows::fs::symlink_dir(&destination, &alias)?;
    let sid = LocalSid::from_string("S-1-5-21-173-281-397-421")?;
    for path in [&alias, &alias.join("child.txt")] {
        // Only this fixture's inert capability SID is used in a normal grant.
        assert!(unsafe { ensure_allow_write_aces(path, &[sid.as_ptr()]) }.is_err());
    }
    let mut granted = Vec::new();
    for path in [&destination, &child] {
        let present = unsafe {
            let (dacl, descriptor) = fetch_dacl_handle(path)?;
            let present = dacl_mask_allows(
                dacl,
                &[sid.as_ptr()],
                FILE_GENERIC_WRITE,
                /*require_all_bits*/ false,
            );
            LocalFree(descriptor as HLOCAL);
            present
        };
        granted.push(present);
    }
    assert_eq!(granted, vec![false, false]);
    assert_eq!(fs::read_to_string(&child)?, "unchanged");
    Ok(())
}
