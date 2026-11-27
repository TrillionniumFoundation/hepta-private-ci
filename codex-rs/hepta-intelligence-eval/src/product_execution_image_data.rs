//! Decode an already observed physical image using the original HEPTEX01
//! grammar. This pure DATA projection takes no file, writer, lock or witness
//! custody and cannot establish that an evaluator acknowledged the image.

use super::*;

/// Project one opaque state from an exact, externally supplied journal cut.
///
/// This function performs no I/O and does not authenticate its input. A live
/// reader must bind the bytes to its original read-only descriptor, compare
/// complete physical reads and independently recheck the original witness and
/// scope. In particular, this does not replace the locked store's readback or
/// its sticky refusal state. Returned completion bytes remain unauthenticated
/// data until the original consumer verifies its signed admission.
pub fn decode_original_product_evaluation_execution_image_v1(
    bytes: &[u8],
    binding: Digest32,
    exact: ProductEvaluationExecutionAnchorV1,
    key: &ProductEvaluationExecutionKeyV1,
) -> Result<State, StoreError> {
    if binding.is_zero() || exact.history_digest.is_zero() || bytes.len() as u64 > MAX_FILE_BYTES {
        return Err(StoreError::Indeterminate);
    }
    let mut replayed =
        physical::replay_image(bytes, binding, exact).map_err(|_| StoreError::Indeterminate)?;
    if replayed.anchor != exact {
        return Err(StoreError::Indeterminate);
    }
    let (actual, state) = replayed
        .records
        .remove(&key.plan_id)
        .ok_or(StoreError::Missing)?;
    if actual != key.binding_digest {
        return Err(StoreError::Conflict);
    }
    Ok(state)
}

/// Project the bounded original records in one exact physical image.
///
/// This is data inspection for an independently admitted original file. It does
/// not acquire an owner or infer authentication from a header or witness. The
/// caller must authenticate each completed payload against its full original
/// operation, scope and signer. Pending records remain pending. At most 64
/// records can be returned; this does not widen the underlying journal format.
pub fn decode_original_product_evaluation_execution_records_v1(
    bytes: &[u8],
    binding: Digest32,
    exact: ProductEvaluationExecutionAnchorV1,
) -> Result<Vec<(ProductEvaluationExecutionKeyV1, State)>, StoreError> {
    if binding.is_zero() || exact.history_digest.is_zero() || bytes.len() as u64 > MAX_FILE_BYTES {
        return Err(StoreError::Indeterminate);
    }
    let replayed =
        physical::replay_image(bytes, binding, exact).map_err(|_| StoreError::Indeterminate)?;
    if replayed.anchor != exact || replayed.records.len() > 64 {
        return Err(StoreError::Indeterminate);
    }
    Ok(replayed
        .records
        .into_iter()
        .map(|(plan_id, (binding_digest, state))| {
            (
                ProductEvaluationExecutionKeyV1 {
                    plan_id,
                    binding_digest,
                },
                state,
            )
        })
        .collect())
}
