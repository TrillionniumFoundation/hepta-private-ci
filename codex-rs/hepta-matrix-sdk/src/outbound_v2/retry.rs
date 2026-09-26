use super::*;

pub(super) async fn release_pre_entry_claims(
    store: &MatrixDurableStore,
    claims: &[MatrixFencedOutboxClaim],
    clock: &DispatchClock,
    first_authority_denied: bool,
) -> Result<(), OutboxDispatchError> {
    let mut first_error = None;
    for (index, claim) in claims.iter().enumerate() {
        let now_ms = clock.now_ms()?;
        let result = if first_authority_denied && index == 0 {
            store.release_outbox_claim_revoked(claim, now_ms).await
        } else {
            store.release_outbox_claim_canceled(claim, now_ms).await
        };
        match result {
            Ok(()) => {}
            // A reclaimed expired capability cannot release its new owner.
            // Reclamation already records expiry; do not invent a new lease.
            Err(MatrixDurableError::Conflict) if now_ms >= claim.lease_until_ms() => {}
            Err(error) => {
                first_error.get_or_insert(store_error(error));
            }
        }
    }
    // Try every unentered claim even if an earlier cleanup conflicts.
    first_error.map_or(Ok(()), Err)
}

pub(super) fn system_time_ms() -> Result<u64, OutboxDispatchError> {
    let millis = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|_| OutboxDispatchError::Invalid)?
        .as_millis();
    u64::try_from(millis).map_err(|_| OutboxDispatchError::Invalid)
}

pub(super) fn reconciliation_attempt_at(
    config: &OutboxDispatchConfig,
    record: &OutboxRecord,
    now_ms: u64,
) -> Result<u64, OutboxDispatchError> {
    if record.attempts >= config.max_attempts {
        return Ok(PARKED_RECONCILIATION_AT_MS);
    }
    let delay = retry_delay_ms(config, record.attempts)?;
    now_ms
        .checked_add(
            delay
                .saturating_add(stable_jitter_ms(record, delay))
                .min(config.max_retry_delay_ms),
        )
        .ok_or(OutboxDispatchError::Invalid)
}

pub(super) fn classified_retry_at(
    config: &OutboxDispatchConfig,
    record: &OutboxRecord,
    now_ms: u64,
    error: MatrixTransportError,
) -> Result<u64, OutboxDispatchError> {
    if record.attempts >= config.max_attempts {
        return Ok(PARKED_RECONCILIATION_AT_MS);
    }
    let base = match error {
        MatrixTransportError::RateLimited { retry_after_ms } => {
            let required = retry_after_ms.max(config.retry_delay_ms);
            if required > config.max_retry_delay_ms {
                return Ok(PARKED_RECONCILIATION_AT_MS);
            }
            required
        }
        MatrixTransportError::Retryable
        | MatrixTransportError::Dns
        | MatrixTransportError::Tls
        | MatrixTransportError::ConnectTimeout
        | MatrixTransportError::ConnectFailure
        | MatrixTransportError::ReadTimeout
        | MatrixTransportError::ConnectionReset
        | MatrixTransportError::ResponseLost
        | MatrixTransportError::ServerUnavailable => {
            retry_delay_ms(config, record.attempts)?
        }
        MatrixTransportError::Permanent => return Err(OutboxDispatchError::Invalid),
    };
    let delay = base
        .saturating_add(stable_jitter_ms(record, base))
        .min(config.max_retry_delay_ms);
    now_ms.checked_add(delay).ok_or(OutboxDispatchError::Invalid)
}

pub(super) fn retry_delay_ms(
    config: &OutboxDispatchConfig,
    attempts: u64,
) -> Result<u64, OutboxDispatchError> {
    let exponent = u32::try_from(attempts.saturating_sub(1).min(63))
        .map_err(|_| OutboxDispatchError::Invalid)?;
    Ok(config
        .retry_delay_ms
        .saturating_mul(1_u64.checked_shl(exponent).unwrap_or(u64::MAX))
        .min(config.max_retry_delay_ms))
}

pub(super) fn stable_jitter_ms(record: &OutboxRecord, delay_ms: u64) -> u64 {
    let ceiling = delay_ms.saturating_div(5).min(1_000);
    if ceiling == 0 {
        return 0;
    }
    let mut state = record.attempts ^ 0xcbf29ce484222325;
    for byte in record.stable_txn_id.as_str().bytes() {
        state ^= u64::from(byte);
        state = state.wrapping_mul(0x100000001b3);
    }
    state % (ceiling + 1)
}

pub(super) fn count_retry(stats: &mut OutboxDispatchStats, next_attempt_at_ms: u64) {
    if next_attempt_at_ms == PARKED_RECONCILIATION_AT_MS {
        stats.indeterminate += 1;
    } else {
        stats.retry_scheduled += 1;
    }
}

pub(super) fn failure_class(error: MatrixTransportError) -> MatrixAttemptFailureClass {
    match error {
        MatrixTransportError::Retryable => MatrixAttemptFailureClass::Retryable,
        MatrixTransportError::RateLimited { .. } => MatrixAttemptFailureClass::RateLimited,
        MatrixTransportError::Dns => MatrixAttemptFailureClass::Dns,
        MatrixTransportError::Tls => MatrixAttemptFailureClass::Tls,
        MatrixTransportError::ConnectTimeout => MatrixAttemptFailureClass::ConnectTimeout,
        MatrixTransportError::ConnectFailure => MatrixAttemptFailureClass::ConnectFailure,
        MatrixTransportError::ReadTimeout => MatrixAttemptFailureClass::ReadTimeout,
        MatrixTransportError::ConnectionReset => MatrixAttemptFailureClass::ConnectionReset,
        MatrixTransportError::ResponseLost => MatrixAttemptFailureClass::ResponseLost,
        MatrixTransportError::ServerUnavailable => MatrixAttemptFailureClass::ServerUnavailable,
        MatrixTransportError::Permanent => MatrixAttemptFailureClass::Permanent,
    }
}

pub(super) fn retry_after_hint(error: MatrixTransportError) -> Option<u64> {
    match error {
        MatrixTransportError::RateLimited { retry_after_ms } => Some(retry_after_ms),
        _ => None,
    }
}

pub(super) fn hex_digest(value: [u8; 32]) -> String {
    const HEX: &[u8; 16] = b"0123456789abcdef";
    let mut output = String::with_capacity(64);
    for byte in value {
        output.push(char::from(HEX[usize::from(byte >> 4)]));
        output.push(char::from(HEX[usize::from(byte & 0x0f)]));
    }
    output
}

pub(super) fn authority_error(_: MatrixAuthorityError) -> OutboxDispatchError {
    OutboxDispatchError::Authority
}

pub(super) fn store_error(_: MatrixDurableError) -> OutboxDispatchError {
    OutboxDispatchError::Store
}
