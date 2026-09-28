impl LearningArtifactOwnerService {
    pub fn install_withdrawal_frontier(
        &mut self,
        next: DatasetWithdrawalRegistry,
    ) -> Result<(), LearningArtifactOwnerServiceError> {
        let observed_at = next
            .snapshot()
            .records()
            .last()
            .map(|record| record.notice.issued_at)
            .unwrap_or(0);
        self.install_withdrawal_frontier_at(next, observed_at)
    }

    pub fn install_withdrawal_frontier_at(
        &mut self,
        next: DatasetWithdrawalRegistry,
        now: u64,
    ) -> Result<(), LearningArtifactOwnerServiceError> {
        if next.scope_digest() != self.withdrawal_registry.scope_digest() {
            self.metrics.increment_withdrawal_frontier_conflict();
            return Err(LearningArtifactOwnerServiceError::WithdrawalScopeConflict);
        }
        let current = self.withdrawal_registry.snapshot();
        let next_snapshot = next.snapshot();
        if next_snapshot.records().len() < current.records().len() {
            self.metrics.increment_withdrawal_frontier_conflict();
            return Err(LearningArtifactOwnerServiceError::WithdrawalFrontierTooOld);
        }
        if &next_snapshot.records()[..current.records().len()] != current.records() {
            self.metrics.increment_withdrawal_frontier_conflict();
            return Err(LearningArtifactOwnerServiceError::WithdrawalFrontierConflict);
        }
        self.withdrawal_registry = next;
        self.operational_state.begin_withdrawal_persist(now);
        let result = self
            .metrics
            .measure(ArtifactOwnerStageV1::WithdrawalPersistence, || {
                self.durable_withdrawals
                    .persist(&self.withdrawal_registry)
                    .map_err(LearningArtifactOwnerServiceError::ControlIo)
            });
        match result {
            Ok(()) => {
                self.operational_state.finish_withdrawal_persist();
                Ok(())
            }
            Err(error) => {
                self.operational_state.fail_withdrawal_persist(now);
                self.metrics.increment_withdrawal_blocked();
                self.metrics.increment_control_persistence_unknown();
                Err(error)
            }
        }
    }

    #[must_use]
    pub fn withdrawal_frontier_is_durable(&self) -> bool {
        self.operational_state.withdrawal_is_durable()
    }

}
