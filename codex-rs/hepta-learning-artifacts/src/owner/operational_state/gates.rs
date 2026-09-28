impl OwnerOperationalState {
    pub(super) fn new(
        durable_drain: bool,
        recovery_operation: Option<StableId>,
        now: u64,
    ) -> Self {
        Self {
            withdrawal: PersistenceState::Durable,
            drain: if durable_drain {
                DrainState::DurableRequested { since: now }
            } else {
                DrainState::Active
            },
            recovery: recovery_operation.map_or(RecoveryState::Clear, |operation_id| {
                RecoveryState::Required {
                    operation_id,
                    since: now,
                }
            }),
            request_identity: RequestIdentityState::Clear,
        }
    }

    pub(super) fn require_operation(
        &self,
        operation_id: &StableId,
    ) -> Result<(), LearningArtifactOwnerServiceError> {
        if let RequestIdentityState::Unknown {
            operation_id: blocked,
            ..
        } = &self.request_identity
            && blocked != operation_id
        {
            return Err(
                LearningArtifactOwnerServiceError::RequestIdentityDurabilityUnknown(
                    blocked.clone(),
                ),
            );
        }
        if let RecoveryState::Required {
            operation_id: blocked,
            ..
        } = &self.recovery
            && blocked != operation_id
        {
            return Err(LearningArtifactOwnerServiceError::RecoveryRequired(
                blocked.clone(),
            ));
        }
        Ok(())
    }

    pub(super) fn require_publish(
        &self,
        operation_id: &StableId,
        existing_checkpoint: bool,
    ) -> Result<(), LearningArtifactOwnerServiceError> {
        self.require_operation(operation_id)?;
        if !matches!(self.withdrawal, PersistenceState::Durable) {
            return Err(LearningArtifactOwnerServiceError::WithdrawalDurabilityUnknown);
        }
        if !matches!(self.drain, DrainState::Active) && !existing_checkpoint {
            return Err(LearningArtifactOwnerServiceError::Draining);
        }
        Ok(())
    }

    pub(super) fn require_current_view(&self) -> Result<(), LearningArtifactOwnerServiceError> {
        if !matches!(self.withdrawal, PersistenceState::Durable) {
            return Err(LearningArtifactOwnerServiceError::WithdrawalDurabilityUnknown);
        }
        if let RequestIdentityState::Unknown { operation_id, .. }
        | RequestIdentityState::Persisting { operation_id, .. } = &self.request_identity
        {
            return Err(
                LearningArtifactOwnerServiceError::RequestIdentityDurabilityUnknown(
                    operation_id.clone(),
                ),
            );
        }
        if let RecoveryState::Required { operation_id, .. } = &self.recovery {
            return Err(LearningArtifactOwnerServiceError::RecoveryRequired(
                operation_id.clone(),
            ));
        }
        Ok(())
    }

}
