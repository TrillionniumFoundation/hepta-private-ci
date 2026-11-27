use super::super::bounded_read::read_control_bytes;
use super::*;
use pretty_assertions::assert_eq;
use std::fs;
use std::io;
use std::io::Cursor;
use std::io::Read;

struct RefuseRead;

impl Read for RefuseRead {
    fn read(&mut self, _buffer: &mut [u8]) -> io::Result<usize> {
        panic!("oversized metadata must be rejected before reading");
    }
}

struct FailedRead;

impl Read for FailedRead {
    fn read(&mut self, _buffer: &mut [u8]) -> io::Result<usize> {
        Err(io::Error::other("injected read failure"))
    }
}

#[test]
fn oversized_metadata_is_rejected_before_reading() {
    assert_eq!(
        read_control_bytes::<MAX_WAL_BYTES>(&mut RefuseRead, MAX_WAL_BYTES as u64 + 1),
        Err(ControlOwnerErrorV1::InvalidDurableSnapshot)
    );
}

#[test]
fn growth_after_metadata_cannot_escape_the_byte_limit() {
    let overflow = 4096;
    let mut source = io::repeat(/*byte*/ 0xa5).take(MAX_WAL_BYTES as u64 + overflow);
    assert_eq!(
        read_control_bytes::<MAX_WAL_BYTES>(&mut source, /*observed_len*/ 0),
        Err(ControlOwnerErrorV1::InvalidDurableSnapshot)
    );
    assert_eq!(source.limit(), overflow - 1);
}

#[test]
fn exact_byte_limit_and_short_inputs_preserve_every_byte() {
    for length in [0, 17, MAX_WAL_BYTES] {
        let mut source = io::repeat(/*byte*/ 0x5a).take(length as u64);
        assert_eq!(
            read_control_bytes::<MAX_WAL_BYTES>(&mut source, length as u64).expect("bounded bytes"),
            vec![0x5a; length]
        );
        assert_eq!(source.limit(), 0);
    }
}

#[test]
fn read_failure_after_a_valid_header_cannot_become_a_partial_snapshot() {
    let cell = StableId::new("read-limit-cell").expect("cell id");
    let scope = Digest32::of_bytes(b"read-limit-scope");
    let header = wal_header(&cell, scope).expect("valid header");
    let observed_len = header.len() as u64;
    let mut source = Cursor::new(header).chain(FailedRead);
    assert_eq!(
        read_control_bytes::<MAX_WAL_BYTES>(&mut source, observed_len),
        Err(ControlOwnerErrorV1::DurableIo)
    );
}

#[test]
fn oversized_wal_open_preserves_the_file_and_releases_its_writer_lock() {
    let directory = std::env::temp_dir().join(format!(
        "hepta-control-wal-bound-{}-{}",
        std::process::id(),
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .expect("clock")
            .as_nanos()
    ));
    let cell = StableId::new("read-limit-cell").expect("cell id");
    let scope = Digest32::of_bytes(b"read-limit-scope");
    let owner = ScopedControlWalOwnerV1::open(&directory, cell.clone(), scope).expect("create");
    let path = owner.path().to_path_buf();
    drop(owner);
    let original_header = fs::read(&path).expect("original header");
    let file = fs::OpenOptions::new()
        .write(true)
        .open(&path)
        .expect("open for growth");
    let oversized_length = MAX_WAL_BYTES as u64 + 1;
    file.set_len(oversized_length).expect("extend");
    file.sync_all().expect("sync");
    drop(file);

    assert!(matches!(
        ScopedControlWalOwnerV1::open(&directory, cell, scope),
        Err(ControlOwnerErrorV1::InvalidDurableSnapshot)
    ));

    let mut file = fs::OpenOptions::new()
        .read(true)
        .write(true)
        .open(&path)
        .expect("reopen original file");
    file.try_lock().expect("failed open released writer lock");
    assert_eq!(file.metadata().expect("metadata").len(), oversized_length);
    let mut actual_header = vec![0; original_header.len()];
    file.read_exact(&mut actual_header)
        .expect("read original prefix");
    assert_eq!(actual_header, original_header);
    drop(file);
    fs::remove_dir_all(directory).expect("cleanup");
}
