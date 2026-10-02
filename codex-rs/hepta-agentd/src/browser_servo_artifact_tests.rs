use std::io;
use std::io::Cursor;
use std::io::Read;

use super::stream_bounded;

#[test]
fn artifact_stream_preserves_all_selected_bytes_at_the_limit() {
    let selected = vec![b'x'; 32_000];
    let mut input = Cursor::new(&selected);
    let mut consumed = Vec::new();
    stream_bounded(&mut input, selected.len(), |bytes| {
        consumed.extend_from_slice(bytes);
        Ok(())
    })
    .expect("exactly bounded artifact");
    assert_eq!(consumed, selected);
}

#[test]
fn artifact_stream_rejects_growth_without_scanning_the_unbounded_tail() {
    let mut input = Cursor::new(vec![b'x'; 1_000_000]);
    let error = stream_bounded(&mut input, /*maximum*/ 64, |_| Ok(()))
        .expect_err("oversized live contents");
    assert_eq!(error.kind(), io::ErrorKind::InvalidData);
    assert_eq!(input.position(), 65);
}

#[test]
fn artifact_stream_rejects_contents_truncated_after_metadata_admission() {
    let mut input = Cursor::new([]);
    let error =
        stream_bounded(&mut input, /*maximum*/ 64, |_| Ok(())).expect_err("empty live contents");
    assert_eq!(error.kind(), io::ErrorKind::InvalidData);
}

#[test]
fn artifact_stream_propagates_read_failure_after_consuming_a_prefix() {
    struct FailingReader {
        emitted_prefix: bool,
    }
    impl Read for FailingReader {
        fn read(&mut self, output: &mut [u8]) -> io::Result<usize> {
            if self.emitted_prefix {
                return Err(io::Error::new(
                    io::ErrorKind::PermissionDenied,
                    "reader failed",
                ));
            }
            self.emitted_prefix = true;
            output[0] = b'x';
            Ok(1)
        }
    }
    let mut consumed = Vec::new();
    let error = stream_bounded(
        &mut FailingReader {
            emitted_prefix: false,
        },
        /*maximum*/ 64,
        |bytes| {
            consumed.extend_from_slice(bytes);
            Ok(())
        },
    )
    .expect_err("incomplete artifact");
    assert_eq!(error.kind(), io::ErrorKind::PermissionDenied);
    assert_eq!(consumed, b"x");
}

#[test]
fn artifact_stream_stops_when_the_snapshot_writer_fails() {
    let mut input = Cursor::new(vec![b'x'; 40_000]);
    let error = stream_bounded(&mut input, /*maximum*/ 40_000, |_| {
        Err(io::Error::new(io::ErrorKind::StorageFull, "snapshot full"))
    })
    .expect_err("snapshot write failure");
    assert_eq!(error.kind(), io::ErrorKind::StorageFull);
    assert_eq!(input.position(), 16_384);
}
