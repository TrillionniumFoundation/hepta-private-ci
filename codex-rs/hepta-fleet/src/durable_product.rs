//! Product-facing execution queries and stop intent for the durable fleet owner.
//!
//! These helpers deliberately do not release capacity. Expiry, revocation, and
//! stop requests transition a live execution hold to `stop_requested`; only
//! `confirm_local_exit` may prove native absence and reclaim the reservation.

use sqlx::Row;

use crate::DurableFleetError;
use crate::DurableFleetStore;
use crate::FleetExecutionHoldV1;
use crate::durable_rows::decode_json;
use crate::durable_rows::to_u64;
use crate::durable_rows::validate_identity;
use crate::durable_schema::sqlx_error;

impl DurableFleetStore {
    /// Read the current durable allocation for owner maintenance. This DTO is
    /// not an authority token and cannot authorize a new launch by itself.
    pub async fn allocation_grant(
        &self,
        allocation_id: &str,
    ) -> Result<Option<crate::AllocationGrant>, DurableFleetError> {
        validate_identity(allocation_id, "allocation")?;
        let mut tx = self.pool.begin().await.map_err(sqlx_error)?;
        let grant = crate::durable_grant_tx::select_grant_tx(&mut tx, allocation_id).await?;
        tx.commit().await.map_err(sqlx_error)?;
        Ok(grant)
    }
    /// Return the one non-terminal execution owned by a principal.
    ///
    /// A principal is intentionally restricted to one live execution at this
    /// boundary. More than one row is durable-state corruption, not a reason to
    /// choose an arbitrary process.
    pub async fn active_execution_for_principal(
        &self,
        principal_id: &str,
    ) -> Result<Option<FleetExecutionHoldV1>, DurableFleetError> {
        validate_identity(principal_id, "principal")?;
        let mut matches = self
            .pending_executions()
            .await?
            .into_iter()
            .filter(|hold| hold.context.principal_id == principal_id);
        let first = matches.next();
        if matches.next().is_some() {
            return Err(DurableFleetError::Corrupt(format!(
                "principal {principal_id} owns multiple non-terminal executions"
            )));
        }
        Ok(first)
    }

    /// Read one execution hold without changing lifecycle state.
    pub async fn execution_hold(
        &self,
        execution_id: &str,
    ) -> Result<Option<FleetExecutionHoldV1>, DurableFleetError> {
        validate_identity(execution_id, "execution")?;
        let row = sqlx::query(
            "SELECT context_json, state, process_id FROM fleet_execution_holds
             WHERE execution_id = ?",
        )
        .bind(execution_id)
        .fetch_optional(&self.pool)
        .await
        .map_err(sqlx_error)?;
        row.map(decode_execution_hold).transpose()
    }

    /// Persist stop intent before signalling the native process.
    ///
    /// This operation is idempotent. It never marks the execution stopped and
    /// never decrements held capacity; the process owner must subsequently call
    /// `confirm_local_exit` after proving that the PID, process group, and
    /// protected cgroup are all gone.
    pub async fn request_local_stop(
        &self,
        execution_id: &str,
    ) -> Result<FleetExecutionHoldV1, DurableFleetError> {
        validate_identity(execution_id, "execution")?;
        let mut tx = self
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(sqlx_error)?;
        let now_ms = self.owner_now_ms()?;
        Self::advance_clock_tx(&mut tx, now_ms).await?;

        let row = sqlx::query(
            "SELECT context_json, state, process_id FROM fleet_execution_holds
             WHERE execution_id = ?",
        )
        .bind(execution_id)
        .fetch_optional(&mut *tx)
        .await
        .map_err(sqlx_error)?
        .ok_or_else(|| DurableFleetError::Missing(execution_id.to_string()))?;
        let current = decode_execution_hold(row)?;

        if current.state != "stopped" && current.state != "stop_requested" {
            let changed = sqlx::query(
                "UPDATE fleet_execution_holds SET state = 'stop_requested'
                 WHERE execution_id = ? AND state IN ('prepared', 'running')",
            )
            .bind(execution_id)
            .execute(&mut *tx)
            .await
            .map_err(sqlx_error)?
            .rows_affected();
            if changed != 1 {
                return Err(DurableFleetError::Conflict(execution_id.to_string()));
            }
        }

        let row = sqlx::query(
            "SELECT context_json, state, process_id FROM fleet_execution_holds
             WHERE execution_id = ?",
        )
        .bind(execution_id)
        .fetch_one(&mut *tx)
        .await
        .map_err(sqlx_error)?;
        let hold = decode_execution_hold(row)?;
        tx.commit().await.map_err(|_| {
            self.indeterminate(format!("stop:{execution_id}"), execution_id.to_string())
        })?;
        Ok(hold)
    }
}

fn decode_execution_hold(
    row: sqlx::sqlite::SqliteRow,
) -> Result<FleetExecutionHoldV1, DurableFleetError> {
    let json: String = row.try_get("context_json").map_err(sqlx_error)?;
    let pid: Option<i64> = row.try_get("process_id").map_err(sqlx_error)?;
    Ok(FleetExecutionHoldV1 {
        context: decode_json(&json)?,
        state: row.try_get("state").map_err(sqlx_error)?,
        process_id: pid.map(to_u64).transpose()?,
    })
}

#[cfg(test)]
mod tests {
    use tempfile::TempDir;

    use super::*;
    use crate::FleetExecutionContextV1;
    use crate::ResourceVectorV1;
    use crate::durable_rows::to_i64;

    #[tokio::test]
    async fn stop_intent_is_idempotent_and_does_not_release_capacity() {
        let (_temp, store) = seeded_store().await;

        let first = store.request_local_stop("execution-a").await.unwrap();
        assert_eq!(first.state, "stop_requested");
        assert_eq!(first.process_id, Some(4242));

        let second = store.request_local_stop("execution-a").await.unwrap();
        assert_eq!(second, first);

        let memory_bytes: i64 = sqlx::query_scalar(
            "SELECT memory_bytes FROM fleet_resource_totals WHERE host_id = 'host-a'",
        )
        .fetch_one(&store.pool)
        .await
        .unwrap();
        assert_eq!(memory_bytes, 1024);
    }

    #[tokio::test]
    async fn principal_lookup_rejects_ambiguous_live_ownership() {
        let (_temp, store) = seeded_store().await;
        assert_eq!(
            store
                .active_execution_for_principal("agent-a")
                .await
                .unwrap()
                .unwrap()
                .context
                .execution_id,
            "execution-a"
        );

        insert_hold(&store, "execution-b", "allocation-b", "agent-a", 4343, 2).await;
        let error = store
            .active_execution_for_principal("agent-a")
            .await
            .unwrap_err();
        assert!(matches!(error, DurableFleetError::Corrupt(_)));
    }

    async fn seeded_store() -> (TempDir, DurableFleetStore) {
        let temp = tempfile::tempdir().unwrap();
        let store = DurableFleetStore::open(&temp.path().join("fleet.sqlite"))
            .await
            .unwrap();
        sqlx::query(
            "INSERT INTO fleet_hosts(
                host_id, failure_domain_id, generation, observed_at_ms, valid_until_ms,
                cpu_millis, memory_bytes, accelerator_millis, concurrent_turns,
                tool_processes, turn_queue_slots, capacity_digest
             ) VALUES('host-a', 'domain-a', 1, 1, 9223372036854775807,
                      1000, 4096, 0, 1, 1, 1, 'capacity')",
        )
        .execute(&store.pool)
        .await
        .unwrap();
        sqlx::query(
            "INSERT INTO fleet_resource_totals(
                host_id, cpu_millis, memory_bytes, accelerator_millis,
                concurrent_turns, tool_processes, turn_queue_slots,
                resource_digest, updated_at_ms
             ) VALUES('host-a', 100, 1024, 0, 1, 1, 1, 'held', 1)",
        )
        .execute(&store.pool)
        .await
        .unwrap();
        insert_hold(&store, "execution-a", "allocation-a", "agent-a", 4242, 1).await;
        (temp, store)
    }

    async fn insert_hold(
        store: &DurableFleetStore,
        execution_id: &str,
        allocation_id: &str,
        principal_id: &str,
        process_id: u64,
        containment_ino: u64,
    ) {
        let context = FleetExecutionContextV1 {
            execution_id: execution_id.to_string(),
            allocation_id: allocation_id.to_string(),
            principal_id: principal_id.to_string(),
            host_id: "host-a".to_string(),
            host_generation: 1,
            lease_generation: 1,
            manifest_digest: "0".repeat(64),
            resources: ResourceVectorV1 {
                cpu_millis: 100,
                memory_bytes: 1024,
                accelerator_millis: 0,
                concurrent_turns: 1,
                tool_processes: 1,
                turn_queue_slots: 1,
            },
            containment: format!("hepta/{execution_id}"),
        };
        sqlx::query(
            "INSERT INTO fleet_execution_holds(
                execution_id, allocation_id, host_id, boot_identity, context_json,
                state, process_id, process_group, process_start_ticks,
                prepared_at_ms, containment_dev, containment_ino
             ) VALUES(?, ?, 'host-a', '00000000-0000-0000-0000-000000000001', ?,
                      'running', ?, ?, 1, 1, 1, ?)",
        )
        .bind(execution_id)
        .bind(allocation_id)
        .bind(serde_json::to_string(&context).unwrap())
        .bind(to_i64(process_id).unwrap())
        .bind(to_i64(process_id).unwrap())
        .bind(to_i64(containment_ino).unwrap())
        .execute(&store.pool)
        .await
        .unwrap();
    }
}
