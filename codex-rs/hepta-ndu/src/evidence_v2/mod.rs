mod iteration;
mod z;

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::{Digest32, StableId};

pub use iteration::{
    bind_solver_iteration_receipt_v2, migrate_iteration_receipt_v1,
    validate_iteration_receipt_v1, NduIterationReceiptV2,
};
pub use z::{
    convert_z_to_original_q24_v2, migrate_z_q24_receipt_v1,
    validate_z_q24_receipt_v1, ZQ24ConversionReceiptV2,
};

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum NduEvidenceV2Error {
    EmptyDigest(&'static str),
    InvalidLegacyReceipt,
    InvalidReceipt,
    ContextMismatch,
    Dimension,
    NonFinite,
    Quantization,
    DigestMismatch,
}

impl fmt::Display for NduEvidenceV2Error {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for NduEvidenceV2Error {}

pub(crate) fn require_digest(
    digest: Digest32,
    field: &'static str,
) -> Result<(), NduEvidenceV2Error> {
    if digest.is_zero() {
        Err(NduEvidenceV2Error::EmptyDigest(field))
    } else {
        Ok(())
    }
}

pub(crate) fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    let raw = value.as_str().as_bytes();
    bytes.extend_from_slice(
        &u32::try_from(raw.len())
            .unwrap_or(u32::MAX)
            .to_be_bytes(),
    );
    bytes.extend_from_slice(raw);
}

pub(crate) fn canonical_f64_bits(value: f64) -> u64 {
    if value == 0.0 {
        0.0_f64.to_bits()
    } else {
        value.to_bits()
    }
}
