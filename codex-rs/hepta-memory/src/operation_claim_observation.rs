//! Read the original append-only dispatch claim chain without renewing a claim.
use super::*;

pub(crate) struct ObservedDispatchClaim {
    pub(crate) receipt: DurableDispatchClaim,
    pub(crate) state: &'static str,
}

/// The scope reader performs a shared byte/count preflight in this transaction.
/// A separate row ceiling prevents this internal primitive from reading an
/// unbounded number of claims even when reused by another original owner.
pub(crate) async fn observe_claims(
    transaction: &mut Transaction<'_, Sqlite>,
    operation_id: &str,
) -> Result<Vec<ObservedDispatchClaim>, LocalLeaseOutboxError> {
    let (count, bytes): (i64, i64) = sqlx::query_as(
        "SELECT COUNT(*), COALESCE(SUM(length(CAST(fencing_token AS BLOB)) +
            length(CAST(claim_state AS BLOB)) + length(CAST(previous_sha256 AS BLOB)) +
            length(CAST(claim_sha256 AS BLOB)) + 56), 0)
         FROM cognitive_operation_dispatch_claims WHERE operation_id = ?",
    ).bind(operation_id).fetch_one(&mut **transaction).await
        .map_err(crate::cognitive_store::unavailable)?;
    if count < 0 || count > 32768 || bytes < 0 || bytes > 64 * 1024 * 1024 {
        return Err(LocalLeaseOutboxError::CapacityExceeded {
            resource: "original dispatch claim observation", maximum: 32768,
        });
    }
    let rows = sqlx::query(
        "SELECT claim_sequence, attempt, owner_generation, fencing_token, claim_state,
            lease_expires_at_unix_ms, next_eligible_at_unix_ms, previous_sha256,
            claim_sha256, recorded_at_unix_ms
         FROM cognitive_operation_dispatch_claims WHERE operation_id = ?
         ORDER BY claim_sequence LIMIT 32769",
    ).bind(operation_id).fetch_all(&mut **transaction).await
        .map_err(crate::cognitive_store::unavailable)?;
    if rows.len() as i64 != count {
        return Err(LocalLeaseOutboxError::Corrupt("dispatch claim snapshot changed".to_owned()));
    }
    let mut result = Vec::with_capacity(rows.len());
    let mut previous: Option<ClaimRow> = None;
    for row in rows {
        let recorded_at = read_u64(&row, "recorded_at_unix_ms")?;
        let current = ClaimRow {
            claim_sequence: read_u64(&row, "claim_sequence")?,
            attempt: u32::try_from(read_u64(&row, "attempt")?).map_err(|_| invalid_chain())?,
            owner_generation: read_u64(&row, "owner_generation")?,
            fencing_token: row.try_get("fencing_token").map_err(crate::cognitive_store::unavailable)?,
            state: ClaimState::parse(row.try_get::<String, _>("claim_state")
                .map_err(crate::cognitive_store::unavailable)?.as_str())?,
            lease_expires_at_unix_ms: read_u64(&row, "lease_expires_at_unix_ms")?,
            next_eligible_at_unix_ms: read_u64(&row, "next_eligible_at_unix_ms")?,
            claim_sha256: Sha256Digest::parse(row.try_get::<String, _>("claim_sha256")
                .map_err(crate::cognitive_store::unavailable)?)
                .map_err(LocalLeaseOutboxError::Corrupt)?,
        };
        let original_previous = Sha256Digest::parse(row.try_get::<String, _>("previous_sha256")
            .map_err(crate::cognitive_store::unavailable)?)
            .map_err(LocalLeaseOutboxError::Corrupt)?;
        let expected_previous = previous.as_ref().map(|item| item.claim_sha256.clone())
            .unwrap_or_else(|| Sha256Digest::for_bytes(CLAIM_GENESIS));
        let expected_sequence = previous.as_ref().map(|item| item.claim_sequence).unwrap_or(0)
            .checked_add(1).ok_or_else(invalid_chain)?;
        if current.claim_sequence != expected_sequence || original_previous != expected_previous
            || current.claim_sha256 != claim_digest(operation_id, current.claim_sequence,
                current.attempt, current.owner_generation, &current.fencing_token, current.state,
                current.lease_expires_at_unix_ms, current.next_eligible_at_unix_ms, &expected_previous)
            || current.attempt == 0 || current.attempt > MAX_DURABLE_DISPATCH_ATTEMPTS
            || current.owner_generation == 0 || current.fencing_token.trim().is_empty()
            || current.fencing_token.len() > 256 || recorded_at == 0
            || current.next_eligible_at_unix_ms != current.lease_expires_at_unix_ms
                .checked_add(retry_backoff_ms(current.attempt)).ok_or_else(invalid_chain)? {
            return Err(invalid_chain());
        }
        verify_transition(previous.as_ref(), &current, recorded_at)?;
        result.push(ObservedDispatchClaim {
            receipt: to_receipt(operation_id, &current), state: current.state.as_str(),
        });
        previous = Some(current);
    }
    Ok(result)
}

fn verify_transition(previous: Option<&ClaimRow>, current: &ClaimRow, recorded_at: u64)
    -> Result<(), LocalLeaseOutboxError> {
    let Some(previous) = previous else {
        if current.state != ClaimState::Claimed || current.attempt != 1 {
            return Err(invalid_chain());
        }
        return verify_new_expiry(current, recorded_at);
    };
    let unentered = matches!(previous.state, ClaimState::Claimed | ClaimState::Renewed);
    let same_owner = current.attempt == previous.attempt
        && current.owner_generation == previous.owner_generation
        && current.fencing_token == previous.fencing_token;
    let same_deadline = current.lease_expires_at_unix_ms == previous.lease_expires_at_unix_ms
        && current.next_eligible_at_unix_ms == previous.next_eligible_at_unix_ms;
    match current.state {
        ClaimState::Claimed if unentered && current.owner_generation > previous.owner_generation
            && current.attempt == previous.attempt.checked_add(1).ok_or_else(invalid_chain)?
            && recorded_at >= previous.next_eligible_at_unix_ms => verify_new_expiry(current, recorded_at),
        ClaimState::Renewed if unentered && same_owner && recorded_at < previous.lease_expires_at_unix_ms
            && current.lease_expires_at_unix_ms > previous.lease_expires_at_unix_ms => verify_new_expiry(current, recorded_at),
        ClaimState::Entered if unentered && same_owner && same_deadline
            && recorded_at < current.lease_expires_at_unix_ms => Ok(()),
        // Original observer settlement also permits Claimed/Renewed -> Settled.
        ClaimState::Settled if previous.state != ClaimState::Settled && same_owner && same_deadline => Ok(()),
        _ => Err(invalid_chain()),
    }
}

fn verify_new_expiry(current: &ClaimRow, recorded_at: u64) -> Result<(), LocalLeaseOutboxError> {
    let duration = current.lease_expires_at_unix_ms.checked_sub(recorded_at).ok_or_else(invalid_chain)?;
    if duration == 0 || duration > MAX_DURABLE_CLAIM_LEASE_MS { return Err(invalid_chain()); }
    Ok(())
}
fn invalid_chain() -> LocalLeaseOutboxError {
    LocalLeaseOutboxError::Corrupt("original dispatch claim chain or transition is invalid".to_owned())
}
