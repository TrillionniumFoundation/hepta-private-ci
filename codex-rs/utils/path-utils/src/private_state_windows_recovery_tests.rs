use std::ffi::OsStr;
use std::fs;
use std::io;
use std::io::Write;

use pretty_assertions::assert_eq;

use super::super::open_private_state_directory;
use super::create_private_recovery_copy;
use super::discard_private_recovery_copy;
use super::open_existing_private_state_directory;
use super::open_existing_private_state_directory_for_sync;
use super::open_private_recovery_source;

#[test]
fn recovery_directory_opens_do_not_create_missing_state() -> io::Result<()> {
    let temporary = tempfile::tempdir()?;
    let missing = temporary.path().join("missing");
    let read_error = open_existing_private_state_directory(&missing)
        .expect_err("a recovery read must not create its source");
    let sync_error = open_existing_private_state_directory_for_sync(&missing)
        .expect_err("a recovery sync must not create its source");
    assert_eq!(
        (read_error.kind(), sync_error.kind(), missing.exists()),
        (io::ErrorKind::NotFound, io::ErrorKind::NotFound, false),
    );
    Ok(())
}

#[test]
fn existing_directory_acquisition_rejects_redirects_without_creating_children() -> io::Result<()> {
    let temporary = tempfile::tempdir()?;
    let root = temporary.path().join("private");
    let directory = open_private_state_directory(&root)?;
    drop(open_private_state_directory(&root.join("child"))?);
    let output = std::process::Command::new("cmd.exe")
        .current_dir(temporary.path())
        .args(["/d", "/c", "mklink", "/J", "alias", "private"])
        .output()?;
    assert!(output.status.success(), "create real junction: {output:?}");
    let alias = temporary.path().join("alias");
    for path in [&alias, &alias.join("child"), &alias.join("missing")] {
        assert!(open_existing_private_state_directory(path).is_err());
        assert!(open_existing_private_state_directory_for_sync(path).is_err());
    }
    assert!(!root.join("missing").exists());
    drop(directory);
    fs::remove_dir(alias)?;
    Ok(())
}

#[test]
fn create_new_copy_preserves_existing_bytes_and_rejects_escaping_names() -> io::Result<()> {
    let temporary = tempfile::tempdir()?;
    let root = temporary.path().join("private");
    let directory = open_private_state_directory(&root)?;
    let mut copy = create_private_recovery_copy(&directory, OsStr::new("entry"))?;
    copy.write_all(b"original")?;
    copy.sync_all()?;
    drop(copy);
    let duplicate = create_private_recovery_copy(&directory, OsStr::new("entry"))
        .expect_err("create-new must never reopen the original");
    assert_eq!(duplicate.kind(), io::ErrorKind::AlreadyExists);
    for name in ["../outside", "nested/entry", "entry:stream", "", ".", ".."] {
        assert!(create_private_recovery_copy(&directory, OsStr::new(name)).is_err());
        assert!(open_private_recovery_source(&directory, OsStr::new(name)).is_err());
    }
    assert_eq!(fs::read(root.join("entry"))?, b"original");
    assert!(!temporary.path().join("outside").exists());
    assert!(!root.join("nested").exists());
    Ok(())
}

#[test]
fn read_source_denies_mutation_until_every_retained_clone_closes() -> io::Result<()> {
    let temporary = tempfile::tempdir()?;
    let root = temporary.path().join("private");
    let directory = open_private_state_directory(&root)?;
    let mut copy = create_private_recovery_copy(&directory, OsStr::new("entry"))?;
    copy.write_all(b"original")?;
    drop(copy);
    let source = open_private_recovery_source(&directory, OsStr::new("entry"))?;
    let clone = source.try_clone()?;
    drop(source);
    let write_error = fs::OpenOptions::new()
        .write(true)
        .open(root.join("entry"))
        .expect_err("the retained read clone must deny a new writer");
    assert_eq!(write_error.raw_os_error(), Some(32));
    assert!(fs::remove_file(root.join("entry")).is_err());
    assert!(discard_private_recovery_copy(&clone).is_err());
    assert_eq!(fs::read(root.join("entry"))?, b"original");
    drop(clone);
    fs::OpenOptions::new()
        .write(true)
        .open(root.join("entry"))?
        .write_all(b"updated!")?;
    assert_eq!(fs::read(root.join("entry"))?, b"updated!");
    Ok(())
}

#[test]
fn recovery_source_rejects_hard_links_without_changing_them() -> io::Result<()> {
    let temporary = tempfile::tempdir()?;
    let root = temporary.path().join("private");
    let directory = open_private_state_directory(&root)?;
    let mut copy = create_private_recovery_copy(&directory, OsStr::new("entry"))?;
    copy.write_all(b"original")?;
    drop(copy);
    fs::hard_link(root.join("entry"), root.join("alias"))?;
    assert!(open_private_recovery_source(&directory, OsStr::new("entry")).is_err());
    assert!(open_private_recovery_source(&directory, OsStr::new("alias")).is_err());
    assert_eq!(fs::read(root.join("entry"))?, b"original");
    assert_eq!(fs::read(root.join("alias"))?, b"original");
    Ok(())
}

#[test]
fn owned_copy_cleanup_deletes_only_the_retained_new_object() -> io::Result<()> {
    let temporary = tempfile::tempdir()?;
    let root = temporary.path().join("private");
    let directory = open_private_state_directory(&root)?;
    fs::write(root.join("retained"), b"untouched")?;
    let copy = create_private_recovery_copy(&directory, OsStr::new("copy"))?;
    discard_private_recovery_copy(&copy)?;
    drop(copy);
    assert!(!root.join("copy").exists());
    assert_eq!(fs::read(root.join("retained"))?, b"untouched");
    Ok(())
}
