use serde::Serialize;
use sqlx::Row;

use crate::AuthBusOutboxError;
use crate::EvidenceError;
use crate::HeptaEvidenceStore;
use crate::authbus_outbox_record::AUTHBUS_OUTBOX_MAX_ATTEMPTS;
use crate::authbus_outbox_record::AUTHBUS_OUTBOX_MAX_ROWS;
use crate::schema_validation::classify_sqlx_error;
use crate::store::now_millis;

#[derive(Clone, Copy, Debug, Default, Eq, PartialEq, Serialize)]
pub struct AuthBusOutboxLatencySummary {
    pub count: u64,
    pub p50_ms: u64,
    pub p95_ms: u64,
    pub p99_ms: u64,
    pub max_ms: u64,
}

/// Bounded, non-secret delivery diagnostics owned by the Evidence outbox.
///
/// Claim counters and acknowledgement latency cover rows retained in the
/// bounded outbox table. Exporters should treat them as a current retained
/// window, not as process-lifetime monotonic counters.
#[derive(Clone, Copy, Debug, Default, Eq, PartialEq, Serialize)]
pub struct AuthBusOutboxOperationalSnapshot {
    pub observed_at_ms: u64,
    pub queued_deliveries: u64,
    pub leased_deliveries: u64,
    pub acknowledged_deliveries: u64,
    pub expired_deliveries: u64,
    pub quarantined_deliveries: u64,
    pub active_deliveries: u64,
    pub oldest_unsettled_age_ms: u64,
    pub retained_claim_attempts: u64,
    pub retained_claim_retries: u64,
    pub exhausted_active_deliveries: u64,
    pub acknowledgement_latency: AuthBusOutboxLatencySummary,
}

impl HeptaEvidenceStore {
    /// Read one consistent, bounded AuthBus outbox projection. This does not
    /// claim a delivery, renew a lease, acknowledge an effect, or mutate replay.
    pub async fn authbus_outbox_operational_snapshot(
        &self,
    ) -> Result<AuthBusOutboxOperationalSnapshot, AuthBusOutboxError> {
        let observed_at_ms = now_millis()?;
        let rows = sqlx::query(
            "SELECT state, attempts, created_at_ms, terminal_at_ms
             FROM authbus_outbox ORDER BY delivery_id LIMIT ?",
        )
        .bind(AUTHBUS_OUTBOX_MAX_ROWS + 1)
        .fetch_all(&self.pool)
        .await
        .map_err(classify_sqlx_error)?;
        if i64::try_from(rows.len()).unwrap_or(i64::MAX) > AUTHBUS_OUTBOX_MAX_ROWS {
            return Err(EvidenceError::Corrupt(
                "AuthBus outbox exceeds its durable row bound".into(),
            )
            .into());
        }

        let mut snapshot = AuthBusOutboxOperationalSnapshot {
            observed_at_ms: nonnegative(observed_at_ms, "negative observation time")?,
            ..AuthBusOutboxOperationalSnapshot::default()
        };
        let mut oldest_active_created_at_ms: Option<i64> = None;
        let mut acknowledgement_latencies = Vec::new();

        for row in rows {
            let state: String = row.try_get("state").map_err(classify_sqlx_error)?;
            let attempts: i64 = row.try_get("attempts").map_err(classify_sqlx_error)?;
            let created_at_ms: i64 = row.try_get("created_at_ms").map_err(classify_sqlx_error)?;
            let terminal_at_ms: Option<i64> =
                row.try_get("terminal_at_ms").map_err(classify_sqlx_error)?;
            if !(0..=AUTHBUS_OUTBOX_MAX_ATTEMPTS).contains(&attempts) || created_at_ms < 0 {
                return Err(EvidenceError::Corrupt(
                    "invalid AuthBus outbox operational row".into(),
                )
                .into());
            }
            if created_at_ms > observed_at_ms {
                return Err(EvidenceError::Unavailable(
                    "clock moved behind AuthBus outbox state".into(),
                )
                .into());
            }

            snapshot.retained_claim_attempts = snapshot
                .retained_claim_attempts
                .checked_add(nonnegative(attempts, "negative AuthBus claim count")?)
                .ok_or_else(|| EvidenceError::Corrupt("AuthBus claim count overflow".into()))?;
            snapshot.retained_claim_retries = snapshot
                .retained_claim_retries
                .checked_add(nonnegative(
                    (attempts - 1).max(0),
                    "negative AuthBus retry count",
                )?)
                .ok_or_else(|| EvidenceError::Corrupt("AuthBus retry count overflow".into()))?;

            match state.as_str() {
                "queued" => {
                    snapshot.queued_deliveries = snapshot.queued_deliveries.saturating_add(1);
                    record_active(
                        &mut snapshot,
                        &mut oldest_active_created_at_ms,
                        created_at_ms,
                        attempts,
                    );
                }
                "leased" => {
                    snapshot.leased_deliveries = snapshot.leased_deliveries.saturating_add(1);
                    record_active(
                        &mut snapshot,
                        &mut oldest_active_created_at_ms,
                        created_at_ms,
                        attempts,
                    );
                }
                "acked" => {
                    snapshot.acknowledged_deliveries =
                        snapshot.acknowledged_deliveries.saturating_add(1);
                    let terminal = terminal_at_ms.ok_or_else(|| {
                        EvidenceError::Corrupt(
                            "acknowledged AuthBus row has no terminal time".into(),
                        )
                    })?;
                    if terminal < created_at_ms {
                        return Err(EvidenceError::Corrupt(
                            "AuthBus acknowledgement predates enqueue".into(),
                        )
                        .into());
                    }
                    acknowledgement_latencies.push(nonnegative(
                        terminal - created_at_ms,
                        "negative AuthBus acknowledgement latency",
                    )?);
                }
                "expired" => {
                    snapshot.expired_deliveries = snapshot.expired_deliveries.saturating_add(1);
                }
                "quarantined" => {
                    snapshot.quarantined_deliveries =
                        snapshot.quarantined_deliveries.saturating_add(1);
                }
                _ => {
                    return Err(EvidenceError::Corrupt(
                        "invalid AuthBus outbox state in operational projection".into(),
                    )
                    .into());
                }
            }
        }

        snapshot.oldest_unsettled_age_ms = oldest_active_created_at_ms
            .map(|created| observed_at_ms.saturating_sub(created))
            .map(|age| nonnegative(age, "negative AuthBus unsettled age"))
            .transpose()?
            .unwrap_or(0);
        snapshot.acknowledgement_latency = latency_summary(&mut acknowledgement_latencies);
        Ok(snapshot)
    }
}

fn record_active(
    snapshot: &mut AuthBusOutboxOperationalSnapshot,
    oldest_active_created_at_ms: &mut Option<i64>,
    created_at_ms: i64,
    attempts: i64,
) {
    snapshot.active_deliveries = snapshot.active_deliveries.saturating_add(1);
    if attempts >= AUTHBUS_OUTBOX_MAX_ATTEMPTS {
        snapshot.exhausted_active_deliveries =
            snapshot.exhausted_active_deliveries.saturating_add(1);
    }
    let oldest = match *oldest_active_created_at_ms {
        Some(oldest) => oldest.min(created_at_ms),
        None => created_at_ms,
    };
    *oldest_active_created_at_ms = Some(oldest);
}

fn latency_summary(samples: &mut [u64]) -> AuthBusOutboxLatencySummary {
    if samples.is_empty() {
        return AuthBusOutboxLatencySummary::default();
    }
    samples.sort_unstable();
    AuthBusOutboxLatencySummary {
        count: u64::try_from(samples.len()).unwrap_or(u64::MAX),
        p50_ms: nearest_rank(samples, 50),
        p95_ms: nearest_rank(samples, 95),
        p99_ms: nearest_rank(samples, 99),
        max_ms: samples.last().copied().unwrap_or(0),
    }
}

fn nearest_rank(samples: &[u64], percentile: usize) -> u64 {
    let rank = samples.len().saturating_mul(percentile).div_ceil(100);
    samples
        .get(rank.saturating_sub(1).min(samples.len().saturating_sub(1)))
        .copied()
        .unwrap_or(0)
}

fn nonnegative(value: i64, message: &'static str) -> Result<u64, EvidenceError> {
    u64::try_from(value).map_err(|_| EvidenceError::Corrupt(message.into()))
}
