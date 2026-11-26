use sqlx::Sqlite;
use sqlx::Transaction;

use crate::DurableFleetError;
use crate::DurableFleetStore;
use crate::FleetOperationReceiptV1;
use crate::LocalCapacityObservationV1;
use crate::LocalCapacityObserver;
use crate::durable_receipt::increment_counter_tx;
use crate::durable_schema::sqlx_error;

// These are navigation/pressure observations, never replayable effect authority.
// Keep a bounded recent window; the current snapshot and receipt always survive.
pub(crate) const MAX_HOST_CAPACITY_SNAPSHOTS: i64 = 128;

impl DurableFleetStore {
    /// Refresh physical pressure under the exact native boot incarnation returned
    /// by `register_local_boot`. Sampling does not change the process fence or
    /// release existing reservations, even when observed capacity shrinks.
    pub async fn refresh_local_capacity(
        &self,
        observer: &LocalCapacityObserver,
    ) -> Result<(LocalCapacityObservationV1, FleetOperationReceiptV1), DurableFleetError> {
        let observed = observer
            .observe(self.owner_now_ms()?)
            .map_err(|error| DurableFleetError::Unavailable(error.to_string()))?;
        let receipt = self
            .observe_host(&observed.host, observed.source_id)
            .await?;
        Ok((observed, receipt))
    }
}

pub(crate) async fn retain_capacity_snapshots_tx(
    tx: &mut Transaction<'_, Sqlite>,
    host_id: &str,
) -> Result<(), DurableFleetError> {
    sqlx::query(
        "DELETE FROM fleet_capacity_observations WHERE host_id = ?
         AND (generation, observed_at_ms) NOT IN (
             SELECT generation, observed_at_ms FROM fleet_capacity_observations
             WHERE host_id = ? ORDER BY generation DESC, observed_at_ms DESC LIMIT ?
         )",
    )
    .bind(host_id)
    .bind(host_id)
    .bind(MAX_HOST_CAPACITY_SNAPSHOTS)
    .execute(&mut **tx)
    .await
    .map_err(sqlx_error)?;
    sqlx::query(
        "DELETE FROM fleet_operation_receipts WHERE subject_id = ?
         AND operation_kind = 'host_observation' AND operation_id NOT IN (
             SELECT operation_id FROM fleet_operation_receipts
             WHERE subject_id = ? AND operation_kind = 'host_observation'
             ORDER BY committed_at_ms DESC, operation_id DESC LIMIT ?
         )",
    )
    .bind(host_id)
    .bind(host_id)
    .bind(MAX_HOST_CAPACITY_SNAPSHOTS)
    .execute(&mut **tx)
    .await
    .map_err(sqlx_error)?;
    increment_counter_tx(tx, "capacity_observation", "success").await
}
