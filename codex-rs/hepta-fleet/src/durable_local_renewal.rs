//! Sole-local-owner upkeep has one pending and one confirmed receipt per hold.
//! Generic externally replayable mutations retain their original receipts.

use sqlx::Row;
use sqlx::Sqlite;
use sqlx::Transaction;

use crate::AllocationGrant;
use crate::DurableFleetError;
use crate::DurableFleetStore;
use crate::FleetAuthorityPort;
use crate::FleetExecutionContextV1;
use crate::FleetMutationKindV1;
use crate::FleetMutationOutcomeV1;
use crate::FleetOperationReceiptV1;
use crate::durable_grant_tx::select_grant_tx;
use crate::durable_grants::renew_grant_tx;
use crate::durable_receipt::increment_counter_tx;
use crate::durable_receipt::insert_receipt_tx;
use crate::durable_receipt::load_receipt_tx;
use crate::durable_rows::decode_json;
use crate::durable_rows::operation_id;
use crate::durable_rows::validate_identity;
use crate::durable_schema::sqlx_error;

/// One exact canonical grant mutation and an optional original pending receipt
/// actually observed by the sole maintenance owner. A missing observation can
/// never clear an outstanding acknowledgement obligation.
#[derive(Debug)]
pub struct LocalRenewalRequestV1<'a> {
    pub expected_grant: &'a AllocationGrant,
    pub expires_at_ms: u64,
    pub observed_pending: Option<&'a FleetOperationReceiptV1>,
}

struct RenewalState {
    context: FleetExecutionContextV1,
    running: bool,
    pending: Option<String>,
    confirmed: Option<String>,
}

impl DurableFleetStore {
    /// Stage one local-maintenance renewal under the existing execution hold.
    /// A committed but unobserved receipt blocks subsequent local renewals until
    /// the sole owner reads and explicitly acknowledges that exact receipt.
    /// These local IDs have bounded retention after acknowledgement; callers
    /// needing permanent exact replay use `mutate_lease_authorized` instead.
    pub async fn stage_local_renewal_authorized(
        &self,
        authority: &FleetAuthorityPort,
        authority_lease_id: &str,
        expected_authority_revision: u64,
        execution_id: &str,
        request: LocalRenewalRequestV1<'_>,
    ) -> Result<FleetOperationReceiptV1, DurableFleetError> {
        let now_ms = self.owner_now_ms()?;
        let mut tx = self
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(sqlx_error)?;
        let state = renewal_state_tx(&mut tx, execution_id).await?;
        match (&state.pending, request.observed_pending) {
            (Some(pending), None) => {
                return Err(self.indeterminate(pending.clone(), state.context.allocation_id));
            }
            (_, Some(observed)) => {
                acknowledge_receipt_tx(&mut tx, execution_id, &state, observed).await?;
            }
            (None, None) => {}
        }
        Self::advance_clock_tx(&mut tx, now_ms).await?;
        self.collect_expired_tx(&mut tx, now_ms).await?;
        let current = select_grant_tx(&mut tx, &state.context.allocation_id)
            .await?
            .ok_or(DurableFleetError::Stale)?;
        if !state.running
            || current != *request.expected_grant
            || current.principal_id != state.context.principal_id
            || current.host_id != state.context.host_id
            || current.host_generation != state.context.host_generation
            || current.resources != state.context.resources
            || current.semantic_digest != state.context.manifest_digest
        {
            return Err(DurableFleetError::Stale);
        }
        let generation = current
            .lease_generation
            .checked_add(1)
            .ok_or_else(|| DurableFleetError::Invalid("lease generation overflow".into()))?;
        let witness = renew_grant_tx(
            &mut tx,
            authority,
            authority_lease_id,
            expected_authority_revision,
            &current,
            request.expires_at_ms,
            now_ms,
        )
        .await?;
        let receipt = FleetOperationReceiptV1 {
            operation_id: operation_id("local_renew", &current.allocation_id, generation),
            kind: FleetMutationKindV1::Renew,
            subject_id: current.allocation_id,
            outcome: FleetMutationOutcomeV1::Updated,
            semantic_digest: current.semantic_digest,
            authority_witness: Some(witness),
            committed_at_ms: now_ms,
        };
        insert_receipt_tx(&mut tx, &receipt).await?;
        sqlx::query("UPDATE fleet_execution_holds SET local_renewal_pending_operation_id = ? WHERE execution_id = ?")
            .bind(&receipt.operation_id).bind(execution_id)
            .execute(&mut *tx).await.map_err(sqlx_error)?;
        increment_counter_tx(&mut tx, "local_renew", "success").await?;
        match tx.commit().await {
            Ok(()) => Ok(receipt),
            Err(_) => Err(self.indeterminate(receipt.operation_id, receipt.subject_id)),
        }
    }

    /// Read the original pending receipt, including its authority witness.
    /// Absence means this hold has no outstanding local-renewal acknowledgement,
    /// never that a process exited or an arbitrary external effect did not occur.
    pub async fn pending_local_renewal(
        &self,
        execution_id: &str,
    ) -> Result<Option<FleetOperationReceiptV1>, DurableFleetError> {
        let mut tx = self.pool.begin().await.map_err(sqlx_error)?;
        let state = renewal_state_tx(&mut tx, execution_id).await?;
        let receipt = match &state.pending {
            Some(id) => Some(local_receipt_tx(&mut tx, &state.context, id).await?),
            None => None,
        };
        tx.commit().await.map_err(sqlx_error)?;
        Ok(receipt)
    }

    /// Confirm a receipt actually observed by the sole local-maintenance owner.
    /// Only the previous confirmed local receipt is removed. Pending receipts,
    /// generic mutation receipts and the native execution hold are retained.
    pub async fn acknowledge_local_renewal(
        &self,
        execution_id: &str,
        observed: &FleetOperationReceiptV1,
    ) -> Result<(), DurableFleetError> {
        let now_ms = self.owner_now_ms()?;
        let mut tx = self
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(sqlx_error)?;
        Self::advance_clock_tx(&mut tx, now_ms).await?;
        let state = renewal_state_tx(&mut tx, execution_id).await?;
        acknowledge_receipt_tx(&mut tx, execution_id, &state, observed).await?;
        match tx.commit().await {
            Ok(()) => Ok(()),
            Err(_) => {
                Err(self.indeterminate(observed.operation_id.clone(), state.context.allocation_id))
            }
        }
    }
}

async fn acknowledge_receipt_tx(
    tx: &mut Transaction<'_, Sqlite>,
    execution_id: &str,
    state: &RenewalState,
    observed: &FleetOperationReceiptV1,
) -> Result<(), DurableFleetError> {
    let id = state
        .pending
        .as_ref()
        .or(state.confirmed.as_ref())
        .ok_or(DurableFleetError::Stale)?;
    if id != &observed.operation_id {
        return Err(DurableFleetError::Stale);
    }
    if local_receipt_tx(tx, &state.context, id).await? != *observed {
        return Err(DurableFleetError::Conflict(id.clone()));
    }
    if state.pending.is_none() {
        return Ok(());
    }
    if let Some(previous) = &state.confirmed {
        if previous == id {
            return Err(DurableFleetError::Corrupt(
                "pending renewal aliases confirmed receipt".into(),
            ));
        }
        local_receipt_tx(tx, &state.context, previous).await?;
        sqlx::query("DELETE FROM fleet_operation_receipts WHERE operation_id = ?")
            .bind(previous)
            .execute(&mut **tx)
            .await
            .map_err(sqlx_error)?;
    }
    sqlx::query("UPDATE fleet_execution_holds SET local_renewal_confirmed_operation_id = ?, local_renewal_pending_operation_id = NULL WHERE execution_id = ?")
            .bind(id).bind(execution_id).execute(&mut **tx).await.map_err(sqlx_error)?;
    Ok(())
}

async fn renewal_state_tx(
    tx: &mut Transaction<'_, Sqlite>,
    execution_id: &str,
) -> Result<RenewalState, DurableFleetError> {
    validate_identity(execution_id, "execution")?;
    let row = sqlx::query("SELECT allocation_id, context_json, state, local_renewal_pending_operation_id, local_renewal_confirmed_operation_id FROM fleet_execution_holds WHERE execution_id = ?")
        .bind(execution_id).fetch_optional(&mut **tx).await.map_err(sqlx_error)?
        .ok_or_else(|| DurableFleetError::Missing(execution_id.into()))?;
    let context: FleetExecutionContextV1 = decode_json(
        &row.try_get::<String, _>("context_json")
            .map_err(sqlx_error)?,
    )?;
    if context.execution_id != execution_id
        || context.allocation_id
            != row
                .try_get::<String, _>("allocation_id")
                .map_err(sqlx_error)?
    {
        return Err(DurableFleetError::Corrupt(
            "local renewal hold identity mismatch".into(),
        ));
    }
    Ok(RenewalState {
        context,
        running: row.try_get::<String, _>("state").map_err(sqlx_error)? == "running",
        pending: row
            .try_get("local_renewal_pending_operation_id")
            .map_err(sqlx_error)?,
        confirmed: row
            .try_get("local_renewal_confirmed_operation_id")
            .map_err(sqlx_error)?,
    })
}

async fn local_receipt_tx(
    tx: &mut Transaction<'_, Sqlite>,
    context: &FleetExecutionContextV1,
    id: &str,
) -> Result<FleetOperationReceiptV1, DurableFleetError> {
    let prefix = format!("fleet:local_renew:{}:", context.allocation_id);
    let generation = id
        .strip_prefix(&prefix)
        .and_then(|value| value.parse::<u64>().ok());
    let receipt = load_receipt_tx(tx, id).await?.ok_or_else(|| {
        DurableFleetError::Corrupt("missing original local renewal receipt".into())
    })?;
    if generation.is_none_or(|generation| {
        generation < 2 || operation_id("local_renew", &context.allocation_id, generation) != id
    }) || receipt.operation_id != id
        || receipt.subject_id != context.allocation_id
        || receipt.semantic_digest != context.manifest_digest
        || receipt.kind != FleetMutationKindV1::Renew
        || receipt.outcome != FleetMutationOutcomeV1::Updated
        || receipt
            .authority_witness
            .as_ref()
            .is_none_or(|witness| witness.validate().is_err())
    {
        return Err(DurableFleetError::Corrupt(
            "invalid original local renewal receipt".into(),
        ));
    }
    Ok(receipt)
}

