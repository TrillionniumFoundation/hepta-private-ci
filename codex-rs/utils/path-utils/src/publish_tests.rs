use std::fs;
use std::io;
use std::io::Write;

use pretty_assertions::assert_eq;

use super::publish_file_with_sync;

#[test]
fn publishes_and_replaces_complete_flushed_files() -> io::Result<()> {
    let directory = tempfile::tempdir()?;
    let destination = directory.path().join("session.json");
    for contents in [
        b"initial session".as_slice(),
        b"refreshed session".as_slice(),
    ] {
        let temporary = directory.path().join("session.tmp");
        let mut file = fs::OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&temporary)?;
        file.write_all(contents)?;
        file.sync_all()?;
        drop(file);
        publish_file_with_sync(&temporary, &destination)?;
        assert_eq!(fs::read(&destination)?, contents);
        assert!(!temporary.exists());
    }
    Ok(())
}

#[test]
fn rejected_publication_preserves_the_current_file() -> io::Result<()> {
    let directory = tempfile::tempdir()?;
    let destination = directory.path().join("session.json");
    fs::write(&destination, b"existing session")?;
    let missing = directory.path().join("missing.tmp");
    assert!(matches!(
        publish_file_with_sync(&missing, &destination),
        Err(error) if error.kind() == io::ErrorKind::NotFound
    ));
    let sibling = directory.path().join("other");
    fs::create_dir(&sibling)?;
    let temporary = sibling.join("session.tmp");
    fs::write(&temporary, b"unpublished session")?;
    assert!(matches!(
        publish_file_with_sync(&temporary, &destination),
        Err(error) if error.kind() == io::ErrorKind::InvalidInput
    ));
    assert_eq!(fs::read(&destination)?, b"existing session");
    assert_eq!(fs::read(&temporary)?, b"unpublished session");
    Ok(())
}
