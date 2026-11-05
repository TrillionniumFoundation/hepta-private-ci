use std::io;
use std::path::Path;
use std::process::Command;

use pretty_assertions::assert_eq;

use crate::QualificationError;
use crate::durable;

#[test]
fn private_artifact_flush_and_bounded_read_preserve_original_bytes()
-> Result<(), QualificationError> {
    let temp = tempfile::tempdir()?;
    let root = temp.path().join("private");
    let artifact = root.join("receipt");
    let original = b"original evidence";
    durable::create_private_directory(&root)?;
    durable::write_private_new(&artifact, original)?;
    durable::sync_directory(&root)?;
    durable::verify_private_tree(&root)?;
    assert_eq!(
        durable::read_private_bounded(&artifact, original.len())?,
        original
    );
    assert!(matches!(
        durable::read_private_bounded(&artifact, original.len() - 1),
        Err(QualificationError::Invalid(message))
            if message == "private artifact exceeds its read bound"
    ));
    assert!(matches!(
        durable::write_private_new(&artifact, b"replacement"),
        Err(QualificationError::Io(error)) if error.kind() == io::ErrorKind::AlreadyExists
    ));
    assert_eq!(std::fs::read(&artifact)?, original);
    Ok(())
}

#[test]
fn private_readback_never_initializes_missing_state() -> Result<(), QualificationError> {
    let temp = tempfile::tempdir()?;
    let missing = temp.path().join("missing");
    assert!(matches!(
        durable::verify_private_directory(&missing),
        Err(QualificationError::Io(error)) if error.kind() == io::ErrorKind::NotFound
    ));
    assert!(matches!(
        durable::read_private_bounded(&missing.join("receipt"), 16),
        Err(QualificationError::Io(error)) if error.kind() == io::ErrorKind::NotFound
    ));
    assert!(matches!(
        durable::sync_directory(&missing),
        Err(QualificationError::Io(error)) if error.kind() == io::ErrorKind::NotFound
    ));
    assert!(!missing.try_exists()?);
    Ok(())
}

#[test]
fn private_artifacts_reject_native_hard_links() -> Result<(), QualificationError> {
    let temp = tempfile::tempdir()?;
    let root = temp.path().join("private");
    let artifact = root.join("receipt");
    let alias = root.join("alias");
    durable::create_private_directory(&root)?;
    durable::write_private_new(&artifact, b"original")?;
    std::fs::hard_link(&artifact, &alias)?;
    assert!(matches!(
        durable::verify_private_regular(&artifact),
        Err(QualificationError::Io(error)) if error.kind() == io::ErrorKind::PermissionDenied
    ));
    assert!(matches!(
        durable::read_private_bounded(&artifact, 16),
        Err(QualificationError::Io(error)) if error.kind() == io::ErrorKind::PermissionDenied
    ));
    std::fs::remove_file(alias)?;
    durable::verify_private_regular(&artifact)?;
    assert_eq!(durable::read_private_bounded(&artifact, 16)?, b"original");
    Ok(())
}

#[test]
fn private_artifacts_reject_foreign_acl_without_repair() -> Result<(), QualificationError> {
    let temp = tempfile::tempdir()?;
    let root = temp.path().join("private");
    let artifact = root.join("receipt");
    durable::create_private_directory(&root)?;
    durable::write_private_new(&artifact, b"original")?;
    grant_world_read(&artifact)?;
    assert!(matches!(
        durable::verify_private_regular(&artifact),
        Err(QualificationError::Io(error)) if error.kind() == io::ErrorKind::PermissionDenied
    ));
    assert!(matches!(
        durable::read_private_bounded(&artifact, 16),
        Err(QualificationError::Io(error)) if error.kind() == io::ErrorKind::PermissionDenied
    ));
    assert!(matches!(
        durable::verify_private_tree(&root),
        Err(QualificationError::Io(error)) if error.kind() == io::ErrorKind::PermissionDenied
    ));
    grant_world_read(&root)?;
    assert!(matches!(
        durable::create_or_verify_private_directory(&root),
        Err(QualificationError::Io(error)) if error.kind() == io::ErrorKind::PermissionDenied
    ));
    assert_eq!(std::fs::read(&artifact)?, b"original");
    Ok(())
}

fn grant_world_read(path: &Path) -> Result<(), QualificationError> {
    // Native fixture mutation on this test's private object only. Numeric SID
    // syntax is independent of the runner's language and account names.
    let result = Command::new("icacls.exe")
        .arg(path)
        .args(["/grant", "*S-1-1-0:R", "/q"])
        .output()?;
    if !result.status.success() {
        return Err(QualificationError::State(format!(
            "native ACL fixture failed: {}",
            String::from_utf8_lossy(&result.stderr)
        )));
    }
    Ok(())
}
