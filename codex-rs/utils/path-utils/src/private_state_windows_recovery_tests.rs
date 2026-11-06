use super::*;
use crate::PrivateFileAccess;
use crate::open_private_state_child;
use crate::open_private_state_directory;
use pretty_assertions::assert_eq;
use std::io::Write;

#[test]
fn existing_only_directory_does_not_create_or_repair_a_missing_source() -> io::Result<()> {
    let temporary = tempfile::tempdir()?;
    let missing = temporary.path().join("missing");
    assert!(open_existing_private_state_directory(&missing).is_err());
    assert!(open_existing_private_state_directory_for_sync(&missing).is_err());
    assert!(!missing.exists());
    Ok(())
}

#[test]
fn frozen_private_child_retains_bytes_and_refuses_write_and_delete_handles() -> io::Result<()> {
    let temporary = tempfile::tempdir()?;
    let root = temporary.path().join("private");
    let directory = open_private_state_directory(&root)?;
    let mut source = open_private_state_child(&directory, "database", PrivateFileAccess::Create)?;
    source.write_all(b"retained bytes")?;
    source.sync_all()?;
    assert!(open_frozen_private_state_child(&directory, "database").is_err());
    drop(source);
    drop(directory);
    let directory = open_existing_private_state_directory(&root)?;
    let mut source = open_frozen_private_state_child(&directory, "database")?;
    let before = private_state_file_snapshot(&source)?;
    assert!(source.write_all(b"not writable").is_err());
    assert!(
        OpenOptions::new()
            .write(true)
            .open(root.join("database"))
            .is_err()
    );
    assert!(std::fs::remove_file(root.join("database")).is_err());
    assert!(std::fs::rename(root.join("database"), root.join("moved")).is_err());
    assert_eq!(std::fs::read(root.join("database"))?, b"retained bytes");
    assert_eq!(private_state_file_snapshot(&source)?, before);
    Ok(())
}

#[test]
fn frozen_child_rejects_missing_alias_and_hard_link_without_creation() -> io::Result<()> {
    let temporary = tempfile::tempdir()?;
    let root = temporary.path().join("private");
    let directory = open_private_state_directory(&root)?;
    drop(open_private_state_child(
        &directory,
        "database",
        PrivateFileAccess::Create,
    )?);
    for name in [
        "missing",
        "../escape",
        "database:stream",
        "database.",
        "database ",
    ] {
        assert!(open_frozen_private_state_child(&directory, name).is_err());
    }
    assert!(!root.join("missing").exists());
    std::fs::hard_link(root.join("database"), root.join("linked"))?;
    assert!(open_frozen_private_state_child(&directory, "database").is_err());
    Ok(())
}

#[test]
fn fresh_materialization_never_opens_an_occupied_name() -> io::Result<()> {
    let temporary = tempfile::tempdir()?;
    let directory = open_private_state_directory(&temporary.path().join("private"))?;
    let mut first = create_new_private_state_child(&directory, "candidate")?;
    first.write_all(b"original")?;
    first.sync_all()?;
    drop(first);
    assert!(create_new_private_state_child(&directory, "candidate").is_err());
    let mut source = open_frozen_private_state_child(&directory, "candidate")?;
    let mut bytes = Vec::new();
    std::io::Read::read_to_end(&mut source, &mut bytes)?;
    assert_eq!(bytes, b"original");
    Ok(())
}
