//! Bounded reads for fixed-shape long-horizon catalog rows.
//!
//! The caller supplies an expected length derived from the protocol, never
//! from an on-disk length field. Host-owned directory isolation remains the
//! caller's responsibility; this is not a hostile-filesystem sandbox.

use std::fs::File;
use std::io::Read;
use std::path::Path;

use super::LongHorizonLedgerErrorV1;
use super::PersistentIndexErrorV1;

pub(super) fn read_catalog_file(
    path: &Path,
    expected_len: usize,
) -> Result<Option<Vec<u8>>, LongHorizonLedgerErrorV1> {
    let file = match File::open(path) {
        Ok(file) => file,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(None),
        Err(error) => return Err(PersistentIndexErrorV1::from(error).into()),
    };
    let metadata = file.metadata().map_err(PersistentIndexErrorV1::from)?;
    let expected =
        u64::try_from(expected_len).map_err(|_| LongHorizonLedgerErrorV1::CatalogCorrupt)?;
    if !metadata.is_file() || metadata.len() != expected {
        return Err(LongHorizonLedgerErrorV1::CatalogCorrupt);
    }
    bounded_contents(file, expected_len).map(Some)
}

fn bounded_contents(
    reader: impl Read,
    expected_len: usize,
) -> Result<Vec<u8>, LongHorizonLedgerErrorV1> {
    let limit = u64::try_from(expected_len)
        .ok()
        .and_then(|length| length.checked_add(1))
        .ok_or(LongHorizonLedgerErrorV1::CatalogCorrupt)?;
    // The extra byte detects growth after metadata inspection. Truncation is
    // detected by the exact length comparison. Neither race causes an unbounded
    // allocation or a read of the entire corrupt file.
    let mut bytes = Vec::with_capacity(expected_len);
    reader
        .take(limit)
        .read_to_end(&mut bytes)
        .map_err(PersistentIndexErrorV1::from)?;
    if bytes.len() != expected_len {
        return Err(LongHorizonLedgerErrorV1::CatalogCorrupt);
    }
    Ok(bytes)
}

#[cfg(test)]
#[path = "long_horizon_catalog_io_tests.rs"]
mod tests;
