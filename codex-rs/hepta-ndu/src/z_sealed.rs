use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;

use crate::AdmittedZConversionProfileV1;
use crate::ZConversionError;
use crate::convert_z_to_original_q24;

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum ZSealedReceiptErrorV2 {
    Conversion(ZConversionError),
    InvalidReceipt,
}

impl fmt::Display for ZSealedReceiptErrorV2 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for ZSealedReceiptErrorV2 {}

impl From<ZConversionError> for ZSealedReceiptErrorV2 {
    fn from(error: ZConversionError) -> Self {
        Self::Conversion(error)
    }
}

/// Sealed Z conversion evidence. Unlike the source-compatible V1 receipt, V2
/// retains the exact source matrix and validates by recomputing every derived
/// field and the canonical digest.
#[derive(Clone, Debug, PartialEq)]
pub struct ZQ24ConversionReceiptV2 {
    source_z: Vec<Vec<f64>>,
    original_z: Vec<Vec<f64>>,
    q24_raw: Vec<Vec<i64>>,
    maximum_absolute_quantization_error: f64,
    profile_digest: Digest32,
    source_digest: Digest32,
    receipt_digest: Digest32,
    authority: AuthorityPosture,
}

impl ZQ24ConversionReceiptV2 {
    #[must_use]
    pub fn source_z(&self) -> &[Vec<f64>] {
        &self.source_z
    }

    #[must_use]
    pub fn original_z(&self) -> &[Vec<f64>] {
        &self.original_z
    }

    #[must_use]
    pub fn q24_raw(&self) -> &[Vec<i64>] {
        &self.q24_raw
    }

    #[must_use]
    pub fn maximum_absolute_quantization_error(&self) -> f64 {
        self.maximum_absolute_quantization_error
    }

    #[must_use]
    pub const fn profile_digest(&self) -> Digest32 {
        self.profile_digest
    }

    #[must_use]
    pub const fn source_digest(&self) -> Digest32 {
        self.source_digest
    }

    #[must_use]
    pub const fn receipt_digest(&self) -> Digest32 {
        self.receipt_digest
    }

    #[must_use]
    pub const fn authority(&self) -> AuthorityPosture {
        self.authority
    }

    pub fn validate(
        &self,
        profile: &AdmittedZConversionProfileV1,
    ) -> Result<(), ZSealedReceiptErrorV2> {
        if self.profile_digest != profile.digest()
            || self.profile_digest.is_zero()
            || self.source_digest.is_zero()
            || self.receipt_digest.is_zero()
            || self.authority != AuthorityPosture::DENY_ALL
        {
            return Err(ZSealedReceiptErrorV2::InvalidReceipt);
        }
        let recomputed = convert_z_to_original_q24(&self.source_z, self.source_digest, profile)?;
        if !matrix_f64_equal(&self.original_z, &recomputed.original_z)
            || self.q24_raw != recomputed.q24_raw
            || canonical_f64_bits(self.maximum_absolute_quantization_error)
                != canonical_f64_bits(recomputed.maximum_absolute_quantization_error)
        {
            return Err(ZSealedReceiptErrorV2::InvalidReceipt);
        }
        let expected = digest_v2_receipt(
            &self.source_z,
            &self.original_z,
            &self.q24_raw,
            self.maximum_absolute_quantization_error,
            self.profile_digest,
            self.source_digest,
        );
        if expected != self.receipt_digest {
            return Err(ZSealedReceiptErrorV2::InvalidReceipt);
        }
        Ok(())
    }
}

pub fn convert_z_to_original_q24_v2(
    source_z: &[Vec<f64>],
    source_digest: Digest32,
    profile: &AdmittedZConversionProfileV1,
) -> Result<ZQ24ConversionReceiptV2, ZSealedReceiptErrorV2> {
    let legacy = convert_z_to_original_q24(source_z, source_digest, profile)?;
    let receipt_digest = digest_v2_receipt(
        source_z,
        &legacy.original_z,
        &legacy.q24_raw,
        legacy.maximum_absolute_quantization_error,
        legacy.profile_digest,
        legacy.source_digest,
    );
    let receipt = ZQ24ConversionReceiptV2 {
        source_z: normalize_matrix(source_z),
        original_z: normalize_matrix(&legacy.original_z),
        q24_raw: legacy.q24_raw,
        maximum_absolute_quantization_error: canonical_f64(
            legacy.maximum_absolute_quantization_error,
        ),
        profile_digest: legacy.profile_digest,
        source_digest: legacy.source_digest,
        receipt_digest,
        authority: AuthorityPosture::DENY_ALL,
    };
    receipt.validate(profile)?;
    Ok(receipt)
}

pub fn migrate_z_q24_receipt_v1_to_v2(
    legacy: &crate::ZQ24ConversionReceiptV1,
    source_z: &[Vec<f64>],
    profile: &AdmittedZConversionProfileV1,
) -> Result<ZQ24ConversionReceiptV2, ZSealedReceiptErrorV2> {
    let recomputed = convert_z_to_original_q24(source_z, legacy.source_digest, profile)?;
    if legacy.profile_digest != recomputed.profile_digest
        || legacy.source_digest != recomputed.source_digest
        || legacy.receipt_digest != recomputed.receipt_digest
        || legacy.authority != AuthorityPosture::DENY_ALL
        || !matrix_f64_equal(&legacy.original_z, &recomputed.original_z)
        || legacy.q24_raw != recomputed.q24_raw
        || legacy.maximum_absolute_quantization_error.to_bits()
            != recomputed.maximum_absolute_quantization_error.to_bits()
    {
        return Err(ZSealedReceiptErrorV2::InvalidReceipt);
    }
    convert_z_to_original_q24_v2(source_z, legacy.source_digest, profile)
}

#[allow(clippy::too_many_arguments)]
fn digest_v2_receipt(
    source_z: &[Vec<f64>],
    original_z: &[Vec<f64>],
    q24_raw: &[Vec<i64>],
    maximum_absolute_quantization_error: f64,
    profile_digest: Digest32,
    source_digest: Digest32,
) -> Digest32 {
    let mut bytes = b"hepta.ndu.z-coordinate-q24-receipt.v2\0".to_vec();
    bytes.extend_from_slice(profile_digest.as_array());
    bytes.extend_from_slice(source_digest.as_array());
    push_f64_matrix(&mut bytes, source_z);
    push_f64_matrix(&mut bytes, original_z);
    push_i64_matrix(&mut bytes, q24_raw);
    bytes.extend_from_slice(
        &canonical_f64_bits(maximum_absolute_quantization_error).to_be_bytes(),
    );
    Digest32::of_bytes(&bytes)
}

fn normalize_matrix(matrix: &[Vec<f64>]) -> Vec<Vec<f64>> {
    matrix
        .iter()
        .map(|row| row.iter().map(|value| canonical_f64(*value)).collect())
        .collect()
}

fn matrix_f64_equal(left: &[Vec<f64>], right: &[Vec<f64>]) -> bool {
    left.len() == right.len()
        && left.iter().zip(right).all(|(left_row, right_row)| {
            left_row.len() == right_row.len()
                && left_row
                    .iter()
                    .zip(right_row)
                    .all(|(left_value, right_value)| {
                        canonical_f64_bits(*left_value) == canonical_f64_bits(*right_value)
                    })
        })
}

fn push_f64_matrix(bytes: &mut Vec<u8>, matrix: &[Vec<f64>]) {
    push_len(bytes, matrix.len());
    for row in matrix {
        push_len(bytes, row.len());
        for value in row {
            bytes.extend_from_slice(&canonical_f64_bits(*value).to_be_bytes());
        }
    }
}

fn push_i64_matrix(bytes: &mut Vec<u8>, matrix: &[Vec<i64>]) {
    push_len(bytes, matrix.len());
    for row in matrix {
        push_len(bytes, row.len());
        for value in row {
            bytes.extend_from_slice(&value.to_be_bytes());
        }
    }
}

fn push_len(bytes: &mut Vec<u8>, length: usize) {
    bytes.extend_from_slice(&u32::try_from(length).unwrap_or(u32::MAX).to_be_bytes());
}

fn canonical_f64(value: f64) -> f64 {
    if value == 0.0 { 0.0 } else { value }
}

fn canonical_f64_bits(value: f64) -> u64 {
    canonical_f64(value).to_bits()
}

#[cfg(test)]
mod tests {
    #![allow(clippy::expect_used)]
    use super::*;
    use crate::NduZConversionProfileV1;
    use crate::ZCoordinateConventionV1;
    use crate::admit_z_conversion_profile;

    #[test]
    fn sealed_receipt_recomputes_all_fields_and_migrates_v1() {
        let profile = admit_z_conversion_profile(NduZConversionProfileV1 {
            units_digest: Digest32::of_bytes(b"units"),
            driver_dimension: 2,
            utility_dimension: 1,
            source_coordinates: ZCoordinateConventionV1::OriginalIncrement,
            whitening_lower: Vec::new(),
            maximum_absolute_z: 10.0,
        })
        .expect("profile");
        let source = vec![vec![-0.0, 1.25]];
        let legacy = convert_z_to_original_q24(
            &source,
            Digest32::of_bytes(b"source"),
            &profile,
        )
        .expect("legacy");
        let sealed = migrate_z_q24_receipt_v1_to_v2(&legacy, &source, &profile)
            .expect("migrated");
        sealed.validate(&profile).expect("valid sealed receipt");
        assert_eq!(sealed.source_z()[0][0].to_bits(), 0.0_f64.to_bits());
    }
}
