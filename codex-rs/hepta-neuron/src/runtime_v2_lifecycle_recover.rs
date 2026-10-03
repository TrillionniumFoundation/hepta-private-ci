impl<W: AnchorWitnessStore> NeuronRuntimeV2<W> {
    fn recover_operation_inner(
        &mut self,
        model: &mut impl DurableNeuronModelPort,
        input: &NeuronTickInputV1,
        input_digest: Digest32,
        disposition: NeuronRecoveryDispositionV2,
        phases: &mut PhaseMeasurementV2,
    ) -> Result<NeuronOperationStatusV2, NeuronRuntimeV2Error> {
        let phase_started = Instant::now();
        // Exact-operation recovery must remain reachable while new-work
        // admission is closed or the independent witness is unavailable. It
        // reconciles local durability first, then queries only the already
        // fenced provider operation. Any observed result still attempts normal
        // witness publication during commit and remains unavailable to product
        // use until the separate live result-use gate succeeds.
        let local = self.reconcile_local_state();
        phases.local_reconciliation_micros = phases
            .local_reconciliation_micros
            .saturating_add(elapsed_micros(phase_started));
        local?;

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

        if !self.index.dispatched()? {
            return match disposition {
                NeuronRecoveryDispositionV2::PreserveUnexecuted => {
                    Ok(NeuronOperationStatusV2::NotExecuted)
                }
                NeuronRecoveryDispositionV2::CloseUnexecuted => {
                    self.record_failure(&key, NeuronOperationFailureV2::AdmissionDenied)?;
                    Ok(NeuronOperationStatusV2::Failed(
                        NeuronOperationFailureV2::AdmissionDenied,
                    ))
                }
            };
        }

        let mut request = self.model_request(input)?;
        request.input_digest = input_digest;
        let provider_started = Instant::now();
        let phase_started = Instant::now();
        let resolution = model.reconcile(&request);
        phases.provider_micros = phases
            .provider_micros
            .saturating_add(elapsed_micros(phase_started));
        match resolution {
            Ok(NeuronModelResolutionV2::Observed(output)) => {
                self.commit_observed_result(
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
                // Witness reconciliation updates durable acknowledgement state;
                // the pre-ack commit snapshot must not become the returned status.
                self.query_operation(&input.tick_id, input_digest)
            }
            Ok(NeuronModelResolutionV2::NotStarted) => match disposition {
                NeuronRecoveryDispositionV2::PreserveUnexecuted => {
                    Ok(NeuronOperationStatusV2::OutcomeUnknown)
                }
                NeuronRecoveryDispositionV2::CloseUnexecuted => {
                    self.record_failure(&key, NeuronOperationFailureV2::AdmissionDenied)?;
                    Ok(NeuronOperationStatusV2::Failed(
                        NeuronOperationFailureV2::AdmissionDenied,
                    ))
                }
            },
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
