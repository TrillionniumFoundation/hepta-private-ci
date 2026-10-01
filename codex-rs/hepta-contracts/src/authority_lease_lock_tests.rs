use super::*;
use std::os::unix::fs::PermissionsExt;

#[test]
fn owner_drop_releases_inherited_lock_and_preserves_successor()
-> Result<(), Box<dyn std::error::Error>> {
    let directory = tempfile::tempdir()?;
    std::fs::set_permissions(directory.path(), std::fs::Permissions::from_mode(0o700))?;
    #[cfg(target_os = "macos")]
    {
        // Only this newly owned fixture is normalized; production never strips ACLs.
        let status = std::process::Command::new("/bin/chmod")
            .arg("-N")
            .arg(directory.path())
            .status()?;
        if !status.success() {
            return Err(std::io::Error::other("clear fresh fixture ACL").into());
        }
    }
    let frontier = AuthorityLeaseFrontier::for_empty_epoch(7)?;
    let (owner, _) = Store::open(directory.path(), "owner", frontier)?;
    // Retain an alias of the actual store lock, without unlocking that alias.
    let inherited = owner._lock.try_clone()?;
    let competing = Store::open(directory.path(), "owner", frontier);
    assert!(
        matches!(&competing, Err(AuthorityLeaseError::StateLocked)),
        "live owner admission returned {:?}",
        competing.as_ref().err()
    );
    drop(owner);

    let wrong_owner = Store::open(directory.path(), "other-owner", frontier);
    assert!(
        matches!(&wrong_owner, Err(AuthorityLeaseError::InvalidTrust)),
        "post-drop wrong-owner admission returned {:?}",
        wrong_owner.as_ref().err()
    );
    let (successor, _) = Store::open(directory.path(), "owner", frontier)?;
    drop(inherited);
    let competing = Store::open(directory.path(), "owner", frontier);
    assert!(
        matches!(&competing, Err(AuthorityLeaseError::StateLocked)),
        "closing an old alias released the successor: {:?}",
        competing.as_ref().err()
    );
    drop(successor);
    Store::open(directory.path(), "owner", frontier)?;
    Ok(())
}
