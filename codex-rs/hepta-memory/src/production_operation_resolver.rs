//! Read the original operation/outbox identity and reconcile terminal evidence.
//! No registry, re-admission, fresh operation id, or authorization is created.

use super::LocalOutcomeState;
use super::LocalReconcileOutcome;
use super::ProductionDispatchReceipt;
use super::ProductionDispatchRequest;
use super::ProductionDurableWriter;
use super::ProductionQueuedReceipt;
use super::ProductionTargetDisposition;
use super::ProductionTargetOutcome;
use super::ProductionWriterError;
use super::QueuedReceipt;
use super::Sha256Digest;
use super::now_unix_ms;
use super::operation_claims;

/// A read-side fact from the original immutable operation ledger, retaining
/// the exclusive side of the original writer's lifetime fence so concurrent
/// operation admission cannot invalidate it. It is not an effect permit or a
/// new grant. The original queue and Core reservations still own the turn.
#[must_use = "retain the original writer observation until the original turn consumes it"]
pub struct ProductionUnusedScope {
    owner_agent_id: super::AgentId,
    lease_id: String,
    scope_sha256: Sha256Digest,
    generation: u64,
    fencing_token: String,
    lifecycle: std::sync::Arc<super::writer_lifecycle::WriterLifecycle>,
    _fence: super::writer_lifecycle::ProductionPreparationFence,
}

impl ProductionUnusedScope {
    pub fn verify_binding(&self, writer: &ProductionDurableWriter, scope: &Sha256Digest) -> Result<(), ProductionWriterError> {
        if &self.owner_agent_id != writer.owner_agent_id()
            || self.lease_id != writer.lease_id() || &self.scope_sha256 != scope
            || self.generation != writer.generation()
            || self.fencing_token != writer.lease.fencing_token()
            || !std::sync::Arc::ptr_eq(&self.lifecycle, &writer.lifecycle)
        {
            return Err(ProductionWriterError::StaleReceipt);
        }
        drop(writer.lifecycle.lock_open()?);
        writer.authority.validate_for_agent(writer.owner_agent_id())?;
        writer.live_verifier.as_ref().ok_or(ProductionWriterError::LiveVerifierRequired)?
            .verify(&writer.authority, writer.owner_agent_id())
            .map_err(ProductionWriterError::AuthorityRejected)
    }
}

impl ProductionDurableWriter {
    /// Prove that the original lease has never admitted any operation in this
    /// immutable execution scope, including queued and terminal operations.
    /// Missing checkpoint files cannot supply this evidence. The ledger's
    /// no-update/no-delete source rows cover every retained lease generation.
    pub async fn observe_unused_scope(&self, scope: &Sha256Digest) -> Result<ProductionUnusedScope, ProductionWriterError> {
        let fence = self.acquire_preparation_fence().await?;
        let present: i64 = sqlx::query_scalar(
            "SELECT EXISTS(SELECT 1 FROM cognitive_operation_ledger WHERE lease_id = ? AND owner_agent_id = ? AND scope_sha256 = ?)",
        )
        .bind(self.lease_id())
        .bind(self.owner_agent_id().as_str())
        .bind(scope.as_str())
        .fetch_one(&self.store.pool).await
        .map_err(|error| ProductionWriterError::Durability(error.to_string()))?;
        if present != 0 {
            return Err(ProductionWriterError::AuthorityRejected(
                "the original execution scope already admitted an operation; preparation cannot restart".to_owned(),
            ));
        }
        Ok(ProductionUnusedScope {
            owner_agent_id: self.owner_agent_id().clone(), lease_id: self.lease_id().to_owned(),
            scope_sha256: scope.clone(), _fence: fence,
            generation: self.generation(), fencing_token: self.lease.fencing_token().to_owned(),
            lifecycle: std::sync::Arc::clone(&self.lifecycle),
        })
    }

    /// Resolve the immutable original operation for dispatch validation or
    /// observer-only recovery. Missing operations are errors, never admission.
    pub async fn resolve_operation_request(
        &self,
        operation_id: &str,
        destination_id: &str,
    ) -> Result<ProductionDispatchRequest, ProductionWriterError> {
        let _lease = self.acquire_current_lease().await?;
        self.reconciliation_request(operation_id, destination_id).await
    }

    /// Recover only an existing queued receipt by its original event/outbox
    /// ids. Unknown, indeterminate and terminal operations cannot obtain entry.
    pub async fn resolve_queued_operation(
        &self,
        operation_id: &str,
        destination_id: &str,
    ) -> Result<ProductionQueuedReceipt, ProductionWriterError> {
        let _lease = self.acquire_current_lease().await?;
        self.reconciliation_request(operation_id, destination_id).await?;
        if self.lease.inspect_occurrence(operation_id).await? != Some(LocalOutcomeState::Queued) {
            return Err(ProductionWriterError::StaleReceipt);
        }
        let (event_id, outbox_id, topic, payload_json, payload_sha256, generation):
            (String, String, String, String, String, i64) = sqlx::query_as(
            "SELECT event_id, outbox_id, topic, payload_json, payload_sha256, generation
             FROM cognitive_local_outbox
             WHERE lease_id = ? AND occurrence_key = ? AND owner_agent_id = ?
             LIMIT 1",
        )
        .bind(self.lease_id())
        .bind(operation_id)
        .bind(self.store.owner_agent_id().as_str())
        .fetch_optional(&self.store.pool)
        .await
        .map_err(|error| ProductionWriterError::Durability(error.to_string()))?
        .ok_or(ProductionWriterError::StaleReceipt)?;
        let generation = u64::try_from(generation).map_err(|_| ProductionWriterError::StaleReceipt)?;
        if generation != self.generation() {
            return self.recover_inherited_queued(operation_id).await?
                .ok_or(ProductionWriterError::StaleReceipt);
        }
        let payload_sha256 = Sha256Digest::parse(&payload_sha256)
            .map_err(ProductionWriterError::Invalid)?;
        self.lease.verify_queued_receipt_binding(
            operation_id, &event_id, &outbox_id, &topic, &payload_json, &payload_sha256,
        ).await?;
        ProductionQueuedReceipt::from_local(
            &self.authority,
            &topic,
            &payload_json,
            QueuedReceipt {
                lease_id: self.lease_id().to_string(),
                occurrence_key: operation_id.to_string(),
                event_id,
                outbox_id,
                owner_agent_id: self.store.owner_agent_id().clone(),
                generation,
                fencing_token: self.lease.fencing_token().to_string(),
                payload_sha256,
                external_effect: false,
            },
            /*replayed*/ true,
        )
    }

    /// Apply independently observed terminal evidence to the same original
    /// operation. A request rejection or ambiguous observation cannot establish
    /// that an already-entered external effect did not happen.
    pub async fn reconcile_observed_operation(
        &self,
        operation_id: &str,
        destination_id: &str,
        outcome: ProductionTargetOutcome,
    ) -> Result<ProductionDispatchReceipt, ProductionWriterError> {
        if self.live_verifier.is_none() {
            return Err(ProductionWriterError::LiveVerifierRequired);
        }
        self.reconcile_registered_observation(operation_id, destination_id, outcome).await
    }

    pub(super) async fn reconcile_registered_observation(
        &self,
        operation_id: &str,
        destination_id: &str,
        outcome: ProductionTargetOutcome,
    ) -> Result<ProductionDispatchReceipt, ProductionWriterError> {
        let writer = self.clone();
        let operation_id = operation_id.to_string();
        let destination_id = destination_id.to_string();
        tokio::spawn(async move {
            let _lease = writer.acquire_owner_lease().await?;
            let request = writer.reconciliation_request(&operation_id, &destination_id).await?;
            let (desired, target_disposition, target_receipt, target_reason) = match outcome {
                ProductionTargetOutcome::Committed { receipt } => (
                    LocalOutcomeState::Committed,
                    ProductionTargetDisposition::Committed, Some(receipt), None,
                ),
                ProductionTargetOutcome::NotApplied { reason } => (
                    LocalOutcomeState::Rejected,
                    ProductionTargetDisposition::NotApplied, None, Some(reason),
                ),
                ProductionTargetOutcome::Rejected { reason }
                | ProductionTargetOutcome::Indeterminate { reason } => (
                    LocalOutcomeState::Indeterminate,
                    ProductionTargetDisposition::Indeterminate, None, Some(reason),
                ),
            };
            let current = writer.lease.status(&operation_id).await?;
            if current != LocalOutcomeState::Indeterminate && current != desired {
                return Err(ProductionWriterError::StaleReceipt);
            }
            let local_event_id = if desired != LocalOutcomeState::Indeterminate {
                let (outcome, evidence) = if desired == LocalOutcomeState::Committed {
                    (LocalReconcileOutcome::Committed, target_receipt.as_deref())
                } else {
                    (LocalReconcileOutcome::Rejected, target_reason.as_deref())
                };
                let evidence = evidence.ok_or_else(|| ProductionWriterError::Invalid(
                    "terminal observation is missing destination evidence".to_string(),
                ))?;
                writer.lease.reconcile_with_terminal_receipt(&operation_id, outcome, evidence)
                    .await?.event_id
            } else {
                sqlx::query_scalar::<_, String>(
                    "SELECT event_id FROM cognitive_local_events
                     WHERE lease_id = ? AND occurrence_key = ? AND owner_agent_id = ?
                     ORDER BY event_sequence DESC LIMIT 1",
                )
                .bind(writer.lease_id())
                .bind(&operation_id)
                .bind(writer.store.owner_agent_id().as_str())
                .fetch_optional(&writer.store.pool)
                .await
                .map_err(|error| ProductionWriterError::Durability(error.to_string()))?
                .ok_or(ProductionWriterError::StaleReceipt)?
            };
            if desired != LocalOutcomeState::Indeterminate {
                operation_claims::settle_reconciled(
                    &writer.store,
                    &operation_id,
                    writer.generation(),
                    writer.lease.fencing_token(),
                    now_unix_ms()?,
                ).await?;
            }
            Ok(ProductionDispatchReceipt {
                request, state: desired, target_disposition, target_receipt, target_reason,
                local_event_id,
                external_effect: desired == LocalOutcomeState::Committed,
            })
        })
        .await
        .map_err(|error| ProductionWriterError::Durability(format!("effect reconciliation task: {error}")))?
    }
}

