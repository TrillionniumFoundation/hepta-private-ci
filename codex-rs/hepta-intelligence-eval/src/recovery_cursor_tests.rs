use super::*;
use std::fs;
use std::fs::OpenOptions;
use std::path::PathBuf;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

static NEXT_FILE: AtomicU64 = AtomicU64::new(0);

struct Fixture(PathBuf);

impl Fixture {
    fn new() -> Self {
        let ordinal = NEXT_FILE.fetch_add(1, Ordering::Relaxed);
        Self(std::env::temp_dir().join(format!(
            "hepta-recovery-cursor-{}-{ordinal}",
            std::process::id()
        )))
    }

    fn create(&self) -> File {
        OpenOptions::new()
            .read(true)
            .write(true)
            .create_new(true)
            .open(&self.0)
            .expect("create cursor")
    }

    fn reopen(&self) -> File {
        OpenOptions::new()
            .read(true)
            .write(true)
            .open(&self.0)
            .expect("reopen cursor")
    }
}

impl Drop for Fixture {
    fn drop(&mut self) {
        let _ = fs::remove_file(&self.0);
    }
}

fn binding() -> Digest32 {
    Digest32::of_bytes(b"cursor-scope")
}
fn id(value: &str) -> StableId {
    StableId::new(value).expect("id")
}

#[test]
fn progress_survives_reopen_and_exact_retries_do_not_write() {
    let fixture = Fixture::new();
    let next = id("attempt:blocked");
    {
        let mut cursor = RecoveryCursor::open(fixture.create(), binding()).expect("open");
        cursor.save(Some(&next)).expect("persist progress");
        let bytes = fs::read(&fixture.0).expect("bytes");
        cursor.save(Some(&next)).expect("exact retry");
        assert_eq!(fs::read(&fixture.0).expect("same bytes"), bytes);
    }
    let mut cursor = RecoveryCursor::open(fixture.reopen(), binding()).expect("recover");
    assert_eq!(cursor.after(), Some(&next));
    cursor.save(None).expect("complete pass");
    drop(cursor);
    let recovered = RecoveryCursor::open(fixture.reopen(), binding()).expect("recover wrap");
    assert_eq!(recovered.after(), None);
}

#[test]
fn live_cursor_excludes_a_second_controller() {
    let fixture = Fixture::new();
    let first = RecoveryCursor::open(fixture.create(), binding()).expect("first owner");
    assert!(matches!(
        RecoveryCursor::open(fixture.reopen(), binding()),
        Err(Error::Busy)
    ));
    drop(first);
    assert!(RecoveryCursor::open(fixture.reopen(), binding()).is_ok());
}

#[test]
fn torn_latest_slot_replays_predecessor_without_resetting_ownership() {
    let fixture = Fixture::new();
    let first = id("attempt:a");
    let second = id("attempt:b");
    let newest_slot = {
        let mut cursor = RecoveryCursor::open(fixture.create(), binding()).expect("open");
        cursor.save(Some(&first)).expect("first progress");
        cursor.save(Some(&second)).expect("second progress");
        cursor.slot
    };
    let mut bytes = fs::read(&fixture.0).expect("bytes");
    bytes[newest_slot * SLOT_BYTES + 80] ^= 1;
    fs::write(&fixture.0, &bytes).expect("inject torn latest slot");
    let mut recovered = RecoveryCursor::open(fixture.reopen(), binding()).expect("predecessor");
    assert_eq!(recovered.after(), Some(&first));
    recovered
        .save(Some(&second))
        .expect("replay scheduling progress");
    drop(recovered);
    assert_eq!(
        RecoveryCursor::open(fixture.reopen(), binding())
            .expect("reopen")
            .after(),
        Some(&second)
    );
}

#[test]
fn different_host_or_namespace_cannot_adopt_existing_cursor() {
    let fixture = Fixture::new();
    drop(RecoveryCursor::open(fixture.create(), binding()).expect("open"));
    let before = fs::read(&fixture.0).expect("bytes");
    assert!(matches!(
        RecoveryCursor::open(fixture.reopen(), Digest32::of_bytes(b"different-scope")),
        Err(Error::Binding)
    ));
    assert_eq!(fs::read(&fixture.0).expect("unchanged"), before);
}

#[test]
fn invalid_slots_and_truncation_fail_closed() {
    let fixture = Fixture::new();
    drop(RecoveryCursor::open(fixture.create(), binding()).expect("open"));
    let original = fs::read(&fixture.0).expect("bytes");
    fs::write(&fixture.0, vec![0_u8; FILE_BYTES]).expect("erase both slots");
    assert!(matches!(
        RecoveryCursor::open(fixture.reopen(), binding()),
        Err(Error::Corrupt)
    ));
    fs::write(&fixture.0, &original[..original.len() - 1]).expect("truncate");
    assert!(matches!(
        RecoveryCursor::open(fixture.reopen(), binding()),
        Err(Error::Corrupt)
    ));
}

#[test]
fn excessive_generation_gap_is_not_accepted_as_new_progress() {
    let fixture = Fixture::new();
    drop(RecoveryCursor::open(fixture.create(), binding()).expect("open"));
    let mut bytes = fs::read(&fixture.0).expect("bytes");
    let substituted = encode(
        &Progress {
            generation: 50,
            after: Some(id("attempt:z")),
        },
        binding(),
    )
    .expect("syntactically valid slot");
    bytes[SLOT_BYTES..].copy_from_slice(&substituted);
    fs::write(&fixture.0, bytes).expect("substitute slot");
    assert!(matches!(
        RecoveryCursor::open(fixture.reopen(), binding()),
        Err(Error::Corrupt)
    ));
}
