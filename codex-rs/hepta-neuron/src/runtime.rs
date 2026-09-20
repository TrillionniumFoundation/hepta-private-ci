//! Stateful host lifecycle for canonical neuron ticks.

use std::fs::File;
use std::time::Instant;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;

use crate::JournalAnchor;
use crate::JournalError;
use crate::JournalScope;
use crate::NeuronDeletionRebuildPlanV1;
use crate::NeuronDeletionRebuildReceiptV1;
use crate::SparseConfig;
use crate::SparseJournal;
use crate::SparseTick;
use crate::runtime_types::*;
use crate::validate_deletion_rebuild;

#[derive(Clone)]
struct PendingWitness {
    input_digest: Digest32,
    expected: Option<JournalAnchor>,
    next: JournalAnchor,
    output: NeuronRuntimeOutputV1,
}

pub struct NeuronRuntime<W: AnchorWitnessStore> {
    config: NeuronRuntimeConfigV1,
    journal: SparseJournal,
    witness: W,
    pending: Option<PendingWitness>,
}

impl<W: AnchorWitnessStore> NeuronRuntime<W> {
    pub fn bootstrap(
        file: File,
        native: SparseConfig,
        scope: JournalScope,
        max_records: usize,
        config: NeuronRuntimeConfigV1,
        witness: W,
    ) -> Result<Self, NeuronRuntimeError> {
        config.validate_native(&native)?;
        if file.metadata().map_err(JournalError::from)?.len() != 0 {
            return Err(NeuronRuntimeError::BootstrapRequiresEmptyJournal);
        }
        if witness.current()?.is_some() {
            return Err(NeuronRuntimeError::BootstrapWitnessPresent);
        }
        let journal = SparseJournal::open(file, native, scope, max_records)?;
        Ok(Self {
            config,
            journal,
            witness,
            pending: None,
        })
    }

    /// Start a fresh generation after authenticated deletion/withdrawal
    /// processing. The predecessor checkpoint is bound for lineage only and is
    /// never loaded into the successor runtime.
    // The bootstrap tuple is atomic across generation, store, config, witness and lineage;\n    // splitting it into independently reusable partial objects would permit mixed-generation use.\n    #[allow(clippy::too_many_arguments)]\n    pub fn bootstrap_after_deletion(\n        file: File,
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
        let runtime = Self::bootstrap(file, native, scope, max_records, config, witness)?;
        Ok((runtime, receipt))
    }

    pub fn recover(
        file: File,
        native: SparseConfig,
        scope: JournalScope,
        max_records: usize,
        config: NeuronRuntimeConfigV1,
        anchor: JournalAnchor,
        mut witness: W,
    ) -> Result<Self, NeuronRuntimeError> {
        config.validate_native(&native)?;
        if witness.current()? != Some(anchor) {
            return Err(NeuronRuntimeError::RecoveryWitnessMismatch);
        }
        let journal = SparseJournal::open_anchored(file, native, scope, max_records, anchor)?;
        let recovered = journal
            .current()?
            .map(|checkpoint| JournalAnchor {
                sequence: checkpoint.sequence(),
                checkpoint_digest: checkpoint.digest(),
            })
            .ok_or(NeuronRuntimeError::RecoveryWitnessMismatch)?;
        if recovered.sequence < anchor.sequence {
            return Err(NeuronRuntimeError::RecoveryWitnessMismatch);
        }
        if recovered != anchor {
            witness.compare_and_swap(Some(anchor), recovered)?;
        }
        Ok(Self {
            config,
            journal,
            witness,
            pending: None,
        })
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
    /// witness is beyond this segment, the segment must be complete; the next
    /// segment header will bind its exact final checkpoint before composition.
    pub fn recover_chain_root(
        file: File,
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
            return Self::recover(file, native, scope, max_records, config, latest, witness);
        }
        let journal = SparseJournal::open(file, native, scope, max_records)?;
        let current = journal
            .current()?
            .ok_or(NeuronRuntimeError::RecoveryWitnessMismatch)?;
        if current.sequence() != max_records as u64 {
            return Err(NeuronRuntimeError::Journal(
                JournalError::AcknowledgedHistoryMissing,
            ));
        }
        Ok(Self {
            config,
            journal,
            witness,
            pending: None,
        })
    }

    /// Rotate to a fresh successor segment while preserving the exact current
    /// checkpoint as the new segment's immutable seed.
    pub fn rollover(&mut self, file: File, max_records: usize) -> Result<(), NeuronRuntimeError> {
        if self.pending.is_some() {
            return Err(NeuronRuntimeError::PendingReconciliation);
        }
        self.journal = self.journal.start_successor(file, max_records)?;
        Ok(())
    }

    /// Recover the next segment in a chain. Intermediate segments must be full
    /// when the external witness lies beyond them. The segment containing the
    /// external witness is opened anchored before any tail repair.
    pub fn recover_next_segment(
        &mut self,
        file: File,
        max_records: usize,
    ) -> Result<(), NeuronRuntimeError> {
        if self.pending.is_some() {
            return Err(NeuronRuntimeError::PendingReconciliation);
        }
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
        Ok(())
    }

    pub fn tick(
        &mut self,
        model: &mut impl NeuronModelPort,
        input: NeuronTickInputV1,
    ) -> Result<NeuronRuntimeOutputV1, NeuronRuntimeError> {
        let model_request = self.model_request(&input)?;
        let input_digest = model_request.input_digest;
        if let Some(pending) = self.pending.clone() {
            if pending.input_digest != input_digest {
                return Err(NeuronRuntimeError::PendingReconciliation);
            }
            match self
                .witness
                .compare_and_swap(pending.expected, pending.next)
            {
                Ok(()) => {
                    self.pending = None;
                    return Ok(pending.output);
                }
                Err(error) => {
                    return Err(NeuronRuntimeError::WitnessAfterCommit {
                        anchor: pending.next,
                        error,
                    });
                }
            }
        }

        let current = self.journal.current()?;
        let expected_checkpoint = current.map_or(Digest32::ZERO, crate::SparseCheckpoint::digest);
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
        let model_runtime_digest = digest_model_binding(&model_output)?;

        let sparse_tick = SparseTick {
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
        let sparse_receipt = self.journal.commit(input.checkpoint_digest, &sparse_tick)?;
        let checkpoint = self
            .journal
            .current()?
            .ok_or(NeuronRuntimeError::CheckpointMismatch)?;
        let (confidence_ppm, ood_ppm, mut abstain) = calibrate(
            &self.config.calibration,
            &sparse_receipt,
            input.logical_sequence,
        )?;
        let execution_micros = u64::try_from(started.elapsed().as_micros()).unwrap_or(u64::MAX);
        let checkpoint_bytes = checkpoint.bounded_encoded_bytes() as u64;
        let journal_bytes_written = u64::try_from(304_usize + 16 * self.config.state_width)
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
        if execution_micros > self.config.resource_envelope.p99_latency_micros
            || model_output.transient_allocation_bytes
                > self.config.resource_envelope.transient_allocation_bytes
            || checkpoint_bytes > self.config.resource_envelope.checkpoint_bytes
            || write_amplification_ppm > self.config.resource_envelope.write_amplification_ppm
        {
            abstain = true;
        }
        let active_indices = sparse_receipt
            .activation_q24
            .iter()
            .enumerate()
            .filter(|(_, value)| **value > 0)
            .map(|(index, _)| u32::try_from(index).map_err(|_| NeuronRuntimeError::Arithmetic))
            .collect::<Result<Vec<_>, _>>()?;
        let activation_digest = digest_q24_vector(
            b"hepta.neuron.activation.q24.v1",
            &sparse_receipt.activation_q24,
        );
        let threshold_digest = digest_q24_vector(
            b"hepta.neuron.threshold.q24.v1",
            checkpoint.thresholds_q24(),
        );
        let eligibility_digest = digest_q24_vector(
            b"hepta.neuron.eligibility.q24.v1",
            checkpoint.eligibility_q24(),
        );
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
            tick_id: input.tick_id.clone(),
            checkpoint_before: sparse_receipt.checkpoint_before,
            checkpoint_after: sparse_receipt.checkpoint_after,
            activation_digest,
            active_indices,
            sparsity_ppm: sparse_receipt.active_fraction_ppm,
            threshold_digest,
            eligibility_digest,
            prediction_error_q24: sparse_receipt.prediction_error_q24,
            confidence_ppm,
            ood_ppm,
            abstain,
            resource_receipt,
        };
        let signal = NeuronSignalReceiptV1 {
            signal_set_id: input.tick_id,
            model_runtime_digest,
            temporal_state_digest: sparse_receipt.checkpoint_after,
            signals_q24: sparse_receipt.activation_q24.clone(),
            activation_sparsity_ppm: sparse_receipt.active_fraction_ppm,
            ood_ppm,
            abstain,
            authority: AuthorityPosture::DENY_ALL,
        };
        let output = NeuronRuntimeOutputV1 {
            tick: tick_receipt,
            signal,
            model_runtime: model_output.runtime_receipt,
        };
        let next_anchor = JournalAnchor {
            sequence: input.logical_sequence,
            checkpoint_digest: sparse_receipt.checkpoint_after,
        };
        if let Err(error) = self.witness.compare_and_swap(expected_anchor, next_anchor) {
            self.pending = Some(PendingWitness {
                input_digest,
                expected: expected_anchor,
                next: next_anchor,
                output,
            });
            return Err(NeuronRuntimeError::WitnessAfterCommit {
                anchor: next_anchor,
                error,
            });
        }
        Ok(output)
    }

    pub fn current_anchor(&self) -> Result<Option<JournalAnchor>, NeuronRuntimeError> {
        Ok(self.journal.current()?.map(|checkpoint| JournalAnchor {
            sequence: checkpoint.sequence(),
            checkpoint_digest: checkpoint.digest(),
        }))
    }

    pub fn current_eligibility_sample(
        &self,
    ) -> Result<Option<crate::EligibilityTraceSampleV1>, NeuronRuntimeError> {
        Ok(self
            .journal
            .current()?
            .map(crate::EligibilityTraceSampleV1::from_checkpoint))
    }
}

#[cfg(test)]
#[path = "runtime_tests.rs"]
mod tests;
