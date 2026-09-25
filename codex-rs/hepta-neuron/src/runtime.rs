//! Stateful host lifecycle for canonical neuron ticks.

use std::fs::File;
use std::time::Instant;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::JournalAnchor;
use crate::JournalError;
use crate::JournalScope;
use crate::NeuronDeletionRebuildPlanV1;
use crate::NeuronDeletionRebuildReceiptV1;
use crate::OperationStoreError;
use crate::SparseCheckpoint;
use crate::SparseConfig;
use crate::SparseJournal;
use crate::SparseSignalReceipt;
use crate::SparseTick;
use crate::operation_store::MAX_OPERATION_RECORDS;
use crate::operation_store::NeuronOperationStore;
use crate::operation_store::NeuronPreparedOperationV1;
use crate::runtime_types::*;
use crate::validate_deletion_rebuild;

pub struct NeuronRuntime<W: AnchorWitnessStore> {
    config: NeuronRuntimeConfigV1,
    journal: SparseJournal,
    operations: NeuronOperationStore,
    witness: W,
    chain_recovery_pending: bool,
}

impl<W: AnchorWitnessStore> NeuronRuntime<W> {
    pub fn bootstrap(
        journal_file: File,
        operation_file: File,
        native: SparseConfig,
        scope: JournalScope,
        max_records: usize,
        config: NeuronRuntimeConfigV1,
        witness: W,
    ) -> Result<Self, NeuronRuntimeError> {
        config.validate_native(&native)?;
        if journal_file.metadata().map_err(JournalError::from)?.len() != 0 {
            return Err(NeuronRuntimeError::BootstrapRequiresEmptyJournal);
        }
        if witness.current()?.is_some() {
            return Err(NeuronRuntimeError::BootstrapWitnessPresent);
        }
        let operations = NeuronOperationStore::open(
            operation_file,
            scope,
            config.generation,
            config.semantic_digest()?,
            MAX_OPERATION_RECORDS,
        )?;
        if !operations.is_empty() {
            return Err(OperationStoreError::Conflict.into());
        }
        let journal = SparseJournal::open(journal_file, native, scope, max_records)?;
        Ok(Self {
            config,
            journal,
            operations,
            witness,
            chain_recovery_pending: false,
        })
    }

    /// Start a fresh generation after authenticated deletion/withdrawal
    /// processing. The predecessor checkpoint is bound for lineage only and is
    /// never loaded into the successor runtime.
    #[allow(clippy::too_many_arguments)]
    pub fn bootstrap_after_deletion(
        journal_file: File,
        operation_file: File,
        native: SparseConfig,
        scope: JournalScope,
        max_records: usize,
        config: NeuronRuntimeConfigV1,
        witness: W,
        predecessor: JournalAnchor,
        plan: &NeuronDeletionRebuildPlanV1,
    ) -> Result<(Self, NeuronDeletionRebuildReceiptV1), NeuronRuntimeError> {
        let receipt = validate_deletion_rebuild(plan)?;
        if receipt.predecessor_checkpoint_digest != predecessor.checkpoint_digest {
            return Err(NeuronRuntimeError::Deletion(
                crate::DeletionRebuildError::PredecessorMismatch,
            ));
        }
        if receipt.successor_generation != config.generation
            || receipt.successor_generation != native.generation
        {
            return Err(NeuronRuntimeError::Deletion(
                crate::DeletionRebuildError::SuccessorMismatch,
            ));
        }
        let runtime = Self::bootstrap(
            journal_file,
            operation_file,
            native,
            scope,
            max_records,
            config,
            witness,
        )?;
        Ok((runtime, receipt))
    }

    /// Recover the exact owner generation. The independent operation store
    /// permits recovery both before and after the first witness is published.
    pub fn recover(
        journal_file: File,
        operation_file: File,
        native: SparseConfig,
        scope: JournalScope,
        max_records: usize,
        config: NeuronRuntimeConfigV1,
        witness: W,
    ) -> Result<Self, NeuronRuntimeError> {
        config.validate_native(&native)?;
        let operations = NeuronOperationStore::open(
            operation_file,
            scope,
            config.generation,
            config.semantic_digest()?,
            MAX_OPERATION_RECORDS,
        )?;
        let acknowledged = witness.current()?;
        let journal = match acknowledged {
            Some(anchor) => {
                SparseJournal::open_anchored(journal_file, native, scope, max_records, anchor)?
            }
            None => SparseJournal::open(journal_file, native, scope, max_records)?,
        };
        let mut runtime = Self {
            config,
            journal,
            operations,
            witness,
            chain_recovery_pending: false,
        };
        runtime.reconcile_frontier()?;
        Ok(runtime)
    }

    pub fn model_request(
        &self,
        input: &NeuronTickInputV1,
    ) -> Result<NeuronModelRequestV1, NeuronRuntimeError> {
        let input_digest = input.semantic_digest()?;
        if input.feature_vector_q24.len() != self.config.input_feature_dimension {
            return Err(NeuronRuntimeError::InvalidInput);
        }
        Ok(NeuronModelRequestV1 {
            request_id: input.tick_id.clone(),
            config_id: self.config.config_id.clone(),
            generation: self.config.generation,
            model_id: self.config.model_id.clone(),
            encoder_digest: self.config.encoder_digest,
            head_digest: self.config.head_digest,
            weights_digest: self.config.weights_digest,
            input_digest,
            feature_vector_q24: input.feature_vector_q24.clone(),
            expected_output_width: self.config.state_width,
        })
    }

    pub fn recover_chain_root(
        journal_file: File,
        operation_file: File,
        native: SparseConfig,
        scope: JournalScope,
        max_records: usize,
        config: NeuronRuntimeConfigV1,
        witness: W,
    ) -> Result<Self, NeuronRuntimeError> {
        config.validate_native(&native)?;
        let latest = witness
            .current()?
            .ok_or(NeuronRuntimeError::RecoveryWitnessMismatch)?;
        if latest.sequence <= max_records as u64 {
            return Self::recover(
                journal_file,
                operation_file,
                native,
                scope,
                max_records,
                config,
                witness,
            );
        }
        let operations = NeuronOperationStore::open(
            operation_file,
            scope,
            config.generation,
            config.semantic_digest()?,
            MAX_OPERATION_RECORDS,
        )?;
        let journal = SparseJournal::open(journal_file, native, scope, max_records)?;
        let current = journal
            .current_anchor()?
            .ok_or(NeuronRuntimeError::RecoveryWitnessMismatch)?;
        if current.sequence != max_records as u64
            || !operations.contains_anchor(current)
            || !operations.contains_anchor(latest)
        {
            return Err(NeuronRuntimeError::Journal(
                JournalError::AcknowledgedHistoryMissing,
            ));
        }
        Ok(Self {
            config,
            journal,
            operations,
            witness,
            chain_recovery_pending: true,
        })
    }

    pub fn rollover(&mut self, file: File, max_records: usize) -> Result<(), NeuronRuntimeError> {
        if self.chain_recovery_pending {
            return Err(NeuronRuntimeError::PendingReconciliation);
        }
        self.reconcile_frontier()?;
        self.journal = self.journal.start_successor(file, max_records)?;
        Ok(())
    }

    pub fn recover_next_segment(
        &mut self,
        file: File,
        max_records: usize,
    ) -> Result<(), NeuronRuntimeError> {
        let latest = self
            .witness
            .current()?
            .ok_or(NeuronRuntimeError::RecoveryWitnessMismatch)?;
        let seed = self
            .journal
            .current()?
            .ok_or(NeuronRuntimeError::RecoveryWitnessMismatch)?;
        let segment_end = seed.sequence().saturating_add(max_records as u64);
        let length = file.metadata().map_err(JournalError::from)?.len();
        let next = if latest.sequence <= segment_end {
            self.journal.recover_successor(file, max_records, latest)?
        } else {
            if length == 0 {
                return Err(NeuronRuntimeError::Journal(
                    JournalError::AcknowledgedHistoryMissing,
                ));
            }
            let recovered = self.journal.start_successor(file, max_records)?;
            let current = recovered
                .current_anchor()?
                .ok_or(NeuronRuntimeError::RecoveryWitnessMismatch)?;
            if current.sequence != segment_end || !self.operations.contains_anchor(current) {
                return Err(NeuronRuntimeError::Journal(
                    JournalError::AcknowledgedHistoryMissing,
                ));
            }
            recovered
        };
        self.journal = next;
        let current = self
            .journal
            .current_anchor()?
            .ok_or(NeuronRuntimeError::RecoveryWitnessMismatch)?;
        self.chain_recovery_pending = current.sequence < latest.sequence;
        if !self.chain_recovery_pending {
            self.reconcile_frontier()?;
        }
        Ok(())
    }

    pub fn tick(
        &mut self,
        model: &mut impl NeuronModelPort,
        input: NeuronTickInputV1,
    ) -> Result<NeuronRuntimeOutputV1, NeuronRuntimeError> {
        if self.chain_recovery_pending {
            return Err(NeuronRuntimeError::PendingReconciliation);
        }
        let model_request = self.model_request(&input)?;
        self.reconcile_frontier()?;

        if let Some(record) = self.operations.find(&input.tick_id).cloned() {
            if record.input_digest != model_request.input_digest {
                return Err(OperationStoreError::Conflict.into());
            }
            let acknowledged = self
                .witness
                .current()?
                .ok_or(NeuronRuntimeError::RecoveryWitnessMismatch)?;
            if acknowledged == record.next
                || self.operations.is_descendant(record.next, acknowledged)
            {
                return Ok(record.output);
            }
            return Err(NeuronRuntimeError::PendingReconciliation);
        }

        let current = self.journal.current()?;
        let expected_checkpoint = current.map_or(Digest32::ZERO, SparseCheckpoint::digest);
        if input.checkpoint_digest != expected_checkpoint {
            return Err(NeuronRuntimeError::CheckpointMismatch);
        }
        let expected_anchor = current.map(|checkpoint| JournalAnchor {
            sequence: checkpoint.sequence(),
            checkpoint_digest: checkpoint.digest(),
        });

        let started = Instant::now();
        let model_output = model.execute(&model_request)?;
        validate_model_output(&self.config, &model_output)?;
        let sparse_tick = SparseTick {
            scope_digest: subject_scope_digest(&input.subject_id)?,
            objective_digest: input.objective_digest,
            ndu_digest: input.ndu_snapshot_digest,
            body_digest: body_digest(&self.config, &input),
            input_digest: model_request.input_digest,
            sequence: input.logical_sequence,
            monotonic_micros: input.monotonic_time_micros,
            drive_q24: model_output.drive_q24.clone(),
            prediction_q24: model_output.prediction_q24.clone(),
        };
        let (checkpoint, sparse_receipt) = self
            .journal
            .preview(input.checkpoint_digest, &sparse_tick)?;
        let execution_micros = u64::try_from(started.elapsed().as_micros()).unwrap_or(u64::MAX);
        let output = build_output(
            &self.config,
            &input.tick_id,
            input.logical_sequence,
            &model_output,
            &sparse_receipt,
            &checkpoint,
            execution_micros,
        )?;
        let next = JournalAnchor {
            sequence: input.logical_sequence,
            checkpoint_digest: sparse_receipt.checkpoint_after,
        };
        self.operations.append(NeuronPreparedOperationV1 {
            tick_id: input.tick_id,
            input_digest: model_request.input_digest,
            expected: expected_anchor,
            next,
            sparse_tick,
            output,
        })?;
        self.reconcile_frontier()?
            .ok_or_else(|| OperationStoreError::Corrupt.into())
    }

    pub fn query_result(
        &mut self,
        tick_id: &StableId,
        input_digest: Digest32,
    ) -> Result<Option<NeuronRuntimeOutputV1>, NeuronRuntimeError> {
        if self.chain_recovery_pending {
            return Err(NeuronRuntimeError::PendingReconciliation);
        }
        self.reconcile_frontier()?;
        let Some(record) = self.operations.find(tick_id) else {
            return Ok(None);
        };
        if record.input_digest != input_digest {
            return Err(OperationStoreError::Conflict.into());
        }
        Ok(Some(record.output.clone()))
    }

    pub fn canonical_checkpoint(
        &self,
        tick: &NeuronTickReceiptV1,
        expires_unix_ms: u64,
    ) -> Result<crate::NeuronCheckpointV1, crate::NeuronProtocolError> {
        let record = self.operations.find(&tick.tick_id).ok_or(
            crate::NeuronProtocolError::BindingMismatch("operation result"),
        )?;
        if record.output.tick != *tick {
            return Err(crate::NeuronProtocolError::BindingMismatch(
                "operation result",
            ));
        }
        let checkpoint = self
            .journal
            .current()
            .map_err(|_| crate::NeuronProtocolError::BindingMismatch("journal"))?
            .ok_or(crate::NeuronProtocolError::BindingMismatch("checkpoint"))?;
        crate::canonical_checkpoint_v1(&self.config, checkpoint, tick, expires_unix_ms)
    }

    pub fn current_anchor(&self) -> Result<Option<JournalAnchor>, NeuronRuntimeError> {
        Ok(self.journal.current_anchor()?)
    }

    pub fn current_eligibility_sample(
        &self,
    ) -> Result<Option<crate::EligibilityTraceSampleV1>, NeuronRuntimeError> {
        Ok(self
            .journal
            .current()?
            .map(crate::EligibilityTraceSampleV1::from_checkpoint))
    }

    fn reconcile_frontier(&mut self) -> Result<Option<NeuronRuntimeOutputV1>, NeuronRuntimeError> {
        if self.chain_recovery_pending {
            return Err(NeuronRuntimeError::PendingReconciliation);
        }
        let journal_current = self.journal.current_anchor()?;
        let witness_current = self.witness.current()?;
        let Some(record) = self.operations.latest().cloned() else {
            if journal_current.is_none() && witness_current.is_none() {
                return Ok(None);
            }
            return Err(OperationStoreError::Conflict.into());
        };

        let receipt = if journal_current == record.expected {
            let expected_digest = record
                .expected
                .map_or(Digest32::ZERO, |anchor| anchor.checkpoint_digest);
            self.journal.commit(expected_digest, &record.sparse_tick)?
        } else if journal_current == Some(record.next) {
            self.journal
                .receipt_at(record.next.sequence)?
                .cloned()
                .unwrap_or_else(|| self.receipt_from_record(&record))
        } else {
            return Err(OperationStoreError::Conflict.into());
        };
        self.validate_committed_record(&record, &receipt)?;

        let observed = self.witness.current()?;
        if observed == Some(record.next) {
            return Ok(Some(record.output));
        }
        if observed != record.expected {
            return Err(NeuronRuntimeError::RecoveryWitnessMismatch);
        }
        if let Err(error) = self.witness.compare_and_swap(record.expected, record.next) {
            if self.witness.current().ok() == Some(Some(record.next)) {
                return Ok(Some(record.output));
            }
            return Err(NeuronRuntimeError::WitnessAfterCommit {
                anchor: record.next,
                error,
            });
        }
        Ok(Some(record.output))
    }

    fn receipt_from_record(&self, record: &NeuronPreparedOperationV1) -> SparseSignalReceipt {
        let checkpoint = self
            .journal
            .current()
            .ok()
            .flatten()
            .filter(|value| value.digest() == record.next.checkpoint_digest);
        SparseSignalReceipt {
            config_digest: self.config.native_config_digest,
            input_digest: checkpoint.map_or(Digest32::ZERO, SparseCheckpoint::input_binding_digest),
            checkpoint_before: record.output.tick.checkpoint_before,
            checkpoint_after: record.output.tick.checkpoint_after,
            activation_q24: record.output.signal.signals_q24.clone(),
            active_fraction_ppm: record.output.tick.sparsity_ppm,
            prediction_error_q24: record.output.tick.prediction_error_q24,
            projection_count: record.output.tick.resource_receipt.saturation_count,
            requires_calibration: true,
            authority: AuthorityPosture::DENY_ALL,
        }
    }

    fn validate_committed_record(
        &self,
        record: &NeuronPreparedOperationV1,
        receipt: &SparseSignalReceipt,
    ) -> Result<(), NeuronRuntimeError> {
        let checkpoint = self
            .journal
            .current()?
            .ok_or(OperationStoreError::Corrupt)?;
        if checkpoint.digest() != record.next.checkpoint_digest
            || receipt.checkpoint_before
                != record
                    .expected
                    .map_or(Digest32::ZERO, |anchor| anchor.checkpoint_digest)
            || receipt.checkpoint_after != record.next.checkpoint_digest
            || receipt.input_digest != checkpoint.input_binding_digest()
            || receipt.activation_q24 != record.output.signal.signals_q24
            || receipt.active_fraction_ppm != record.output.tick.sparsity_ppm
            || receipt.prediction_error_q24 != record.output.tick.prediction_error_q24
            || receipt.projection_count != record.output.tick.resource_receipt.saturation_count
            || checkpoint.activation_digest() != record.output.tick.activation_digest
            || checkpoint.threshold_digest() != record.output.tick.threshold_digest
            || checkpoint.eligibility_digest() != record.output.tick.eligibility_digest
            || checkpoint.temporal_state_digest() != record.output.signal.temporal_state_digest
        {
            return Err(OperationStoreError::Corrupt.into());
        }
        let model_output = NeuronModelOutputV1 {
            encoder_digest: self.config.encoder_digest,
            head_digest: self.config.head_digest,
            output_digest: canonical_model_output_digest_v1(
                &record.sparse_tick.drive_q24,
                &record.sparse_tick.prediction_q24,
                &record.output.model_runtime,
            )?,
            drive_q24: record.sparse_tick.drive_q24.clone(),
            prediction_q24: record.sparse_tick.prediction_q24.clone(),
            queue_age_micros: record.output.tick.resource_receipt.queue_age_micros,
            transient_allocation_bytes: record
                .output
                .tick
                .resource_receipt
                .transient_allocation_bytes,
            runtime_receipt: record.output.model_runtime.clone(),
        };
        validate_model_output(&self.config, &model_output)?;
        if digest_model_binding(&model_output)? != record.output.signal.model_runtime_digest {
            return Err(OperationStoreError::Corrupt.into());
        }
        let (confidence_ppm, ood_ppm, calibration_abstain) =
            calibrate(&self.config.calibration, receipt, record.next.sequence)?;
        let resource = &record.output.tick.resource_receipt;
        let resource_abstain = resource.execution_micros
            > self.config.resource_envelope.p99_latency_micros
            || resource.transient_allocation_bytes
                > self.config.resource_envelope.transient_allocation_bytes
            || resource.checkpoint_bytes > self.config.resource_envelope.checkpoint_bytes
            || resource.write_amplification_ppm
                > self.config.resource_envelope.write_amplification_ppm;
        if record.output.tick.confidence_ppm != confidence_ppm
            || record.output.tick.ood_ppm != ood_ppm
            || record.output.signal.ood_ppm != ood_ppm
            || record.output.tick.abstain != (calibration_abstain || resource_abstain)
            || record.output.signal.abstain != record.output.tick.abstain
        {
            return Err(OperationStoreError::Corrupt.into());
        }
        Ok(())
    }
}

fn build_output(
    config: &NeuronRuntimeConfigV1,
    tick_id: &StableId,
    logical_sequence: u64,
    model_output: &NeuronModelOutputV1,
    sparse_receipt: &SparseSignalReceipt,
    checkpoint: &SparseCheckpoint,
    execution_micros: u64,
) -> Result<NeuronRuntimeOutputV1, NeuronRuntimeError> {
    let model_runtime_digest = digest_model_binding(model_output)?;
    let (confidence_ppm, ood_ppm, mut abstain) =
        calibrate(&config.calibration, sparse_receipt, logical_sequence)?;
    let checkpoint_bytes = checkpoint.bounded_encoded_bytes() as u64;
    let journal_bytes_written = u64::try_from(304_usize + 16 * config.state_width)
        .map_err(|_| NeuronRuntimeError::Arithmetic)?;
    let write_amplification_ppm = {
        let numerator = u128::from(journal_bytes_written)
            .checked_mul(1_000_000)
            .ok_or(NeuronRuntimeError::Arithmetic)?;
        let denominator = u128::from(checkpoint_bytes);
        let rounded_up = numerator
            .checked_add(denominator.saturating_sub(1))
            .ok_or(NeuronRuntimeError::Arithmetic)?
            / denominator;
        u32::try_from(rounded_up).map_err(|_| NeuronRuntimeError::Arithmetic)?
    };
    if execution_micros > config.resource_envelope.p99_latency_micros
        || model_output.transient_allocation_bytes
            > config.resource_envelope.transient_allocation_bytes
        || checkpoint_bytes > config.resource_envelope.checkpoint_bytes
        || write_amplification_ppm > config.resource_envelope.write_amplification_ppm
    {
        abstain = true;
    }
    let active_indices = checkpoint
        .activation_q24()
        .iter()
        .enumerate()
        .filter(|(_, value)| **value > 0)
        .map(|(index, _)| u32::try_from(index).map_err(|_| NeuronRuntimeError::Arithmetic))
        .collect::<Result<Vec<_>, _>>()?;
    let resource_receipt = NeuronResourceReceiptV1 {
        execution_micros,
        transient_allocation_bytes: model_output.transient_allocation_bytes,
        checkpoint_bytes,
        journal_bytes_written,
        write_amplification_ppm,
        saturation_count: sparse_receipt.projection_count,
        queue_age_micros: model_output.queue_age_micros,
    };
    let tick = NeuronTickReceiptV1 {
        tick_id: tick_id.clone(),
        checkpoint_before: sparse_receipt.checkpoint_before,
        checkpoint_after: sparse_receipt.checkpoint_after,
        activation_digest: checkpoint.activation_digest(),
        active_indices,
        sparsity_ppm: sparse_receipt.active_fraction_ppm,
        threshold_digest: checkpoint.threshold_digest(),
        eligibility_digest: checkpoint.eligibility_digest(),
        prediction_error_q24: sparse_receipt.prediction_error_q24,
        confidence_ppm,
        ood_ppm,
        abstain,
        resource_receipt,
    };
    let signal = NeuronSignalReceiptV1 {
        signal_set_id: tick_id.clone(),
        model_runtime_digest,
        temporal_state_digest: checkpoint.temporal_state_digest(),
        signals_q24: sparse_receipt.activation_q24.clone(),
        activation_sparsity_ppm: sparse_receipt.active_fraction_ppm,
        ood_ppm,
        abstain,
        authority: AuthorityPosture::DENY_ALL,
    };
    Ok(NeuronRuntimeOutputV1 {
        tick,
        signal,
        model_runtime: model_output.runtime_receipt.clone(),
    })
}

#[cfg(test)]
#[path = "runtime_tests.rs"]
mod tests;
