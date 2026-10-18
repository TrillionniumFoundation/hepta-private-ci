use sqlx::Row;
use sqlx::Sqlite;
use sqlx::Transaction;

use crate::AllocationGrant;
use crate::DurableFleetError;
use crate::DurableFleetStore;
use crate::FleetMutationKindV1;
use crate::FleetMutationOutcomeV1;
use crate::FleetOperationReceiptV1;
use crate::HostObservation;
use crate::MAX_DURABLE_EXPIRY_BATCH;
use crate::ResourceVectorV1;
use crate::durable_receipt::increment_counter_tx;
use crate::durable_receipt::insert_receipt_tx;
use crate::durable_rows::content_digest;
use crate::durable_rows::decode_grant;
use crate::durable_rows::decode_vector;
use crate::durable_rows::encode_json;
use crate::durable_rows::operation_id;
use crate::durable_rows::resource_digest;
use crate::durable_rows::to_i64;
use crate::durable_rows::to_u64;
use crate::durable_schema::sqlx_error;

const GRANT_SELECT: &str = "SELECT allocation_id, request_id, principal_id, host_id,
    failure_domain_id, host_generation, authority_epoch, lease_generation, expires_at_ms,
    cpu_millis, memory_bytes, accelerator_millis, concurrent_turns, tool_processes,
    turn_queue_slots, semantic_digest FROM fleet_grants";

impl DurableFleetStore {
    pub(crate) async fn ensure_zero_total_tx(
        &self,
        tx: &mut Transaction<'_, Sqlite>,
        host_id: &str,
        now_ms: u64,
    ) -> Result<(), DurableFleetError> {
        sqlx::query(
            "INSERT INTO fleet_resource_totals(host_id, cpu_millis, memory_bytes,
             accelerator_millis, concurrent_turns, tool_processes, turn_queue_slots,
             resource_digest, updated_at_ms) VALUES(?, 0, 0, 0, 0, 0, 0, ?, ?)
             ON CONFLICT(host_id) DO NOTHING",
        )
        .bind(host_id)
        .bind(resource_digest(ResourceVectorV1::default()))
        .bind(to_i64(now_ms)?)
        .execute(&mut **tx)
        .await
        .map_err(sqlx_error)?;
        Ok(())
    }

    pub(crate) async fn retire_host_generation_tx(
        &self,
        tx: &mut Transaction<'_, Sqlite>,
        host_id: &str,
        generation: u64,
        now_ms: u64,
    ) -> Result<usize, DurableFleetError> {
        let mut query = sqlx::QueryBuilder::<Sqlite>::new(GRANT_SELECT);
        query
            .push(" WHERE host_id = ")
            .push_bind(host_id)
            .push(" AND host_generation < ")
            .push_bind(to_i64(generation)?)
            .push(" ORDER BY allocation_id");
        let rows = query
            .build()
            .fetch_all(&mut **tx)
            .await
            .map_err(sqlx_error)?;
        for row in &rows {
            let grant = decode_grant(row)?;
            retire_grant_tx(tx, &grant, "host_generation_fenced", now_ms).await?;
            let receipt = FleetOperationReceiptV1 {
                operation_id: operation_id("fence", &grant.allocation_id, grant.lease_generation),
                kind: FleetMutationKindV1::Fence,
                subject_id: grant.allocation_id.clone(),
                outcome: FleetMutationOutcomeV1::Fenced,
                semantic_digest: grant.semantic_digest.clone(),
                authority_witness: None,
                committed_at_ms: now_ms,
            };
            insert_receipt_tx(tx, &receipt).await?;
            increment_counter_tx(tx, "fence", "success").await?;
        }
        Ok(rows.len())
    }

    pub(crate) async fn collect_expired_tx(
        &self,
        tx: &mut Transaction<'_, Sqlite>,
        now_ms: u64,
    ) -> Result<usize, DurableFleetError> {
        let mut query = sqlx::QueryBuilder::<Sqlite>::new(GRANT_SELECT);
        query
            .push(" WHERE expires_at_ms <= ")
            .push_bind(to_i64(now_ms)?)
            .push(" ORDER BY expires_at_ms, allocation_id LIMIT ")
            .push_bind(MAX_DURABLE_EXPIRY_BATCH);
        let rows = query
            .build()
            .fetch_all(&mut **tx)
            .await
            .map_err(sqlx_error)?;
        for row in &rows {
            let grant = decode_grant(row)?;
            retire_grant_tx(tx, &grant, "expired", now_ms).await?;
            let receipt = FleetOperationReceiptV1 {
                operation_id: operation_id("expire", &grant.allocation_id, grant.lease_generation),
                kind: FleetMutationKindV1::Expire,
                subject_id: grant.allocation_id.clone(),
                outcome: FleetMutationOutcomeV1::Expired,
                semantic_digest: grant.semantic_digest.clone(),
                authority_witness: None,
                committed_at_ms: now_ms,
            };
            insert_receipt_tx(tx, &receipt).await?;
            increment_counter_tx(tx, "expire", "success").await?;
        }
        Ok(rows.len())
    }
}

pub(crate) async fn select_host_tx(
    tx: &mut Transaction<'_, Sqlite>,
    host_id: &str,
) -> Result<Option<HostObservation>, DurableFleetError> {
    let row = sqlx::query(
        "SELECT host_id, failure_domain_id, generation, observed_at_ms, valid_until_ms,
         cpu_millis, memory_bytes, accelerator_millis, concurrent_turns, tool_processes,
         turn_queue_slots FROM fleet_hosts WHERE host_id = ?",
    )
    .bind(host_id)
    .fetch_optional(&mut **tx)
    .await
    .map_err(sqlx_error)?;
    row.map(|row| {
        Ok(HostObservation {
            host_id: row.try_get("host_id").map_err(sqlx_error)?,
            failure_domain_id: row.try_get("failure_domain_id").map_err(sqlx_error)?,
            generation: to_u64(row.try_get("generation").map_err(sqlx_error)?)?,
            observed_at_ms: to_u64(row.try_get("observed_at_ms").map_err(sqlx_error)?)?,
            valid_until_ms: to_u64(row.try_get("valid_until_ms").map_err(sqlx_error)?)?,
            capacity: decode_vector(&row, "")?,
        })
    })
    .transpose()
}

pub(crate) async fn select_grant_tx(
    tx: &mut Transaction<'_, Sqlite>,
    allocation_id: &str,
) -> Result<Option<AllocationGrant>, DurableFleetError> {
    let mut query = sqlx::QueryBuilder::<Sqlite>::new(GRANT_SELECT);
    query
        .push(" WHERE allocation_id = ")
        .push_bind(allocation_id);
    query
        .build()
        .fetch_optional(&mut **tx)
        .await
        .map_err(sqlx_error)?
        .map(|row| decode_grant(&row))
        .transpose()
}

pub(crate) async fn load_total_tx(
    tx: &mut Transaction<'_, Sqlite>,
    host_id: &str,
) -> Result<ResourceVectorV1, DurableFleetError> {
    let row = sqlx::query(
        "SELECT cpu_millis, memory_bytes, accelerator_millis,
         concurrent_turns, tool_processes, turn_queue_slots
         FROM fleet_resource_totals WHERE host_id = ?",
    )
    .bind(host_id)
    .fetch_optional(&mut **tx)
    .await
    .map_err(sqlx_error)?
    .ok_or_else(|| DurableFleetError::Corrupt(format!("missing resource total for {host_id}")))?;
    decode_vector(&row, "")
}

pub(crate) async fn write_total_tx(
    tx: &mut Transaction<'_, Sqlite>,
    host_id: &str,
    total: ResourceVectorV1,
    now_ms: u64,
) -> Result<(), DurableFleetError> {
    sqlx::query(
        "INSERT INTO fleet_resource_totals(host_id, cpu_millis, memory_bytes,
         accelerator_millis, concurrent_turns, tool_processes, turn_queue_slots,
         resource_digest, updated_at_ms) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
         ON CONFLICT(host_id) DO UPDATE SET cpu_millis = excluded.cpu_millis,
         memory_bytes = excluded.memory_bytes, accelerator_millis = excluded.accelerator_millis,
         concurrent_turns = excluded.concurrent_turns, tool_processes = excluded.tool_processes,
         turn_queue_slots = excluded.turn_queue_slots, resource_digest = excluded.resource_digest,
         updated_at_ms = excluded.updated_at_ms",
    )
    .bind(host_id)
    .bind(to_i64(total.cpu_millis)?)
    .bind(to_i64(total.memory_bytes)?)
    .bind(to_i64(total.accelerator_millis)?)
    .bind(to_i64(total.concurrent_turns)?)
    .bind(to_i64(total.tool_processes)?)
    .bind(to_i64(total.turn_queue_slots)?)
    .bind(resource_digest(total))
    .bind(to_i64(now_ms)?)
    .execute(&mut **tx)
    .await
    .map_err(sqlx_error)?;
    Ok(())
}

pub(crate) async fn retire_grant_tx(
    tx: &mut Transaction<'_, Sqlite>,
    grant: &AllocationGrant,
    terminal_state: &str,
    now_ms: u64,
) -> Result<(), DurableFleetError> {
    let execution_held: bool = sqlx::query_scalar(
        "SELECT EXISTS(SELECT 1 FROM fleet_execution_holds
         WHERE allocation_id = ? AND state != 'stopped')",
    )
    .bind(&grant.allocation_id)
    .fetch_one(&mut **tx)
    .await
    .map_err(sqlx_error)?;
    if execution_held {
        // Invalidate use immediately, retaining actual occupancy until native
        // stop confirmation. The stop obligation and retirement commit together.
        sqlx::query(
            "UPDATE fleet_execution_holds SET state = 'stop_requested'
             WHERE allocation_id = ? AND state != 'stopped'",
        )
        .bind(&grant.allocation_id)
        .execute(&mut **tx)
        .await
        .map_err(sqlx_error)?;
    } else {
        let total = load_total_tx(tx, &grant.host_id).await?;
        let next = total
            .checked_sub(grant.resources)
            .map_err(|error| DurableFleetError::Corrupt(error.to_string()))?;
        write_total_tx(tx, &grant.host_id, next, now_ms).await?;
    }
    sqlx::query("DELETE FROM fleet_grants WHERE allocation_id = ?")
        .bind(&grant.allocation_id)
        .execute(&mut **tx)
        .await
        .map_err(sqlx_error)?;
    sqlx::query(
        "INSERT INTO fleet_grant_history(allocation_id, terminal_state, grant_json,
         final_digest, retired_at_ms, compacted) VALUES(?, ?, ?, ?, ?, 0)
         ON CONFLICT(allocation_id) DO NOTHING",
    )
    .bind(&grant.allocation_id)
    .bind(terminal_state)
    .bind(encode_json(grant)?)
    .bind(content_digest(grant)?)
    .bind(to_i64(now_ms)?)
    .execute(&mut **tx)
    .await
    .map_err(sqlx_error)?;
    Ok(())
}
