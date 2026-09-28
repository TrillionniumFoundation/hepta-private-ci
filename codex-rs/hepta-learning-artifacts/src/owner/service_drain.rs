impl LearningArtifactOwnerService {
    pub fn begin_drain(&mut self) {
        self.begin_drain_at(0);
    }

    pub fn begin_drain_at(&mut self, now: u64) {
        self.operational_state.begin_drain_volatile(now);
    }

    pub fn begin_drain_durable(&mut self) -> Result<(), LearningArtifactOwnerServiceError> {
        self.begin_drain_durable_at(0)
    }

    pub fn begin_drain_durable_at(
        &mut self,
        now: u64,
    ) -> Result<(), LearningArtifactOwnerServiceError> {
        self.operational_state.begin_drain_persist(now);
        let result = self
            .metrics
            .measure(ArtifactOwnerStageV1::DrainPersistence, || {
                self.durable_drain
                    .persist()
                    .map_err(LearningArtifactOwnerServiceError::ControlIo)
            });
        match result {
            Ok(()) => {
                self.operational_state.finish_drain_durable();
                Ok(())
            }
            Err(error) => {
                self.operational_state.fail_drain_persist(now);
                self.metrics.increment_control_persistence_unknown();
                Err(error)
            }
        }
    }

    #[must_use]
    pub fn durable_drain_requested(&self) -> bool {
        self.operational_state.durable_drain_requested()
    }

    #[must_use]
    pub fn is_drained(&self) -> bool {
        self.operational_state.is_drained()
    }

}
