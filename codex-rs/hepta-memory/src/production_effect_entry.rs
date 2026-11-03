//! One-shot handoff from the existing durable writer to an asynchronous effect.
//!
//! This is a child of `production_writer`: it reuses that writer's operation
//! ledger, dispatch claim, lease and FinalUse authority. It owns no second
//! outbox. Dropping a prepared entry leaves the original operation
//! indeterminate; a transport acknowledgement never makes it committed.

use codex_hepta_contracts::EnteredUseToken;
use std::sync::Arc;

use super::effect_observation::EffectEntryPhase;
use super::ProductionCurrentLeaseGuard;
use super::ProductionEffectObservation;

use super::FinalUseAuthority;
use super::FinalUseBinding;
use super::LocalLeaseOutboxError;
use super::LocalOutcomeState;
use super::PRODUCTION_DISPATCH_CLAIM_LEASE_MS;
use super::PRODUCTION_DURABLE_WRITER_NAMESPACE;
use super::PRODUCTION_DURABLE_WRITER_SCHEMA_VERSION;
use super::ProductionDispatchRequest;
use super::ProductionDurableWriter;
use super::ProductionQueuedReceipt;
use super::ProductionWriterError;
use super::SignedFinalUseGrant;
use super::now_unix_ms;
use super::operation_claims;
use super::operation_digest;
use super::verify_final_use_dispatch_binding;

/// The embedding host's final, synchronous Fleet/turn/queue fence.
///
/// Implementations must validate the exact request, cancellation and deadline,
/// and invoke `enter` exactly once while holding the original owner's
/// cancellation/lifecycle lock. The callback claims the signed grant and
/// consumes the real FinalUse token inside that synchronous critical section.
/// Returned guards retain any asynchronous owner lease; no application await
/// precedes physical entry.
/// There is deliberately no permissive default or production fixture.
pub trait ProductionEntryCurrentness: Send + Sync {
    fn enter(
        &self,
        request: &ProductionDispatchRequest,
        enter: &mut dyn FnMut() -> Result<(), ProductionWriterError>,
    ) -> Result<Box<dyn Send>, ProductionWriterError>;
}

/// Non-cloneable handoff for one already durably claimed operation.
///
/// The retained writer shares its original lock and authority. This value is
/// neither serializable nor a replacement operation on recovery. The retained
/// signed grant has not yet claimed a FinalUse nonce.
#[must_use = "dropping an entry leaves the original operation indeterminate"]
pub struct ProductionEffectEntry {
    writer: ProductionDurableWriter,
    request: ProductionDispatchRequest,
    expected: FinalUseBinding,
    final_use: FinalUseAuthority,
    signed: SignedFinalUseGrant,
    lease: ProductionCurrentLeaseGuard,
    phase: Arc<EffectEntryPhase>,
}

/// A prepared entry whose durable owner was rechecked after asynchronous work.
#[must_use = "the final synchronous gate is still required before an effect"]
pub struct ProductionReadyEffectEntry(ProductionEffectEntry);

/// Proof and host guard retained across the concrete initial transport entry.
///
/// This is not a terminal result. Reconciliation still requires independent
/// evidence for the same original operation and response or physical job.
#[must_use = "retain this guard through the initial transport entry"]
pub struct ProductionEnteredEffect {
    _writer: ProductionDurableWriter,
    _entered: EnteredUseToken,
    _currentness: Box<dyn Send>,
    _lease: ProductionCurrentLeaseGuard,
}

impl ProductionEffectEntry {
    pub fn request(&self) -> &ProductionDispatchRequest {
        &self.request
    }

    /// Recheck the live writer and original indeterminate operation after all
    /// asynchronous preparation. The returned value still requires `enter`.
    pub async fn revalidate(self) -> Result<ProductionReadyEffectEntry, ProductionWriterError> {
        self.writer.verify_current_authority().await?;
        if self.writer.status(&self.request.occurrence_key).await?
            != LocalOutcomeState::Indeterminate
        {
            return Err(ProductionWriterError::StaleReceipt);
        }
        Ok(ProductionReadyEffectEntry(self))
    }
}

impl ProductionReadyEffectEntry {
    /// Claim and consume the exact FinalUse grant immediately before HTTP send
    /// or spawn. Owner rejection leaves the nonce unclaimed. Once claiming
    /// starts, a failure may retain the nonce; no failure makes the original
    /// operation automatically retryable.
    /// No application await may be inserted between this call and that entry.
    pub fn enter(
        self,
        currentness: &dyn ProductionEntryCurrentness,
    ) -> Result<ProductionEnteredEffect, ProductionWriterError> {
        let entry = self.0;
        // Host cancel/drain and real FinalUse consumption linearize under
        // the same original owner lock, with no await in the critical section.
        let mut signed = Some(entry.signed);
        let mut entered = None;
        let guard = currentness.enter(&entry.request, &mut || {
            let _lifetime = entry.writer.lifecycle.lock_open()?;
            entry.writer.authority.validate_for_agent(entry.writer.store.owner_agent_id())?;
            let verifier = entry.writer.live_verifier.as_ref().ok_or(ProductionWriterError::LiveVerifierRequired)?;
            verifier.verify(&entry.writer.authority, entry.writer.store.owner_agent_id())
                .map_err(ProductionWriterError::AuthorityRejected)?;
            let signed = signed.take().ok_or_else(|| ProductionWriterError::Invalid("entry callback was invoked twice".to_owned()))?;
            let token = entry.final_use.claim(&signed, &entry.expected)?;
            entered = Some(entry.final_use.enter_verified_use(token, &entry.expected)?);
            entry.phase.enter()?;
            Ok(())
        })?;
        let entered = entered.ok_or_else(|| ProductionWriterError::Invalid("host did not consume final-use entry".to_owned()))?;
        Ok(ProductionEnteredEffect {
            _writer: entry.writer,
            _entered: entered,
            _currentness: guard,
            _lease: entry.lease,
        })
    }
}

impl ProductionDurableWriter {
    /// Prepare the original operation for one checked streaming/tool entry.
    ///
    /// This uses the same durable transition and owner-local claim as the
    /// ordinary dispatcher. Once it succeeds, a crash, dropped handoff or lost
    /// acknowledgement can only observe/reconcile that operation, never resend.
    pub async fn begin_effect_entry(
        &self,
        final_use: &FinalUseAuthority,
        signed: &SignedFinalUseGrant,
        expected: &FinalUseBinding,
        destination_id: &str,
        receipt: ProductionQueuedReceipt,
    ) -> Result<(ProductionEffectEntry, ProductionEffectObservation), ProductionWriterError> {
        let writer = self.clone();
        let final_use = final_use.clone();
        let signed = signed.clone();
        let expected = expected.clone();
        let destination_id = destination_id.to_string();
        tokio::spawn(async move {
            writer.prepare_effect_entry(final_use, signed, expected, destination_id, receipt).await
        })
        .await
        .map_err(|error| ProductionWriterError::Durability(format!("effect preparation task: {error}")))?
    }

    async fn prepare_effect_entry(
        &self,
        final_use: FinalUseAuthority,
        signed: SignedFinalUseGrant,
        expected: FinalUseBinding,
        destination_id: String,
        receipt: ProductionQueuedReceipt,
    ) -> Result<(ProductionEffectEntry, ProductionEffectObservation), ProductionWriterError> {
        let lease = self.acquire_current_lease().await?;
        self.validate_queued_receipt(&receipt)?;
        if receipt.inherited_from_generation.is_none() {
            self.lease
                .verify_queued_receipt_binding(
                    &receipt.occurrence_key,
                    &receipt.event_id,
                    &receipt.outbox_id,
                    &receipt.topic,
                    &receipt.payload_json,
                    &receipt.payload_sha256,
                )
                .await
                .map_err(|error| match error {
                    LocalLeaseOutboxError::StaleFence(_)
                    | LocalLeaseOutboxError::IllegalTransition(_)
                    | LocalLeaseOutboxError::CasConflict(_) => ProductionWriterError::StaleReceipt,
                    other => ProductionWriterError::Local(other),
                })?;
        }
        let operation = self
            .lease
            .verify_operation_dispatch_binding(&receipt.occurrence_key, &destination_id)
            .await
            .map_err(|error| match error {
                LocalLeaseOutboxError::StaleFence(_)
                | LocalLeaseOutboxError::IllegalTransition(_)
                | LocalLeaseOutboxError::CasConflict(_) => ProductionWriterError::StaleReceipt,
                other => ProductionWriterError::Local(other),
            })?;
        let request = ProductionDispatchRequest {
            schema_version: PRODUCTION_DURABLE_WRITER_SCHEMA_VERSION,
            namespace: PRODUCTION_DURABLE_WRITER_NAMESPACE.to_string(),
            lease_id: receipt.lease_id.clone(),
            occurrence_key: receipt.occurrence_key.clone(),
            topic: receipt.topic.clone(),
            payload_json: receipt.payload_json.clone(),
            payload_sha256: receipt.payload_sha256.clone(),
            idempotency_key: receipt.occurrence_key.clone(),
            operation_scope_sha256: operation.scope_sha256.clone(),
            operation_subject_id: operation.subject_id.clone(),
            operation_destination_id: operation.destination_id.clone(),
            operation_semantic_sha256: operation.operation_semantic_sha256.clone(),
            operation_policy_generation: operation.policy_generation,
            expected_predecessor_sha256: operation.expected_predecessor_sha256.clone(),
            operation_digest: operation_digest(&self.authority, &receipt, &operation),
        };
        verify_final_use_dispatch_binding(
            self.store.owner_agent_id(),
            &destination_id,
            &operation.scope_sha256,
            &request,
            &expected,
        )?;
        let owner_claim = self
            .claim_dispatch_lease(&receipt, PRODUCTION_DISPATCH_CLAIM_LEASE_MS)
            .await?;
        let dispatch_claim_event_id = match receipt.inherited_from_generation {
            Some(source_generation) => {
                self.lease
                    .claim_inherited_dispatch(
                        &receipt.occurrence_key,
                        &receipt.event_id,
                        &receipt.outbox_id,
                        source_generation,
                        &receipt.topic,
                        &receipt.payload_json,
                        &receipt.payload_sha256,
                        &self.authority.grant_digest,
                        &request.operation_digest,
                    )
                    .await
            }
            None => {
                self.lease
                    .claim_dispatch(
                        &receipt.occurrence_key,
                        &self.authority.grant_digest,
                        &request.operation_digest,
                    )
                    .await
            }
        }
        .map_err(|error| match error {
            LocalLeaseOutboxError::StaleFence(_)
            | LocalLeaseOutboxError::IllegalTransition(_)
            | LocalLeaseOutboxError::CasConflict(_) => ProductionWriterError::StaleReceipt,
            other => ProductionWriterError::Local(other),
        })?.event_id;
        let entered_claim =
            operation_claims::mark_entered(&self.store, &owner_claim, now_unix_ms()?).await?;
        // The original operation is already indeterminate. Keep the signed
        // grant unclaimed until the final synchronous owner fence; abandoning
        // this handoff must not settle the operation or admit another dispatch.
        let phase = Arc::new(EffectEntryPhase::default());
        let observation = ProductionEffectObservation {
            writer: self.clone(),
            request: request.clone(),
            dispatch_claim_event_id,
            claim: entered_claim,
            inherited: receipt.inherited_from_generation.is_some(),
            phase: Arc::clone(&phase),
        };
        Ok((ProductionEffectEntry {
            writer: self.clone(),
            request,
            expected,
            final_use,
            signed,
            lease,
            phase,
        }, observation))
    }
}

impl super::ProductionFinalUseOutboxDispatcher {
    /// Use this registered destination's existing FinalUse authority for the
    /// original operation; the streaming/native target consumes the handoff.
    pub async fn begin_effect_entry(
        &self,
        writer: &ProductionDurableWriter,
        signed: &SignedFinalUseGrant,
        expected: &FinalUseBinding,
        receipt: ProductionQueuedReceipt,
    ) -> Result<(ProductionEffectEntry, ProductionEffectObservation), ProductionWriterError> {
        writer.begin_effect_entry(
            &self.final_use, signed, expected, self.target.destination_id(), receipt,
        ).await
    }
}

#[cfg(test)]
#[path = "production_effect_entry_tests.rs"]
mod tests;
