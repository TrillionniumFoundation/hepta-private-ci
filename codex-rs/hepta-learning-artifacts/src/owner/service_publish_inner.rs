impl LearningArtifactOwnerService {
    fn publish_inner(
        &mut self,
        request: &LearningArtifactPublishRequestV1,
    ) -> Result<ArtifactPublicationReceiptV1, LearningArtifactOwnerServiceError> {
        if request.signed_current_head.binding != self.storage_binding
            || request.signed_current_head.witness.predecessor_head_digest
                != request.expected_registry_predecessor_head
            || request.signed_current_head.withdrawal_scope_digest
                != request.admission.withdrawal_scope_digest
        {
            self.metrics.increment_owner_context_conflict();
            return Err(LearningArtifactOwnerServiceError::StaleOwnerContext);
        }
        self.metrics
            .measure(ArtifactOwnerStageV1::PayloadValidationHash, || {
                self.request_identity.verify(request)
            })?;
        let checkpoint = self
            .metrics
            .measure(ArtifactOwnerStageV1::RecoveryScan, || {
                self.host
                    .recover_publication(&request.operation_id)
                    .map_err(LearningArtifactOwnerServiceError::from)
            })?;
        if let Some(recovery) = checkpoint.as_ref() {
            validate_request_against_checkpoint(request, &recovery.checkpoint)?;
        }
        if let Err(error) = self
            .operational_state
            .require_publish(&request.operation_id, checkpoint.is_some())
        {
            if matches!(
                error,
                LearningArtifactOwnerServiceError::WithdrawalDurabilityUnknown
            ) {
                self.metrics.increment_withdrawal_blocked();
            }
            return Err(error);
        }
        self.operational_state
            .begin_request_identity_persist(request.operation_id.clone(), request.now);
        let identity_result = self.metrics.measure(
            ArtifactOwnerStageV1::RequestIdentityPersistence,
            || self.request_identity.bind_or_verify(request),
        );
        match identity_result {
            Ok(()) => self.operational_state.finish_request_identity_persist(),
            Err(LearningArtifactOwnerServiceError::RequestIdentityConflict) => {
                self.operational_state.cancel_request_identity_persist();
                self.metrics.increment_request_identity_conflict();
                return Err(LearningArtifactOwnerServiceError::RequestIdentityConflict);
            }
            Err(LearningArtifactOwnerServiceError::CapacityExceeded) => {
                // Capacity rejection occurs before any create-only identity write.
                // It is not a persistence-unknown state and must not fence reads.
                self.operational_state.cancel_request_identity_persist();
                self.metrics.increment_capacity_rejection();
                return Err(LearningArtifactOwnerServiceError::CapacityExceeded);
            }
            Err(error) => {
                self.operational_state.fail_request_identity_persist(
                    request.operation_id.clone(),
                    request.now,
                );
                self.metrics.increment_control_persistence_unknown();
                return Err(match error {
                    LearningArtifactOwnerServiceError::ControlIo(_) => {
                        LearningArtifactOwnerServiceError::RequestIdentityDurabilityUnknown(
                            request.operation_id.clone(),
                        )
                    }
                    other => other,
                });
            }
        }
        if let Some(recovery) = checkpoint.as_ref()
            && recovery.checkpoint.phase == ArtifactPublicationPhaseV1::Acknowledged
        {
            return receipt_from_checkpoint(&recovery.checkpoint);
        }
        if request.admission.validated_manifest.manifest.predecessor_ids.len() > 1 {
            return Err(LearningArtifactOwnerServiceError::RequestMismatch);
        }
        if checkpoint.is_none() {
            let current = self.host.recover_current_registry(request.now)?;
            if current.snapshot().head_digest != request.expected_registry_predecessor_head {
                self.metrics.increment_owner_context_conflict();
                return Err(LearningArtifactOwnerServiceError::StaleOwnerContext);
            }
        }
        let predecessor = self
            .host
            .recover_registry_by_head(request.expected_registry_predecessor_head)?;
        let mut staged = predecessor.clone();
        let preview = ArtifactPublicationTransactionV1::begin(
            request.operation_id.clone(),
            request.admission.clone(),
            &self.withdrawal_registry,
            &predecessor,
            request.expected_registry_predecessor_head,
            request.now,
        )?;
        self.host
            .stage_compatibility_registration(&preview, &mut staged, request.now)?;
        if staged.snapshot().head_digest != request.signed_current_head.witness.head_digest {
            self.metrics.increment_owner_context_conflict();
            return Err(LearningArtifactOwnerServiceError::StaleOwnerContext);
        }
        if let Some(recovery) = checkpoint.as_ref() {
            verify_durable_inputs(&self.root, &staged, request, &recovery.checkpoint)?;
        }
        let mut transaction = self.metrics.measure(
            ArtifactOwnerStageV1::CheckpointAcknowledge,
            || {
                self.host
                    .begin_publication(
                        request.operation_id.clone(),
                        request.admission.clone(),
                        &self.withdrawal_registry,
                        &predecessor,
                        request.expected_registry_predecessor_head,
                        request.now,
                    )
                    .map_err(LearningArtifactOwnerServiceError::from)
            },
        )?;
        if let Some(recovery) = checkpoint {
            transaction = rebuild_transaction(
                transaction,
                &staged,
                &self.withdrawal_registry,
                request,
                &recovery.checkpoint,
            )?;
            transaction = self
                .host
                .resume_publication(transaction.snapshot(), request.now)?;
        }
        if transaction.phase() == ArtifactPublicationPhaseV1::Prepared {
            self.metrics.measure(ArtifactOwnerStageV1::PayloadWriteSync, || {
                self.host
                    .ensure_payload_durable(
                        &mut transaction,
                        &staged,
                        &request.payload,
                        request.now,
                    )
                    .map(|_| ())
                    .map_err(LearningArtifactOwnerServiceError::from)
            })?;
        }
        if transaction.phase() == ArtifactPublicationPhaseV1::PayloadDurable {
            self.metrics.measure(ArtifactOwnerStageV1::RegistryWriteSync, || {
                self.host
                    .ensure_registry_durable(
                        &mut transaction,
                        &staged,
                        &self.withdrawal_registry,
                        self.storage_binding,
                        request.now,
                    )
                    .map(|_| ())
                    .map_err(LearningArtifactOwnerServiceError::from)
            })?;
        }
        if transaction.phase() == ArtifactPublicationPhaseV1::RegistryDurable {
            self.metrics.measure(ArtifactOwnerStageV1::CurrentSwitch, || {
                self.host
                    .ensure_witness_durable(
                        &mut transaction,
                        &request.signed_current_head,
                        &self.withdrawal_registry,
                        request.now,
                    )
                    .map(|_| ())
                    .map_err(LearningArtifactOwnerServiceError::from)
            })?;
        }
        let receipt = if transaction.phase() == ArtifactPublicationPhaseV1::WitnessDurable {
            self.metrics.measure(
                ArtifactOwnerStageV1::CheckpointAcknowledge,
                || {
                    self.host
                        .acknowledge(
                            &mut transaction,
                            &self.withdrawal_registry,
                            request.now,
                        )
                        .map_err(LearningArtifactOwnerServiceError::from)
                },
            )?
        } else {
            return Err(LearningArtifactOwnerServiceError::UnexpectedPhase);
        };
        self.registry = staged;
        Ok(receipt)
    }
}
