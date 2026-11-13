//! Reuse the original complete Material binding for the sole read-only Source
//! lane. This validates/pins data and signers; it does not issue any authority.

use super::{Error, OriginalCellQ24MaterialReceiptConfigV1, wire};
use codex_hepta_types::Digest32;

impl OriginalCellQ24MaterialReceiptConfigV1 {
    pub(crate) fn original_source_loan_binding(&self, at: u64) -> Result<Digest32, Error> {
        wire::context_binding(self, at)
    }
}
