impl LearningArtifactOwnerService {
    #[must_use]
    pub fn registry(&self) -> &ArtifactRegistry {
        &self.registry
    }

    pub fn current_registry_view(
        &self,
        now: u64,
    ) -> Result<VerifiedCurrentRegistryViewV1, LearningArtifactOwnerServiceError> {
        if let Err(error) = self.operational_state.require_current_view() {
            if matches!(
                error,
                LearningArtifactOwnerServiceError::WithdrawalDurabilityUnknown
            ) {
                self.metrics.increment_withdrawal_blocked();
            }
            return Err(error);
        }
        self.metrics
            .measure(ArtifactOwnerStageV1::CurrentView, || {
                self.host
                    .current_registry_view(now)
                    .map_err(LearningArtifactOwnerServiceError::from)
            })
    }

    #[must_use]
    pub fn withdrawal_registry(&self) -> &DatasetWithdrawalRegistry {
        &self.withdrawal_registry
    }

    #[must_use]
    pub fn recovery_required(&self) -> Option<&StableId> {
        self.operational_state.recovery_required()
    }

    #[must_use]
    pub fn operational_metrics(&self, now: u64) -> ArtifactOwnerOperationalSnapshotV1 {
        self.metrics
            .snapshot(now, self.operational_state.gauges())
    }

    /// Supply externally observed resource gauges. This does not grant deletion
    /// authority and does not infer that a dropped cache entry released a pin.
    pub fn report_resource_usage(&self, usage: ArtifactOwnerResourceUsageV1) {
        self.metrics.report_resource_usage(usage);
    }
}
