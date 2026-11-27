use std::io;
use std::path::Path;
use std::process::Command;

use pretty_assertions::assert_eq;

use super::ParentPin;
use crate::AcceptanceError;
use crate::durable;
use crate::test_support::private_tempdir;

#[test]
fn private_sidecar_roundtrip_preserves_atomic_replace_and_refuses_duplicate()
-> Result<(), AcceptanceError> {
    let temporary = private_tempdir("private sidecar roundtrip");
    let root = temporary.path().canonicalize()?;
    let path = root.join("receipt");
    durable::write_private_new(&path, b"original")?;
    assert_eq!(durable::secure_read(&path, /*max_bytes*/ 64)?, b"original");
    assert!(matches!(
        durable::write_private_new(&path, b"unwanted"),
        Err(AcceptanceError::Io(error)) if error.kind() == io::ErrorKind::AlreadyExists
    ));
    assert_eq!(std::fs::read(&path)?, b"original");
    let candidate = root.join("receipt.next");
    durable::write_private_atomic_replace(&path, &candidate, b"replacement")?;
    assert_eq!(
        durable::secure_hash(&path)?,
        (durable::sha256(b"replacement"), 11)
    );
    assert!(!candidate.try_exists()?);
    Ok(())
}

#[test]
fn retained_parent_refuses_replacement_and_missing_parent_is_not_created()
-> Result<(), AcceptanceError> {
    let temporary = private_tempdir("private sidecar parent");
    let root = temporary.path().canonicalize()?;
    let moved = root.with_file_name("moved-private-parent");
    let pin = ParentPin::open(&root)?;
    assert!(std::fs::rename(&root, &moved).is_err());
    pin.revalidate()?;
    let missing = root.join("missing");
    assert!(matches!(
        durable::write_private_new(&missing.join("receipt"), b"original"),
        Err(AcceptanceError::Io(error)) if error.kind() == io::ErrorKind::NotFound
    ));
    assert!(!missing.try_exists()?);
    drop(pin);
    std::fs::rename(&root, &moved)?;
    std::fs::rename(&moved, &root)?;
    Ok(())
}

#[test]
fn sidecar_lock_is_exclusive_until_its_original_guard_drops() -> Result<(), AcceptanceError> {
    let temporary = private_tempdir("exclusive sidecar lock");
    let root = temporary.path().canonicalize()?;
    let lock_path = root.join(".operator-acceptance.lock");
    let first = durable::lock_sidecar(&root)?;
    let before = super::open_without_following(&lock_path)?;
    let identity = super::FileSnapshot::capture(&before, "original lock")?;
    assert!(durable::lock_sidecar(&root).is_err());
    assert!(durable::lock_existing_sidecar(&root).is_err());
    assert!(std::fs::rename(&lock_path, root.join("old.lock")).is_err());
    drop(first);
    let second = durable::lock_existing_sidecar(&root)?;
    super::verify_unchanged(&before, &lock_path, &identity, "original lock")?;
    drop(second);
    Ok(())
}

#[test]
fn foreign_acl_is_rejected_without_repair_or_partial_write() -> Result<(), AcceptanceError> {
    let temporary = private_tempdir("private sidecar ACL");
    let root = temporary.path().canonicalize()?;
    let path = root.join("receipt");
    durable::write_private_new(&path, b"original")?;
    grant_world_read(&path)?;
    let before_file = acl(&path)?;
    assert!(matches!(
        durable::secure_read(&path, /*max_bytes*/ 64),
        Err(AcceptanceError::Io(error)) if error.kind() == io::ErrorKind::PermissionDenied
    ));
    assert!(matches!(
        durable::secure_hash(&path),
        Err(AcceptanceError::Io(error)) if error.kind() == io::ErrorKind::PermissionDenied
    ));
    assert_eq!(acl(&path)?, before_file);
    grant_world_read(&root)?;
    let before_directory = acl(&root)?;
    let rejected = root.join("must-not-exist");
    assert!(matches!(
        durable::write_private_new(&rejected, b"unwanted"),
        Err(AcceptanceError::Io(error)) if error.kind() == io::ErrorKind::PermissionDenied
    ));
    assert!(!rejected.try_exists()?);
    assert_eq!(acl(&root)?, before_directory);
    assert_eq!(std::fs::read(&path)?, b"original");
    Ok(())
}

fn grant_world_read(path: &Path) -> Result<(), AcceptanceError> {
    // This changes only a freshly owned attack fixture, using a numeric SID.
    let output = Command::new("icacls.exe")
        .arg(path)
        .args(["/grant", "*S-1-1-0:R", "/q"])
        .output()?;
    if !output.status.success() {
        return Err(AcceptanceError::Invalid(format!(
            "native ACL fixture failed: {}",
            String::from_utf8_lossy(&output.stderr)
        )));
    }
    Ok(())
}

fn acl(path: &Path) -> Result<Vec<u8>, AcceptanceError> {
    let output = Command::new("icacls.exe").arg(path).output()?;
    if !output.status.success() {
        return Err(AcceptanceError::Invalid(
            "native ACL observation failed".to_string(),
        ));
    }
    Ok(output.stdout)
}
