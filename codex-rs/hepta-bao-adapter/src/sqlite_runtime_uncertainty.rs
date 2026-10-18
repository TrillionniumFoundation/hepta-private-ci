//! sqlite runtime uncertainty implementation.

use super::*;

impl BaoFinalUseHost {
    pub(super) async fn mark_sqlite_indeterminate(
        &self,
        owner: &SqliteBaoOwnerV1,
        operation_id: &str,
        _error: &BaoAuthBusError,
    ) -> Result<(), BaoProductHostError> {
        let current = owner
            .consumption_result(operation_id)
            .await
            .map_err(BaoProductHostError::SqliteStore)?;
        if current
            .operation
            .state
            .allows_transition_to(BaoConsumptionStateV1::Indeterminate)
        {
            owner
                .mark_consumption_indeterminate(
                    operation_id,
                    current.revision,
                    Digest32::of_bytes(b"hepta.bao.sqlite.indeterminate.v1").into_array(),
                    self.product_now()?,
                )
                .await
                .map_err(BaoProductHostError::SqliteStore)?;
        }
        Ok(())
    }

    pub(super) async fn close_unreserved_sqlite_failure(
        &self,
        authbus: &AuthBusAuthorityHost,
        owner: &SqliteBaoOwnerV1,
        operation_id: &str,
        error: &BaoAuthBusError,
    ) -> Result<Option<BaoConsumptionOperationV1>, BaoProductHostError> {
        let row = owner
            .consumption_result(operation_id)
            .await
            .map_err(BaoProductHostError::SqliteStore)?;
        if row.operation.state != BaoConsumptionStateV1::Claimed {
            return Ok(None);
        }
        let stable_operation = StableId::new(operation_id.to_owned()).map_err(|_| {
            BaoProductHostError::SqliteStore(SqliteBaoOwnerErrorV1::CorruptState(
                "invalid durable operation identifier",
            ))
        })?;
        if authbus
            .seal_unreserved_operation(
                &stable_operation,
                Digest32::from_array(row.operation.effect_sha256),
            )
            .await
            .map_err(|error| BaoProductHostError::AuthBus(error.into()))?
            .is_some()
        {
            return Ok(None);
        }
        let evidence = Digest32::of_bytes(
            format!("hepta.bao.sqlite.pre-reservation.v1:{operation_id}:{error:?}").as_bytes(),
        )
        .into_array();
        let terminal = owner
            .abort_consumption_before_reservation(
                operation_id,
                row.revision,
                evidence,
                self.product_now()?,
            )
            .await
            .map_err(BaoProductHostError::SqliteStore)?;
        Ok(Some(terminal.operation))
    }
}
