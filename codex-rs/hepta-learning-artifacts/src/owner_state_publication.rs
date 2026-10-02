//! Ordered durable phases for authenticated owner state changes.

use super::*;

impl LearningArtifactOwnerHost {
    pub(crate) fn publish_state_snapshots(
        &self,
        request: &LearningArtifactStatePublishRequestV1,
        registry: &ArtifactRegistry,
        predecessor_withdrawal: &DatasetWithdrawalRegistry,
    ) -> Result<ArtifactOwnerStatePublicationReceiptV1, ArtifactOwnerHostError> {
        let _gate = self
            .publication_gate
            .lock()
            .map_err(|_| ArtifactOwnerHostError::Indeterminate)?;
        let operation = &request.intent.operation_id;
        if !self.recovery_required_operations()?.is_empty()
            || self
                .state_recovery_operations()?
                .iter()
                .any(|pending| pending != operation)
        {
            return Err(ArtifactOwnerHostError::CheckpointMismatch);
        }
        if self.recover_publication(operation)?.is_some() || self.bootstrap_record_exists(operation)
        {
            return Err(ArtifactOwnerHostError::IdentityConflict);
        }
        let existing = self.recover_state_publication(operation)?;
        if existing.is_none() {
            capacity::reserve_state(self)?;
        }
        let request_digest = Self::state_request_digest(request);
        if let Some(checkpoint) = &existing {
            if checkpoint.request_digest != request_digest
                || checkpoint.state_authorization_signature != request.state_authorization_signature
            {
                return Err(ArtifactOwnerHostError::IdentityConflict);
            }
            if checkpoint.is_acknowledged() {
                self.validate_state_head(request, checkpoint)?;
                return checkpoint.receipt();
            }
        }
        self.require_current_writer(request.now)?;
        let withdrawal = &request.intent.next_withdrawal_registry;
        let scope = self.verifier.trust.withdrawal_scope_digest;
        let signed = &request.signed_current_head;
        if withdrawal.scope_digest() != Some(scope)
            || signed.withdrawal_scope_digest != scope
            || signed.witness.head_digest != registry.snapshot().head_digest
        {
            return Err(ArtifactOwnerHostError::CurrentHeadConflict);
        }
        let base =
            self.recover_registry_by_head(request.intent.expected_registry_predecessor_head)?;
        if registry.records().len() < base.records().len()
            || &registry.records()[..base.records().len()] != base.records()
        {
            return Err(ArtifactOwnerHostError::RegistryPredecessorMismatch);
        }
        if signed.witness.head_digest != request.intent.expected_registry_predecessor_head {
            if signed.witness.predecessor_head_digest
                != request.intent.expected_registry_predecessor_head
            {
                return Err(ArtifactOwnerHostError::RegistryPredecessorMismatch);
            }
        } else if self
            .discover_current_head(request.now)?
            .map(|current| current.signed)
            != Some(signed.clone())
        {
            return Err(ArtifactOwnerHostError::CurrentHeadConflict);
        }
        let requirement = self.state_head_requirement(signed, request.now)?;
        let verified = self
            .verifier
            .verify_signed_head(signed, &requirement, true)?;
        let registry_bytes = encode_snapshot(registry, signed.binding)?;
        let withdrawal_bytes =
            crate::durable_snapshots::encode_withdrawal_snapshot(withdrawal, signed.binding)?;
        let predecessor_bytes = crate::durable_snapshots::encode_withdrawal_snapshot(
            predecessor_withdrawal,
            signed.binding,
        )?;
        let witness_bytes = encode_head_witness(&signed.witness, signed.binding)?;
        let mut signed_bytes = signed.signing_bytes();
        signed_bytes.extend_from_slice(&signed.signature);
        let prepared = StateCheckpoint {
            operation_id: operation.clone(),
            phase: StatePhase::Prepared,
            request_digest,
            expected_registry_predecessor_head: request.intent.expected_registry_predecessor_head,
            expected_withdrawal_predecessor_head: request
                .intent
                .expected_withdrawal_predecessor_head,
            registry_receipt: RegistrySnapshotReceipt {
                binding: signed.binding,
                head_digest: signed.witness.head_digest,
                file_digest: Digest32::of_bytes(&registry_bytes),
                records: registry.records().len(),
                encoded_bytes: registry_bytes.len(),
            },
            withdrawal_receipt: DatasetWithdrawalSnapshotReceiptV1 {
                binding: signed.binding,
                scope_digest: scope,
                head_digest: withdrawal.head_digest(),
                file_digest: Digest32::of_bytes(&withdrawal_bytes),
                records: withdrawal.snapshot().records().len(),
                encoded_bytes: withdrawal_bytes.len(),
            },
            predecessor_withdrawal_receipt: DatasetWithdrawalSnapshotReceiptV1 {
                binding: signed.binding,
                scope_digest: scope,
                head_digest: predecessor_withdrawal.head_digest(),
                file_digest: Digest32::of_bytes(&predecessor_bytes),
                records: predecessor_withdrawal.snapshot().records().len(),
                encoded_bytes: predecessor_bytes.len(),
            },
            witness_receipt: RegistryHeadWitnessReceipt {
                binding: signed.binding,
                witness_digest: verified.witness_digest,
                file_digest: Digest32::of_bytes(&witness_bytes),
                encoded_bytes: witness_bytes.len(),
            },
            signed_head_digest: Digest32::of_bytes(&signed_bytes),
            original_writer_lease_digest: existing
                .as_ref()
                .map_or(self.writer_lease_digest(), |checkpoint| {
                    checkpoint.original_writer_lease_digest
                }),
            acknowledged_at: None,
            signed_head: signed.clone(),
            authorized_at: request.authorized_at,
            authorization_expires_at: request.authorization_expires_at,
            state_authorization_signature: request.state_authorization_signature,
        };
        self.authenticate_state_checkpoint(&prepared, request.now, true)?;
        let mut checkpoint = match existing {
            Some(checkpoint) => {
                let mut normalized = checkpoint.clone();
                normalized.phase = StatePhase::Prepared;
                normalized.acknowledged_at = None;
                if normalized != prepared {
                    return Err(ArtifactOwnerHostError::CheckpointMismatch);
                }
                checkpoint
            }
            None => {
                storage::persist(self, &prepared)?;
                prepared
            }
        };
        if checkpoint.phase == StatePhase::Prepared {
            storage::persist_withdrawal(
                self,
                checkpoint.predecessor_withdrawal_receipt,
                predecessor_withdrawal,
            )?;
            self.persist_state_snapshots(&checkpoint, registry, withdrawal)?;
            checkpoint.phase = StatePhase::SnapshotsDurable;
            storage::persist(self, &checkpoint)?;
        }
        if checkpoint.phase == StatePhase::SnapshotsDurable {
            self.persist_state_witness(&checkpoint, signed, &requirement, request.now)?;
            checkpoint.phase = StatePhase::WitnessDurable;
            storage::persist(self, &checkpoint)?;
        }
        if checkpoint.phase == StatePhase::WitnessDurable {
            self.validate_state_head(request, &checkpoint)?;
            let current = self
                .discover_current_head(request.now)?
                .ok_or(ArtifactOwnerHostError::CurrentHeadConflict)?;
            if current.signed != *signed {
                return Err(ArtifactOwnerHostError::CurrentHeadConflict);
            }
            checkpoint.phase = StatePhase::Acknowledged;
            checkpoint.acknowledged_at = Some(request.now);
            storage::persist(self, &checkpoint)?;
        }
        checkpoint.receipt()
    }
}
