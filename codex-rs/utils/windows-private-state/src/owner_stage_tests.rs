use super::StageReplaceError;
use crate::parent_anchor::ParentAnchor;
use crate::parent_anchor::tests::Fixture;
use std::error::Error;
use std::fs;
use std::io::Write;

type Result = std::result::Result<(), Box<dyn Error>>;

#[test]
fn actual_locked_stage_replaces_synced_original_without_path_reopen() -> Result {
    let fixture = Fixture::new()?;
    let mut directory =
        ParentAnchor::for_create_only(&fixture.0)?.create_private_directory("private")?;
    let owner = directory.lock_owner("authority.lock")?;
    let mut original = owner.create_private_file("state", 40)?;
    original.write_all(b"old-state")?;
    original.sync_all()?;
    drop(original);
    let mut stage = owner.create_state_stage("input", 40)?;
    stage.write_all(b"new-state")?;
    stage.sync_all()?;
    stage.replace_synced("state")?;
    assert!(stage.write_all(b"must-not-alter-published-state").is_err());
    assert!(stage.set_len(0).is_err());
    assert!(stage.replace_synced("input").is_err());
    drop(stage);
    owner.sync_all()?;
    assert!(!fixture.0.join("private/input").exists());
    assert_eq!(owner.read_bounded("state", 40)?, b"new-state");
    Ok(())
}

#[test]
fn actual_locked_stage_share_conflict_never_replaces_or_repairs_state() -> Result {
    let fixture = Fixture::new()?;
    let mut directory =
        ParentAnchor::for_create_only(&fixture.0)?.create_private_directory("private")?;
    let owner = directory.lock_owner("authority.lock")?;
    let mut original = owner.create_private_file("state", 40)?;
    original.write_all(b"old-state")?;
    original.sync_all()?;
    let mut stage = owner.create_state_stage("input", 40)?;
    stage.write_all(b"new-state")?;
    let result = stage.replace_synced("state");
    assert!(matches!(result, Err(StageReplaceError::Indeterminate(_))));
    drop(original);
    assert!(owner.sync_all().is_err(), "rename failure remains fenced");
    assert_eq!(fs::read(fixture.0.join("private/state"))?, b"old-state");
    assert_eq!(fs::read(fixture.0.join("private/input"))?, b"new-state");
    Ok(())
}
