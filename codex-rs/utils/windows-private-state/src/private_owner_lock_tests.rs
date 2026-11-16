use super::OwnerLockError;
use crate::parent_anchor::ParentAnchor;
use crate::parent_anchor::tests::Fixture;
use crate::security::ValidationError;
use std::error::Error;
use std::fs::OpenOptions;
use std::os::windows::fs::OpenOptionsExt;
use std::sync::Arc;
use windows_sys::Win32::Storage::FileSystem::FILE_SHARE_READ;

type Result = std::result::Result<(), Box<dyn Error>>;

#[test]
fn actual_marker_sharing_error_is_rejection_not_state_locked_and_stays_refused() -> Result {
    let fixture = Fixture::new()?;
    let mut directory =
        ParentAnchor::for_create_only(&fixture.0)?.create_private_directory("private")?;
    drop(directory.lock_owner("state")?);
    let deny_write = OpenOptions::new()
        .read(true)
        .share_mode(FILE_SHARE_READ)
        .open(fixture.0.join("private/state"))?;
    assert!(matches!(directory.lock_owner("state"),
        Err(OwnerLockError::Rejected(ValidationError::Os(error))) if error.raw_os_error() == Some(32)));
    drop(deny_write);
    assert!(directory.revalidate().is_err());
    assert!(directory.lock_owner("state").is_err());
    Ok(())
}

#[test]
fn actual_owner_lock_refuses_shared_context_poison_without_recovery() -> Result {
    let fixture = Fixture::new()?;
    let mut directory =
        ParentAnchor::for_create_only(&fixture.0)?.create_private_directory("private")?;
    let mut owner = directory.lock_owner("state")?;
    let context = Arc::clone(&owner.context);
    assert!(
        std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
            let _held = context.lock().expect("initial unpoisoned owner");
            panic!("interrupted native owner");
        }))
        .is_err()
    );
    assert!(owner.revalidate().is_err());
    assert!(directory.revalidate().is_err());
    Ok(())
}
