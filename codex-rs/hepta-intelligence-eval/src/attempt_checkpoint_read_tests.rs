use std::io::Cursor;

use pretty_assertions::assert_eq;

use super::*;

#[derive(Default)]
struct GrowingReader {
    bytes_read: usize,
}

impl Read for GrowingReader {
    fn read(&mut self, bytes: &mut [u8]) -> io::Result<usize> {
        bytes.fill(0x41);
        self.bytes_read += bytes.len();
        Ok(bytes.len())
    }
}

struct MustNotRead;

impl Read for MustNotRead {
    fn read(&mut self, _bytes: &mut [u8]) -> io::Result<usize> {
        panic!("invalid captured length must be rejected before reading")
    }
}

#[test]
fn continuously_growing_input_stops_after_observed_length_and_one_byte() {
    let mut reader = GrowingReader::default();
    assert_eq!(
        read_exact_length(&mut reader, /*captured_len*/ 8),
        Err(ProductEvaluationAttemptJournalErrorV1::Corrupt)
    );
    assert_eq!(reader.bytes_read, 9);
}

#[test]
fn invalid_observed_length_is_rejected_before_reading_or_allocating() {
    for length in [0, MAX_CHECKPOINT_BYTES + 1, u64::MAX] {
        assert_eq!(
            read_exact_length(&mut MustNotRead, length),
            Err(ProductEvaluationAttemptJournalErrorV1::Capacity)
        );
    }
}

#[test]
fn truncated_input_cannot_satisfy_the_observed_length() {
    assert_eq!(
        read_exact_length(&mut Cursor::new(b"short"), /*captured_len*/ 8),
        Err(ProductEvaluationAttemptJournalErrorV1::Corrupt)
    );
}

#[test]
fn exact_input_round_trips_without_changing_bytes() {
    let bytes = b"immutable canonical checkpoint bytes";
    assert_eq!(
        read_exact_length(&mut Cursor::new(bytes), bytes.len() as u64),
        Ok(bytes.to_vec())
    );
}

#[test]
fn actual_read_failure_preserves_its_typed_io_error() {
    struct FailedReader;
    impl Read for FailedReader {
        fn read(&mut self, _bytes: &mut [u8]) -> io::Result<usize> {
            Err(io::Error::from(io::ErrorKind::PermissionDenied))
        }
    }
    assert_eq!(
        read_exact_length(&mut FailedReader, /*captured_len*/ 8),
        Err(ProductEvaluationAttemptJournalErrorV1::Io(
            io::ErrorKind::PermissionDenied
        ))
    );
}
