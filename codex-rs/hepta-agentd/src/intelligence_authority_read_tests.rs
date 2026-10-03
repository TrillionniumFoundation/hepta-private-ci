use super::*;
use std::cell::Cell;
use std::io;
use std::io::Write;
use tempfile::tempdir;

struct EndlessAuthority<'a> {
    consumed: &'a Cell<usize>,
}

impl Read for EndlessAuthority<'_> {
    fn read(&mut self, buffer: &mut [u8]) -> io::Result<usize> {
        buffer.fill(b' ');
        self.consumed.set(self.consumed.get() + buffer.len());
        Ok(buffer.len())
    }
}

#[test]
#[allow(
    clippy::expect_used,
    reason = "Resource bounds must fail on fixture drift."
)]
fn unauthenticated_stream_stops_after_one_over_limit_byte() {
    let requested = StableId::new("intuition.policy").expect("owner");
    let consumed = Cell::new(0);
    let error = read_bytes(
        EndlessAuthority {
            consumed: &consumed,
        },
        &requested,
    )
    .expect_err("endless owner input must reject");
    assert_eq!(
        error,
        CanonicalIntelligenceError::FreshnessUnavailable(requested)
    );
    assert_eq!(
        consumed.get() as u64,
        MAX_INTELLIGENCE_AUTHORITY_FILE_BYTES + 1
    );
}

#[test]
#[allow(
    clippy::expect_used,
    reason = "File growth after metadata must stay bounded."
)]
fn file_growth_after_handle_metadata_cannot_bypass_the_read_limit() {
    let directory = tempdir().expect("directory");
    let path = directory.path().join("authority");
    let mut writer = File::create(&path).expect("writer");
    writer.write_all(b"small").expect("initial content");
    let reader = File::open(&path).expect("reader");
    assert_eq!(reader.metadata().expect("initial metadata").len(), 5);
    writer
        .set_len(MAX_INTELLIGENCE_AUTHORITY_FILE_BYTES * 2)
        .expect("grow the already-open file");
    let requested = StableId::new("intuition.policy").expect("owner");
    assert_eq!(
        read_bytes(reader, &requested),
        Err(CanonicalIntelligenceError::FreshnessUnavailable(requested))
    );
}

#[cfg(unix)]
#[test]
#[allow(
    clippy::expect_used,
    reason = "The existing private-file policy must be preserved."
)]
fn symlinks_and_writable_authority_files_remain_rejected() {
    use std::os::unix::fs::PermissionsExt;
    use std::os::unix::fs::symlink;
    let directory = tempdir().expect("directory");
    let path = directory.path().join("authority");
    std::fs::write(&path, b"private").expect("content");
    std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o600)).expect("private");
    let requested = StableId::new("intuition.policy").expect("owner");
    assert_eq!(
        read_file(&path, &requested).expect("private file"),
        b"private"
    );
    let link = directory.path().join("link");
    symlink(&path, &link).expect("symlink");
    assert!(read_file(&link, &requested).is_err());
    std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o622)).expect("writable");
    assert!(read_file(&path, &requested).is_err());
}
