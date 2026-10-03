use sqlx::Row;
use sqlx::Sqlite;
use sqlx::Transaction;

use crate::DurableFleetError;
use crate::DurableFleetStore;
use crate::FleetHostResourcesV1;
use crate::FleetMetricsSnapshotV1;
use crate::FleetResultCounterV1;
use crate::MAX_DURABLE_HISTORY_ROWS;
use crate::durable_rows::decode_vector;
use crate::durable_rows::to_i64;
use crate::durable_rows::to_u64;
use crate::durable_schema::sqlx_error;

impl DurableFleetStore {
    /// One coherent read transaction. Missing observations stay unknown; missing
    /// authoritative totals are corruption, never a healthy zero-capacity row.
    pub async fn metrics(&self) -> Result<FleetMetricsSnapshotV1, DurableFleetError> {
        let mut tx = self.pool.begin().await.map_err(sqlx_error)?;
        let frontier: i64 =
            sqlx::query_scalar("SELECT last_now_ms FROM fleet_clock WHERE singleton = 1")
                .fetch_one(&mut *tx)
                .await
                .map_err(sqlx_error)?;
        let now_ms = self.owner_now_ms()?;
        if now_ms < to_u64(frontier)? {
            return Err(DurableFleetError::ClockRollback);
        }
        let active_grants = scalar_count(&mut tx, "SELECT COUNT(*) FROM fleet_grants").await?;
        let expired_uncollected_grants = sqlx::query_scalar::<_, i64>(
            "SELECT COUNT(*) FROM fleet_grants WHERE expires_at_ms <= ?",
        )
        .bind(to_i64(now_ms)?)
        .fetch_one(&mut *tx)
        .await
        .map_err(sqlx_error)
        .and_then(to_u64)?;
        let revoked_uncompacted_grants = scalar_count(
            &mut tx,
            "SELECT COUNT(*) FROM fleet_grant_history
             WHERE terminal_state = 'revoked' AND compacted = 0",
        )
        .await?;
        let stale_hosts = sqlx::query_scalar::<_, i64>(
            "SELECT COUNT(*) FROM fleet_hosts WHERE valid_until_ms <= ?",
        )
        .bind(to_i64(now_ms)?)
        .fetch_one(&mut *tx)
        .await
        .map_err(sqlx_error)
        .and_then(to_u64)?;
        let rows = sqlx::query(
            "SELECT h.host_id, h.valid_until_ms, t.host_id AS total_host_id,
                    h.cpu_millis AS observed_cpu_millis,
                    h.memory_bytes AS observed_memory_bytes,
                    h.accelerator_millis AS observed_accelerator_millis,
                    h.concurrent_turns AS observed_concurrent_turns,
                    h.tool_processes AS observed_tool_processes,
                    h.turn_queue_slots AS observed_turn_queue_slots,
                    t.cpu_millis AS reserved_cpu_millis,
                    t.memory_bytes AS reserved_memory_bytes,
                    t.accelerator_millis AS reserved_accelerator_millis,
                    t.concurrent_turns AS reserved_concurrent_turns,
                    t.tool_processes AS reserved_tool_processes,
                    t.turn_queue_slots AS reserved_turn_queue_slots
             FROM fleet_hosts h LEFT JOIN fleet_resource_totals t USING(host_id)
             ORDER BY h.host_id",
        )
        .fetch_all(&mut *tx)
        .await
        .map_err(sqlx_error)?;
        let host_resources = rows
            .into_iter()
            .map(|row| {
                let total_host: Option<String> =
                    row.try_get("total_host_id").map_err(sqlx_error)?;
                let host_id: String = row.try_get("host_id").map_err(sqlx_error)?;
                if total_host.as_deref() != Some(host_id.as_str()) {
                    return Err(DurableFleetError::Corrupt(format!(
                        "missing resource total for {host_id}"
                    )));
                }
                Ok(FleetHostResourcesV1 {
                    host_id,
                    observed: decode_vector(&row, "observed_")?,
                    reserved: decode_vector(&row, "reserved_")?,
                    observation_valid_until_ms: to_u64(
                        row.try_get("valid_until_ms").map_err(sqlx_error)?,
                    )?,
                })
            })
            .collect::<Result<_, DurableFleetError>>()?;
        let counter_rows = sqlx::query(
            "SELECT operation, result, value FROM fleet_metric_counters
             ORDER BY operation, result",
        )
        .fetch_all(&mut *tx)
        .await
        .map_err(sqlx_error)?;
        let result_counters = counter_rows
            .into_iter()
            .map(|row| {
                Ok(FleetResultCounterV1 {
                    operation: row.try_get("operation").map_err(sqlx_error)?,
                    result: row.try_get("result").map_err(sqlx_error)?,
                    value: to_u64(row.try_get("value").map_err(sqlx_error)?)?,
                })
            })
            .collect::<Result<_, DurableFleetError>>()?;
        let issued_at: Option<i64> = sqlx::query_scalar(
            "SELECT issued_at_ms FROM fleet_revocation_frontier WHERE singleton = 1",
        )
        .fetch_optional(&mut *tx)
        .await
        .map_err(sqlx_error)?;
        let revocation_update_age_ms = issued_at
            .map(to_u64)
            .transpose()?
            .map(|issued| {
                now_ms.checked_sub(issued).ok_or_else(|| {
                    DurableFleetError::Corrupt("revocation issue time is in the future".into())
                })
            })
            .transpose()?;
        let full_history = scalar_count(
            &mut tx,
            "SELECT COUNT(*) FROM fleet_grant_history WHERE compacted = 0",
        )
        .await?;
        let registry_conflicts = metric_value(&mut tx, "registry", "conflict").await?;
        let indeterminate_commits = metric_value(&mut tx, "commit", "indeterminate").await?;
        let staging_debris = metric_value(&mut tx, "registry", "staging_debris").await?;
        tx.commit().await.map_err(sqlx_error)?;
        Ok(FleetMetricsSnapshotV1 {
            active_grants,
            expired_uncollected_grants,
            revoked_uncompacted_grants,
            host_resources,
            stale_hosts,
            result_counters,
            // Update age does not measure acknowledgement/convergence lag.
            // A selected-owner roster and real acknowledgement observations are
            // required before the latter can be reported.
            revocation_lag_ms: None,
            revocation_update_age_ms,
            registry_conflicts,
            indeterminate_commits,
            staging_debris,
            compaction_backlog: full_history
                .saturating_sub(u64::try_from(MAX_DURABLE_HISTORY_ROWS).unwrap_or(u64::MAX)),
        })
    }

    /// Publish an observation from the existing operational owner. Absence of a
    /// publication is `None` in metrics, not an observed zero.
    pub async fn set_operational_gauge(
        &self,
        operation: &str,
        result: &str,
        value: u64,
    ) -> Result<(), DurableFleetError> {
        if ![
            ("registry", "conflict"),
            ("commit", "indeterminate"),
            ("registry", "staging_debris"),
        ]
        .contains(&(operation, result))
        {
            return Err(DurableFleetError::Invalid(
                "unregistered operational gauge".into(),
            ));
        }
        let mut tx = self
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(sqlx_error)?;
        let now_ms = self.owner_now_ms()?;
        Self::advance_clock_tx(&mut tx, now_ms).await?;
        sqlx::query(
            "INSERT INTO fleet_metric_counters(operation, result, value) VALUES(?, ?, ?)
             ON CONFLICT(operation, result) DO UPDATE SET value = excluded.value",
        )
        .bind(operation)
        .bind(result)
        .bind(to_i64(value)?)
        .execute(&mut *tx)
        .await
        .map_err(sqlx_error)?;
        tx.commit().await.map_err(|_| {
            self.indeterminate(
                format!("gauge:{operation}:{result}:{now_ms}"),
                format!("{operation}:{result}"),
            )
        })
    }
}

async fn scalar_count(
    tx: &mut Transaction<'_, Sqlite>,
    sql: &'static str,
) -> Result<u64, DurableFleetError> {
    let value: i64 = sqlx::query_scalar(sql)
        .fetch_one(&mut **tx)
        .await
        .map_err(sqlx_error)?;
    to_u64(value)
}

async fn metric_value(
    tx: &mut Transaction<'_, Sqlite>,
    operation: &str,
    result: &str,
) -> Result<Option<u64>, DurableFleetError> {
    let value: Option<i64> = sqlx::query_scalar(
        "SELECT value FROM fleet_metric_counters WHERE operation = ? AND result = ?",
    )
    .bind(operation)
    .bind(result)
    .fetch_optional(&mut **tx)
    .await
    .map_err(sqlx_error)?;
    value.map(to_u64).transpose()
}
