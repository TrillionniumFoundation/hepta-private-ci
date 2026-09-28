//! Ordered publication with one canonical request binding before Prepared.

use super::*;

impl LearningArtifactOwnerService {
    pub(super) fn publish_inner(&mut self, request: &LearningArtifactPublishRequestV1)
        -> Result<ArtifactPublicationReceiptV1, LearningArtifactOwnerServiceError>
    {
        if request.signed_current_head.binding != self.storage_binding
            || request.signed_current_head.witness.predecessor_head_digest != request.expected_registry_predecessor_head
            || request.signed_current_head.withdrawal_scope_digest != request.admission.withdrawal_scope_digest
        { return Err(LearningArtifactOwnerServiceError::RequestMismatch); }
        let started = Instant::now();
        let identity = self.request_identity.verify(request);
        self.observations.record(Phase::Identity, started, &identity);
        let identity = identity?;
        self.observations.last_verified_request_digest = Some(identity);
        let bound = self.request_journal.get(&request.operation_id);
        if bound.is_some_and(|record| record.identity != identity) {
            return Err(LearningArtifactOwnerServiceError::RequestMismatch);
        }
        let already_bound = bound.is_some();
        let started = Instant::now();
        let checkpoint = self.host.recover_publication(&request.operation_id);
        self.observations.record(Phase::Reconcile, started, &checkpoint);
        let checkpoint = checkpoint?;
        if let Some(recovery) = checkpoint.as_ref() {
            validate_request_against_checkpoint(request, &recovery.checkpoint)?;
            if recovery.checkpoint.phase == ArtifactPublicationPhaseV1::Acknowledged {
                // Legacy historical receipts retain the old fully validated
                // checkpoint path. They do not silently acquire a new binding.
                return receipt_from_checkpoint(&recovery.checkpoint);
            }
            if !already_bound { return Err(LearningArtifactOwnerServiceError::LegacyRequestUnbound); }
        }
        if request.admission.validated_manifest.manifest.predecessor_ids.len() > 1 {
            return Err(LearningArtifactOwnerServiceError::RequestMismatch);
        }
        if self.draining && checkpoint.is_none() && !already_bound {
            return Err(LearningArtifactOwnerServiceError::Draining);
        }
        if checkpoint.is_none() {
            let current = self.host.recover_current_registry(request.now)?;
            if current.snapshot().head_digest != request.expected_registry_predecessor_head {
                return Err(LearningArtifactOwnerServiceError::RequestMismatch);
            }
        }
        let predecessor = self.host.recover_registry_by_head(request.expected_registry_predecessor_head)?;
        let mut staged = predecessor.clone();
        let preview = ArtifactPublicationTransactionV1::begin(request.operation_id.clone(),
            request.admission.clone(), &self.withdrawal_registry, &predecessor,
            request.expected_registry_predecessor_head, request.now)?;
        self.host.stage_compatibility_registration(&preview, &mut staged, request.now)?;
        if staged.snapshot().head_digest != request.signed_current_head.witness.head_digest {
            return Err(LearningArtifactOwnerServiceError::RequestMismatch);
        }
        if let Some(recovery) = checkpoint.as_ref() {
            verify_durable_inputs(&self.root, &staged, request, &recovery.checkpoint)?;
        }
        if !already_bound {
            let record = RequestRecord::from_request(request, identity)?;
            self.recovery_required = Some(request.operation_id.clone());
            let result = self.request_journal.bind(record, &self.request_identity);
            if matches!(&result, Err(LearningArtifactOwnerServiceError::Host(ArtifactOwnerHostError::Capacity))) {
                // Capacity is checked before the first create; no uncertain write.
                self.recovery_required = None;
            }
            result?;
        }
        let mut transaction = self.host.begin_publication(request.operation_id.clone(),
            request.admission.clone(), &self.withdrawal_registry, &predecessor,
            request.expected_registry_predecessor_head, request.now)?;
        if let Some(recovery) = checkpoint {
            transaction = rebuild_transaction(transaction, &staged, &self.withdrawal_registry,
                request, &recovery.checkpoint)?;
            transaction = self.host.resume_publication(transaction.snapshot(), request.now)?;
        }
        if transaction.phase() == ArtifactPublicationPhaseV1::Prepared {
            let started = Instant::now();
            let outcome = self.host.ensure_payload_durable(&mut transaction, &staged, &request.payload, request.now);
            self.observations.record(Phase::Payload, started, &outcome);
            outcome?;
        }
        if transaction.phase() == ArtifactPublicationPhaseV1::PayloadDurable {
            let started = Instant::now();
            let outcome = self.host.ensure_registry_durable(&mut transaction, &staged,
                &self.withdrawal_registry, self.storage_binding, request.now);
            self.observations.record(Phase::Registry, started, &outcome);
            outcome?;
        }
        if transaction.phase() == ArtifactPublicationPhaseV1::RegistryDurable {
            let started = Instant::now();
            let outcome = self.host.ensure_witness_durable(&mut transaction,
                &request.signed_current_head, &self.withdrawal_registry, request.now);
            self.observations.record(Phase::Witness, started, &outcome);
            outcome?;
        }
        let receipt = if transaction.phase() == ArtifactPublicationPhaseV1::WitnessDurable {
            let started = Instant::now();
            let outcome = self.host.acknowledge(&mut transaction, &self.withdrawal_registry, request.now);
            self.observations.record(Phase::Acknowledge, started, &outcome);
            outcome?
        } else { return Err(LearningArtifactOwnerServiceError::UnexpectedPhase); };
        self.registry = staged;
        Ok(receipt)
    }
}
