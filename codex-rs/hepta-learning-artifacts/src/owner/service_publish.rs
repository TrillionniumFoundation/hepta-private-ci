impl LearningArtifactOwnerService {
    pub fn publish(
        &mut self,
        request: LearningArtifactPublishRequestV1,
    ) -> Result<ArtifactPublicationReceiptV1, LearningArtifactOwnerServiceError> {
        let operation_id = request.operation_id.clone();
        self.operational_state.require_operation(&operation_id)?;
        let result = self.publish_inner(&request);
        match result {
            Ok(receipt) => {
                self.operational_state.clear_recovery(&operation_id);
                Ok(receipt)
            }
            Err(error) => {
                match self.host.recover_publication(&operation_id) {
                    Ok(Some(recovery))
                        if recovery.checkpoint.phase != ArtifactPublicationPhaseV1::Acknowledged =>
                    {
                        self.operational_state
                            .require_recovery(operation_id, request.now);
                    }
                    Ok(_) => {}
                    Err(recovery_error) => {
                        self.metrics.increment_recovery_reconciliation_failure();
                        self.operational_state
                            .require_recovery(operation_id, request.now);
                        return Err(recovery_error.into());
                    }
                }
                Err(error)
            }
        }
    }

}
