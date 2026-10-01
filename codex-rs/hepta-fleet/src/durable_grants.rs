use sqlx::Row;

use crate::AllocationGrant;
use crate::DurableFleetError;
use crate::DurableFleetStore;
use crate::DurableGrantReceiptV1;
use crate::DurableLeaseDispositionV1;
use crate::FleetAuthorityPort;
use crate::FleetMutationKindV1;
use crate::FleetMutationOutcomeV1;
use crate::FleetOperationReceiptV1;
use crate::FleetUsePermitV1;
use crate::MAX_DURABLE_ACTIVE_GRANTS;
use crate::MAX_DURABLE_HISTORY_ROWS;
use crate::durable_grant_tx::load_total_tx;
use crate::durable_grant_tx::retire_grant_tx;
use crate::durable_grant_tx::select_grant_tx;
use crate::durable_grant_tx::select_host_tx;
use crate::durable_grant_tx::write_total_tx;
use crate::durable_receipt::increment_counter_tx;
use crate::durable_receipt::insert_receipt_tx;
use crate::durable_receipt::load_receipt_tx;
use crate::durable_rows::encode_json;
use crate::durable_rows::operation_id;
use crate::durable_rows::resource_digest;
use crate::durable_rows::to_i64;
use crate::durable_rows::validate_digest;
use crate::durable_rows::validate_grant;
use crate::durable_rows::validate_identity;
use crate::durable_schema::sqlx_error;

impl DurableFleetStore {
    pub async fn issue_authorized(
        &self,
        authority: &FleetAuthorityPort,
        authority_lease_id: &str,
        expected_authority_revision: u64,
        grant: AllocationGrant,
    ) -> Result<DurableGrantReceiptV1, DurableFleetError> {
        validate_grant(&grant)?;
        let operation_id = operation_id("issue", &grant.allocation_id, grant.lease_generation);
        let mut tx = self
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(sqlx_error)?;
        let now_ms = self.owner_now_ms()?;
        Self::advance_clock_tx(&mut tx, now_ms).await?;
        self.collect_expired_tx(&mut tx, now_ms).await?;

        if let Some(receipt) = load_receipt_tx(&mut tx, &operation_id).await? {
            let existing = select_grant_tx(&mut tx, &grant.allocation_id)
                .await?
                .ok_or_else(|| {
                    DurableFleetError::Corrupt(
                        "issue receipt exists without active grant".to_string(),
                    )
                })?;
            if !same_grant(&existing, &grant) {
                return Err(DurableFleetError::Conflict(grant.allocation_id));
            }
            tx.commit().await.map_err(sqlx_error)?;
            return Ok(DurableGrantReceiptV1 {
                grant: existing,
                operation: receipt,
            });
        }
        let retired: bool = sqlx::query_scalar(
            "SELECT EXISTS(SELECT 1 FROM fleet_grant_history WHERE allocation_id = ?)",
        )
        .bind(&grant.allocation_id)
        .fetch_one(&mut *tx)
        .await
        .map_err(sqlx_error)?;
        if retired {
            return Err(DurableFleetError::Conflict(grant.allocation_id));
        }
        let witness = authority.verify_issue_witness(
            authority_lease_id,
            expected_authority_revision,
            &grant,
        )?;
        let host = select_host_tx(&mut tx, &grant.host_id)
            .await?
            .ok_or_else(|| DurableFleetError::Missing(grant.host_id.clone()))?;
        if now_ms < host.observed_at_ms
            || now_ms >= host.valid_until_ms
            || host.generation != grant.host_generation
            || host.failure_domain_id != grant.failure_domain_id
            || grant.expires_at_ms <= now_ms
            || grant.expires_at_ms > host.valid_until_ms
        {
            return Err(DurableFleetError::Stale);
        }
        let active_count: i64 = sqlx::query_scalar("SELECT COUNT(*) FROM fleet_grants")
            .fetch_one(&mut *tx)
            .await
            .map_err(sqlx_error)?;
        if active_count >= MAX_DURABLE_ACTIVE_GRANTS {
            return Err(DurableFleetError::Capacity);
        }
        let total = load_total_tx(&mut tx, &grant.host_id).await?;
        let next = total
            .checked_add(grant.resources)
            .map_err(|error| DurableFleetError::Invalid(error.to_string()))?;
        grant
            .resources
            .compatible_with(host.capacity)
            .map_err(|error| DurableFleetError::Invalid(error.to_string()))?;
        if !next.fits(host.capacity) {
            return Err(DurableFleetError::Capacity);
        }
        insert_grant_tx(&mut tx, &grant, &encode_json(&witness)?, now_ms).await?;
        write_total_tx(&mut tx, &grant.host_id, next, now_ms).await?;
        let receipt = FleetOperationReceiptV1 {
            operation_id,
            kind: FleetMutationKindV1::Issue,
            subject_id: grant.allocation_id.clone(),
            outcome: FleetMutationOutcomeV1::Inserted,
            semantic_digest: grant.semantic_digest.clone(),
            authority_witness: Some(witness),
            committed_at_ms: now_ms,
        };
        insert_receipt_tx(&mut tx, &receipt).await?;
        increment_counter_tx(&mut tx, "issue", "success").await?;
        match tx.commit().await {
            Ok(()) => Ok(DurableGrantReceiptV1 {
                grant,
                operation: receipt,
            }),
            Err(_) => Err(self.indeterminate(receipt.operation_id, receipt.subject_id)),
        }
    }

    pub async fn mutate_lease_authorized(
        &self,
        authority: &FleetAuthorityPort,
        authority_lease_id: &str,
        expected_authority_revision: u64,
        allocation_id: &str,
        expected_lease_generation: u64,
        authority_epoch: u64,
        semantic_digest: &str,
        disposition: DurableLeaseDispositionV1,
    ) -> Result<FleetOperationReceiptV1, DurableFleetError> {
        validate_identity(allocation_id, "allocation")?;
        validate_digest(semantic_digest)?;
        let next_generation = expected_lease_generation
            .checked_add(1)
            .ok_or_else(|| DurableFleetError::Invalid("lease generation overflow".into()))?;
        let operation = match &disposition {
            DurableLeaseDispositionV1::Renew { .. } => "renew",
            DurableLeaseDispositionV1::Revoke => "revoke",
        };
        let operation_id = operation_id(operation, allocation_id, next_generation);
        let mut tx = self
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(sqlx_error)?;
        let now_ms = self.owner_now_ms()?;
        Self::advance_clock_tx(&mut tx, now_ms).await?;
        self.collect_expired_tx(&mut tx, now_ms).await?;
        if let Some(receipt) = load_receipt_tx(&mut tx, &operation_id).await? {
            tx.commit().await.map_err(sqlx_error)?;
            return Ok(receipt);
        }
        let current = select_grant_tx(&mut tx, allocation_id)
            .await?
            .ok_or(DurableFleetError::Stale)?;
        if current.lease_generation != expected_lease_generation
            || current.authority_epoch != authority_epoch
            || current.semantic_digest != semantic_digest
        {
            return Err(DurableFleetError::Stale);
        }
        let (kind, outcome, witness) = match disposition {
            DurableLeaseDispositionV1::Renew { expires_at_ms } => {
                let witness = renew_grant_tx(
                    &mut tx,
                    authority,
                    authority_lease_id,
                    expected_authority_revision,
                    &current,
                    expires_at_ms,
                    now_ms,
                )
                .await?;
                (
                    FleetMutationKindV1::Renew,
                    FleetMutationOutcomeV1::Updated,
                    witness,
                )
            }
            DurableLeaseDispositionV1::Revoke => {
                let witness = authority.verify_revoke_witness(
                    authority_lease_id,
                    expected_authority_revision,
                    &current,
                )?;
                let mut terminal = current.clone();
                terminal.lease_generation = next_generation;
                terminal.revoked = true;
                retire_grant_tx(&mut tx, &terminal, "revoked", now_ms).await?;
                (
                    FleetMutationKindV1::Revoke,
                    FleetMutationOutcomeV1::Revoked,
                    witness,
                )
            }
        };
        let receipt = FleetOperationReceiptV1 {
            operation_id,
            kind,
            subject_id: allocation_id.to_string(),
            outcome,
            semantic_digest: semantic_digest.to_string(),
            authority_witness: Some(witness),
            committed_at_ms: now_ms,
        };
        insert_receipt_tx(&mut tx, &receipt).await?;
        increment_counter_tx(&mut tx, operation, "success").await?;
        match tx.commit().await {
            Ok(()) => Ok(receipt),
            Err(_) => Err(self.indeterminate(receipt.operation_id, receipt.subject_id)),
        }
    }

    pub async fn collect_expired(&self) -> Result<usize, DurableFleetError> {
        let mut tx = self
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(sqlx_error)?;
        let now_ms = self.owner_now_ms()?;
        Self::advance_clock_tx(&mut tx, now_ms).await?;
        let retired = self.collect_expired_tx(&mut tx, now_ms).await?;
        match tx.commit().await {
            Ok(()) => Ok(retired),
            Err(_) => Err(self.indeterminate(
                operation_id("expiry_sweep", "fleet", now_ms),
                "fleet".into(),
            )),
        }
    }

    pub async fn verify_use(
        &self,
        allocation_id: &str,
        principal_id: &str,
        host_id: &str,
        host_generation: u64,
        expected_lease_generation: u64,
        semantic_digest: &str,
    ) -> Result<FleetUsePermitV1, DurableFleetError> {
        validate_identity(allocation_id, "allocation")?;
        validate_identity(principal_id, "principal")?;
        validate_identity(host_id, "host")?;
        validate_digest(semantic_digest)?;
        let mut tx = self.pool.begin().await.map_err(sqlx_error)?;
        let grant = select_grant_tx(&mut tx, allocation_id)
            .await?
            .ok_or(DurableFleetError::Stale)?;
        let host = select_host_tx(&mut tx, host_id)
            .await?
            .ok_or(DurableFleetError::Stale)?;
        let now_ms = self.owner_now_ms()?;
        if grant.principal_id != principal_id
            || grant.host_id != host_id
            || grant.host_generation != host_generation
            || grant.lease_generation != expected_lease_generation
            || grant.semantic_digest != semantic_digest
            || grant.expires_at_ms <= now_ms
            || host.generation != host_generation
            || host.valid_until_ms <= now_ms
        {
            return Err(DurableFleetError::Stale);
        }
        tx.commit().await.map_err(sqlx_error)?;
        Ok(FleetUsePermitV1 {
            allocation_id: grant.allocation_id,
            principal_id: grant.principal_id,
            host_id: grant.host_id,
            host_generation: grant.host_generation,
            lease_generation: grant.lease_generation,
            expires_at_ms: grant.expires_at_ms,
            resources: grant.resources,
            semantic_digest: grant.semantic_digest,
            checked_at_ms: now_ms,
        })
    }

    pub async fn compact_history(&self, limit: u64) -> Result<u64, DurableFleetError> {
        if limit == 0 {
            return Err(DurableFleetError::Invalid(
                "compaction limit must be positive".into(),
            ));
        }
        let mut tx = self
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(sqlx_error)?;
        let now_ms = self.owner_now_ms()?;
        Self::advance_clock_tx(&mut tx, now_ms).await?;
        let full_count: i64 =
            sqlx::query_scalar("SELECT COUNT(*) FROM fleet_grant_history WHERE compacted = 0")
                .fetch_one(&mut *tx)
                .await
                .map_err(sqlx_error)?;
        let excess = full_count.saturating_sub(MAX_DURABLE_HISTORY_ROWS);
        let target = excess.min(to_i64(limit)?);
        if target == 0 {
            tx.commit().await.map_err(sqlx_error)?;
            return Ok(0);
        }
        let rows = sqlx::query(
            "SELECT allocation_id FROM fleet_grant_history
             WHERE compacted = 0 ORDER BY retired_at_ms, allocation_id LIMIT ?",
        )
        .bind(target)
        .fetch_all(&mut *tx)
        .await
        .map_err(sqlx_error)?;
        for row in &rows {
            let allocation_id: String = row.try_get("allocation_id").map_err(sqlx_error)?;
            sqlx::query(
                "UPDATE fleet_grant_history
                 SET grant_json = NULL, compacted = 1 WHERE allocation_id = ?",
            )
            .bind(allocation_id)
            .execute(&mut *tx)
            .await
            .map_err(sqlx_error)?;
        }
        increment_counter_tx(&mut tx, "compact", "success").await?;
        let compacted = u64::try_from(rows.len()).unwrap_or(u64::MAX);
        match tx.commit().await {
            Ok(()) => Ok(compacted),
            Err(_) => {
                Err(self
                    .indeterminate(operation_id("compact", "history", now_ms), "history".into()))
            }
        }
    }

    pub async fn operation_receipt(
        &self,
        operation_id: &str,
    ) -> Result<Option<FleetOperationReceiptV1>, DurableFleetError> {
        let row =
            sqlx::query("SELECT payload_json FROM fleet_operation_receipts WHERE operation_id = ?")
                .bind(operation_id)
                .fetch_optional(&self.pool)
                .await
                .map_err(sqlx_error)?;
        row.map(|row| {
            let json: String = row.try_get("payload_json").map_err(sqlx_error)?;
            crate::durable_rows::decode_json(&json)
        })
        .transpose()
    }
}

async fn insert_grant_tx(
    tx: &mut sqlx::Transaction<'_, sqlx::Sqlite>,
    grant: &AllocationGrant,
    witness_json: &str,
    now_ms: u64,
) -> Result<(), DurableFleetError> {
    sqlx::query(
        "INSERT INTO fleet_grants(
            allocation_id, request_id, principal_id, host_id, failure_domain_id,
            host_generation, authority_epoch, lease_generation, expires_at_ms,
            cpu_millis, memory_bytes, accelerator_millis,
            concurrent_turns, tool_processes, turn_queue_slots,
            resource_digest, semantic_digest, authority_witness_json,
            created_at_ms, updated_at_ms
         ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
    )
    .bind(&grant.allocation_id)
    .bind(&grant.request_id)
    .bind(&grant.principal_id)
    .bind(&grant.host_id)
    .bind(&grant.failure_domain_id)
    .bind(to_i64(grant.host_generation)?)
    .bind(to_i64(grant.authority_epoch)?)
    .bind(to_i64(grant.lease_generation)?)
    .bind(to_i64(grant.expires_at_ms)?)
    .bind(to_i64(grant.resources.cpu_millis)?)
    .bind(to_i64(grant.resources.memory_bytes)?)
    .bind(to_i64(grant.resources.accelerator_millis)?)
    .bind(to_i64(grant.resources.concurrent_turns)?)
    .bind(to_i64(grant.resources.tool_processes)?)
    .bind(to_i64(grant.resources.turn_queue_slots)?)
    .bind(resource_digest(grant.resources))
    .bind(&grant.semantic_digest)
    .bind(witness_json)
    .bind(to_i64(now_ms)?)
    .bind(to_i64(now_ms)?)
    .execute(&mut **tx)
    .await
    .map_err(sqlx_error)?;
    Ok(())
}

pub(crate) fn same_grant(left: &AllocationGrant, right: &AllocationGrant) -> bool {
    left.allocation_id == right.allocation_id
        && left.request_id == right.request_id
        && left.principal_id == right.principal_id
        && left.host_id == right.host_id
        && left.failure_domain_id == right.failure_domain_id
        && left.host_generation == right.host_generation
        && left.authority_epoch == right.authority_epoch
        && left.lease_generation == right.lease_generation
        && left.expires_at_ms == right.expires_at_ms
        && left.resources == right.resources
        && left.semantic_digest == right.semantic_digest
}

pub(crate) async fn renew_grant_tx(
    tx: &mut sqlx::Transaction<'_, sqlx::Sqlite>,
    authority: &FleetAuthorityPort,
    authority_lease_id: &str,
    expected_authority_revision: u64,
    current: &AllocationGrant,
    expires_at_ms: u64,
    now_ms: u64,
) -> Result<codex_hepta_contracts::VerifiedUseTokenWitnessV1, DurableFleetError> {
    let next_generation = current
        .lease_generation
        .checked_add(1)
        .ok_or_else(|| DurableFleetError::Invalid("lease generation overflow".into()))?;
    let host = select_host_tx(tx, &current.host_id)
        .await?
        .ok_or_else(|| DurableFleetError::Missing(current.host_id.clone()))?;
    if now_ms >= host.valid_until_ms
        || host.generation != current.host_generation
        || expires_at_ms <= now_ms
        || expires_at_ms > host.valid_until_ms
    {
        return Err(DurableFleetError::Stale);
    }
    let witness = authority.verify_renew_witness(
        authority_lease_id,
        expected_authority_revision,
        current,
        expires_at_ms,
    )?;
    sqlx::query(
        "UPDATE fleet_grants SET lease_generation = ?, expires_at_ms = ?,
         authority_witness_json = ?, updated_at_ms = ?
         WHERE allocation_id = ? AND lease_generation = ?",
    )
    .bind(to_i64(next_generation)?)
    .bind(to_i64(expires_at_ms)?)
    .bind(encode_json(&witness)?)
    .bind(to_i64(now_ms)?)
    .bind(&current.allocation_id)
    .bind(to_i64(current.lease_generation)?)
    .execute(&mut **tx)
    .await
    .map_err(sqlx_error)?;
    Ok(witness)
}
