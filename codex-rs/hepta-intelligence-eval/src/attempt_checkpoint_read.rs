//! Read a checkpoint within both its observed length and the format byte limit.

use std::io;
use std::io::Read;

use super::MAX_CHECKPOINT_BYTES;
use super::ProductEvaluationAttemptJournalErrorV1;
use super::io_error;

pub(super) fn read_exact_length<R: Read + ?Sized>(
    reader: &mut R,
    captured_len: u64,
) -> Result<Vec<u8>, ProductEvaluationAttemptJournalErrorV1> {
    if captured_len == 0 || captured_len > MAX_CHECKPOINT_BYTES {
        return Err(ProductEvaluationAttemptJournalErrorV1::Capacity);
    }
    let length = usize::try_from(captured_len)
        .map_err(|_| ProductEvaluationAttemptJournalErrorV1::Capacity)?;
    // Allocate only the captured length. A writer ignoring the file lock must
    // not turn read_to_end into unbounded input or geometric buffer growth.
    let mut bytes = vec![0_u8; length];
    let mut bounded = reader.take(MAX_CHECKPOINT_BYTES + 1);
    if let Err(error) = bounded.read_exact(&mut bytes) {
        return Err(if error.kind() == io::ErrorKind::UnexpectedEof {
            ProductEvaluationAttemptJournalErrorV1::Corrupt
        } else {
            io_error(error)
        });
    }
    // One extra byte detects any growth without retaining the added content.
    // read_exact retries interrupted reads, including this EOF probe.
    match bounded.read_exact(&mut [0_u8; 1]) {
        Ok(()) => Err(ProductEvaluationAttemptJournalErrorV1::Corrupt),
        Err(error) if error.kind() == io::ErrorKind::UnexpectedEof => Ok(bytes),
        Err(error) => Err(io_error(error)),
    }
}

#[cfg(test)]
#[path = "attempt_checkpoint_read_tests.rs"]
mod tests;
