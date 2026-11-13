//! Native regressions for strict private directory and child API dispositions.

use std::fs;
use std::io;
use std::io::Read;
use std::io::Write;

use pretty_assertions::assert_eq;

use super::super::PrivateFileAccess;
use super::super::create_private_state_child;
use super::super::create_private_state_directory;
use super::super::final_path;
use super::super::open_existing_private_state_directory;
use super::super::open_private_state_child;
use super::tests::HookGuard;
use super::tests::private_directory_fixture;

#[test]
fn exclusive_creation_refuses_existing_and_racing_directories() -> io::Result<()> {
    let temporary = tempfile::tempdir()?;
    let existing = temporary.path().join("existing");
    let retained = create_private_state_directory(&existing)?;
    fs::write(existing.join("sentinel"), b"original")?;
    let original = final_path(&retained)?;
    let error = create_private_state_directory(&existing)
        .expect_err("an existing private directory is not a new creation");
    assert_eq!(error.kind(), io::ErrorKind::AlreadyExists);
    assert_eq!(final_path(&retained)?, original);
    assert_eq!(fs::read(existing.join("sentinel"))?, b"original");

    let raced = temporary.path().join("raced");
    let before_open = raced.clone();
    let hook = HookGuard::install(move || {
        drop(private_directory_fixture(&before_open)?);
        fs::write(before_open.join("sentinel"), b"created by the other owner")?;
        Ok(())
    });
    let result = create_private_state_directory(&raced);
    drop(hook);
    let error = result.expect_err("a directory created at acquisition cannot be adopted");
    assert_eq!(error.kind(), io::ErrorKind::AlreadyExists);
    assert_eq!(
        fs::read(raced.join("sentinel"))?,
        b"created by the other owner"
    );
    Ok(())
}

#[test]
fn existing_directory_open_never_initializes_missing_state() -> io::Result<()> {
    let temporary = tempfile::tempdir()?;
    let missing = temporary.path().join("missing");
    let error = open_existing_private_state_directory(&missing)
        .expect_err("readback must not initialize absent state");
    assert_eq!(error.kind(), io::ErrorKind::NotFound);
    assert!(!missing.try_exists()?);
    drop(create_private_state_directory(&missing)?);
    drop(open_existing_private_state_directory(&missing)?);
    Ok(())
}

#[test]
fn exclusive_child_creation_preserves_an_existing_private_file() -> io::Result<()> {
    let temporary = tempfile::tempdir()?;
    let directory = create_private_state_directory(&temporary.path().join("private"))?;
    let mut first = create_private_state_child(&directory, "receipt")?;
    first.write_all(b"original receipt")?;
    first.sync_all()?;
    let error = create_private_state_child(&directory, "receipt")
        .expect_err("exclusive creation cannot adopt a retained artifact");
    assert_eq!(error.kind(), io::ErrorKind::AlreadyExists);
    let mut observed = Vec::new();
    open_private_state_child(&directory, "receipt", PrivateFileAccess::Read)?
        .read_to_end(&mut observed)?;
    assert_eq!(observed, b"original receipt");
    Ok(())
}
