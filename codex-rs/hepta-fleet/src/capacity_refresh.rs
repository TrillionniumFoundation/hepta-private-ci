use sqlx::Row;

use crate::DurableFleetError;
use crate::DurableFleetStore;
use crate::FleetMutationKindV1;
use crate::FleetMutationOutcomeV1;
use crate::FleetOperationReceiptV1;
use crate::LocalCapacityObservationV1;
use crate::LocalCapacityObserver;
use crate::durable_receipt::increment_counter_tx;
use crate::durable_receipt::insert_receipt_tx;
use crate::durable_rows::content_digest;
use crate::durable_rows::operation_id;
use crate::durable_rows::resource_digest;
use crate::durable_rows::to_i64;
use crate::durable_rows::to_u64;
use crate::durable_schema::sqlx_error;

impl DurableFleetStore {
    /// Refreshes the selected local host's physical capacity without changing
    /// its process-generation fence. A newer supervisor process uses
    /// `next_host_generation` first; later pressure samples reuse that exact
    /// generation and only advance `observed_at_ms`.
    pub async fn refresh_local_capacity(
        &self,
        observer: &LocalCapacityObserver,
    ) -> Result<(LocalCapacityObservationV1, FleetOperationReceiptV1), DurableFleetError> {
        let now_ms = self.owner_now_ms()?;
        let observed = observer
            .observe(now_ms)
            .map_err(|error| DurableFleetError::Unavailable(error.to_string()))?;
        let host = &observed.host;
        let receipt_id = operation_id(
            FleetMutationKindV1::HostObservation.as_str(),
            &host.host_id,
            host.observed_at_ms,
        );
        let mut tx = self
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(sqlx_error)?;
        Self::advance_clock_tx(&mut tx, now_ms).await?;
        let current = sqlx::query(
            "SELECT failure_domain_id, generation, observed_at_ms
             FROM fleet_hosts WHERE host_id = ?",
        )
        .bind(&host.host_id)
        .fetch_optional(&mut *tx)
        .await
        .map_err(sqlx_error)?;
        if let Some(row) = current {
            let current_generation = to_u64(row.try_get("generation").map_err(sqlx_error)?)?;
            let current_observed_at = to_u64(row.try_get("observed_at_ms").map_err(sqlx_error)?)?;
            let current_failure_domain: String =
                row.try_get("failure_domain_id").map_err(sqlx_error)?;
            if host.generation < current_generation {
                return Err(DurableFleetError::Stale);
            }
            if host.generation == current_generation {
                if host.failure_domain_id != current_failure_domain {
                    return Err(DurableFleetError::Conflict(host.host_id.clone()));
                }
                if host.observed_at_ms <= current_observed_at {
                    return Err(DurableFleetError::Stale);
                }
            } else {
                self.retire_host_generation_tx(&mut tx, &host.host_id, host.generation, now_ms)
                    .await?;
            }
        }
        let capacity_digest = resource_digest(host.capacity);
        sqlx::query(
            "INSERT INTO fleet_capacity_observations(
                host_id, generation, observed_at_ms, valid_until_ms, source_id,
                cpu_millis, memory_bytes, accelerator_millis,
                concurrent_turns, tool_processes, turn_queue_slots, capacity_digest
             ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        )
        .bind(&host.host_id)
        .bind(to_i64(host.generation)?)
        .bind(to_i64(host.observed_at_ms)?)
        .bind(to_i64(host.valid_until_ms)?)
        .bind(observed.source_id)
        .bind(to_i64(host.capacity.cpu_millis)?)
        .bind(to_i64(host.capacity.memory_bytes)?)
        .bind(to_i64(host.capacity.accelerator_millis)?)
        .bind(to_i64(host.capacity.concurrent_turns)?)
        .bind(to_i64(host.capacity.tool_processes)?)
        .bind(to_i64(host.capacity.turn_queue_slots)?)
        .bind(&capacity_digest)
        .execute(&mut *tx)
        .await
        .map_err(sqlx_error)?;
        sqlx::query(
            "INSERT INTO fleet_hosts(
                host_id, failure_domain_id, generation, observed_at_ms, valid_until_ms,
                cpu_millis, memory_bytes, accelerator_millis,
                concurrent_turns, tool_processes, turn_queue_slots, capacity_digest
             ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
             ON CONFLICT(host_id) DO UPDATE SET
                failure_domain_id = excluded.failure_domain_id,
                generation = excluded.generation,
                observed_at_ms = excluded.observed_at_ms,
                valid_until_ms = excluded.valid_until_ms,
                cpu_millis = excluded.cpu_millis,
                memory_bytes = excluded.memory_bytes,
                accelerator_millis = excluded.accelerator_millis,
                concurrent_turns = excluded.concurrent_turns,
                tool_processes = excluded.tool_processes,
                turn_queue_slots = excluded.turn_queue_slots,
                capacity_digest = excluded.capacity_digest",
        )
        .bind(&host.host_id)
        .bind(&host.failure_domain_id)
        .bind(to_i64(host.generation)?)
        .bind(to_i64(host.observed_at_ms)?)
        .bind(to_i64(host.valid_until_ms)?)
        .bind(to_i64(host.capacity.cpu_millis)?)
        .bind(to_i64(host.capacity.memory_bytes)?)
        .bind(to_i64(host.capacity.accelerator_millis)?)
        .bind(to_i64(host.capacity.concurrent_turns)?)
        .bind(to_i64(host.capacity.tool_processes)?)
        .bind(to_i64(host.capacity.turn_queue_slots)?)
        .bind(&capacity_digest)
        .execute(&mut *tx)
        .await
        .map_err(sqlx_error)?;
        self.ensure_zero_total_tx(&mut tx, &host.host_id, now_ms)
            .await?;
        let receipt = FleetOperationReceiptV1 {
            operation_id: receipt_id,
            kind: FleetMutationKindV1::HostObservation,
            subject_id: host.host_id.clone(),
            outcome: FleetMutationOutcomeV1::Updated,
            semantic_digest: content_digest(host)?,
            authority_witness: None,
            committed_at_ms: now_ms,
        };
        insert_receipt_tx(&mut tx, &receipt).await?;
        increment_counter_tx(&mut tx, "capacity_observation", "success").await?;
        match tx.commit().await {
            Ok(()) => Ok((observed, receipt)),
            Err(_) => Err(self.indeterminate(receipt.operation_id, receipt.subject_id)),
        }
    }
}
