impl<W: AnchorWitnessStore> NeuronRuntimeV2<W> {
    fn recover_operation_inner(
        &mut self,
        model: &mut impl DurableNeuronModelPort,
        input: &NeuronTickInputV1,
        phases: &mut PhaseMeasurementV2,
    ) -> Result<NeuronOperationStatusV2, NeuronRuntimeV2Error> {
        let phase_started = Instant::now();
        let local = self.reconcile();
        phases.local_reconciliation_micros = phases
            .local_reconciliation_micros
            .saturating_add(elapsed_micros(phase_started));
        local?;

        let input_digest = input.semantic_digest()?;
        let status = self.query_operation(&input.tick_id, input_digest)?;
        match &status {
            NeuronOperationStatusV2::NotRecorded
            | NeuronOperationStatusV2::Failed(_)
            | NeuronOperationStatusV2::Committed { .. } => return Ok(status),
            NeuronOperationStatusV2::NotExecuted | NeuronOperationStatusV2::OutcomeUnknown => {}
        }

        let key = NeuronOperationKeyV2 {
            tick_id: input.tick_id.clone(),
            input_semantic_digest: input_digest,
        };
        let pending = self
            .index
            .pending()?
            .ok_or(NeuronRuntimeV2Error::RecoveryMismatch)?;
        if pending.key != key || pending.expected_anchor != self.current_checkpoint_anchor() {
            return Err(NeuronRuntimeV2Error::RecoveryMismatch);
        }
        if input.body_generation != Some(self.body_bundle.body_generation.get()) {
            return Err(NeuronRuntimeV2Error::ContextMismatch);
        }
        self.require_expected_checkpoint(input, pending.expected_anchor)?;
        self.preflight_new_tick(input)?;
        let mut request = self.model_request(input)?;
        request.input_digest = input_digest;

        if !self.index.dispatched()? {
            self.record_failure(&key, NeuronOperationFailureV2::AdmissionDenied)?;
            return Ok(NeuronOperationStatusV2::Failed(
                NeuronOperationFailureV2::AdmissionDenied,
            ));
        }

        let provider_started = Instant::now();
        let phase_started = Instant::now();
        let resolution = model.reconcile(&request);
        phases.provider_micros = phases
            .provider_micros
            .saturating_add(elapsed_micros(phase_started));
        match resolution {
            Ok(NeuronModelResolutionV2::Observed(output)) => {
                let record = self.commit_observed_result(
                    model,
                    input,
                    input_digest,
                    &key,
                    pending.expected_anchor,
                    &request,
                    *output,
                    provider_started,
                    phases,
                )?;
                Ok(NeuronOperationStatusV2::Committed {
                    commit: Box::new(self.commit_from_record(&record)?),
                    witness_acknowledged: record.witness_acknowledged,
                })
            }
            Ok(NeuronModelResolutionV2::NotStarted) => {
                self.record_failure(&key, NeuronOperationFailureV2::AdmissionDenied)?;
                Ok(NeuronOperationStatusV2::Failed(
                    NeuronOperationFailureV2::AdmissionDenied,
                ))
            }
            Ok(NeuronModelResolutionV2::Unknown) => Ok(NeuronOperationStatusV2::OutcomeUnknown),
            Err(NeuronModelError::Rejected) => {
                self.record_failure(&key, NeuronOperationFailureV2::ModelRejected)?;
                Ok(NeuronOperationStatusV2::Failed(
                    NeuronOperationFailureV2::ModelRejected,
                ))
            }
            Err(error @ (NeuronModelError::Unavailable | NeuronModelError::Indeterminate)) => {
                Err(NeuronRuntimeV2Error::Model(error))
            }
        }
    }
}
