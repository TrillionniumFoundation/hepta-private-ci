use sqlx::Row;
use sqlx::SqlitePool;

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
    pub async fn metrics(&self) -> Result<FleetMetricsSnapshotV1, DurableFleetError> {
        let now_ms = self.owner_now_ms()?;
        let active_grants = scalar_count(&self.pool, "SELECT COUNT(*) FROM fleet_grants").await?;
        let expired_uncollected_grants = sqlx::query_scalar::<_, i64>(
            "SELECT COUNT(*) FROM fleet_grants WHERE expires_at_ms <= ?",
        )
        .bind(to_i64(now_ms)?)
        .fetch_one(&self.pool)
        .await
        .map_err(sqlx_error)
        .and_then(to_u64)?;
        let revoked_uncompacted_grants = scalar_count(
            &self.pool,
            "SELECT COUNT(*) FROM fleet_grant_history
             WHERE terminal_state = 'revoked' AND compacted = 0",
        )
        .await?;
        let stale_hosts = sqlx::query_scalar::<_, i64>(
            "SELECT COUNT(*) FROM fleet_hosts WHERE valid_until_ms <= ?",
        )
        .bind(to_i64(now_ms)?)
        .fetch_one(&self.pool)
        .await
        .map_err(sqlx_error)
        .and_then(to_u64)?;
        let rows = sqlx::query(
            "SELECT h.host_id, h.valid_until_ms,
                    h.cpu_millis AS observed_cpu_millis,
                    h.memory_bytes AS observed_memory_bytes,
                    h.accelerator_millis AS observed_accelerator_millis,
                    h.concurrent_turns AS observed_concurrent_turns,
                    h.tool_processes AS observed_tool_processes,
                    h.turn_queue_slots AS observed_turn_queue_slots,
                    COALESCE(t.cpu_millis, 0) AS reserved_cpu_millis,
                    COALESCE(t.memory_bytes, 0) AS reserved_memory_bytes,
                    COALESCE(t.accelerator_millis, 0) AS reserved_accelerator_millis,
                    COALESCE(t.concurrent_turns, 0) AS reserved_concurrent_turns,
                    COALESCE(t.tool_processes, 0) AS reserved_tool_processes,
                    COALESCE(t.turn_queue_slots, 0) AS reserved_turn_queue_slots
             FROM fleet_hosts h LEFT JOIN fleet_resource_totals t USING(host_id)
             ORDER BY h.host_id",
        )
        .fetch_all(&self.pool)
        .await
        .map_err(sqlx_error)?;
        let host_resources = rows
            .into_iter()
            .map(|row| {
                Ok(FleetHostResourcesV1 {
                    host_id: row.try_get("host_id").map_err(sqlx_error)?,
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
        .fetch_all(&self.pool)
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
        .fetch_optional(&self.pool)
        .await
        .map_err(sqlx_error)?;
        let revocation_lag_ms = issued_at
            .map(to_u64)
            .transpose()?
            .map(|issued| now_ms.saturating_sub(issued));
        let full_history = scalar_count(
            &self.pool,
            "SELECT COUNT(*) FROM fleet_grant_history WHERE compacted = 0",
        )
        .await?;
        Ok(FleetMetricsSnapshotV1 {
            active_grants,
            expired_uncollected_grants,
            revoked_uncompacted_grants,
            host_resources,
            stale_hosts,
            result_counters,
            revocation_lag_ms,
            registry_conflicts: metric_value(&self.pool, "registry", "conflict").await?,
            indeterminate_commits: metric_value(&self.pool, "commit", "indeterminate").await?,
            staging_debris: metric_value(&self.pool, "registry", "staging_debris").await?,
            compaction_backlog: full_history.saturating_sub(
                u64::try_from(MAX_DURABLE_HISTORY_ROWS).unwrap_or(u64::MAX),
            ),
        })
    }

    pub async fn set_operational_gauge(
        &self,
        operation: &str,
        result: &str,
        value: u64,
    ) -> Result<(), DurableFleetError> {
        sqlx::query(
            "INSERT INTO fleet_metric_counters(operation, result, value) VALUES(?, ?, ?)
             ON CONFLICT(operation, result) DO UPDATE SET value = excluded.value",
        )
        .bind(operation)
        .bind(result)
        .bind(to_i64(value)?)
        .execute(&self.pool)
        .await
        .map_err(sqlx_error)?;
        Ok(())
    }
}

async fn scalar_count(pool: &SqlitePool, sql: &str) -> Result<u64, DurableFleetError> {
    let value: i64 = sqlx::query_scalar(sql)
        .fetch_one(pool)
        .await
        .map_err(sqlx_error)?;
    to_u64(value)
}

async fn metric_value(
    pool: &SqlitePool,
    operation: &str,
    result: &str,
) -> Result<u64, DurableFleetError> {
    let value: Option<i64> = sqlx::query_scalar(
        "SELECT value FROM fleet_metric_counters WHERE operation = ? AND result = ?",
    )
    .bind(operation)
    .bind(result)
    .fetch_optional(pool)
    .await
    .map_err(sqlx_error)?;
    value.map(to_u64).transpose().map(Option::unwrap_or_default)
}
