use super::CreationFailure;
use super::ParentAnchor;
use crate::parent_anchor::tests::Fixture;
use crate::parent_anchor::tests::set_fixture_dacl;
use crate::security::CurrentUser;
use crate::security::ObjectKind;
use crate::security::ValidationError;
use crate::security::validate_owner_descriptor;
use std::error::Error;
use std::fs;
use std::fs::OpenOptions;
use std::io;
use std::io::Write;
use std::os::windows::fs::OpenOptionsExt;
use windows_sys::Win32::Storage::FileSystem::FILE_GENERIC_READ;
use windows_sys::Win32::Storage::FileSystem::FILE_GENERIC_WRITE;
use windows_sys::Win32::Storage::FileSystem::FILE_SHARE_READ;
use windows_sys::Win32::Storage::FileSystem::FILE_SHARE_WRITE;

type Result<T = ()> = std::result::Result<T, Box<dyn Error>>;

#[test]
fn actual_private_root_allows_compatible_second_owner_open_before_lock() -> Result {
    let fixture = Fixture::new()?;
    let directory =
        ParentAnchor::for_create_only(&fixture.0)?.create_private_directory("private")?;
    let second = OpenOptions::new()
        .read(true)
        .write(true)
        .share_mode(FILE_SHARE_READ | FILE_SHARE_WRITE)
        .custom_flags(0x0220_0000)
        .open(fixture.0.join("private"))?;
    assert_eq!(
        crate::mechanism::identity(&second)?,
        directory.lock_context()?.identity
    );
    Ok(()) // no DELETE request on either root; original OS lock is the next gate
}

#[test]
fn actual_directory_context_poison_never_recovers_into_success() -> Result {
    let fixture = Fixture::new()?;
    let mut directory =
        ParentAnchor::for_create_only(&fixture.0)?.create_private_directory("private")?;
    let context = std::sync::Arc::clone(&directory.context);
    let failure = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
        let _held = context.lock().expect("initially unpoisoned context");
        panic!("native directory owner interrupted while held");
    }));
    assert!(failure.is_err());
    assert!(directory.revalidate().is_err());
    assert!(directory.sync_all().is_err());
    assert!(directory.sync_parent_namespace().is_err());
    Ok(())
}

#[test]
fn actual_writable_directory_syncs_new_entry_without_noop_or_fallback() -> Result {
    let fixture = Fixture::new()?;
    let mut directory =
        ParentAnchor::for_create_only(&fixture.0)?.create_private_directory("private")?;
    let mut file = crate::mechanism::open_relative(
        &directory.lock_context()?.directory.file,
        "state",
        FILE_GENERIC_READ | FILE_GENERIC_WRITE,
        FILE_SHARE_READ | FILE_SHARE_WRITE,
        crate::mechanism::FILE_CREATE,
        |_| {},
    )?;
    file.write_all(b"native-entry-before-directory-flush")?;
    file.sync_all()?;
    drop(file);
    directory.sync_all()?;
    directory.sync_parent_namespace()?;
    assert_eq!(
        fs::read(fixture.0.join("private/state"))?,
        b"native-entry-before-directory-flush"
    );
    Ok(())
}

#[test]
fn actual_parent_write_sharing_conflict_is_not_retried_or_repaired() -> Result {
    let fixture = Fixture::new()?;
    let mut directory =
        ParentAnchor::for_create_only(&fixture.0)?.create_private_directory("private")?;
    let deny_write = OpenOptions::new()
        .read(true)
        .share_mode(FILE_SHARE_READ)
        .custom_flags(0x0220_0000)
        .open(&fixture.0)?;
    let result = directory.sync_parent_namespace();
    assert!(matches!(result, Err(ValidationError::Os(error)) if error.raw_os_error() == Some(32)));
    drop(deny_write);
    assert!(
        directory.revalidate().is_err(),
        "native flush failure is sticky"
    );
    Ok(())
}

#[test]
fn actual_parent_flush_uses_held_id_after_former_path_is_replaced() -> Result {
    // Mechanism fixture only: arbitrary Files here grant no parent/store authority.
    let fixture = Fixture::new()?;
    let original_path = fixture.0.join("private");
    fs::create_dir(&original_path)?;
    let original = OpenOptions::new()
        .read(true)
        .share_mode(FILE_SHARE_READ | FILE_SHARE_WRITE | 4)
        .custom_flags(0x0220_0000)
        .open(&original_path)?;
    let before = crate::mechanism::identity(&original)?;
    fs::rename(&original_path, fixture.0.join("moved"))?;
    fs::create_dir(&original_path)?;
    let replacement = OpenOptions::new()
        .read(true)
        .custom_flags(0x0220_0000)
        .open(&original_path)?;
    assert_ne!(crate::mechanism::identity(&replacement)?, before);
    crate::namespace_flush::flush_held_namespace(&original)?;
    assert_eq!(crate::mechanism::identity(&original)?, before);
    Ok(())
}

#[test]
fn actual_new_directory_has_exact_protected_owner_dacl_on_original_handle() -> Result {
    let fixture = Fixture::new()?;
    let mut directory =
        ParentAnchor::for_create_only(&fixture.0)?.create_private_directory("private")?;
    directory.revalidate()?;
    let context = directory.lock_context()?;
    let observed = validate_owner_descriptor(
        &context.directory.file,
        &CurrentUser::capture_effective()?,
        ObjectKind::Directory,
    )?;
    assert_eq!(observed.identity, context.identity);
    assert!(fixture.0.join("private").is_dir());
    Ok(())
}

#[test]
fn create_only_collision_never_adopts_or_overwrites_existing_state() -> Result {
    let fixture = Fixture::new()?;
    fs::create_dir(fixture.0.join("private"))?;
    fs::write(fixture.0.join("private/state"), b"must-not-reset")?;
    let result = ParentAnchor::for_create_only(&fixture.0)?.create_private_directory("private");
    assert!(
        matches!(result, Err(CreationFailure::NotAdmitted(ValidationError::Os(error)))
        if error.kind() == io::ErrorKind::AlreadyExists)
    );
    assert_eq!(
        fs::read(fixture.0.join("private/state"))?,
        b"must-not-reset"
    );
    Ok(())
}

#[test]
fn changed_child_descriptor_cannot_be_repaired_into_same_fresh_role() -> Result {
    let fixture = Fixture::new()?;
    let mut directory =
        ParentAnchor::for_create_only(&fixture.0)?.create_private_directory("private")?;
    set_fixture_dacl(&fixture.0.join("private"), "(A;;FR;;;WD)")?;
    assert!(directory.revalidate().is_err());
    set_fixture_dacl(&fixture.0.join("private"), "")?;
    assert!(directory.revalidate().is_err());
    Ok(())
}

#[test]
fn actual_cold_candidate_preserves_existing_bytes_and_shared_identity() -> Result {
    let fixture = Fixture::new()?;
    let directory =
        ParentAnchor::for_create_only(&fixture.0)?.create_private_directory("private")?;
    fs::write(fixture.0.join("private/state"), b"original-cold-state")?;
    let mut candidate =
        ParentAnchor::for_create_only(&fixture.0)?.open_existing_candidate("private")?;
    candidate.revalidate()?;
    assert_eq!(
        candidate
            .context
            .lock()
            .map_err(|_| io::Error::other("poison"))?
            .identity,
        directory.lock_context()?.identity
    );
    assert_eq!(
        fs::read(fixture.0.join("private/state"))?,
        b"original-cold-state"
    );
    Ok(())
}

#[test]
fn actual_cold_candidate_never_creates_missing_or_adopts_changed_dacl() -> Result {
    let fixture = Fixture::new()?;
    assert!(
        ParentAnchor::for_create_only(&fixture.0)?
            .open_existing_candidate("private")
            .is_err()
    );
    assert!(!fixture.0.join("private").exists());
    let _directory =
        ParentAnchor::for_create_only(&fixture.0)?.create_private_directory("private")?;
    let mut candidate =
        ParentAnchor::for_create_only(&fixture.0)?.open_existing_candidate("private")?;
    set_fixture_dacl(&fixture.0.join("private"), "(A;;FR;;;WD)")?;
    assert!(candidate.revalidate().is_err());
    assert!(
        ParentAnchor::for_create_only(&fixture.0)?
            .open_existing_candidate("private")
            .is_err()
    );
    set_fixture_dacl(&fixture.0.join("private"), "")?;
    assert!(candidate.revalidate().is_err());
    Ok(())
}
