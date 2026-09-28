//! Operation lifecycle: preflight -> reservation -> dispatch fence -> local
//! result commit -> index completion -> external witness reconciliation.
use super::*;
use crate::NeuronOperationFailureV2;

/// Administrative status only; this value grants no execution/use authority.
/// A read error is never converted into `NotRecorded`. `Committed` may precede
/// witness acknowledgement, so callers must not treat it as external acceptance.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum NeuronOperationStatusV2 {
    NotRecorded,
    NotExecuted,
    OutcomeUnknown,
    Failed(NeuronOperationFailureV2),
    Committed {
        commit: Box<NeuronRuntimeCommitV2>,
        witness_acknowledged: bool,
    },
}

impl NeuronOperationStatusV2 {
    /// Stable low-cardinality code for logs, metrics and host runbooks. It is
    /// deliberately independent from `Debug` formatting and grants no authority.
    #[must_use]
    pub fn stable_code(&self) -> &'static str {
        match self {
            Self::NotRecorded => "not_recorded",
            Self::NotExecuted => "reserved_not_executed",
            Self::OutcomeUnknown => "outcome_unknown",
            Self::Failed(_) => "failed",
            Self::Committed {
                witness_acknowledged: true,
                ..
            } => "committed_witnessed",
            Self::Committed {
                witness_acknowledged: false,
                ..
            } => "committed_witness_pending",
        }
    }

    #[must_use]
    pub fn is_terminal(&self) -> bool {
        matches!(self, Self::Failed(_) | Self::Committed { .. })
    }

    /// True when the same exact operation still needs runtime/provider or
    /// witness reconciliation. This never authorizes a changed-input retry.
    #[must_use]
    pub fn requires_reconciliation(&self) -> bool {
        matches!(
            self,
            Self::NotExecuted
                | Self::OutcomeUnknown
                | Self::Committed {
                    witness_acknowledged: false,
                    ..
                }
        )
    }
}

impl NeuronRuntimeV2Error {
    /// Stable low-cardinality error family. Callers that need execution truth
    /// must still query the exact operation key; an error string is not state.
    #[must_use]
    pub fn stable_code(&self) -> &'static str {
        match self {
            Self::Admission(_) => "admission",
            Self::Configuration(_) => "configuration",
            Self::Store(GenerationStoreError::Backpressure) => "store_backpressure",
            Self::Store(GenerationStoreError::Capacity) => "store_capacity",
            Self::Store(GenerationStoreError::Indeterminate | GenerationStoreError::Poisoned) => {
                "store_outcome_unknown"
            }
            Self::Store(_) => "store",
            Self::Index(NeuronRuntimeIndexError::Pending) => "index_pending",
            Self::Index(NeuronRuntimeIndexError::Capacity) => "index_capacity",
            Self::Index(
                NeuronRuntimeIndexError::Indeterminate | NeuronRuntimeIndexError::Poisoned,
            ) => "index_outcome_unknown",
            Self::Index(NeuronRuntimeIndexError::TerminalFailure(_)) => "terminal_failure",
            Self::Index(_) => "index",
            Self::Witness(WitnessStoreError::Unavailable | WitnessStoreError::Busy) => {
                "witness_unavailable"
            }
            Self::Witness(WitnessStoreError::Indeterminate | WitnessStoreError::Poisoned) => {
                "witness_outcome_unknown"
            }
            Self::Witness(_) => "witness",
            Self::Model(NeuronModelError::Unavailable) => "model_unavailable",
            Self::Model(NeuronModelError::Indeterminate) => "model_outcome_unknown",
            Self::Model(NeuronModelError::Rejected) => "model_rejected",
            Self::Semantic(_) => "semantic",
            Self::Codec(_) => "codec",
            Self::ReceiptExtension(_) => "receipt_extension",
            Self::Mechanism(_) => "mechanism",
            Self::ContextMismatch => "context_mismatch",
            Self::CheckpointMismatch => "checkpoint_mismatch",
            Self::OperationConflict => "operation_conflict",
            Self::RecoveryMismatch => "recovery_mismatch",
            Self::PendingOperation => "pending_operation",
            Self::Arithmetic => "arithmetic",
            Self::TerminalFailure(_) => "terminal_failure",
        }
    }
}

impl<W: AnchorWitnessStore> NeuronRuntimeV2<W> {
    pub fn query_operation(
        &mut self,
        tick_id: &StableId,
        input_digest: Digest32,
    ) -> Result<NeuronOperationStatusV2, NeuronRuntimeV2Error> {
        let key = NeuronOperationKeyV2 {
            tick_id: tick_id.clone(),
            input_semantic_digest: input_digest,
        };
        key.semantic_digest()?;
        // Recover the local commit without making a remote witness outage hide
        // an already durable outcome. The normal tick path still reconciles it.
        self.finish_pending_index_commit()?;
        if let Some(record) = self.store.find_operation(&key)? {
            if self.index.failure(&key)?.is_some() {
                return Err(NeuronRuntimeV2Error::RecoveryMismatch);
            }
            return Ok(NeuronOperationStatusV2::Committed {
                commit: Box::new(self.commit_from_record(&record)?),
                witness_acknowledged: record.witness_acknowledged,
            });
        }
        if let Some(failure) = self.index.failure(&key)? {
            return Ok(NeuronOperationStatusV2::Failed(failure));
        }
        if let Some(pending) = self.index.pending()?
            && pending.key.tick_id == key.tick_id
        {
            if pending.key != key {
                return Err(NeuronRuntimeV2Error::OperationConflict);
            }
            return Ok(if self.index.dispatched()? {
                NeuronOperationStatusV2::OutcomeUnknown
            } else {
                NeuronOperationStatusV2::NotExecuted
            });
        }
        Ok(NeuronOperationStatusV2::NotRecorded)
    }

    /// Convenience entry point that derives the exact semantic operation key
    /// from the same immutable input accepted by `tick_guarded`.
    pub fn query_input_operation(
        &mut self,
        input: &NeuronTickInputV1,
    ) -> Result<NeuronOperationStatusV2, NeuronRuntimeV2Error> {
        self.query_operation(&input.tick_id, input.semantic_digest()?)
    }

    pub fn query_result(
        &mut self,
        tick_id: &StableId,
        input_digest: Digest32,
    ) -> Result<Option<NeuronRuntimeCommitV2>, NeuronRuntimeV2Error> {
        self.reconcile()?;
        match self.query_operation(tick_id, input_digest)? {
            NeuronOperationStatusV2::Committed { commit, .. } => Ok(Some(*commit)),
            NeuronOperationStatusV2::Failed(failure) => {
                Err(NeuronRuntimeV2Error::TerminalFailure(failure))
            }
            NeuronOperationStatusV2::NotRecorded => Ok(None),
            NeuronOperationStatusV2::NotExecuted | NeuronOperationStatusV2::OutcomeUnknown => {
                Err(NeuronRuntimeV2Error::PendingOperation)
            }
        }
    }

    /// Measurements are process-local and include admission, model/reconcile,
    /// commit, witness and final guard. They never modify a durable receipt.
    pub fn tick_guarded(
        &mut self,
        model: &mut impl DurableNeuronModelPort,
        input: NeuronTickInputV1,
        guard: &mut dyn NeuronAdmissionGuard,
    ) -> Result<NeuronRuntimeCommitV2, NeuronRuntimeV2Error> {
        let started = Instant::now();
        let store_before = self.store.storage_observation();
        let index_before = self.index.storage_observation();
        let witness_before = self.witness.io_metrics();
        let result = self.tick_guarded_inner(model, input, guard);
        let store_after = self.store.storage_observation();
        let index_after = self.index.storage_observation();
        let witness_after = self.witness.io_metrics();
        self.last_measurement = Some(crate::NeuronRuntimeMeasurementV2 {
            total_micros: u64::try_from(started.elapsed().as_micros()).unwrap_or(u64::MAX),
            returned_success: result.is_ok(),
            store_before,
            store_after,
            index_before,
            index_after,
            witness_sync: witness_after
                .zip(witness_before)
                .map(|(after, before)| after.since(before)),
        });
        result
    }

    pub fn last_measurement(&self) -> Option<&crate::NeuronRuntimeMeasurementV2> {
        self.last_measurement.as_ref()
    }

    pub fn recovery_micros(&self) -> Option<u64> {
        self.recovery_micros
    }

    pub fn capacity_snapshot(
        &self,
    ) -> Result<crate::NeuronRuntimeCapacityV2, NeuronRuntimeV2Error> {
        Ok(crate::NeuronRuntimeCapacityV2 {
            generation: self.store.capacity_snapshot()?,
            index: self.index.capacity_snapshot()?,
            witness_records_remaining: self.witness.capacity_remaining()?,
        })
    }

    fn tick_guarded_inner(
        &mut self,
        model: &mut impl DurableNeuronModelPort,
        input: NeuronTickInputV1,
        guard: &mut dyn NeuronAdmissionGuard,
    ) -> Result<NeuronRuntimeCommitV2, NeuronRuntimeV2Error> {
        guard
            .check(&self.config, &input)
            .map_err(NeuronRuntimeV2Error::Admission)?;
        self.reconcile()?;
        let input_digest = input.semantic_digest()?;
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
                guard
                    .check(&self.config, &input)
                    .map_err(NeuronRuntimeV2Error::Admission)?;
                return self.commit_from_record(&record);
            }
            (NeuronRuntimeIndexAdmissionV2::New, NeuronGenerationAdmissionV2::New)
            | (NeuronRuntimeIndexAdmissionV2::Pending(_), NeuronGenerationAdmissionV2::New) => {}
            // reconcile() finishes every durable store commit before admission.
            _ => return Err(NeuronRuntimeV2Error::RecoveryMismatch),
        }
        self.require_expected_checkpoint(&input, expected_anchor)?;
        self.preflight_new_tick(&input)?;
        let request = self.model_request(&input)?;
        self.witness.admit_new_anchor(expected_anchor)?;
        self.index.prepare(key.clone(), expected_anchor)?;
        crash_cut("after_reservation");
        let started = Instant::now();
        let model_result = if self.index.dispatched()? {
            match model.reconcile(&request) {
                Ok(NeuronModelResolutionV2::Observed(output)) => Ok(*output),
                Ok(NeuronModelResolutionV2::NotStarted) => {
                    // Only an authoritative query from the same durable owner
                    // can establish that resuming this fenced operation is safe.
                    if guard.check(&self.config, &input).is_err() {
                        return self.fail_attempt(&key, NeuronOperationFailureV2::AdmissionDenied);
                    }
                    model.execute(&request)
                }
                Ok(NeuronModelResolutionV2::Unknown) => Err(NeuronModelError::Indeterminate),
                Err(error) => Err(error),
            }
        } else {
            if guard.check(&self.config, &input).is_err() {
                return self.fail_attempt(&key, NeuronOperationFailureV2::AdmissionDenied);
            }
            self.index.mark_dispatched(&key)?;
            crash_cut("after_dispatch_fence");
            model.execute(&request)
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
        if validate_model_output(&self.config, &model_output).is_err() {
            return self.fail_attempt(&key, NeuronOperationFailureV2::InvalidModelOutput);
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
                    return self.fail_attempt(&key, NeuronOperationFailureV2::InvalidTransition);
                }
            };
        let (output, disposition) = match self.build_output(
            &input.tick_id,
            &model_output,
            &checkpoint,
            &sparse_receipt,
            started,
        ) {
            Ok(result) => result,
            Err(_) => return self.fail_attempt(&key, NeuronOperationFailureV2::InvalidTransition),
        };
        let receipt_extension = model.receipt_extension(&request, &model_output, &output)?;
        if let Some(extension) = &receipt_extension {
            extension.validate()?;
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
            Err(_) => return self.fail_attempt(&key, NeuronOperationFailureV2::InvalidTransition),
        };
        let checkpoint_bytes = match encode_prepared(&prepared) {
            Ok(bytes) => bytes,
            Err(_) => return self.fail_attempt(&key, NeuronOperationFailureV2::InvalidTransition),
        };
        let full_receipt_bytes =
            encode_full_receipt_v2(&checkpoint_bytes, receipt_extension.as_ref())?;
        if full_receipt_bytes.len() > self.store_context.max_full_receipt_bytes
            || checkpoint_bytes.len() > self.store_context.max_checkpoint_bytes
        {
            return self.fail_attempt(&key, NeuronOperationFailureV2::ResultOverBudget);
        }
        let (model_semantic_digest, model_observation_digest) = match self
            .model_identities(&prepared.output, prepared.sparse_tick.monotonic_micros)
        {
            Ok(identities) => identities,
            Err(_) => return self.fail_attempt(&key, NeuronOperationFailureV2::InvalidModelOutput),
        };
        if guard.check(&self.config, &input).is_err() {
            return self.fail_attempt(&key, NeuronOperationFailureV2::AdmissionDenied);
        }
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
        })?;
        crash_cut("after_store_commit");
        let record = match committed {
            NeuronGenerationCommitResultV2::Committed(record)
            | NeuronGenerationCommitResultV2::Duplicate(record) => record,
        };
        let replayed = self.replay_record(self.checkpoint.as_ref(), &record)?;
        self.index
            .complete(&key, next_anchor, record.operation_digest)?;
        crash_cut("after_index_completion");
        self.checkpoint = Some(replayed);
        self.reconcile_witnesses()?;
        crash_cut("after_witness_acknowledgement");
        guard
            .check(&self.config, &input)
            .map_err(NeuronRuntimeV2Error::Admission)?;
        self.commit_from_record(&record)
    }

    fn fail_attempt(
        &mut self,
        key: &NeuronOperationKeyV2,
        failure: NeuronOperationFailureV2,
    ) -> Result<NeuronRuntimeCommitV2, NeuronRuntimeV2Error> {
        // Poisoned/indeterminate storage cannot prove absence. Never write a
        // negative outcome in those cases, or after any actual local commit.
        if self.store.find_operation(key)?.is_some() {
            return Err(NeuronRuntimeV2Error::RecoveryMismatch);
        }
        self.index.fail_operation(key, failure)?;
        Err(NeuronRuntimeV2Error::TerminalFailure(failure))
    }
}

#[cfg(test)]
fn crash_cut(phase: &str) {
    if std::env::var("HEPTA_NEURON_V2_CLOSURE_CHILD").as_deref() == Ok("crash")
        && std::env::var("HEPTA_NEURON_V2_CLOSURE_CUT").as_deref() == Ok(phase)
    {
        std::process::exit(73);
    }
}

#[cfg(not(test))]
fn crash_cut(_phase: &str) {}

#[cfg(test)]
mod status_code_tests {
    use super::*;

    #[test]
    fn operation_codes_are_stable_and_distinguish_reconciliation() {
        let absent = NeuronOperationStatusV2::NotRecorded;
        assert_eq!(absent.stable_code(), "not_recorded");
        assert!(!absent.is_terminal());
        assert!(!absent.requires_reconciliation());

        let reserved = NeuronOperationStatusV2::NotExecuted;
        assert_eq!(reserved.stable_code(), "reserved_not_executed");
        assert!(!reserved.is_terminal());
        assert!(reserved.requires_reconciliation());

        let unknown = NeuronOperationStatusV2::OutcomeUnknown;
        assert_eq!(unknown.stable_code(), "outcome_unknown");
        assert!(!unknown.is_terminal());
        assert!(unknown.requires_reconciliation());

        let failed = NeuronOperationStatusV2::Failed(NeuronOperationFailureV2::ModelRejected);
        assert_eq!(failed.stable_code(), "failed");
        assert!(failed.is_terminal());
        assert!(!failed.requires_reconciliation());
    }

    #[test]
    fn error_codes_do_not_collapse_unknown_outcomes_into_failures() {
        assert_eq!(
            NeuronRuntimeV2Error::Store(GenerationStoreError::Indeterminate).stable_code(),
            "store_outcome_unknown"
        );
        assert_eq!(
            NeuronRuntimeV2Error::Model(NeuronModelError::Indeterminate).stable_code(),
            "model_outcome_unknown"
        );
        assert_eq!(
            NeuronRuntimeV2Error::TerminalFailure(NeuronOperationFailureV2::ModelRejected)
                .stable_code(),
            "terminal_failure"
        );
    }
}
