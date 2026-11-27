use super::*;
use std::io::Write;
use std::os::unix::fs::PermissionsExt;

use pretty_assertions::assert_eq;

type TestResult = Result<(), Box<dyn std::error::Error>>;

fn original(path: &Path) -> std::io::Result<File> {
    OpenOptions::new()
        .read(true)
        .write(true)
        .create_new(true)
        .mode(0o600)
        .open(path)
}

#[test]
fn initial_q24_files_refuse_missing_symlink_and_shared_permissions() -> TestResult {
    let directory = tempfile::tempdir()?;
    let path = directory.path().join("owner");
    let mut files = OriginalFiles::new()?;
    assert!(files.write(&path).is_err());
    assert!(!path.exists());
    let _file = original(&path)?;
    let alias = directory.path().join("symlink");
    std::os::unix::fs::symlink(&path, &alias)?;
    assert!(files.read(&alias).is_err());
    std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o640))?;
    assert!(files.read(&path).is_err());
    assert!(files.write(&path).is_err());
    std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o600))?;
    assert_eq!(files.read(&path)?.metadata()?.len(), 0);
    Ok(())
}

#[test]
fn initial_q24_files_track_writer_aliases_across_late_assembly() -> TestResult {
    let directory = tempfile::tempdir()?;
    let path = directory.path().join("owner");
    let _original = original(&path)?;
    let mut files = OriginalFiles::new()?;
    let read = files.read(&path)?;
    let _second_read = files.read(&path)?;
    assert!(files.write(&path).is_err());
    assert!(files.append(&path).is_err());
    drop(read);
    // The tracker must survive the earlier reader, including model parsing.
    assert!(files.write(&path).is_err());
    let mut later = OriginalFiles::new()?;
    let writer = later.write(&path)?;
    assert!(later.read(&path).is_err());
    assert!(later.append(&path).is_err());
    drop(writer);
    assert!(later.write(&path).is_err());
    Ok(())
}

#[test]
fn initial_q24_files_reject_hard_links_and_preserve_existing_history() -> TestResult {
    let directory = tempfile::tempdir()?;
    let path = directory.path().join("owner");
    let mut file = original(&path)?;
    require_unwritten(&file)?;
    file.write_all(b"retained-original-header")?;
    file.sync_all()?;
    assert!(require_unwritten(&file).is_err());
    let alias = directory.path().join("hardlink");
    std::fs::hard_link(&path, &alias)?;
    let mut files = OriginalFiles::new()?;
    assert!(files.read(&path).is_err());
    assert!(files.write(&alias).is_err());
    std::fs::remove_file(alias)?;
    let reopened = files.write(&path)?;
    assert!(require_unwritten(&reopened).is_err());
    assert_eq!(std::fs::read(path)?, b"retained-original-header");
    Ok(())
}
