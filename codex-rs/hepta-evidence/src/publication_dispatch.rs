//! Keep the admitted trust, publication owner and operation identity in one
//! SQLite write epoch while the synchronous backend boundary is crossed.

use codex_hepta_contracts::Sha256Digest;
use sqlx::Row;
use sqlx::Sqlite;
use sqlx::Transaction;

use crate::EvidenceAcceptedFrontierV1;
use crate::EvidenceError;
use crate::EvidenceFrontierBackendError;
use crate::EvidenceFrontierDurableAckV1;
use crate::EvidencePublicationAckDisposition;
use crate::EvidencePublicationOwnerLeaseV1;
use crate::EvidenceRecoveryFrontierV2;
use crate::EvidenceTrustSnapshotView;
use crate::HeptaEvidenceStore;
use crate::VerifiedEvidenceTrustSnapshot;
use crate::canonical::canonical_json;
use crate::evidence_recovery_frontier_v2_sha256;
use crate::frontier_acceptance::accept_in_transaction;
use crate::schema_validation::classify_sqlx_error;
use crate::store::now_millis;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum EvidencePublicationDispatchModeV1 {
    PublishOrRecover,
    RecoverOnly,
}

impl HeptaEvidenceStore {
    /// Execute one synchronous backend boundary under the current durable
    /// owner/trust epoch. The callback must not re-enter this database and must
    /// use bounded/nonblocking backend lock acquisition. Signature, backup and
    /// build admission remain the product caller's responsibility.
    ///
    /// The durable Dispatching record is committed BEFORE entering this method.
    /// This transaction changes no rows. Dropping it never erases that record;
    /// any uncertain external result must reconcile the same batch. Holding the
    /// writer reservation prevents a concurrent owner/trust acceptance from
    /// committing between the final check and the external call.
    pub async fn with_publication_dispatch_guard<F>(
        &self,
        lease: &EvidencePublicationOwnerLeaseV1,
        batch_id: &str,
        trust: &VerifiedEvidenceTrustSnapshot,
        proposed: &EvidenceRecoveryFrontierV2,
        dispatch: F,
    ) -> Result<EvidenceFrontierDurableAckV1, EvidenceFrontierBackendError>
    where
        F: FnOnce(
            EvidencePublicationDispatchModeV1,
        ) -> Result<EvidenceFrontierDurableAckV1, EvidenceFrontierBackendError>,
    {
        proposed.validate_structure().map_err(local_error)?;
        if !trust.is_monotonic() || proposed.snapshot.schema_version != 2 {
            return Err(invalid(
                "publication dispatch requires admitted V2 trust and snapshot",
            ));
        }
        let digest = evidence_recovery_frontier_v2_sha256(proposed).map_err(local_error)?;
        let mut transaction = self
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(sql_error)?;
        trust.validate_store(self).map_err(local_error)?;
        let mode = validate_dispatch_epoch(
            &mut transaction, lease, batch_id, trust, proposed, &digest,
        )
        .await?;
        // File checks are not a replacement for the durable generation check
        // above. Recheck the private file after all asynchronous SQL reads too.
        trust.validate_store(self).map_err(local_error)?;
        require_live_lease(lease)?;
        let outcome = dispatch(mode);
        let policy_after = trust.validate_store(self);
        let lease_after = require_live_lease(lease);
        let release = transaction.rollback().await;
        if let Err(error) = release {
            return Err(EvidenceFrontierBackendError::Indeterminate(format!(
                "external publication outcome {outcome:?}; dispatch epoch release failed: {error}"
            )));
        }
        if policy_after.is_err() || lease_after.is_err() {
            return Err(EvidenceFrontierBackendError::Indeterminate(format!(
                "external publication outcome {outcome:?}; policy or lease changed during dispatch; reconcile the same batch"
            )));
        }
        let ack = outcome?;
        if ack.store_id != proposed.store_id
            || ack.frontier_generation != proposed.frontier_generation
            || ack.frontier_sha256 != digest
            || ack.backend_identity_sha256 != proposed.backend_identity_sha256
            || ack.audit_sequence == 0
        {
            return Err(EvidenceFrontierBackendError::Indeterminate(
                "backend acknowledgement differs from the guarded operation; reconcile the same batch"
                    .to_string(),
            ));
        }
        Ok(ack)
    }

    /// Admit the matching backend observation in the same write epoch as the
    /// current trust and owner checks. The raw compatibility acknowledgement
    /// method is not the Agentd production admission path.
    pub async fn acknowledge_publication_with_trust(
        &self,
        lease: &EvidencePublicationOwnerLeaseV1,
        batch_id: &str,
        trust: &VerifiedEvidenceTrustSnapshot,
        proposed: &EvidenceRecoveryFrontierV2,
        acknowledgement: &EvidenceFrontierDurableAckV1,
    ) -> Result<EvidencePublicationAckDisposition, EvidenceFrontierBackendError> {
        proposed.validate_structure().map_err(local_error)?;
        if !trust.is_monotonic() || proposed.snapshot.schema_version != 2 {
            return Err(invalid(
                "publication acknowledgement requires admitted V2 trust and snapshot",
            ));
        }
        let digest = evidence_recovery_frontier_v2_sha256(proposed).map_err(local_error)?;
        if acknowledgement.store_id != proposed.store_id
            || acknowledgement.frontier_generation != proposed.frontier_generation
            || acknowledgement.frontier_sha256 != digest
            || acknowledgement.backend_identity_sha256 != proposed.backend_identity_sha256
            || acknowledgement.audit_sequence == 0
        {
            return Err(invalid(
                "publication acknowledgement identity differs from the proposal",
            ));
        }
        let mut transaction = self
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(sql_error)?;
        trust.validate_store(self).map_err(local_error)?;
        let mode = validate_dispatch_epoch(
            &mut transaction, lease, batch_id, trust, proposed, &digest,
        )
        .await?;
        require_live_lease(lease)?;
        let row = sqlx::query(
            "SELECT intent_count, durable_audit_sequence FROM evidence_publication_batches WHERE batch_id = ?",
        )
        .bind(batch_id)
        .fetch_one(&mut *transaction)
        .await
        .map_err(sql_error)?;
        if mode == EvidencePublicationDispatchModeV1::RecoverOnly {
            let sequence: Option<i64> = row
                .try_get("durable_audit_sequence")
                .map_err(sql_error)?;
            if sequence.and_then(|value| u64::try_from(value).ok())
                != Some(acknowledgement.audit_sequence)
            {
                return Err(invalid(
                    "terminal publication acknowledgement was substituted",
                ));
            }
            trust.validate_store(self).map_err(local_error)?;
            transaction.rollback().await.map_err(sql_error)?;
            return Ok(EvidencePublicationAckDisposition::AlreadyAcknowledged);
        }
        let intent_count: i64 = row.try_get("intent_count").map_err(sql_error)?;
        let now = now_millis().map_err(local_error)?;
        accept_in_transaction(
            &mut transaction,
            &EvidenceAcceptedFrontierV1 {
                store_id: proposed.store_id.clone(),
                frontier_generation: proposed.frontier_generation,
                frontier_sha256: digest,
                backend_identity_sha256: proposed.backend_identity_sha256.clone(),
                accepted_at_unix_ms: u64::try_from(now)
                    .map_err(|_| invalid("invalid acknowledgement clock"))?,
            },
            false,
        )
        .await
        .map_err(local_error)?;
        let audit_sequence = i64::try_from(acknowledgement.audit_sequence)
            .map_err(|_| invalid("publication audit sequence overflow"))?;
        let batch = sqlx::query(
            "UPDATE evidence_publication_batches SET state = 'acknowledged', durable_audit_sequence = ?, updated_at_ms = ?
             WHERE batch_id = ? AND state IN ('dispatching', 'indeterminate')",
        )
        .bind(audit_sequence)
        .bind(now)
        .bind(batch_id)
        .execute(&mut *transaction)
        .await
        .map_err(sql_error)?;
        let intents = sqlx::query(
            "UPDATE evidence_publication_intents SET state = 'acknowledged', updated_at_ms = ?
             WHERE batch_id = ? AND state = 'batched'",
        )
        .bind(now)
        .bind(batch_id)
        .execute(&mut *transaction)
        .await
        .map_err(sql_error)?;
        if batch.rows_affected() != 1
            || Some(intents.rows_affected()) != u64::try_from(intent_count).ok()
        {
            return Err(EvidenceFrontierBackendError::Corrupt(
                "publication acknowledgement did not cover the exact durable batch".to_string(),
            ));
        }
        trust.validate_store(self).map_err(local_error)?;
        require_live_lease(lease)?;
        transaction.commit().await.map_err(|error| {
            EvidenceFrontierBackendError::Indeterminate(format!(
                "local publication acknowledgement commit is unresolved: {error}"
            ))
        })?;
        Ok(EvidencePublicationAckDisposition::Acknowledged)
    }
}

async fn validate_dispatch_epoch(
    transaction: &mut Transaction<'_, Sqlite>,
    lease: &EvidencePublicationOwnerLeaseV1,
    batch_id: &str,
    trust: &VerifiedEvidenceTrustSnapshot,
    proposed: &EvidenceRecoveryFrontierV2,
    digest: &Sha256Digest,
) -> Result<EvidencePublicationDispatchModeV1, EvidenceFrontierBackendError> {
    let row = sqlx::query(
        "SELECT b.store_id, b.state, b.proposed_frontier_generation,
                b.proposed_frontier_sha256, b.backend_identity_sha256,
                b.snapshot_sha256, b.expected_frontier_generation,
                b.expected_frontier_sha256, b.expected_backend_identity_sha256,
                o.owner_id, o.owner_generation, o.lease_expires_at_ms
         FROM evidence_publication_batches AS b
         JOIN evidence_recovery_identity AS i ON i.singleton = 1 AND i.store_id = b.store_id
         JOIN evidence_publication_owner AS o ON o.store_id = b.store_id
         WHERE b.batch_id = ?",
    )
    .bind(batch_id)
    .fetch_optional(&mut **transaction)
    .await
    .map_err(sql_error)?
    .ok_or_else(|| invalid("publication dispatch has no enrolled batch and owner"))?;
    let store_id: String = row.try_get("store_id").map_err(sql_error)?;
    let owner_id: String = row.try_get("owner_id").map_err(sql_error)?;
    let owner_generation: i64 = row.try_get("owner_generation").map_err(sql_error)?;
    let expiry: i64 = row.try_get("lease_expires_at_ms").map_err(sql_error)?;
    let generation: i64 = row
        .try_get("proposed_frontier_generation")
        .map_err(sql_error)?;
    let stored_digest: Option<String> = row
        .try_get("proposed_frontier_sha256")
        .map_err(sql_error)?;
    let backend: Option<String> = row
        .try_get("backend_identity_sha256")
        .map_err(sql_error)?;
    let snapshot: String = row.try_get("snapshot_sha256").map_err(sql_error)?;
    let expected_snapshot =
        Sha256Digest::for_bytes(&canonical_json(&proposed.snapshot).map_err(local_error)?);
    if store_id != lease.store_id
        || store_id != proposed.store_id
        || owner_id != lease.owner_id
        || u64::try_from(owner_generation).ok() != Some(lease.owner_generation)
        || u64::try_from(expiry).ok() != Some(lease.lease_expires_at_unix_ms)
        || u64::try_from(generation).ok() != Some(proposed.frontier_generation)
        || stored_digest.as_deref() != Some(digest.as_str())
        || backend.as_deref() != Some(proposed.backend_identity_sha256.as_str())
        || snapshot != expected_snapshot.as_str()
    {
        return Err(invalid("publication dispatch identity or owner was replaced"));
    }
    let accepted_trust = sqlx::query(
        "SELECT agent_id, registry_generation, registry_sha256, backend_identity_sha256
         FROM evidence_trust_acceptance WHERE store_id = ? ORDER BY seq DESC LIMIT 1",
    )
    .bind(&store_id)
    .fetch_optional(&mut **transaction)
    .await
    .map_err(sql_error)?
    .ok_or_else(|| invalid("publication dispatch requires accepted production trust"))?;
    let agent: String = accepted_trust.try_get("agent_id").map_err(sql_error)?;
    let trust_generation = blob_u64(&accepted_trust, "registry_generation")?;
    let trust_digest: String = accepted_trust
        .try_get("registry_sha256")
        .map_err(sql_error)?;
    let trust_backend: String = accepted_trust
        .try_get("backend_identity_sha256")
        .map_err(sql_error)?;
    if agent != trust.agent_id()
        || trust_generation == 0
        || trust_generation != trust.registry_generation()
        || trust_digest != trust.registry_sha256().as_str()
        || trust_digest != proposed.issuer_trust_registry_sha256.as_str()
        || trust_backend != proposed.backend_identity_sha256.as_str()
    {
        return Err(invalid(
            "publication dispatch trust is not the currently admitted generation",
        ));
    }
    let accepted = sqlx::query(
        "SELECT frontier_generation, frontier_sha256, backend_identity_sha256
         FROM evidence_frontier_acceptance WHERE store_id = ? ORDER BY seq DESC LIMIT 1",
    )
    .bind(&store_id)
    .fetch_optional(&mut **transaction)
    .await
    .map_err(sql_error)?
    .ok_or_else(|| invalid("publication dispatch requires an accepted predecessor"))?;
    let accepted_generation = blob_u64(&accepted, "frontier_generation")?;
    let accepted_digest: String = accepted.try_get("frontier_sha256").map_err(sql_error)?;
    let accepted_backend: String = accepted
        .try_get("backend_identity_sha256")
        .map_err(sql_error)?;
    let state: String = row.try_get("state").map_err(sql_error)?;
    if state == "acknowledged" {
        if accepted_generation < proposed.frontier_generation
            || accepted_backend != proposed.backend_identity_sha256.as_str()
            || (accepted_generation == proposed.frontier_generation
                && accepted_digest != digest.as_str())
        {
            return Err(invalid(
                "acknowledged publication is ahead of or conflicts with local acceptance",
            ));
        }
        return Ok(EvidencePublicationDispatchModeV1::RecoverOnly);
    }
    let expected_generation: Option<i64> = row
        .try_get("expected_frontier_generation")
        .map_err(sql_error)?;
    let expected_digest: Option<String> = row
        .try_get("expected_frontier_sha256")
        .map_err(sql_error)?;
    let expected_backend: Option<String> = row
        .try_get("expected_backend_identity_sha256")
        .map_err(sql_error)?;
    if !matches!(state.as_str(), "dispatching" | "indeterminate")
        || expected_generation.and_then(|value| u64::try_from(value).ok())
            != Some(accepted_generation)
        || expected_digest.as_deref() != Some(accepted_digest.as_str())
        || expected_backend.as_deref() != Some(accepted_backend.as_str())
        || accepted_generation.checked_add(1) != Some(proposed.frontier_generation)
    {
        return Err(invalid(
            "publication predecessor or durable dispatch state changed",
        ));
    }
    Ok(EvidencePublicationDispatchModeV1::PublishOrRecover)
}

fn blob_u64(
    row: &sqlx::sqlite::SqliteRow,
    column: &str,
) -> Result<u64, EvidenceFrontierBackendError> {
    let bytes: Vec<u8> = row.try_get(column).map_err(sql_error)?;
    let bytes: [u8; 8] = bytes.try_into().map_err(|_| {
        EvidenceFrontierBackendError::Corrupt(format!("invalid publication {column} width"))
    })?;
    Ok(u64::from_be_bytes(bytes))
}

fn require_live_lease(
    lease: &EvidencePublicationOwnerLeaseV1,
) -> Result<(), EvidenceFrontierBackendError> {
    let now = u64::try_from(now_millis().map_err(local_error)?)
        .map_err(|_| invalid("publication clock predates Unix epoch"))?;
    if now == 0 || lease.owner_generation == 0 || now >= lease.lease_expires_at_unix_ms {
        return Err(EvidenceFrontierBackendError::Unavailable(
            "publication lease expired at the external boundary".to_string(),
        ));
    }
    Ok(())
}

fn invalid(message: &str) -> EvidenceFrontierBackendError {
    EvidenceFrontierBackendError::Invalid(message.to_string())
}

fn sql_error(error: sqlx::Error) -> EvidenceFrontierBackendError {
    local_error(classify_sqlx_error(error))
}

fn local_error(error: EvidenceError) -> EvidenceFrontierBackendError {
    match error {
        EvidenceError::Unavailable(message) => EvidenceFrontierBackendError::Unavailable(message),
        EvidenceError::Corrupt(message) => EvidenceFrontierBackendError::Corrupt(message),
        other => EvidenceFrontierBackendError::Invalid(other.to_string()),
    }
}

#[cfg(all(test, unix))]
#[path = "publication_dispatch_tests.rs"]
mod tests;
