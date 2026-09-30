impl<W: AnchorWitnessStore> NeuronRuntimeV2<W> {
    fn tick_guarded_inner(
        &mut self,
        model: &mut impl DurableNeuronModelPort,
        input: NeuronTickInputV1,
        input_digest: Digest32,
        guard: &mut dyn NeuronAdmissionGuard,
        phases: &mut PhaseMeasurementV2,
    ) -> Result<NeuronRuntimeCommitV2, NeuronRuntimeV2Error> {
        // Local obligations are recoverable even when current admission is
        // revoked. Provider recovery uses the separate `recover_operation` API.
        let phase_started = Instant::now();
        let local = self.reconcile();
        phases.local_reconciliation_micros = phases
            .local_reconciliation_micros
            .saturating_add(elapsed_micros(phase_started));
        local?;

        let key = NeuronOperationKeyV2 {
            tick_id: input.tick_id.clone(),
            input_semantic_digest: input_digest,
        };
        key.semantic_digest()?;
        if let Some(failure) = self.index.failure(&key)? {
            return Err(NeuronRuntimeV2Error::TerminalFailure(failure));
        }
        let expected_anchor = self.current_checkpoint_anchor();
        if input.body_generation != Some(self.body_bundle.body_generation.get()) {
            return Err(NeuronRuntimeV2Error::ContextMismatch);
        }
        let index_admission = self.index.admit(&key, expected_anchor)?;
        let store_admission = self.store.admit_operation(
            &key,
            expected_anchor,
            self.store_context.max_checkpoint_bytes,
            self.store_context.max_full_receipt_bytes,
        )?;
        match (index_admission, store_admission) {
            (
                NeuronRuntimeIndexAdmissionV2::Historical(indexed),
                NeuronGenerationAdmissionV2::Historical(record),
            ) => {
                validate_index_record(&indexed, &record)?;
                let phase_started = Instant::now();
                let checked = guard.check(&self.config, &input);
                phases.final_use_check_micros = phases
                    .final_use_check_micros
                    .saturating_add(elapsed_micros(phase_started));
                checked.map_err(NeuronRuntimeV2Error::Admission)?;
                return self.commit_from_record(&record);
            }
            (NeuronRuntimeIndexAdmissionV2::New, NeuronGenerationAdmissionV2::New)
            | (NeuronRuntimeIndexAdmissionV2::Pending(_), NeuronGenerationAdmissionV2::New) => {}
            // reconcile() finishes every durable store commit before admission.
            _ => return Err(NeuronRuntimeV2Error::RecoveryMismatch),
        }

        let phase_started = Instant::now();
        let checked = guard.check(&self.config, &input);
        phases.admission_micros = phases
            .admission_micros
            .saturating_add(elapsed_micros(phase_started));
        checked.map_err(NeuronRuntimeV2Error::Admission)?;

        self.require_expected_checkpoint(&input, expected_anchor)?;
        self.preflight_new_tick(&input)?;
        let mut request = self.model_request(&input)?;
        request.input_digest = input_digest;

        let phase_started = Instant::now();
        let witness_admission = self.witness.admit_new_anchor(expected_anchor);
        phases.witness_micros = phases
            .witness_micros
            .saturating_add(elapsed_micros(phase_started));
        witness_admission?;

        let phase_started = Instant::now();
        let prepared = self.index.prepare(key.clone(), expected_anchor);
        phases.index_commit_micros = phases
            .index_commit_micros
            .saturating_add(elapsed_micros(phase_started));
        prepared?;
        crash_cut("after_reservation");

        let provider_started = Instant::now();
        let model_result = if self.index.dispatched()? {
            let phase_started = Instant::now();
            let resolution = model.reconcile(&request);
            phases.provider_micros = phases
                .provider_micros
                .saturating_add(elapsed_micros(phase_started));
            match resolution {
                Ok(NeuronModelResolutionV2::Observed(output)) => Ok(*output),
                Ok(NeuronModelResolutionV2::NotStarted) => {
                    let phase_started = Instant::now();
                    let checked = guard.check(&self.config, &input);
                    phases.admission_micros = phases
                        .admission_micros
                        .saturating_add(elapsed_micros(phase_started));
                    if checked.is_err() {
                        return self.fail_attempt(
                            &key,
                            NeuronOperationFailureV2::AdmissionDenied,
                        );
                    }
                    let phase_started = Instant::now();
                    let output = model.execute(&request);
                    phases.provider_micros = phases
                        .provider_micros
                        .saturating_add(elapsed_micros(phase_started));
                    output
                }
                Ok(NeuronModelResolutionV2::Unknown) => Err(NeuronModelError::Indeterminate),
                Err(error) => Err(error),
            }
        } else {
            let phase_started = Instant::now();
            let checked = guard.check(&self.config, &input);
            phases.admission_micros = phases
                .admission_micros
                .saturating_add(elapsed_micros(phase_started));
            if checked.is_err() {
                return self.fail_attempt(&key, NeuronOperationFailureV2::AdmissionDenied);
            }
            let phase_started = Instant::now();
            let dispatched = self.index.mark_dispatched(&key);
            phases.index_commit_micros = phases
                .index_commit_micros
                .saturating_add(elapsed_micros(phase_started));
            dispatched?;
            crash_cut("after_dispatch_fence");
            let phase_started = Instant::now();
            let output = model.execute(&request);
            phases.provider_micros = phases
                .provider_micros
                .saturating_add(elapsed_micros(phase_started));
            output
        };
        crash_cut("after_model_observation");
        let model_output = match model_result {
            Ok(output) => output,
            Err(NeuronModelError::Rejected) => {
                return self.fail_attempt(&key, NeuronOperationFailureV2::ModelRejected);
            }
            Err(error @ (NeuronModelError::Unavailable | NeuronModelError::Indeterminate)) => {
                return Err(NeuronRuntimeV2Error::Model(error));
            }
        };
        let record = self.commit_observed_result(
            model,
            &input,
            input_digest,
            &key,
            expected_anchor,
            &request,
            model_output,
            provider_started,
            phases,
        )?;

        let phase_started = Instant::now();
        let checked = guard.check(&self.config, &input);
        phases.final_use_check_micros = phases
            .final_use_check_micros
            .saturating_add(elapsed_micros(phase_started));
        checked.map_err(NeuronRuntimeV2Error::Admission)?;
        self.commit_from_record(&record)
    }
}
