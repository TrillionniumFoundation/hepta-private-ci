//! Validate the retained claim chain before protected external entry.

use super::*;
use futures::TryStreamExt;

/// Read the complete original claim chain through the caller's held lock.
/// Streaming keeps memory bounded even for a repeatedly renewed lease.
pub(crate) async fn require_entered_transaction(
    transaction: &mut Transaction<'_, Sqlite>,
    store: &CognitiveStore,
    entered: &DurableDispatchClaim,
) -> Result<(), LocalLeaseOutboxError> {
    verify_operation_fence(
        transaction,
        store,
        &entered.operation_id,
        entered.owner_generation,
        &entered.fencing_token,
    )
    .await?;
    let mut rows = sqlx::query(
        "SELECT claim_sequence, attempt, owner_generation, fencing_token, claim_state,
                lease_expires_at_unix_ms, next_eligible_at_unix_ms, previous_sha256, claim_sha256
         FROM cognitive_operation_dispatch_claims WHERE operation_id = ? ORDER BY claim_sequence",
    )
    .bind(&entered.operation_id)
    .fetch(&mut **transaction);
    let mut previous = Sha256Digest::for_bytes(CLAIM_GENESIS);
    let mut sequence = 0_u64;
    let mut head = None;
    while let Some(row) = rows
        .try_next()
        .await
        .map_err(crate::cognitive_store::unavailable)?
    {
        sequence = sequence.checked_add(1).ok_or_else(|| {
            LocalLeaseOutboxError::Corrupt("dispatch claim sequence overflow".to_string())
        })?;
        let current = ClaimRow {
            claim_sequence: read_u64(&row, "claim_sequence")?,
            attempt: u32::try_from(read_u64(&row, "attempt")?).map_err(|_| {
                LocalLeaseOutboxError::Corrupt("dispatch claim attempt overflow".to_string())
            })?,
            owner_generation: read_u64(&row, "owner_generation")?,
            fencing_token: row
                .try_get("fencing_token")
                .map_err(crate::cognitive_store::unavailable)?,
            state: ClaimState::parse(
                row.try_get::<&str, _>("claim_state")
                    .map_err(crate::cognitive_store::unavailable)?,
            )?,
            lease_expires_at_unix_ms: read_u64(&row, "lease_expires_at_unix_ms")?,
            next_eligible_at_unix_ms: read_u64(&row, "next_eligible_at_unix_ms")?,
            claim_sha256: Sha256Digest::parse(
                row.try_get::<String, _>("claim_sha256")
                    .map_err(crate::cognitive_store::unavailable)?,
            )
            .map_err(LocalLeaseOutboxError::Corrupt)?,
        };
        if current.claim_sequence != sequence
            || sequence > entered.claim_sequence
            || row
                .try_get::<&str, _>("previous_sha256")
                .map_err(crate::cognitive_store::unavailable)?
                != previous.as_str()
            || current.claim_sha256
                != claim_digest(
                    &entered.operation_id,
                    sequence,
                    current.attempt,
                    current.owner_generation,
                    &current.fencing_token,
                    current.state,
                    current.lease_expires_at_unix_ms,
                    current.next_eligible_at_unix_ms,
                    &previous,
                )
        {
            return Err(LocalLeaseOutboxError::Corrupt(
                "dispatch claim chain differs from retained entry".to_string(),
            ));
        }
        previous = current.claim_sha256.clone();
        head = Some(current);
    }
    let head = head
        .ok_or_else(|| LocalLeaseOutboxError::StaleFence("entered claim is absent".to_string()))?;
    if head.state != ClaimState::Entered || to_receipt(&entered.operation_id, &head) != *entered {
        return Err(LocalLeaseOutboxError::StaleFence(
            "complete entered claim differs from its retained head".to_string(),
        ));
    }
    Ok(())
}
