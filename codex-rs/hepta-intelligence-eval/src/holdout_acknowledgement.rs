//! An existing independent Observer attests when it received the original
//! durable reservation ACK. Host CAS clock alone does not prove fsync completed
//! before a future window; these are different observations.
use codex_hepta_types::Digest32;

use crate::CrossFoldPlanReceiptV1;
use crate::FencedHoldoutError;
use crate::FinalHoldoutJournalReceiptV1;
use crate::HoldoutWriterFenceV1;

/// Canonical evidence bytes, never acquisition or selection authority. The
/// observer must retain its actual ACK receive time and sign with its existing
/// Observer role. Replaying a reservation cannot manufacture a past ACK.
pub fn holdout_reservation_acknowledgement_payload_v1(
    binding: Digest32,
    fence: &HoldoutWriterFenceV1,
    plan: &CrossFoldPlanReceiptV1,
    receipt: &FinalHoldoutJournalReceiptV1,
    received_at_unix_micros: u64,
) -> Result<Vec<u8>, FencedHoldoutError> {
    let time = receipt
        .reservation_time
        .ok_or(FencedHoldoutError::Binding)?;
    if binding.is_zero()
        || fence.generation == 0
        || fence.lease_digest.is_zero()
        || receipt.authority.grants_any()
        || receipt.sequence == 0
        || receipt.record_digest.is_zero()
        || receipt.use_receipt.plan_digest != plan.plan_digest
        || receipt.use_receipt.holdout_digest != plan.final_holdout_digest
        || received_at_unix_micros < time.reserved_at_unix_micros()
        || received_at_unix_micros >= time.window_not_before_unix_micros()
    {
        return Err(FencedHoldoutError::Binding);
    }
    let encoded_plan =
        crate::closure::encode_holdout_plan(plan).map_err(|_| FencedHoldoutError::Binding)?;
    let owner = fence.owner_id.as_str().as_bytes();
    let mut bytes = b"hepta.intelligence-eval.durable-holdout-acknowledgement.v1\0".to_vec();
    bytes.extend_from_slice(binding.as_array());
    bytes.extend_from_slice(&(owner.len() as u64).to_be_bytes());
    bytes.extend_from_slice(owner);
    bytes.extend_from_slice(&fence.generation.to_be_bytes());
    bytes.extend_from_slice(fence.lease_digest.as_array());
    bytes.extend_from_slice(&receipt.sequence.to_be_bytes());
    bytes.extend_from_slice(receipt.record_digest.as_array());
    bytes.extend_from_slice(receipt.use_receipt.use_digest.as_array());
    bytes.extend_from_slice(&time.reserved_at_unix_micros().to_be_bytes());
    bytes.extend_from_slice(&time.window_not_before_unix_micros().to_be_bytes());
    bytes.extend_from_slice(&received_at_unix_micros.to_be_bytes());
    bytes.extend_from_slice(&(encoded_plan.len() as u64).to_be_bytes());
    bytes.extend_from_slice(&encoded_plan);
    Ok(bytes)
}
