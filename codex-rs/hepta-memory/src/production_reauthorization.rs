//! Recovery of internal FinalUse pre-boundary rejection proofs.

use super::*;
use crate::operation_claims::ReauthorizationBinding;
use crate::operation_claims::RejectionStage;

/// Not Clone, Deserialize, public or constructible by a target. Only the two
/// synchronous FinalUse error branches in the parent writer create this value.
pub(crate) struct PreBoundaryRejected {
    binding: ReauthorizationBinding,
    entered: DurableDispatchClaim,
    dispatch_event_id: String,
    stage: RejectionStage,
    rejected_nonce: [u8; 32],
}

impl PreBoundaryRejected {
    pub(super) fn at_rejected_entry(
        binding: ReauthorizationBinding,
        entered: DurableDispatchClaim,
        dispatch_event_id: String,
        stage: RejectionStage,
        rejected_nonce: [u8; 32],
    ) -> Self {
        Self {
            binding,
            entered,
            dispatch_event_id,
            stage,
            rejected_nonce,
        }
    }

    pub(crate) fn into_parts(
        self,
    ) -> (
        ReauthorizationBinding,
        DurableDispatchClaim,
        String,
        RejectionStage,
        [u8; 32],
    ) {
        (
            self.binding,
            self.entered,
            self.dispatch_event_id,
            self.stage,
            self.rejected_nonce,
        )
    }
}

impl ProductionDurableWriter {
    pub(super) fn reauthorization_binding(
        &self,
        request: &ProductionDispatchRequest,
    ) -> ReauthorizationBinding {
        ReauthorizationBinding {
            operation_id: request.occurrence_key.clone(),
            lease_id: request.lease_id.clone(),
            semantic_sha256: request.operation_semantic_sha256.clone(),
            payload_sha256: request.payload_sha256.clone(),
            request_sha256: request.operation_digest.clone(),
            authority_grant_sha256: self.authority.grant_digest.clone(),
            authority_epoch: self.authority.authority_epoch,
            owner_epoch: self.authority.owner_epoch,
            owner_generation: self.generation(),
            fencing_token: self.lease.fencing_token().to_string(),
        }
    }

    /// Discover only current, eligible internal pre-boundary proofs. Returned
    /// receipts reuse the original outbox bytes; they are still unprivileged
    /// values and dispatch requires a fresh grant from the original issuer.
    /// Source-unknown operations without such a proof are never returned.
    pub async fn awaiting_authorization(
        &self,
        destination_id: &str,
        limit: usize,
    ) -> Result<Vec<ProductionQueuedReceipt>, ProductionWriterError> {
        self.verify_authority().await?;
        if !(1..=256).contains(&limit) {
            return Err(ProductionWriterError::Invalid(
                "reauthorization limit must be 1..=256".to_string(),
            ));
        }
        if destination_id != crate::HOS2_DESTINATION_V1 {
            return Ok(Vec::new());
        }
        let ids: Vec<String> = sqlx::query_scalar(
            "SELECT o.operation_id FROM cognitive_operation_ledger o
             JOIN cognitive_operation_dispatch_claims c ON c.operation_id = o.operation_id
             JOIN cognitive_operation_pre_boundary_rejections p
               ON p.operation_id = c.operation_id AND p.settled_claim_sha256 = c.claim_sha256
             WHERE o.lease_id = ? AND o.destination_id = ? AND c.claim_state = 'settled'
               AND c.claim_sequence = (SELECT MAX(claim_sequence)
                   FROM cognitive_operation_dispatch_claims WHERE operation_id = o.operation_id)
               AND c.next_eligible_at_unix_ms <= ? AND c.attempt < 64
               AND p.dispatch_event_id = (SELECT event_id FROM cognitive_local_events
                   WHERE lease_id = o.lease_id AND occurrence_key = o.operation_id
                   ORDER BY event_sequence DESC LIMIT 1)
             ORDER BY o.prepared_at_unix_seconds, o.operation_id LIMIT ?",
        )
        .bind(self.lease_id())
        .bind(destination_id)
        .bind(
            i64::try_from(now_unix_ms()?)
                .map_err(|_| ProductionWriterError::Invalid("clock overflow".to_string()))?,
        )
        .bind(
            i64::try_from(limit)
                .map_err(|_| ProductionWriterError::Invalid("limit overflow".to_string()))?,
        )
        .fetch_all(&self.store.pool)
        .await
        .map_err(|error| ProductionWriterError::Durability(error.to_string()))?;
        let mut receipts = Vec::with_capacity(ids.len());
        for id in ids {
            let request = self.reconciliation_request(&id, destination_id).await?;
            if !operation_claims::awaiting_reauthorization(
                &self.store,
                &self.reauthorization_binding(&request),
                now_unix_ms()?,
            )
            .await?
            {
                continue;
            }
            let (event_id, outbox_id): (String, String) = sqlx::query_as(
                "SELECT event_id, outbox_id FROM cognitive_operation_ledger WHERE operation_id = ?",
            )
            .bind(&id)
            .fetch_one(&self.store.pool)
            .await
            .map_err(|error| ProductionWriterError::Durability(error.to_string()))?;
            receipts.push(ProductionQueuedReceipt {
                schema_version: PRODUCTION_DURABLE_WRITER_SCHEMA_VERSION,
                namespace: PRODUCTION_DURABLE_WRITER_NAMESPACE.to_string(),
                lease_id: request.lease_id,
                occurrence_key: id,
                event_id,
                outbox_id,
                owner_agent_id: self.store.owner_agent_id().clone(),
                authority_grant_digest: self.authority.grant_digest.clone(),
                authority_epoch: self.authority.authority_epoch,
                owner_epoch: self.authority.owner_epoch,
                generation: self.generation(),
                fencing_token_digest: self.authority.fencing_token_digest()?,
                topic: request.topic,
                payload_json: request.payload_json,
                payload_sha256: request.payload_sha256,
                inherited_from_generation: None,
                replayed: true,
                external_effect: false,
            });
        }
        Ok(receipts)
    }
}
