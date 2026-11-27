use super::*;
use pretty_assertions::assert_eq;
use std::error::Error;
use std::io::Read;

fn directory(label: &str) -> Result<PathBuf, Box<dyn Error>> {
    let nonce = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)?
        .as_nanos();
    let path = std::env::temp_dir().join(format!(
        "hepta-wal-windows-{label}-{}-{nonce}",
        std::process::id()
    ));
    fs::create_dir(&path)?;
    Ok(path)
}

#[test]
fn unchanged_locked_writer_accepts_an_event_and_reopens() -> Result<(), Box<dyn Error>> {
    let directory = directory("unchanged")?;
    let cell = StableId::new("windows-identity-cell")?;
    let scope = Digest32::of_bytes(b"windows-identity-scope");
    let mut owner = ScopedControlWalOwnerV1::open(&directory, cell.clone(), scope)?;
    owner.set_now_ms(1)?;
    let head = owner.head();
    let events = owner.committed_events();
    drop(owner);
    let reopened = ScopedControlWalOwnerV1::open(&directory, cell, scope)?;
    assert_eq!(reopened.head(), head);
    assert_eq!(reopened.committed_events(), events);
    drop(reopened);
    fs::remove_dir_all(directory)?;
    Ok(())
}

#[test]
fn same_size_replacement_is_rejected_before_any_append() -> Result<(), Box<dyn Error>> {
    let directory = directory("replacement")?;
    let cell = StableId::new("windows-identity-cell")?;
    let scope = Digest32::of_bytes(b"windows-identity-scope");
    let mut owner = ScopedControlWalOwnerV1::open(&directory, cell.clone(), scope)?;
    let original_bytes = wal_header(&cell, scope)?;
    let original_head = owner.head();
    let original_events = owner.committed_events();
    let original_path = owner.path().to_path_buf();
    let retired = directory.join("retired.wal");
    fs::rename(&original_path, &retired)?;
    fs::write(&original_path, &original_bytes)?;

    assert_eq!(
        owner.set_now_ms(1),
        Err(ControlOwnerErrorV1::InvalidDurableSnapshot)
    );
    assert_eq!(owner.head(), original_head);
    assert_eq!(owner.committed_events(), original_events);
    assert_eq!(fs::read(&original_path)?, original_bytes);
    owner.writer.seek(SeekFrom::Start(0))?;
    let mut retained_bytes = Vec::new();
    owner.writer.read_to_end(&mut retained_bytes)?;
    assert_eq!(retained_bytes, original_bytes);
    assert_eq!(
        owner.set_now_ms(2),
        Err(ControlOwnerErrorV1::InvalidDurableSnapshot)
    );
    drop(owner);
    fs::remove_dir_all(directory)?;
    Ok(())
}
