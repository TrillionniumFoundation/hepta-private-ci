use super::OriginalFileAccess;
use super::PrivateStoreDirectory;
use crate::parent_anchor::OwnerLockOrigin;
use crate::parent_anchor::ParentAnchor;
use crate::parent_anchor::tests::Fixture;
use std::error::Error;
use std::io::Read;
use std::io::Seek;
use std::io::SeekFrom;
use std::io::Write;

type Result = std::result::Result<(), Box<dyn Error>>;

#[test]
fn actual_original_io_keeps_marker_and_payload_bytes_across_cold_open() -> Result {
    let fixture = Fixture::new()?;
    let fresh = ParentAnchor::for_create_only(&fixture.0)?.create_private_directory("private")?;
    let owner = PrivateStoreDirectory::Fresh(fresh).lock_original_marker("authority.lock")?;
    assert_eq!(owner.origin(), &OwnerLockOrigin::Created);
    let mut stage = owner.open_original_file("input", 40, OriginalFileAccess::Stage)?;
    stage.set_len(0)?;
    stage.write_all(b"original-journal")?;
    stage.sync_all()?;
    stage.replace_synced("state")?;
    owner.sync_all()?;
    drop(stage);
    drop(owner);
    let cold = ParentAnchor::for_create_only(&fixture.0)?.open_existing_candidate("private")?;
    let owner = PrivateStoreDirectory::Existing(cold).lock_original_marker("authority.lock")?;
    assert_eq!(owner.origin(), &OwnerLockOrigin::Existing);
    let mut file = owner.open_original_file("state", 40, OriginalFileAccess::Write)?;
    file.seek(SeekFrom::End(0))?;
    file.write_all(b"-append")?;
    file.sync_all()?;
    drop(file);
    let mut file = owner.open_original_file("state", 40, OriginalFileAccess::Read)?;
    let mut bytes = Vec::new();
    file.read_to_end(&mut bytes)?;
    assert_eq!(bytes, b"original-journal-append");
    assert!(file.replace_synced("input").is_err());
    Ok(())
}
