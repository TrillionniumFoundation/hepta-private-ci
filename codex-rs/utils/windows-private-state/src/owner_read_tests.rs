use super::OwnerLock;
use crate::mechanism;
use crate::parent_anchor::ParentAnchor;
use crate::parent_anchor::tests::Fixture;
use crate::parent_anchor::tests::set_fixture_dacl;
use crate::protected_descriptor::ProtectedDescriptor;
use std::error::Error;
use std::fs;
use std::io::Write;

type Result<T = ()> = std::result::Result<T, Box<dyn Error>>;

fn input(owner: &OwnerLock, bytes: &[u8]) -> Result {
    let mut held = owner
        .context
        .lock()
        .map_err(|_| std::io::Error::other("poison"))?;
    owner.validate_locked(&mut held)?;
    let descriptor = ProtectedDescriptor::for_user(held.directory.parent.owner.current_user()?)?;
    let mut file =
        mechanism::create_protected_file(&held.directory.file, "input", &descriptor, |_| {})?;
    file.write_all(bytes)?;
    file.sync_all()?;
    Ok(())
}

#[test]
fn actual_locked_read_keeps_ancestry_alive_and_missing_is_only_observation() -> Result {
    let fixture = Fixture::new()?;
    let mut directory =
        ParentAnchor::for_create_only(&fixture.0)?.create_private_directory("private")?;
    let owner = directory.lock_owner("authority.lock")?;
    input(&owner, b"original-state")?;
    drop(directory);
    assert!(!owner.entry_exists("missing")?);
    assert!(!fixture.0.join("private/missing").exists());
    assert!(owner.entry_exists("input")?);
    assert_eq!(owner.read_bounded("input", 14)?, b"original-state");
    Ok(())
}

#[test]
fn actual_locked_read_size_error_fences_later_larger_read_without_reset() -> Result {
    let fixture = Fixture::new()?;
    let mut directory =
        ParentAnchor::for_create_only(&fixture.0)?.create_private_directory("private")?;
    let owner = directory.lock_owner("authority.lock")?;
    input(&owner, b"original-state")?;
    assert!(owner.read_bounded("input", 13).is_err());
    assert!(owner.read_bounded("input", 14).is_err());
    assert_eq!(
        fs::read(fixture.0.join("private/input"))?,
        b"original-state"
    );
    Ok(())
}

#[test]
fn actual_locked_read_descriptor_change_is_not_absence_or_repairable() -> Result {
    let fixture = Fixture::new()?;
    let mut directory =
        ParentAnchor::for_create_only(&fixture.0)?.create_private_directory("private")?;
    let owner = directory.lock_owner("authority.lock")?;
    input(&owner, b"original-state")?;
    set_fixture_dacl(&fixture.0.join("private/input"), "(A;;FR;;;WD)")?;
    assert!(owner.entry_exists("input").is_err());
    set_fixture_dacl(&fixture.0.join("private/input"), "")?;
    assert!(owner.read_bounded("input", 14).is_err());
    assert_eq!(
        fs::read(fixture.0.join("private/input"))?,
        b"original-state"
    );
    Ok(())
}

#[test]
fn actual_locked_read_rejects_real_hardlink_without_adopting_it() -> Result {
    let fixture = Fixture::new()?;
    let mut directory =
        ParentAnchor::for_create_only(&fixture.0)?.create_private_directory("private")?;
    let owner = directory.lock_owner("authority.lock")?;
    input(&owner, b"original-state")?;
    fs::hard_link(
        fixture.0.join("private/input"),
        fixture.0.join("private/state"),
    )?;
    assert!(owner.entry_exists("input").is_err());
    assert!(owner.read_bounded("input", 14).is_err());
    assert_eq!(
        fs::read(fixture.0.join("private/state"))?,
        b"original-state"
    );
    Ok(())
}
