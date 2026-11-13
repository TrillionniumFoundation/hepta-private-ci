//! One fixed Material Source read. No request selects a run, operation, stage,
//! path, signer or receipt. The complete original payload must fit one frame.

use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};
use codex_hepta_types::Digest32;
use crate::{CircuitTaskErrorV1 as Error, OriginalCellQ24MaterialReceiptConfigV1};
pub(crate) use crate::circuit_task::root_bootstrap_codec::{Reader, Writer};

pub(crate) const BOUND: usize = 16_384;
pub(crate) const TIMEOUT: Duration = Duration::from_millis(500);
pub(crate) const LIMIT: u64 = 128;

pub(crate) fn context(config: &OriginalCellQ24MaterialReceiptConfigV1) -> Result<Digest32, Error> {
    let at = SystemTime::now().duration_since(UNIX_EPOCH)
        .map_err(|_| Error::Unavailable)?.as_secs();
    OriginalCellQ24MaterialReceiptConfigV1::original_source_loan_binding(config, at)
        .map_err(|_| Error::InvalidBinding)
}

pub(crate) fn before(end: Instant) -> Result<(), Error> {
    if Instant::now() >= end { return Err(Error::DeadlineExceeded); }
    Ok(())
}

pub(crate) fn bounded(bytes: &[u8]) -> Result<(), Error> {
    if bytes.is_empty() || bytes.len() > BOUND { return Err(Error::InvalidBinding); }
    Ok(())
}

pub(crate) fn request(binding: Digest32, nonce: [u8; 16], id: u64) -> Result<Vec<u8>, Error> {
    if binding.is_zero() || nonce == [0; 16] || !(1..=LIMIT).contains(&id) {
        return Err(Error::InvalidBinding);
    }
    let mut bytes = b"HCMATRD1".to_vec();
    bytes.extend_from_slice(binding.as_array());
    bytes.extend_from_slice(&nonce);
    bytes.extend_from_slice(&id.to_be_bytes());
    Ok(bytes)
}

pub(crate) fn response(request: &[u8], payload: &[u8]) -> Result<Vec<u8>, Error> {
    let mut bytes = request.to_vec();
    bytes.extend_from_slice(payload);
    bounded(&bytes)?;
    Ok(bytes)
}

pub(crate) fn read_response<'a>(request: &[u8], response: &'a [u8]) -> Result<&'a [u8], Error> {
    bounded(response)?;
    response.strip_prefix(request).filter(|payload| !payload.is_empty())
        .ok_or(Error::InvalidBinding)
}
