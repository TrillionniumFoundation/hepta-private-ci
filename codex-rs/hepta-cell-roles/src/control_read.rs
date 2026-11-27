//! Bound bytes before replay of either versioned control owner. Callers retain
//! their existing writer locks and supply each format's unchanged size limit.

use super::ControlOwnerErrorV1;
use std::fs::File;
use std::io::Read;
use std::path::Path;

pub(super) fn read_control_file<const MAX_BYTES: usize>(
    path: &Path,
) -> Result<Vec<u8>, ControlOwnerErrorV1> {
    let mut file = File::open(path).map_err(|_| ControlOwnerErrorV1::DurableIo)?;
    let observed_len = file
        .metadata()
        .map_err(|_| ControlOwnerErrorV1::DurableIo)?
        .len();
    read_control_bytes::<MAX_BYTES>(&mut file, observed_len)
}

pub(super) fn read_control_bytes<const MAX_BYTES: usize>(
    reader: &mut impl Read,
    observed_len: u64,
) -> Result<Vec<u8>, ControlOwnerErrorV1> {
    if observed_len > MAX_BYTES as u64 {
        return Err(ControlOwnerErrorV1::InvalidDurableSnapshot);
    }
    // Metadata alone cannot bound a file that changes while it is read. One
    // extra byte distinguishes the exact limit from an oversized stream.
    let mut bytes = Vec::new();
    reader
        .take(MAX_BYTES as u64 + 1)
        .read_to_end(&mut bytes)
        .map_err(|_| ControlOwnerErrorV1::DurableIo)?;
    if bytes.len() > MAX_BYTES {
        return Err(ControlOwnerErrorV1::InvalidDurableSnapshot);
    }
    Ok(bytes)
}
