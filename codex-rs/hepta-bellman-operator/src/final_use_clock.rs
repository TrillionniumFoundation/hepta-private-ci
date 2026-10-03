//! Explicit boundary between fit microseconds and learning-authority milliseconds.
//!
//! Never infer units from magnitude: historical fixture values and real host values
//! receive the same conversion. Signed evidence and root distributions keep their
//! original millisecond preimages; work deadlines and publication remain microseconds.

use super::FinalUseErrorV1;

pub(super) fn learning_millis(unix_micros: u64) -> Result<u64, FinalUseErrorV1> {
    let unix_millis = unix_micros / 1_000;
    if unix_millis == 0 {
        return Err(FinalUseErrorV1::Binding("learning authority clock is zero"));
    }
    Ok(unix_millis)
}
