impl<W: AnchorWitnessStore> NeuronRuntimeV2<W> {
    #[allow(clippy::too_many_arguments)]
    fn commit_observed_result(
        &mut self,
        model: &mut impl DurableNeuronModelPort,
        input: &NeuronTickInputV1,
        input_digest: Digest32,
        key: &NeuronOperationKeyV2,
        expected_anchor: Option<JournalAnchor>,
        request: &NeuronModelRequestV1,
        model_output: NeuronModelOutputV1,
        provider_started: Instant,
        phases: &mut PhaseMeasurementV2,
    ) -> Result<NeuronGenerationRecordV2, NeuronRuntimeV2Error> {
        let phase_started = Instant::now();
        if validate_model_output(&self.config, &model_output).is_err() {
            return self.fail_attempt(key, NeuronOperationFailureV2::InvalidModelOutput);
        }
        let native_tick = SparseTick {
            scope_digest: subject_scope_digest(&input.subject_id)?,
            objective_digest: input.objective_digest,
            ndu_digest: input.ndu_snapshot_digest,
            body_digest: self.body_bundle_digest,
            input_digest,
            sequence: input.logical_sequence,
            monotonic_micros: input.monotonic_time_micros,
            drive_q24: model_output.drive_q24.clone(),
            prediction_q24: model_output.prediction_q24.clone(),
        };
        let (checkpoint, sparse_receipt) =
            match sparse_tick(&self.native, &native_tick, self.checkpoint.as_ref()) {
                Ok(result) => result,
                Err(_) => {
                    return self.fail_attempt(key, NeuronOperationFailureV2::InvalidTransition);
                }
            };
        let (output, disposition) = match self.build_output(
            &input.tick_id,
            &model_output,
            &checkpoint,
            &sparse_receipt,
            provider_started,
        ) {
            Ok(result) => result,
            Err(_) => {
                return self.fail_attempt(key, NeuronOperationFailureV2::InvalidTransition);
            }
        };
        phases.transition_micros = phases
            .transition_micros
            .saturating_add(elapsed_micros(phase_started));

        let phase_started = Instant::now();
        let receipt_extension = match model.receipt_extension(request, &model_output, &output) {
            Ok(extension) => extension,
            Err(NeuronModelError::Rejected) => {
                return self.fail_attempt(key, NeuronOperationFailureV2::InvalidModelOutput);
            }
            Err(error @ (NeuronModelError::Unavailable | NeuronModelError::Indeterminate)) => {
                return Err(NeuronRuntimeV2Error::Model(error));
            }
        };
        if let Some(extension) = &receipt_extension
            && extension.validate().is_err()
        {
            return self.fail_attempt(key, NeuronOperationFailureV2::InvalidModelOutput);
        }
        let next_anchor = JournalAnchor {
            sequence: input.logical_sequence,
            checkpoint_digest: sparse_receipt.checkpoint_after,
        };
        let prepared = match PreparedNeuronOperationV1::new(
            input_digest,
            input.tick_id.clone(),
            expected_anchor,
            next_anchor,
            native_tick,
            output,
        ) {
            Ok(prepared) => prepared,
            Err(_) => {
                return self.fail_attempt(key, NeuronOperationFailureV2::InvalidTransition);
            }
        };
        let checkpoint_bytes = match encode_prepared(&prepared) {
            Ok(bytes) => bytes,
            Err(_) => {
                return self.fail_attempt(key, NeuronOperationFailureV2::InvalidTransition);
            }
        };
        let full_receipt_bytes =
            encode_full_receipt_v2(&checkpoint_bytes, receipt_extension.as_ref())?;
        if full_receipt_bytes.len() > self.store_context.max_full_receipt_bytes
            || checkpoint_bytes.len() > self.store_context.max_checkpoint_bytes
        {
            return self.fail_attempt(key, NeuronOperationFailureV2::ResultOverBudget);
        }
        phases.checkpoint_payload_bytes =
            u64::try_from(checkpoint_bytes.len()).unwrap_or(u64::MAX);
        phases.full_receipt_bytes =
            u64::try_from(full_receipt_bytes.len()).unwrap_or(u64::MAX);
        let (model_semantic_digest, model_observation_digest) = match self
            .model_identities(&prepared.output, prepared.sparse_tick.monotonic_micros)
        {
            Ok(identities) => identities,
            Err(_) => {
                return self.fail_attempt(key, NeuronOperationFailureV2::InvalidModelOutput);
            }
        };
        phases.receipt_encode_micros = phases
            .receipt_encode_micros
            .saturating_add(elapsed_micros(phase_started));

        // Once a provider result is observed, current admission may prevent
        // release but cannot erase the durable truth. Commit before final-use
        // authorization, preserving the exact operation identity.
        let phase_started = Instant::now();
        let committed = self.store.commit_result(NeuronGenerationCommitV2 {
            key: key.clone(),
            config_semantic_digest: self.config.semantic_digest()?,
            body_bundle_digest: self.body_bundle_digest,
            model_semantic_digest,
            model_observation_digest,
            expected_anchor,
            next_anchor,
            checkpoint_bytes,
            full_receipt_bytes,
            disposition,
        });
        phases.store_commit_micros = phases
            .store_commit_micros
            .saturating_add(elapsed_micros(phase_started));
        let committed = committed?;
        crash_cut("after_store_commit");
        let record = match committed {
            NeuronGenerationCommitResultV2::Committed(record)
            | NeuronGenerationCommitResultV2::Duplicate(record) => record,
        };

        let phase_started = Instant::now();
        let replayed = self.replay_record(self.checkpoint.as_ref(), &record)?;
        let completed = self
            .index
            .complete(key, next_anchor, record.operation_digest);
        phases.index_commit_micros = phases
            .index_commit_micros
            .saturating_add(elapsed_micros(phase_started));
        completed?;
        crash_cut("after_index_completion");
        self.checkpoint = Some(replayed);

        let phase_started = Instant::now();
        let witnessed = self.reconcile_witnesses();
        phases.witness_micros = phases
            .witness_micros
            .saturating_add(elapsed_micros(phase_started));
        witnessed?;
        crash_cut("after_witness_acknowledgement");
        Ok(record)
    }

    fn record_failure(
        &mut self,
        key: &NeuronOperationKeyV2,
        failure: NeuronOperationFailureV2,
    ) -> Result<(), NeuronRuntimeV2Error> {
        // Poisoned/indeterminate storage cannot prove absence. Never write a
        // negative outcome in those cases, or after any actual local commit.
        if self.store.find_operation(key)?.is_some() {
            return Err(NeuronRuntimeV2Error::RecoveryMismatch);
        }
        self.index.fail_operation(key, failure)?;
        Ok(())
    }

    fn fail_attempt<T>(
        &mut self,
        key: &NeuronOperationKeyV2,
        failure: NeuronOperationFailureV2,
    ) -> Result<T, NeuronRuntimeV2Error> {
        self.record_failure(key, failure)?;
        Err(NeuronRuntimeV2Error::TerminalFailure(failure))
    }
}
