use std::path::Path;
use std::path::PathBuf;
use std::sync::Arc;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;
use std::time::Duration;

use codex_hepta_contracts::AuthorityClock;
use codex_hepta_contracts::SystemAuthorityClock;
use sqlx::Row;
use sqlx::Sqlite;
use sqlx::SqlitePool;
use sqlx::Transaction;
use sqlx::sqlite::SqliteConnectOptions;
use sqlx::sqlite::SqliteJournalMode;
use sqlx::sqlite::SqlitePoolOptions;
use sqlx::sqlite::SqliteSynchronous;

use crate::DurableFleetError;
use crate::FleetMutationKindV1;
use crate::FleetMutationOutcomeV1;
use crate::FleetOperationReceiptV1;
use crate::HostObservation;
use crate::durable_receipt::insert_receipt_tx;
use crate::durable_rows::content_digest;
use crate::durable_rows::decode_vector;
use crate::durable_rows::operation_id;
use crate::durable_rows::resource_digest;
use crate::durable_rows::to_i64;
use crate::durable_rows::to_u64;
use crate::durable_rows::validate_identity;
use crate::durable_schema::initialize_schema;
use crate::durable_schema::sqlx_error;

#[derive(Clone)]
pub struct DurableFleetStore {
    pub(crate) pool: SqlitePool,
    path: PathBuf,
    clock: Arc<dyn AuthorityClock>,
    last_now_ms: Arc<AtomicU64>,
}

impl std::fmt::Debug for DurableFleetStore {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter
            .debug_struct("DurableFleetStore")
            .field("path", &self.path)
            .field("last_now_ms", &self.last_now_ms.load(Ordering::Acquire))
            .finish_non_exhaustive()
    }
}

impl DurableFleetStore {
    /// Compatibility/testing constructor. Selected production hosts inject a
    /// protected clock with `open_with_clock`.
    pub async fn open(path: &Path) -> Result<Self, DurableFleetError> {
        Self::open_with_clock(path, Arc::new(SystemAuthorityClock)).await
    }

    pub async fn open_with_clock(
        path: &Path,
        clock: Arc<dyn AuthorityClock>,
    ) -> Result<Self, DurableFleetError> {
        if let Some(parent) = path.parent() {
            std::fs::create_dir_all(parent)
                .map_err(|error| DurableFleetError::Unavailable(error.to_string()))?;
        }
        let now_ms = clock
            .now_unix_ms()
            .map_err(|_| DurableFleetError::ClockUnavailable)?;
        let options = SqliteConnectOptions::new()
            .filename(path)
            .create_if_missing(true)
            .journal_mode(SqliteJournalMode::Wal)
            .synchronous(SqliteSynchronous::Full)
            .foreign_keys(true)
            .busy_timeout(Duration::from_secs(5));
        let pool = SqlitePoolOptions::new()
            .max_connections(4)
            .connect_with(options)
            .await
            .map_err(sqlx_error)?;
        if let Err(error) = initialize_schema(&pool, to_i64(now_ms)?).await {
            pool.close().await;
            return Err(error);
        }
        let persisted: i64 =
            sqlx::query_scalar("SELECT last_now_ms FROM fleet_clock WHERE singleton = 1")
                .fetch_one(&pool)
                .await
                .map_err(sqlx_error)?;
        let persisted = to_u64(persisted)?;
        if now_ms < persisted {
            pool.close().await;
            return Err(DurableFleetError::ClockRollback);
        }
        if now_ms > persisted {
            sqlx::query("UPDATE fleet_clock SET last_now_ms = ? WHERE singleton = 1")
                .bind(to_i64(now_ms)?)
                .execute(&pool)
                .await
                .map_err(sqlx_error)?;
        }
        Ok(Self {
            pool,
            path: path.to_path_buf(),
            clock,
            last_now_ms: Arc::new(AtomicU64::new(now_ms)),
        })
    }

    pub fn path(&self) -> &Path {
        &self.path
    }

    pub async fn close(&self) {
        self.pool.close().await;
    }

    pub(crate) fn owner_now_ms(&self) -> Result<u64, DurableFleetError> {
        let now_ms = self
            .clock
            .now_unix_ms()
            .map_err(|_| DurableFleetError::ClockUnavailable)?;
        loop {
            let current = self.last_now_ms.load(Ordering::Acquire);
            if now_ms < current {
                return Err(DurableFleetError::ClockRollback);
            }
            if now_ms == current
                || self
                    .last_now_ms
                    .compare_exchange(current, now_ms, Ordering::AcqRel, Ordering::Acquire)
                    .is_ok()
            {
                return Ok(now_ms);
            }
        }
    }

    pub(crate) async fn advance_clock_tx(
        tx: &mut Transaction<'_, Sqlite>,
        now_ms: u64,
    ) -> Result<(), DurableFleetError> {
        let persisted: i64 =
            sqlx::query_scalar("SELECT last_now_ms FROM fleet_clock WHERE singleton = 1")
                .fetch_one(&mut **tx)
                .await
                .map_err(sqlx_error)?;
        if now_ms < to_u64(persisted)? {
            return Err(DurableFleetError::ClockRollback);
        }
        sqlx::query("UPDATE fleet_clock SET last_now_ms = ? WHERE singleton = 1")
            .bind(to_i64(now_ms)?)
            .execute(&mut **tx)
            .await
            .map_err(sqlx_error)?;
        Ok(())
    }

    pub async fn observe_host(
        &self,
        observation: &HostObservation,
        source_id: &str,
    ) -> Result<FleetOperationReceiptV1, DurableFleetError> {
        validate_identity(&observation.host_id, "host")?;
        validate_identity(&observation.failure_domain_id, "failure domain")?;
        validate_identity(source_id, "capacity observation source")?;
        observation
            .capacity
            .validate_nonzero()
            .map_err(|error| DurableFleetError::Invalid(error.to_string()))?;
        if observation.generation == 0 || observation.observed_at_ms >= observation.valid_until_ms {
            return Err(DurableFleetError::Invalid(
                "invalid capacity observation interval".to_string(),
            ));
        }
        let now_ms = self.owner_now_ms()?;
        if observation.observed_at_ms > now_ms || now_ms >= observation.valid_until_ms {
            return Err(DurableFleetError::Stale);
        }
        let operation_id = operation_id(
            FleetMutationKindV1::HostObservation.as_str(),
            &content_digest(&(observation.host_id.as_str(), observation.generation))?,
            observation.observed_at_ms,
        );
        let mut tx = self
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(sqlx_error)?;
        Self::advance_clock_tx(&mut tx, now_ms).await?;
        let incarnation = sqlx::query(
            "SELECT boot_identity, generation FROM fleet_host_incarnations WHERE host_id = ?",
        )
        .bind(&observation.host_id)
        .fetch_optional(&mut *tx)
        .await
        .map_err(sqlx_error)?;
        if let Some(row) = incarnation {
            let generation = to_u64(row.try_get("generation").map_err(sqlx_error)?)?;
            if generation != observation.generation {
                return Err(DurableFleetError::Stale);
            }
            if source_id == crate::LOCAL_CAPACITY_SOURCE_ID {
                let boot: String = row.try_get("boot_identity").map_err(sqlx_error)?;
                if boot != crate::durable_execution::native_boot_identity()? {
                    return Err(DurableFleetError::Stale);
                }
            }
        } else if source_id == crate::LOCAL_CAPACITY_SOURCE_ID {
            return Err(DurableFleetError::Stale);
        }
        if let Some(row) = sqlx::query(
            "SELECT failure_domain_id, generation, observed_at_ms, valid_until_ms,
                    cpu_millis, memory_bytes, accelerator_millis,
                    concurrent_turns, tool_processes, turn_queue_slots
             FROM fleet_hosts WHERE host_id = ?",
        )
        .bind(&observation.host_id)
        .fetch_optional(&mut *tx)
        .await
        .map_err(sqlx_error)?
        {
            let current_generation = to_u64(row.try_get("generation").map_err(sqlx_error)?)?;
            if observation.generation < current_generation
                || observation.observed_at_ms
                    < to_u64(row.try_get("observed_at_ms").map_err(sqlx_error)?)?
            {
                return Err(DurableFleetError::Stale);
            }
            let current = HostObservation {
                host_id: observation.host_id.clone(),
                failure_domain_id: row.try_get("failure_domain_id").map_err(sqlx_error)?,
                generation: current_generation,
                observed_at_ms: to_u64(row.try_get("observed_at_ms").map_err(sqlx_error)?)?,
                valid_until_ms: to_u64(row.try_get("valid_until_ms").map_err(sqlx_error)?)?,
                capacity: decode_vector(&row, "")?,
            };
            if observation.generation == current_generation {
                if observation == &current {
                    let digest = content_digest(observation)?;
                    let mut retained = None;
                    // Both predecessor writers used generation or timestamp IDs.
                    // Preserve their exact committed receipt across this upgrade.
                    for id in [
                        operation_id.clone(),
                        crate::durable_rows::operation_id(
                            FleetMutationKindV1::HostObservation.as_str(),
                            &observation.host_id,
                            observation.generation,
                        ),
                        crate::durable_rows::operation_id(
                            FleetMutationKindV1::HostObservation.as_str(),
                            &observation.host_id,
                            observation.observed_at_ms,
                        ),
                    ] {
                        if let Some(receipt) =
                            crate::durable_receipt::load_receipt_tx(&mut tx, &id).await?
                            && receipt.semantic_digest == digest
                            && receipt.subject_id == observation.host_id
                            && receipt.kind == FleetMutationKindV1::HostObservation
                            && receipt.authority_witness.is_none()
                        {
                            retained = Some(receipt);
                            break;
                        }
                    }
                    let receipt = retained.ok_or_else(|| {
                        DurableFleetError::Corrupt("missing exact capacity receipt".into())
                    })?;
                    tx.commit().await.map_err(sqlx_error)?;
                    return Ok(receipt);
                }
                if observation.failure_domain_id != current.failure_domain_id
                    || observation.observed_at_ms == current.observed_at_ms
                {
                    return Err(DurableFleetError::Conflict(observation.host_id.clone()));
                }
                if observation.observed_at_ms < current.observed_at_ms {
                    return Err(DurableFleetError::Stale);
                }
            }
            if observation.generation > current_generation {
                self.retire_host_generation_tx(
                    &mut tx,
                    &observation.host_id,
                    observation.generation,
                    now_ms,
                )
                .await?;
            }
        }
        let capacity_digest = resource_digest(observation.capacity);
        insert_capacity_observation_tx(&mut tx, observation, source_id, &capacity_digest).await?;
        upsert_host_tx(&mut tx, observation, &capacity_digest).await?;
        self.ensure_zero_total_tx(&mut tx, &observation.host_id, now_ms)
            .await?;
        let receipt = FleetOperationReceiptV1 {
            operation_id,
            kind: FleetMutationKindV1::HostObservation,
            subject_id: observation.host_id.clone(),
            outcome: FleetMutationOutcomeV1::Updated,
            semantic_digest: content_digest(observation)?,
            authority_witness: None,
            committed_at_ms: now_ms,
        };
        insert_receipt_tx(&mut tx, &receipt).await?;
        crate::capacity_refresh::retain_capacity_snapshots_tx(&mut tx, &observation.host_id)
            .await?;
        match tx.commit().await {
            Ok(()) => Ok(receipt),
            Err(_) => Err(self.indeterminate(receipt.operation_id, receipt.subject_id)),
        }
    }

    pub(crate) fn indeterminate(
        &self,
        operation_id: String,
        subject_id: String,
    ) -> DurableFleetError {
        DurableFleetError::IndeterminateCommit {
            operation_id,
            subject_id,
        }
    }
}

async fn insert_capacity_observation_tx(
    tx: &mut Transaction<'_, Sqlite>,
    observation: &HostObservation,
    source_id: &str,
    capacity_digest: &str,
) -> Result<(), DurableFleetError> {
    sqlx::query(
        "INSERT INTO fleet_capacity_observations(
            host_id, generation, observed_at_ms, valid_until_ms, source_id,
            cpu_millis, memory_bytes, accelerator_millis,
            concurrent_turns, tool_processes, turn_queue_slots, capacity_digest
         ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
         ON CONFLICT(host_id, generation, observed_at_ms) DO NOTHING",
    )
    .bind(&observation.host_id)
    .bind(to_i64(observation.generation)?)
    .bind(to_i64(observation.observed_at_ms)?)
    .bind(to_i64(observation.valid_until_ms)?)
    .bind(source_id)
    .bind(to_i64(observation.capacity.cpu_millis)?)
    .bind(to_i64(observation.capacity.memory_bytes)?)
    .bind(to_i64(observation.capacity.accelerator_millis)?)
    .bind(to_i64(observation.capacity.concurrent_turns)?)
    .bind(to_i64(observation.capacity.tool_processes)?)
    .bind(to_i64(observation.capacity.turn_queue_slots)?)
    .bind(capacity_digest)
    .execute(&mut **tx)
    .await
    .map_err(sqlx_error)?;
    Ok(())
}

async fn upsert_host_tx(
    tx: &mut Transaction<'_, Sqlite>,
    observation: &HostObservation,
    capacity_digest: &str,
) -> Result<(), DurableFleetError> {
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
    .bind(&observation.host_id)
    .bind(&observation.failure_domain_id)
    .bind(to_i64(observation.generation)?)
    .bind(to_i64(observation.observed_at_ms)?)
    .bind(to_i64(observation.valid_until_ms)?)
    .bind(to_i64(observation.capacity.cpu_millis)?)
    .bind(to_i64(observation.capacity.memory_bytes)?)
    .bind(to_i64(observation.capacity.accelerator_millis)?)
    .bind(to_i64(observation.capacity.concurrent_turns)?)
    .bind(to_i64(observation.capacity.tool_processes)?)
    .bind(to_i64(observation.capacity.turn_queue_slots)?)
    .bind(capacity_digest)
    .execute(&mut **tx)
    .await
    .map_err(sqlx_error)?;
    Ok(())
}

#[cfg(all(test, unix))]
#[path = "durable_store_tests.rs"]
mod tests;
