use super::PrivateFileAccess;
use crate::parent_anchor::ParentAnchor;
use crate::parent_anchor::tests::Fixture;
use std::error::Error;
use std::fs;
use std::io::Read;
use std::io::Seek;
use std::io::SeekFrom;
use std::io::Write;

type Result = std::result::Result<(), Box<dyn Error>>;

#[test]
fn actual_private_journal_reopens_original_bytes_and_appends_under_same_lock() -> Result {
    let fixture = Fixture::new()?;
    let mut directory =
        ParentAnchor::for_create_only(&fixture.0)?.create_private_directory("private")?;
    let owner = directory.lock_owner("authority.lock")?;
    let mut file = owner.create_private_file("input", 40)?;
    file.write_all(b"first")?;
    file.sync_all()?;
    drop(file);
    let mut file = owner.create_private_file("input", 40)?;
    assert_eq!(file.len()?, 5, "collision must not truncate");
    file.seek(SeekFrom::End(0))?;
    file.write_all(b"-second")?;
    file.sync_all()?;
    file.seek(SeekFrom::Start(0))?;
    let mut bytes = Vec::new();
    file.read_to_end(&mut bytes)?;
    assert_eq!(bytes, b"first-second");
    drop(file);
    assert_eq!(owner.read_bounded("input", 40)?, b"first-second");
    Ok(())
}

#[test]
fn actual_private_file_extent_error_refuses_later_writes_without_growth() -> Result {
    let fixture = Fixture::new()?;
    let mut directory =
        ParentAnchor::for_create_only(&fixture.0)?.create_private_directory("private")?;
    let owner = directory.lock_owner("authority.lock")?;
    let mut file = owner.create_private_file("input", 4)?;
    file.write_all(b"four")?;
    file.sync_all()?;
    assert!(file.write_all(b"extra").is_err());
    assert!(file.seek(SeekFrom::Start(0)).is_err());
    drop(file);
    assert!(owner.entry_exists("input").is_err());
    assert_eq!(fs::read(fixture.0.join("private/input"))?, b"four");
    Ok(())
}

#[test]
fn actual_read_only_private_file_cannot_write_truncate_or_create_missing() -> Result {
    let fixture = Fixture::new()?;
    let mut directory =
        ParentAnchor::for_create_only(&fixture.0)?.create_private_directory("private")?;
    let owner = directory.lock_owner("authority.lock")?;
    let mut created = owner.create_private_file("input", 4)?;
    created.write_all(b"four")?;
    created.sync_all()?;
    drop(created);
    let mut read = owner.open_existing_file("input", 4, PrivateFileAccess::Read)?;
    assert!(read.write_all(b"fail").is_err());
    assert!(read.set_len(0).is_err());
    let mut bytes = Vec::new();
    read.read_to_end(&mut bytes)?;
    assert_eq!(bytes, b"four");
    drop(read);
    assert!(
        owner
            .open_existing_file("missing", 4, PrivateFileAccess::Read)
            .is_err()
    );
    assert!(!fixture.0.join("private/missing").exists());
    Ok(())
}
