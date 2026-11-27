use super::open_existing;
use super::publish_staging;
use pretty_assertions::assert_eq;
use std::fs;
use std::fs::OpenOptions;
use std::io;
use std::io::Write;

#[test]
fn windows_cas_publish_keeps_an_existing_object_and_its_staging() -> io::Result<()> {
    let directory = tempfile::tempdir()?;
    let root = directory.path().canonicalize()?;
    let staging = root.join("candidate.tmp");
    let destination = root.join("occupied-object");
    fs::write(&staging, b"candidate")?;
    fs::write(&destination, b"original")?;
    let result = publish_staging(&staging, &destination);
    assert!(matches!(result, Err(error) if error.kind() == io::ErrorKind::AlreadyExists));
    assert_eq!(fs::read(&destination)?, b"original");
    assert_eq!(fs::read(&staging)?, b"candidate");
    Ok(())
}

#[test]
fn windows_cas_publish_consumes_staging_and_reopened_file_can_flush() -> io::Result<()> {
    let directory = tempfile::tempdir()?;
    let root = directory.path().canonicalize()?;
    let staging = root.join("candidate.tmp");
    let destination = root.join("new-object");
    let mut file = OpenOptions::new()
        .create_new(/*create_new*/ true)
        .write(/*write*/ true)
        .open(&staging)?;
    file.write_all(b"candidate")?;
    file.sync_all()?;
    drop(file);
    publish_staging(&staging, &destination)?;
    assert!(!staging.try_exists()?);
    assert_eq!(fs::read(&destination)?, b"candidate");
    open_existing(&destination)?.sync_all()?;
    Ok(())
}
