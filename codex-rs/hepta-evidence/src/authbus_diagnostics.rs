//! Read-only, bounded projections of AuthBus delivery facts owned by Evidence.
//! Retention-window aggregates are not process-lifetime counters or provider
//! latency measurements. Reading diagnostics never claims, retries or acks.
use serde::Serialize;
use sqlx::Row;

use crate::EvidenceError;
use crate::HeptaEvidenceStore;
use crate::authbus_outbox_record::AUTHBUS_OUTBOX_MAX_ROWS;
use crate::authbus_recovery::replay_checkpoint_pending;
use crate::schema_validation::classify_sqlx_error;
use crate::store::now_millis;

#[derive(Clone, Debug, Default, Eq, PartialEq, Serialize)]
pub struct AuthBusOutboxDiagnostics {
    pub observed_at_ms: i64,
    pub replay_checkpoint_pending: bool,
    pub queued: u64,
    pub leased: u64,
    pub quarantined: u64,
    pub expired: u64,
    pub acked: u64,
    pub waiting_for_backoff: u64,
    pub expired_leases: u64,
    pub oldest_unsettled_age_ms: Option<u64>,
    pub retained_claim_retries: u64,
    pub retained_ack_latency_samples: u64,
    pub retained_ack_latency_total_ms: u64,
    pub retained_ack_latency_max_ms: u64,
}

impl HeptaEvidenceStore {
    pub async fn authbus_outbox_diagnostics(
        &self,
    ) -> Result<AuthBusOutboxDiagnostics, EvidenceError> {
        let mut tx = self.pool.begin().await.map_err(classify_sqlx_error)?;
        let now = now_millis()?;
        let pending = replay_checkpoint_pending(&mut tx).await?;
        // One row beyond the documented bound detects corruption without
        // allocating an unbounded collection or loading any payload/secret.
        let rows = sqlx::query(
            "SELECT state, attempts, created_at_ms, updated_at_ms,
            available_at_ms, lease_until_ms FROM authbus_outbox ORDER BY delivery_id LIMIT ?",
        )
        .bind(AUTHBUS_OUTBOX_MAX_ROWS + 1)
        .fetch_all(&mut *tx)
        .await
        .map_err(classify_sqlx_error)?;
        if rows.len() > AUTHBUS_OUTBOX_MAX_ROWS as usize {
            return Err(EvidenceError::Corrupt(
                "AuthBus outbox exceeds its declared bound".into(),
            ));
        }
        let mut snapshot = AuthBusOutboxDiagnostics {
            observed_at_ms: now,
            replay_checkpoint_pending: pending,
            ..AuthBusOutboxDiagnostics::default()
        };
        for row in rows {
            let state: String = row.try_get("state").map_err(classify_sqlx_error)?;
            let attempts: i64 = row.try_get("attempts").map_err(classify_sqlx_error)?;
            let created: i64 = row.try_get("created_at_ms").map_err(classify_sqlx_error)?;
            let updated: i64 = row.try_get("updated_at_ms").map_err(classify_sqlx_error)?;
            let available: i64 = row
                .try_get("available_at_ms")
                .map_err(classify_sqlx_error)?;
            let until: Option<i64> = row.try_get("lease_until_ms").map_err(classify_sqlx_error)?;
            if attempts < 0 || created < 0 || updated < created {
                return Err(EvidenceError::Corrupt(
                    "invalid AuthBus diagnostic time/count".into(),
                ));
            }
            snapshot.retained_claim_retries = snapshot
                .retained_claim_retries
                .saturating_add(attempts.saturating_sub(1).max(0) as u64);
            match state.as_str() {
                "queued" => {
                    snapshot.queued += 1;
                    if available > now {
                        snapshot.waiting_for_backoff += 1;
                    }
                }
                "leased" => {
                    snapshot.leased += 1;
                    if until.is_some_and(|deadline| deadline <= now) {
                        snapshot.expired_leases += 1;
                    }
                }
                "quarantined" => snapshot.quarantined += 1,
                "expired" => snapshot.expired += 1,
                "acked" => {
                    snapshot.acked += 1;
                    let elapsed = updated.saturating_sub(created) as u64;
                    snapshot.retained_ack_latency_samples += 1;
                    snapshot.retained_ack_latency_total_ms = snapshot
                        .retained_ack_latency_total_ms
                        .saturating_add(elapsed);
                    snapshot.retained_ack_latency_max_ms =
                        snapshot.retained_ack_latency_max_ms.max(elapsed);
                }
                _ => {
                    return Err(EvidenceError::Corrupt(
                        "invalid AuthBus delivery state".into(),
                    ));
                }
            }
            if matches!(state.as_str(), "queued" | "leased") {
                let age = now.saturating_sub(created).max(0) as u64;
                snapshot.oldest_unsettled_age_ms =
                    Some(snapshot.oldest_unsettled_age_ms.unwrap_or(0).max(age));
            }
        }
        tx.commit().await.map_err(classify_sqlx_error)?;
        Ok(snapshot)
    }
}
