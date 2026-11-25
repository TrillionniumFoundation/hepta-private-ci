use std::ffi::OsString;
use std::path::Path;
use std::time::SystemTime;

use pretty_assertions::assert_eq;

use super::lock_existing_sidecar;
use super::lock_sidecar;
use super::write_private_atomic_replace;
use super::write_private_new;
use crate::AcceptanceError;

#[derive(Debug, Eq, PartialEq)]
struct FileSnapshot {
    name: OsString,
    bytes: Vec<u8>,
    created: SystemTime,
    modified: SystemTime,
    readonly: bool,
}

#[derive(Debug, Eq, PartialEq)]
struct DirectorySnapshot {
    created: SystemTime,
    modified: SystemTime,
    files: Vec<FileSnapshot>,
}

impl DirectorySnapshot {
    fn capture(root: &Path) -> std::io::Result<Self> {
        let metadata = std::fs::metadata(root)?;
        let mut files = Vec::new();
        for entry in std::fs::read_dir(root)? {
            let entry = entry?;
            let metadata = entry.metadata()?;
            files.push(FileSnapshot {
                name: entry.file_name(),
                bytes: std::fs::read(entry.path())?,
                created: metadata.created()?,
                modified: metadata.modified()?,
                readonly: metadata.permissions().readonly(),
            });
        }
        files.sort_by(|left, right| left.name.cmp(&right.name));
        Ok(Self {
            created: metadata.created()?,
            modified: metadata.modified()?,
            files,
        })
    }
}

#[test]
fn private_create_refuses_before_creating_a_file() -> std::io::Result<()> {
    let temporary = tempfile::tempdir()?;
    let root = temporary.path();
    std::fs::write(root.join("sentinel"), b"unchanged")?;
    let before = DirectorySnapshot::capture(root)?;

    assert!(matches!(
        write_private_new(&root.join("target"), b"candidate"),
        Err(AcceptanceError::UnsupportedPrivateDirectoryOwner)
    ));
    assert_eq!(DirectorySnapshot::capture(root)?, before);
    Ok(())
}

#[test]
fn atomic_replace_preserves_target_and_does_not_create_temporary() -> std::io::Result<()> {
    let temporary = tempfile::tempdir()?;
    let root = temporary.path();
    let target = root.join("target");
    std::fs::write(&target, b"original")?;
    std::fs::write(root.join("sentinel"), b"unchanged")?;
    let before = DirectorySnapshot::capture(root)?;

    assert!(matches!(
        write_private_atomic_replace(&target, &root.join("target.next"), b"replacement"),
        Err(AcceptanceError::UnsupportedPrivateDirectoryOwner)
    ));
    assert_eq!(DirectorySnapshot::capture(root)?, before);
    Ok(())
}

#[test]
fn new_sidecar_lock_refuses_before_creating_a_lock_file() -> std::io::Result<()> {
    let temporary = tempfile::tempdir()?;
    let root = temporary.path();
    std::fs::write(root.join("sentinel"), b"unchanged")?;
    let before = DirectorySnapshot::capture(root)?;

    assert!(matches!(
        lock_sidecar(root),
        Err(AcceptanceError::UnsupportedPrivateDirectoryOwner)
    ));
    assert_eq!(DirectorySnapshot::capture(root)?, before);
    Ok(())
}

#[test]
fn existing_sidecar_lock_refuses_without_changing_the_directory() -> std::io::Result<()> {
    let temporary = tempfile::tempdir()?;
    let root = temporary.path();
    std::fs::write(root.join(".operator-acceptance.lock"), b"existing lock")?;
    let before = DirectorySnapshot::capture(root)?;

    assert!(matches!(
        lock_existing_sidecar(root),
        Err(AcceptanceError::UnsupportedPrivateDirectoryOwner)
    ));
    assert_eq!(DirectorySnapshot::capture(root)?, before);
    Ok(())
}
