use codex_hepta_types::{AuthorityPosture, Digest32};

use crate::{
    convert_z_to_original_q24, AdmittedZConversionProfileV1,
    ZQ24ConversionReceiptV1,
};

use super::{canonical_f64_bits, require_digest, NduEvidenceV2Error};

#[derive(Clone, Debug, PartialEq)]
pub struct ZQ24ConversionReceiptV2 {
    source_z: Vec<Vec<f64>>,
    original_z: Vec<Vec<f64>>,
    q24_raw: Vec<Vec<i64>>,
    maximum_absolute_quantization_error: f64,
    profile_digest: Digest32,
    source_digest: Digest32,
    legacy_receipt_digest: Digest32,
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
    pub const fn legacy_receipt_digest(&self) -> Digest32 {
        self.legacy_receipt_digest
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
    ) -> Result<(), NduEvidenceV2Error> {
        require_digest(self.profile_digest, "profile")?;
        require_digest(self.source_digest, "source")?;
        require_digest(self.legacy_receipt_digest, "legacy receipt")?;
        require_digest(self.receipt_digest, "receipt")?;
        if self.authority != AuthorityPosture::DENY_ALL
            || self.profile_digest != profile.digest()
            || !self.maximum_absolute_quantization_error.is_finite()
            || self.maximum_absolute_quantization_error < 0.0
        {
            return Err(NduEvidenceV2Error::InvalidReceipt);
        }
        let legacy = rebuild_legacy(&self.source_z, self.source_digest, profile)?;
        if legacy.original_z != self.original_z
            || legacy.q24_raw != self.q24_raw
            || canonical_f64_bits(legacy.maximum_absolute_quantization_error)
                != canonical_f64_bits(self.maximum_absolute_quantization_error)
            || legacy.profile_digest != self.profile_digest
            || legacy.receipt_digest != self.legacy_receipt_digest
            || legacy.authority != self.authority
        {
            return Err(NduEvidenceV2Error::InvalidReceipt);
        }
        let expected = digest_v2(
            &self.source_z,
            &self.original_z,
            &self.q24_raw,
            self.maximum_absolute_quantization_error,
            self.profile_digest,
            self.source_digest,
            self.legacy_receipt_digest,
        );
        if expected != self.receipt_digest {
            return Err(NduEvidenceV2Error::DigestMismatch);
        }
        Ok(())
    }
}

pub fn validate_z_q24_receipt_v1(
    receipt: &ZQ24ConversionReceiptV1,
    source_z: &[Vec<f64>],
    profile: &AdmittedZConversionProfileV1,
) -> Result<(), NduEvidenceV2Error> {
    require_digest(receipt.profile_digest, "profile")?;
    require_digest(receipt.source_digest, "source")?;
    require_digest(receipt.receipt_digest, "receipt")?;
    if receipt.authority != AuthorityPosture::DENY_ALL
        || receipt.profile_digest != profile.digest()
    {
        return Err(NduEvidenceV2Error::InvalidLegacyReceipt);
    }
    let rebuilt = rebuild_legacy(source_z, receipt.source_digest, profile)?;
    if rebuilt.original_z != receipt.original_z
        || rebuilt.q24_raw != receipt.q24_raw
        || canonical_f64_bits(rebuilt.maximum_absolute_quantization_error)
            != canonical_f64_bits(receipt.maximum_absolute_quantization_error)
        || rebuilt.profile_digest != receipt.profile_digest
        || rebuilt.receipt_digest != receipt.receipt_digest
        || rebuilt.authority != receipt.authority
    {
        return Err(NduEvidenceV2Error::InvalidLegacyReceipt);
    }
    Ok(())
}

pub fn migrate_z_q24_receipt_v1(
    receipt: &ZQ24ConversionReceiptV1,
    source_z: &[Vec<f64>],
    profile: &AdmittedZConversionProfileV1,
) -> Result<ZQ24ConversionReceiptV2, NduEvidenceV2Error> {
    validate_z_q24_receipt_v1(receipt, source_z, profile)?;
    let migrated = ZQ24ConversionReceiptV2 {
        source_z: source_z.to_vec(),
        original_z: receipt.original_z.clone(),
        q24_raw: receipt.q24_raw.clone(),
        maximum_absolute_quantization_error: receipt.maximum_absolute_quantization_error,
        profile_digest: receipt.profile_digest,
        source_digest: receipt.source_digest,
        legacy_receipt_digest: receipt.receipt_digest,
        receipt_digest: digest_v2(
            source_z,
            &receipt.original_z,
            &receipt.q24_raw,
            receipt.maximum_absolute_quantization_error,
            receipt.profile_digest,
            receipt.source_digest,
            receipt.receipt_digest,
        ),
        authority: AuthorityPosture::DENY_ALL,
    };
    migrated.validate(profile)?;
    Ok(migrated)
}

pub fn convert_z_to_original_q24_v2(
    source_z: &[Vec<f64>],
    source_digest: Digest32,
    profile: &AdmittedZConversionProfileV1,
) -> Result<ZQ24ConversionReceiptV2, NduEvidenceV2Error> {
    let legacy = rebuild_legacy(source_z, source_digest, profile)?;
    migrate_z_q24_receipt_v1(&legacy, source_z, profile)
}

fn rebuild_legacy(
    source_z: &[Vec<f64>],
    source_digest: Digest32,
    profile: &AdmittedZConversionProfileV1,
) -> Result<ZQ24ConversionReceiptV1, NduEvidenceV2Error> {
    convert_z_to_original_q24(source_z, source_digest, profile)
        .map_err(|_| NduEvidenceV2Error::InvalidLegacyReceipt)
}

#[allow(clippy::too_many_arguments)]
fn digest_v2(
    source_z: &[Vec<f64>],
    original_z: &[Vec<f64>],
    q24_raw: &[Vec<i64>],
    maximum_absolute_quantization_error: f64,
    profile_digest: Digest32,
    source_digest: Digest32,
    legacy_receipt_digest: Digest32,
) -> Digest32 {
    let mut bytes = b"hepta.ndu.z-coordinate-q24-receipt.v2\0".to_vec();
    bytes.extend_from_slice(profile_digest.as_array());
    bytes.extend_from_slice(source_digest.as_array());
    bytes.extend_from_slice(legacy_receipt_digest.as_array());
    push_matrix_shape(&mut bytes, source_z);
    for value in source_z.iter().flatten() {
        bytes.extend_from_slice(&canonical_f64_bits(*value).to_be_bytes());
    }
    push_matrix_shape(&mut bytes, original_z);
    for value in original_z.iter().flatten() {
        bytes.extend_from_slice(&canonical_f64_bits(*value).to_be_bytes());
    }
    bytes.extend_from_slice(
        &u32::try_from(q24_raw.len())
            .unwrap_or(u32::MAX)
            .to_be_bytes(),
    );
    for row in q24_raw {
        bytes.extend_from_slice(
            &u32::try_from(row.len())
                .unwrap_or(u32::MAX)
                .to_be_bytes(),
        );
        for raw in row {
            bytes.extend_from_slice(&raw.to_be_bytes());
        }
    }
    bytes.extend_from_slice(
        &canonical_f64_bits(maximum_absolute_quantization_error).to_be_bytes(),
    );
    bytes.push(0);
    Digest32::of_bytes(&bytes)
}

fn push_matrix_shape(bytes: &mut Vec<u8>, matrix: &[Vec<f64>]) {
    bytes.extend_from_slice(
        &u32::try_from(matrix.len())
            .unwrap_or(u32::MAX)
            .to_be_bytes(),
    );
    for row in matrix {
        bytes.extend_from_slice(
            &u32::try_from(row.len())
                .unwrap_or(u32::MAX)
                .to_be_bytes(),
        );
    }
}

#[cfg(test)]
mod tests {
    use crate::{
        admit_z_conversion_profile, NduZConversionProfileV1,
        ZCoordinateConventionV1,
    };

    use super::*;

    fn digest(value: &str) -> Digest32 {
        Digest32::of_bytes(value.as_bytes())
    }

    #[test]
    fn v2_keeps_source_and_rejects_mutated_legacy_fields() {
        let profile = admit_z_conversion_profile(NduZConversionProfileV1 {
            units_digest: digest("units"),
            driver_dimension: 2,
            utility_dimension: 1,
            source_coordinates: ZCoordinateConventionV1::OriginalIncrement,
            whitening_lower: Vec::new(),
            maximum_absolute_z: 8.0,
        })
        .expect("profile");
        let source_z = vec![vec![0.25, -0.5]];
        let source_digest = digest("source");
        let legacy = convert_z_to_original_q24(
            &source_z,
            source_digest,
            &profile,
        )
        .expect("legacy");
        let migrated = migrate_z_q24_receipt_v1(
            &legacy,
            &source_z,
            &profile,
        )
        .expect("migration");
        migrated.validate(&profile).expect("valid v2");

        let mut corrupted = legacy;
        corrupted.q24_raw[0][0] += 1;
        assert_eq!(
            validate_z_q24_receipt_v1(&corrupted, &source_z, &profile),
            Err(NduEvidenceV2Error::InvalidLegacyReceipt)
        );
    }
}
