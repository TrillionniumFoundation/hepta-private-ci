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
use std::io;

type Result<T = ()> = std::result::Result<T, Box<dyn Error>>;

#[test]
fn actual_new_directory_has_exact_protected_owner_dacl_on_original_handle() -> Result {
    let fixture = Fixture::new()?;
    let mut directory =
        ParentAnchor::for_create_only(&fixture.0)?.create_private_directory("private")?;
    directory.revalidate()?;
    let observed = validate_owner_descriptor(
        &directory.created.file,
        &CurrentUser::capture_effective()?,
        ObjectKind::Directory,
    )?;
    assert_eq!(observed.identity, directory.identity);
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
