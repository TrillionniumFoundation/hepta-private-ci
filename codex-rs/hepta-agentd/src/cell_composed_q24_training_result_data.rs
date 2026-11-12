//! Shared exact HQ24TRES header parsing for the original writer and data-only
//! remote observation. This parser does not create an owner or a receipt.

use super::*;

pub(super) const PREFIX_BYTES: usize = 221;

pub(super) struct OriginalResultHeader {
    pub(super) binding: Digest32,
    pub(super) tag: u8,
    pub(super) bundle_digest: Digest32,
    pub(super) metrics: CellQ24TrainingMetricsV1,
    pub(super) length: usize,
}

pub(super) fn decode_header(bytes: &mut &[u8]) -> Result<OriginalResultHeader, Error> {
    if take::<8>(bytes)? != *b"HQ24TRES" {
        return Err(Error::Binding("training result and original job"));
    }
    Ok(OriginalResultHeader {
        binding: Digest32::from_array(take::<32>(bytes)?),
        tag: take::<1>(bytes)?[0],
        bundle_digest: Digest32::from_array(take::<32>(bytes)?),
        metrics: CellQ24TrainingMetricsV1 {
            batch_digest: Digest32::from_array(take::<32>(bytes)?),
            optimizer_rule: Digest32::from_array(take::<32>(bytes)?),
            update_rule: Digest32::from_array(take::<32>(bytes)?),
            optimizer_steps: u64::from_le_bytes(take::<8>(bytes)?),
            squared_error_before_q48: u128::from_le_bytes(take::<16>(bytes)?),
            squared_error_after_q48: u128::from_le_bytes(take::<16>(bytes)?),
            elapsed_microseconds: u64::from_le_bytes(take::<8>(bytes)?),
        },
        length: u32::from_le_bytes(take::<4>(bytes)?) as usize,
    })
}
