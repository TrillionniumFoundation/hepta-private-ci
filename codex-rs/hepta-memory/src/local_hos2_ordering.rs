//! HOS2 ordering and retirement use the original immutable outbox/event chain.

use super::*;
use crate::HOS2_DESTINATION_V1;
use crate::HOS2_INSTALL_TOPIC_V1;
use crate::Hos2DeliveryId;
use crate::Hos2InstallBudgetV1;
use crate::production_hos2::Hos2TerminalReceipt;

fn namespace(delivery: &Hos2DeliveryId) -> Result<(String, String), LocalLeaseOutboxError> {
    delivery
        .sequence()
        .map_err(LocalLeaseOutboxError::Invalid)?;
    Ok((
        serde_json::to_string(&delivery.boot_id).map_err(serialization)?,
        serde_json::to_string(&delivery.space_id).map_err(serialization)?,
    ))
}

fn serialization(error: serde_json::Error) -> LocalLeaseOutboxError {
    LocalLeaseOutboxError::Serialization(error.to_string())
}

pub(crate) async fn validate_hos2_admission(
    transaction: &mut Transaction<'_, Sqlite>,
    owner: &AgentId,
    operation: Option<&OperationIntentV1>,
    payload_json: &str,
) -> Result<(), LocalLeaseOutboxError> {
    let payload =
        Hos2InstallBudgetV1::from_json(payload_json).map_err(LocalLeaseOutboxError::Invalid)?;
    let operation = operation.ok_or_else(|| {
        LocalLeaseOutboxError::Invalid("HOS2 requires the original operation ledger".to_string())
    })?;
    if operation.destination_id().as_str() != HOS2_DESTINATION_V1
        || operation.scope_digest() != payload.scope_digest()
        || operation.expected_predecessor().is_some()
    {
        return Err(LocalLeaseOutboxError::Invalid(
            "HOS2 operation scope mismatch".to_string(),
        ));
    }
    let sequence = payload
        .delivery
        .sequence()
        .map_err(LocalLeaseOutboxError::Invalid)?;
    let (boot, space) = namespace(&payload.delivery)?;
    let existing: Option<String> = sqlx::query_scalar(
        "SELECT occurrence_key FROM cognitive_local_outbox
         WHERE topic = 'hepta.hos2.install-budget.v1'
           AND json_extract(payload_json, '$.delivery.boot_id') = ?
           AND json_extract(payload_json, '$.delivery.space_id') = ?
           AND json_extract(payload_json, '$.delivery.sequence') = ?",
    )
    .bind(&boot)
    .bind(&space)
    .bind(format!("{sequence:016x}"))
    .fetch_optional(&mut **transaction)
    .await
    .map_err(crate::cognitive_store::unavailable)?;
    if let Some(existing) = existing {
        if existing != operation.operation_id().as_str() {
            return Err(LocalLeaseOutboxError::CasConflict(
                "HOS2 D is already bound to another K".to_string(),
            ));
        }
        // The original admission still verifies every immutable replay field.
        return Ok(());
    }
    let last: Option<String> = sqlx::query_scalar(
        "SELECT json_extract(payload_json, '$.delivery.sequence') FROM cognitive_local_outbox
         WHERE topic = 'hepta.hos2.install-budget.v1'
           AND json_extract(payload_json, '$.delivery.boot_id') = ?
           AND json_extract(payload_json, '$.delivery.space_id') = ?
         ORDER BY json_extract(payload_json, '$.delivery.sequence') DESC LIMIT 1",
    )
    .bind(&boot)
    .bind(&space)
    .fetch_optional(&mut **transaction)
    .await
    .map_err(crate::cognitive_store::unavailable)?;
    let expected = match last {
        None => 1,
        Some(last) => u64::from_str_radix(&last, 16)
            .ok()
            .and_then(|value| value.checked_add(1))
            .ok_or_else(|| corrupt("HOS2 planned sequence overflow"))?,
    };
    if sequence != expected {
        return Err(LocalLeaseOutboxError::IllegalTransition(
            "HOS2 admission requires the next sequence in the original namespace".to_string(),
        ));
    }
    validate_hos2_predecessor(transaction, owner, &payload).await
}

pub(crate) async fn validate_hos2_predecessor(
    transaction: &mut Transaction<'_, Sqlite>,
    owner: &AgentId,
    payload: &Hos2InstallBudgetV1,
) -> Result<(), LocalLeaseOutboxError> {
    let sequence = payload
        .delivery
        .sequence()
        .map_err(LocalLeaseOutboxError::Invalid)?;
    if sequence == 1 {
        return Ok(());
    }
    let (boot, space) = namespace(&payload.delivery)?;
    let previous = sequence - 1;
    let pair: Option<(String, String)> = sqlx::query_as(
        "SELECT lease_id, occurrence_key FROM cognitive_local_outbox
         WHERE topic = 'hepta.hos2.install-budget.v1'
           AND json_extract(payload_json, '$.delivery.boot_id') = ?
           AND json_extract(payload_json, '$.delivery.space_id') = ?
           AND json_extract(payload_json, '$.delivery.sequence') = ?",
    )
    .bind(boot)
    .bind(space)
    .bind(format!("{previous:016x}"))
    .fetch_optional(&mut **transaction)
    .await
    .map_err(crate::cognitive_store::unavailable)?;
    let (lease, operation) = pair.ok_or_else(|| {
        LocalLeaseOutboxError::IllegalTransition(
            "HOS2 predecessor is absent from the original outbox".to_string(),
        )
    })?;
    verified_terminal(transaction, owner, &lease, &operation).await?;
    Ok(())
}

async fn verified_terminal(
    transaction: &mut Transaction<'_, Sqlite>,
    owner: &AgentId,
    lease: &str,
    operation_id: &str,
) -> Result<(Hos2InstallBudgetV1, Sha256Digest), LocalLeaseOutboxError> {
    let admission = find_admission(transaction, lease, operation_id, owner)
        .await?
        .ok_or_else(|| corrupt("HOS2 terminal admission is absent"))?;
    let outbox = find_outbox(transaction, lease, operation_id, owner)
        .await?
        .ok_or_else(|| corrupt("HOS2 terminal outbox is absent"))?;
    verify_occurrence_pair_incremental(lease, owner, &admission, &outbox)?;
    let operation = find_operation(transaction, operation_id)
        .await?
        .ok_or_else(|| corrupt("HOS2 terminal operation is absent"))?;
    let intent = verify_operation_row_incremental(&operation, lease, owner, &admission, &outbox)?;
    let payload = Hos2InstallBudgetV1::from_json(&outbox.payload_json)
        .map_err(LocalLeaseOutboxError::Corrupt)?;
    if outbox.topic != HOS2_INSTALL_TOPIC_V1
        || intent.destination_id().as_str() != HOS2_DESTINATION_V1
        || intent.scope_digest() != payload.scope_digest()
    {
        return Err(corrupt(
            "HOS2 terminal namespace or operation scope differs",
        ));
    }
    let latest = latest_occurrence_event(transaction, lease, operation_id, owner)
        .await?
        .ok_or_else(|| corrupt("HOS2 terminal event is absent"))?;
    let receipt = Hos2TerminalReceipt::from_json(&latest.payload_json, &payload).map_err(|_| {
        LocalLeaseOutboxError::IllegalTransition(
            "HOS2 predecessor lacks complete durable native terminal evidence".to_string(),
        )
    })?;
    let expected_kind = match receipt.outcome() {
        LocalReconcileOutcome::Committed => "reconcile_committed",
        LocalReconcileOutcome::Rejected => "reconcile_rejected",
        LocalReconcileOutcome::StillIndeterminate => {
            return Err(corrupt("HOS2 terminal outcome is unknown"));
        }
    };
    if latest.kind != expected_kind {
        return Err(LocalLeaseOutboxError::IllegalTransition(
            "HOS2 source is not terminal".to_string(),
        ));
    }
    Ok((payload, latest.event_sha256))
}

impl LocalLeaseOutbox {
    /// The exact current writer reads every member of the requested prefix
    /// from its original database. No cursor or caller receipt is trusted.
    pub(crate) async fn hos2_durable_prefix(
        &self,
        through: &Hos2DeliveryId,
    ) -> Result<Sha256Digest, LocalLeaseOutboxError> {
        let frontier = through.sequence().map_err(LocalLeaseOutboxError::Invalid)?;
        let (boot, space) = namespace(through)?;
        let mut transaction = self
            .store
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(crate::cognitive_store::unavailable)?;
        let lease = self.current_lease(&mut transaction).await?;
        ensure_current_active(&lease, self)?;
        let pairs: Vec<(String, String)> = sqlx::query_as(
            "SELECT lease_id, occurrence_key FROM cognitive_local_outbox
             WHERE topic = 'hepta.hos2.install-budget.v1'
               AND json_extract(payload_json, '$.delivery.boot_id') = ?
               AND json_extract(payload_json, '$.delivery.space_id') = ?
               AND json_extract(payload_json, '$.delivery.sequence') <= ?
             ORDER BY json_extract(payload_json, '$.delivery.sequence') LIMIT ?",
        )
        .bind(boot)
        .bind(space)
        .bind(format!("{frontier:016x}"))
        .bind((MAX_OUTBOX_ROWS + 1) as i64)
        .fetch_all(&mut *transaction)
        .await
        .map_err(crate::cognitive_store::unavailable)?;
        if pairs.len() > MAX_OUTBOX_ROWS || u64::try_from(pairs.len()).ok() != Some(frontier) {
            return Err(LocalLeaseOutboxError::IllegalTransition(
                "HOS2 durable terminal prefix has a gap".to_string(),
            ));
        }
        let mut digest = Sha256::new();
        digest.update(b"hepta.hos2.original-terminal-prefix.v1\0");
        digest.update(through.boot_id);
        digest.update(through.space_id);
        for (index, (source_lease, operation)) in pairs.iter().enumerate() {
            let (payload, event_digest) = verified_terminal(
                &mut transaction,
                &self.owner_agent_id,
                source_lease,
                operation,
            )
            .await?;
            if payload.delivery.boot_id != through.boot_id
                || payload.delivery.space_id != through.space_id
                || payload
                    .delivery
                    .sequence()
                    .map_err(LocalLeaseOutboxError::Corrupt)?
                    != index as u64 + 1
            {
                return Err(corrupt(
                    "HOS2 terminal prefix has a different namespace or sequence",
                ));
            }
            frame_part(&mut digest, operation.as_bytes());
            frame_part(&mut digest, event_digest.as_str().as_bytes());
        }
        let digest = Sha256Digest::parse(format!("{:x}", digest.finalize()))
            .map_err(LocalLeaseOutboxError::Corrupt)?;
        transaction
            .commit()
            .await
            .map_err(crate::cognitive_store::unavailable)?;
        Ok(digest)
    }
}
