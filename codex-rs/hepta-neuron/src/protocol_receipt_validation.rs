//! Shared borrowed validation for owner receipt projection and registered DTOs.
//! Public caller-owned vectors are checked before canonical projection copies them.

use codex_hepta_types::Digest32;

use super::MAX_ACTIVATION_DIMENSION;
use super::MAX_ACTIVE_INDICES;
use super::NeuronProtocolError;
use super::NeuronTickReceiptProtocolV1;
use super::PPM;
use super::Q24_LIMIT;
use crate::NeuronTickReceiptV1;

pub(super) struct TickReceiptFields<'a> {
    checkpoint_after: Digest32,
    activation_digest: Digest32,
    threshold_digest: Digest32,
    eligibility_digest: Digest32,
    active_indices: &'a [u32],
    sparsity_ppm: u32,
    confidence_ppm: u32,
    ood_ppm: u32,
    prediction_error_q24: i64,
    checkpoint_bytes: u64,
}

impl<'a> From<&'a NeuronTickReceiptV1> for TickReceiptFields<'a> {
    fn from(value: &'a NeuronTickReceiptV1) -> Self {
        Self {
            checkpoint_after: value.checkpoint_after,
            activation_digest: value.activation_digest,
            threshold_digest: value.threshold_digest,
            eligibility_digest: value.eligibility_digest,
            active_indices: &value.active_indices,
            sparsity_ppm: value.sparsity_ppm,
            confidence_ppm: value.confidence_ppm,
            ood_ppm: value.ood_ppm,
            prediction_error_q24: value.prediction_error_q24,
            checkpoint_bytes: value.resource_receipt.checkpoint_bytes,
        }
    }
}

impl<'a> From<&'a NeuronTickReceiptProtocolV1> for TickReceiptFields<'a> {
    fn from(value: &'a NeuronTickReceiptProtocolV1) -> Self {
        Self {
            checkpoint_after: value.checkpoint_after,
            activation_digest: value.activation_digest,
            threshold_digest: value.threshold_digest,
            eligibility_digest: value.eligibility_digest,
            active_indices: &value.active_indices,
            sparsity_ppm: value.sparsity_ppm,
            confidence_ppm: value.confidence_ppm,
            ood_ppm: value.ood_ppm,
            prediction_error_q24: value.prediction_error_q24,
            checkpoint_bytes: value.checkpoint_bytes,
        }
    }
}

pub(super) fn validate_tick_receipt_fields(
    value: TickReceiptFields<'_>,
) -> Result<(), NeuronProtocolError> {
    for (field, digest) in [
        ("checkpointAfter", value.checkpoint_after),
        ("activationDigest", value.activation_digest),
        ("thresholdDigest", value.threshold_digest),
        ("eligibilityDigest", value.eligibility_digest),
    ] {
        if digest.is_zero() {
            return Err(NeuronProtocolError::InvalidDigest(field));
        }
    }
    if value.active_indices.len() > MAX_ACTIVE_INDICES
        || value
            .active_indices
            .iter()
            .any(|index| *index >= MAX_ACTIVATION_DIMENSION)
        || value
            .active_indices
            .windows(2)
            .any(|pair| pair[0] >= pair[1])
        || value.sparsity_ppm > PPM
        || value.active_indices.is_empty() != (value.sparsity_ppm == 0)
        || value.confidence_ppm > PPM
        || value.ood_ppm > PPM
        || !(0..=2 * Q24_LIMIT).contains(&value.prediction_error_q24)
        || value.checkpoint_bytes == 0
    {
        return Err(NeuronProtocolError::InvalidField("tick receipt"));
    }
    Ok(())
}
