//! Stateful host lifecycle for canonical neuron ticks.

use std::fs::File;
use std::time::Instant;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::FileNeuronOperationStore;
use crate::JournalAnchor;
use crate::JournalError;
use crate::JournalScope;
use crate::NeuronDeletionRebuildPlanV1;
use crate::NeuronDeletionRebuildReceiptV1;
use crate::SparseCheckpoint;
use crate::SparseConfig;
use crate::SparseJournal;
use crate::SparseSignalReceipt;
use crate::SparseTick;
use crate::operation_store::PreparedNeuronOperationV1;
use crate::runtime_types::*;
use crate::sparse_tick;
use crate::validate_deletion_rebuild;

pub struct NeuronRuntime<W: AnchorWitnessStore> {
    config: NeuronRuntimeConfigV1,
    native: SparseConfig,
    journal: SparseJournal,
    operations: FileNeuronOperationStore,
    witness: W,
}

impl<W: AnchorWitnessStore> NeuronRuntime<W> {
    #[allow(clippy::too_many_arguments)]
    pub fn bootstrap(
        journal_file: File,
        operation_file: File,
        native: SparseConfig,
        scope: JournalScope,
        max_records: usize,
        max_operations: usize,
        config: NeuronRuntimeConfigV1,
        witness: W,
    ) -> Result<Self, NeuronRuntimeError> {
        config.validate_native(&native)?;
        let config_digest = config.semantic_digest()?;
        if journal_file.metadata().map_err(JournalError::from)?.len() != 0 {
            return Err(NeuronRuntimeError::BootstrapRequiresEmptyJournal);
        }
        if witness.current()?.is_some() {
            return Err(NeuronRuntimeError::BootstrapWitnessPresent);
        }
        let operations = FileNeuronOperationStore::open(
            operation_file,
            config_digest,
            scope,
            config.generation,
            config.state_width,
            max_operations,
        )?;
        if !operations.is_empty()? {
            return Err(NeuronRuntimeError::OperationHistoryMismatch);
        }
        let journal = SparseJournal::open(journal_file, native.clone(), scope, max_records)?;
        Ok(Self {
            config,
            native,
            journal,
            operations,
            witness,
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
        max_operations: usize,
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
            max_operations,
            config,
            witness,
        )?;
        Ok((runtime, receipt))
    }

    /// Recover from the three durable stores. The operation ledger permits a
    /// first commit with no witness yet and distinguishes that state from loss
    /// of an already acknowledged history.
    #[allow(clippy::too_many_arguments)]
    pub fn recover(
        journal_file: File,
        operation_file: File,
        native: SparseConfig,
        scope: JournalScope,
        max_records: usize,
        max_operations: usize,
        config: NeuronRuntimeConfigV1,
        witness: W,
    ) -> Result<Self, NeuronRuntimeError> {
        config.validate_native(&native)?;
        let config_digest = config.semantic_digest()?;
        let operations = FileNeuronOperationStore::open_existing(
            operation_file,
            config_digest,
            scope,
            config.generation,
            config.state_width,
            max_operations,
        )?;
        let pending = operations.pending()?;
        let acknowledged = witness.current()?;
        let journal = match acknowledged {
            Some(anchor) => SparseJournal::open_anchored(
                journal_file,
                native.clone(),
                scope,
                max_records,
                anchor,
            )?,
            None if pending.is_some() => {
                SparseJournal::open(journal_file, native.clone(), scope, max_records)?
            }
            None => return Err(NeuronRuntimeError::RecoveryWitnessMismatch),
        };
        let mut runtime = Self {
            config,
            native,
            journal,
            operations,
            witness,
        };
        runtime.validate_recovered_frontiers()?;
        let _ = runtime.reconcile_pending()?;
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

    /// Recover the first segment of a multi-segment chain. If the independent
    /// witness is beyond this segment, later calls to `recover_next_segment`
    /// reach the current frontier before any pending operation is reconciled.
    #[allow(clippy::too_many_arguments)]
    pub fn recover_chain_root(
        journal_file: File,
        operation_file: File,
        native: SparseConfig,
        scope: JournalScope,
        max_records: usize,
        max_operations: usize,
        config: NeuronRuntimeConfigV1,
        witness: W,
    ) -> Result<Self, NeuronRuntimeError> {
        config.validate_native(&native)?;
        let operations = FileNeuronOperationStore::open_existing(
            operation_file,
            config.semantic_digest()?,
            scope,
            config.generation,
            config.state_width,
            max_operations,
        )?;
        let latest = witness.current()?;
        let pending = operations.pending()?;
        let journal = match latest {
            Some(anchor) if anchor.sequence <= max_records as u64 => SparseJournal::open_anchored(
                journal_file,
                native.clone(),
                scope,
                max_records,
                anchor,
            )?,
            Some(_) => SparseJournal::open(journal_file, native.clone(), scope, max_records)?,
            None if pending.is_some() => {
                SparseJournal::open(journal_file, native.clone(), scope, max_records)?
            }
            None => return Err(NeuronRuntimeError::RecoveryWitnessMismatch),
        };
        let mut runtime = Self {
            config,
            native,
            journal,
            operations,
            witness,
        };
        let current = runtime
            .journal
            .current_anchor()?
            .ok_or(NeuronRuntimeError::RecoveryWitnessMismatch)?;
        if latest.is_some_and(|anchor| anchor.sequence > max_records as u64)
            && current.sequence != max_records as u64
        {
            return Err(NeuronRuntimeError::Journal(
                JournalError::AcknowledgedHistoryMissing,
            ));
        }
        if latest.is_none_or(|anchor| anchor.sequence <= max_records as u64) {
            runtime.validate_recovered_frontiers()?;
            let _ = runtime.reconcile_pending()?;
        }
        Ok(runtime)
    }

    /// Rotate to a fresh successor segment while preserving the exact current
    /// checkpoint as the new segment's immutable seed.
    pub fn rollover(&mut self, file: File, max_records: usize) -> Result<(), NeuronRuntimeError> {
        if self.operations.pending()?.is_some() {
            return Err(NeuronRuntimeError::PendingReconciliation);
        }
        self.journal = self.journal.start_successor(file, max_records)?;
        Ok(())
    }

    /// Recover the next segment in a chain. Intermediate segments must be full
    /// when the external witness lies beyond them. The pending durable result is
    /// reconciled as soon as its segment is reached.
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
                .current()?
                .ok_or(NeuronRuntimeError::RecoveryWitnessMismatch)?;
            if current.sequence() != segment_end {
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
        let pending = self.operations.pending()?;
        let pending_reached = pending.as_ref().is_some_and(|value| {
            Some(current) == value.expected_anchor || current == value.next_anchor
        });
        if current == latest || pending_reached {
            self.validate_recovered_frontiers()?;
            let _ = self.reconcile_pending()?;
        }
        Ok(())
    }

    pub fn tick(
        &mut self,
        model: &mut impl NeuronModelPort,
        input: NeuronTickInputV1,
    ) -> Result<NeuronRuntimeOutputV1, NeuronRuntimeError> {
        let model_request = self.model_request(&input)?;
        let input_digest = model_request.input_digest;
        if let Some(stored) = self.operations.find_tick(&input.tick_id)? {
            if stored.input_digest != input_digest {
                return Err(NeuronRuntimeError::OperationConflict);
            }
            return self.reconcile_operation(stored);
        }
        if self.operations.pending()?.is_some() {
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
        let native_tick = SparseTick {
            scope_digest: subject_scope_digest(&input.subject_id)?,
            objective_digest: input.objective_digest,
            ndu_digest: input.ndu_snapshot_digest,
            body_digest: body_digest(&self.config, &input),
            input_digest,
            sequence: input.logical_sequence,
            monotonic_micros: input.monotonic_time_micros,
            drive_q24: model_output.drive_q24.clone(),
            prediction_q24: model_output.prediction_q24.clone(),
        };
        let (checkpoint, sparse_receipt) =
            sparse_tick(&self.native, &native_tick, self.journal.current()?)
                .map_err(JournalError::Mechanism)?;
        let output = self.build_output(
            &input.tick_id,
            &model_output,
            &checkpoint,
            &sparse_receipt,
            started,
        )?;
        let next_anchor = JournalAnchor {
            sequence: input.logical_sequence,
            checkpoint_digest: sparse_receipt.checkpoint_after,
        };
        let prepared = PreparedNeuronOperationV1::new(
            input_digest,
            input.tick_id,
            expected_anchor,
            next_anchor,
            native_tick,
            output,
        )?;
        self.operations.prepare(prepared.clone())?;
        self.reconcile_operation(prepared)
    }

    pub fn canonical_checkpoint(
        &self,
        tick: &NeuronTickReceiptV1,
        expires_unix_ms: u64,
    ) -> Result<crate::NeuronCheckpointV1, crate::NeuronProtocolError> {
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

    fn build_output(
        &self,
        tick_id: &StableId,
        model_output: &NeuronModelOutputV1,
        checkpoint: &SparseCheckpoint,
        sparse_receipt: &SparseSignalReceipt,
        started: Instant,
    ) -> Result<NeuronRuntimeOutputV1, NeuronRuntimeError> {
        let (confidence_ppm, ood_ppm, mut abstain) = calibrate(
            &self.config.calibration,
            sparse_receipt,
            checkpoint.sequence(),
        )?;
        let execution_micros = u64::try_from(started.elapsed().as_micros()).unwrap_or(u64::MAX);
        let checkpoint_bytes = checkpoint.bounded_encoded_bytes() as u64;
        let journal_bytes_written = u64::try_from(304_usize + 16 * self.config.state_width)
            .map_err(|_| NeuronRuntimeError::Arithmetic)?;
        let write_amplification_ppm = write_amplification(journal_bytes_written, checkpoint_bytes)?;
        if execution_micros > self.config.resource_envelope.p99_latency_micros
            || model_output.transient_allocation_bytes
                > self.config.resource_envelope.transient_allocation_bytes
            || checkpoint_bytes > self.config.resource_envelope.checkpoint_bytes
            || write_amplification_ppm > self.config.resource_envelope.write_amplification_ppm
        {
            abstain = true;
        }
        let active_indices = committed_active_indices(checkpoint)?;
        let resource_receipt = NeuronResourceReceiptV1 {
            execution_micros,
            transient_allocation_bytes: model_output.transient_allocation_bytes,
            checkpoint_bytes,
            journal_bytes_written,
            write_amplification_ppm,
            saturation_count: sparse_receipt.projection_count,
            queue_age_micros: model_output.queue_age_micros,
        };
        let tick_receipt = NeuronTickReceiptV1 {
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
            model_runtime_digest: digest_model_binding(model_output)?,
            temporal_state_digest: checkpoint.temporal_state_digest(),
            signals_q24: sparse_receipt.activation_q24.clone(),
            activation_sparsity_ppm: sparse_receipt.active_fraction_ppm,
            ood_ppm,
            abstain,
            authority: AuthorityPosture::DENY_ALL,
        };
        Ok(NeuronRuntimeOutputV1 {
            tick: tick_receipt,
            signal,
            model_runtime: model_output.runtime_receipt.clone(),
        })
    }

    fn reconcile_pending(&mut self) -> Result<Option<NeuronRuntimeOutputV1>, NeuronRuntimeError> {
        self.operations
            .pending()?
            .map(|value| self.reconcile_operation(value))
            .transpose()
    }

    fn reconcile_operation(
        &mut self,
        value: PreparedNeuronOperationV1,
    ) -> Result<NeuronRuntimeOutputV1, NeuronRuntimeError> {
        let pending = self.operations.pending()?;
        if pending.is_none() {
            return Ok(value.output);
        }
        if pending.as_ref().map(|record| record.operation_digest) != Some(value.operation_digest) {
            return Err(NeuronRuntimeError::PendingReconciliation);
        }
        let current = self.journal.current_anchor()?;
        if current == value.expected_anchor {
            let receipt = self.journal.commit(
                value
                    .expected_anchor
                    .map_or(Digest32::ZERO, |anchor| anchor.checkpoint_digest),
                &value.sparse_tick,
            )?;
            if receipt.checkpoint_after != value.next_anchor.checkpoint_digest {
                return Err(NeuronRuntimeError::OperationHistoryMismatch);
            }
        } else if current != Some(value.next_anchor) {
            return Err(NeuronRuntimeError::OperationHistoryMismatch);
        }
        self.validate_committed_operation(&value)?;

        let witness_current = self.witness.current()?;
        if witness_current == value.expected_anchor {
            if let Err(error) = self
                .witness
                .compare_and_swap(value.expected_anchor, value.next_anchor)
            {
                match self.witness.current() {
                    Ok(Some(current)) if current == value.next_anchor => {}
                    Ok(_) | Err(_) => {
                        return Err(NeuronRuntimeError::WitnessAfterCommit {
                            anchor: value.next_anchor,
                            error,
                        });
                    }
                }
            }
        } else if witness_current != Some(value.next_anchor) {
            return Err(NeuronRuntimeError::RecoveryWitnessMismatch);
        }
        self.operations.complete(value.operation_digest)?;
        Ok(value.output)
    }

    fn validate_recovered_frontiers(&self) -> Result<(), NeuronRuntimeError> {
        let journal = self.journal.current_anchor()?;
        let witness = self.witness.current()?;
        if let Some(pending) = self.operations.pending()? {
            if journal != pending.expected_anchor && journal != Some(pending.next_anchor) {
                return Err(NeuronRuntimeError::OperationHistoryMismatch);
            }
            if witness != pending.expected_anchor && witness != Some(pending.next_anchor) {
                return Err(NeuronRuntimeError::RecoveryWitnessMismatch);
            }
        } else {
            if self.operations.frontier()? != journal || witness != journal {
                return Err(NeuronRuntimeError::OperationHistoryMismatch);
            }
            if let Some(latest) = self.operations.latest()? {
                self.validate_committed_operation(&latest)?;
            }
        }
        Ok(())
    }

    fn validate_committed_operation(
        &self,
        value: &PreparedNeuronOperationV1,
    ) -> Result<(), NeuronRuntimeError> {
        let checkpoint = self
            .journal
            .current()?
            .ok_or(NeuronRuntimeError::OperationHistoryMismatch)?;
        if checkpoint.digest() != value.next_anchor.checkpoint_digest
            || checkpoint.predecessor_digest()
                != value
                    .expected_anchor
                    .map_or(Digest32::ZERO, |anchor| anchor.checkpoint_digest)
            || value.output.tick.checkpoint_after != checkpoint.digest()
            || value.output.tick.activation_digest != checkpoint.activation_digest()
            || value.output.tick.threshold_digest != checkpoint.threshold_digest()
            || value.output.tick.eligibility_digest != checkpoint.eligibility_digest()
            || value.output.tick.active_indices != committed_active_indices(checkpoint)?
            || value.output.signal.temporal_state_digest != checkpoint.temporal_state_digest()
            || value.output.signal.signals_q24 != checkpoint.activation_q24()
        {
            return Err(NeuronRuntimeError::OperationHistoryMismatch);
        }
        let model_output = NeuronModelOutputV1 {
            encoder_digest: self.config.encoder_digest,
            head_digest: self.config.head_digest,
            output_digest: canonical_model_output_digest_v1(
                &value.sparse_tick.drive_q24,
                &value.sparse_tick.prediction_q24,
                &value.output.model_runtime,
            )?,
            drive_q24: value.sparse_tick.drive_q24.clone(),
            prediction_q24: value.sparse_tick.prediction_q24.clone(),
            queue_age_micros: value.output.tick.resource_receipt.queue_age_micros,
            transient_allocation_bytes: value
                .output
                .tick
                .resource_receipt
                .transient_allocation_bytes,
            runtime_receipt: value.output.model_runtime.clone(),
        };
        validate_model_output(&self.config, &model_output)?;
        if value.output.signal.model_runtime_digest != digest_model_binding(&model_output)? {
            return Err(NeuronRuntimeError::OperationHistoryMismatch);
        }
        let receipt = SparseSignalReceipt {
            config_digest: self.native.digest().map_err(JournalError::Mechanism)?,
            input_digest: value.sparse_tick.input_digest,
            checkpoint_before: value.output.tick.checkpoint_before,
            checkpoint_after: value.output.tick.checkpoint_after,
            activation_q24: value.output.signal.signals_q24.clone(),
            active_fraction_ppm: value.output.tick.sparsity_ppm,
            prediction_error_q24: value.output.tick.prediction_error_q24,
            projection_count: value.output.tick.resource_receipt.saturation_count,
            requires_calibration: true,
            authority: AuthorityPosture::DENY_ALL,
        };
        let (confidence, ood, calibration_abstain) =
            calibrate(&self.config.calibration, &receipt, checkpoint.sequence())?;
        let resource = &value.output.tick.resource_receipt;
        let resource_abstain = resource.execution_micros
            > self.config.resource_envelope.p99_latency_micros
            || resource.transient_allocation_bytes
                > self.config.resource_envelope.transient_allocation_bytes
            || resource.checkpoint_bytes > self.config.resource_envelope.checkpoint_bytes
            || resource.write_amplification_ppm
                > self.config.resource_envelope.write_amplification_ppm;
        if value.output.tick.confidence_ppm != confidence
            || value.output.tick.ood_ppm != ood
            || value.output.signal.ood_ppm != ood
            || value.output.tick.abstain != (calibration_abstain || resource_abstain)
            || value.output.signal.abstain != value.output.tick.abstain
            || value.output.signal.activation_sparsity_ppm != value.output.tick.sparsity_ppm
            || value.output.signal.authority.grants_any()
            || resource.checkpoint_bytes != checkpoint.bounded_encoded_bytes() as u64
            || resource.journal_bytes_written
                != u64::try_from(304_usize + 16 * self.config.state_width)
                    .map_err(|_| NeuronRuntimeError::Arithmetic)?
            || resource.write_amplification_ppm
                != write_amplification(resource.journal_bytes_written, resource.checkpoint_bytes)?
        {
            return Err(NeuronRuntimeError::OperationHistoryMismatch);
        }
        Ok(())
    }
}

fn committed_active_indices(checkpoint: &SparseCheckpoint) -> Result<Vec<u32>, NeuronRuntimeError> {
    checkpoint
        .activation_q24()
        .iter()
        .enumerate()
        .filter(|(_, value)| **value > 0)
        .map(|(index, _)| u32::try_from(index).map_err(|_| NeuronRuntimeError::Arithmetic))
        .collect()
}

fn write_amplification(
    journal_bytes_written: u64,
    checkpoint_bytes: u64,
) -> Result<u32, NeuronRuntimeError> {
    if checkpoint_bytes == 0 {
        return Err(NeuronRuntimeError::Arithmetic);
    }
    let numerator = u128::from(journal_bytes_written)
        .checked_mul(1_000_000)
        .ok_or(NeuronRuntimeError::Arithmetic)?;
    let denominator = u128::from(checkpoint_bytes);
    let rounded_up = numerator
        .checked_add(denominator.saturating_sub(1))
        .ok_or(NeuronRuntimeError::Arithmetic)?
        / denominator;
    u32::try_from(rounded_up).map_err(|_| NeuronRuntimeError::Arithmetic)
}

#[cfg(test)]
#[path = "runtime_tests.rs"]
mod tests;
