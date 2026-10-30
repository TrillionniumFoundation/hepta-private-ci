//! Stateful host lifecycle for canonical neuron ticks.

use std::fs::File;
use std::time::Instant;

use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_contracts::claim_final_use;
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

fn append_final_use_identity(bytes: &mut Vec<u8>, value: &str) {
    bytes.extend_from_slice(&(value.len() as u64).to_be_bytes());
    bytes.extend_from_slice(value.as_bytes());
}

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
    // The bootstrap tuple is atomic across generation, store, config, witness and lineage;
    // splitting it into independently reusable partial objects would permit mixed-generation use.
    #[allow(clippy::too_many_arguments)]
    pub fn bootstrap_after_deletion(
        file: File,
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

    /// Canonical, fully scoped request to the independently operated final-use
    /// issuer. This value is NOT a grant: only its matching, signed, current,
    /// single-use token can authorize model invocation.
    pub fn final_use_binding(
        &self,
        input: &NeuronTickInputV1,
    ) -> Result<FinalUseBinding, NeuronRuntimeError> {
        let request = self.model_request(input)?;

        let mut scope = b"hepta.neuron.final-use.scope.v1\0".to_vec();
        append_final_use_identity(&mut scope, input.subject_id.as_str());
        append_final_use_identity(&mut scope, self.config.config_id.as_str());
        append_final_use_identity(&mut scope, self.config.model_id.as_str());
        scope.extend_from_slice(&self.config.generation.get().to_be_bytes());
        scope.extend_from_slice(input.objective_digest.as_array());
        scope.extend_from_slice(input.ndu_snapshot_digest.as_array());

        // Freeze every model artifact, execution identity, state geometry,
        // calibration and resource-limit setting, not only the short tick ID.
        let mut payload = b"hepta.neuron.final-use.payload.v1\0".to_vec();
        payload.extend_from_slice(request.input_digest.as_array());
        for digest in [
            self.config.model_manifest_digest,
            self.config.encoder_digest,
            self.config.head_digest,
            self.config.weights_digest,
            self.config.tokenizer_digest,
            self.config.preprocessor_digest,
            self.config.quantization_digest,
            self.config.runtime_digest,
            self.config.device_digest,
            self.config.normalization_digest,
            self.config.native_config_digest,
            self.config.calibration.calibration_artifact_digest,
            self.config.calibration.ood_artifact_digest,
        ] {
            payload.extend_from_slice(digest.as_array());
        }
        for dimension in [
            self.config.input_feature_dimension,
            self.config.state_width,
            self.config.modulator_dimension,
        ] {
            payload.extend_from_slice(&(dimension as u64).to_be_bytes());
        }
        let calibration = &self.config.calibration;
        for value in [
            calibration.generation.get(),
            calibration.valid_from_sequence,
            calibration.expires_after_sequence,
        ] {
            payload.extend_from_slice(&value.to_be_bytes());
        }
        for value in [
            calibration.zero_confidence_error_q24,
            calibration.maximum_in_domain_error_q24,
        ] {
            payload.extend_from_slice(&value.to_be_bytes());
        }
        for value in [
            calibration.minimum_confidence_ppm,
            calibration.maximum_ood_ppm,
            calibration.minimum_active_ppm,
            calibration.maximum_active_ppm,
            calibration.maximum_projection_count,
            calibration.measured_ece_ppm,
            calibration.maximum_ece_ppm,
            calibration.measured_false_acceptance_ppm,
            calibration.maximum_false_acceptance_ppm,
        ] {
            payload.extend_from_slice(&value.to_be_bytes());
        }
        let resource = &self.config.resource_envelope;
        for value in [
            resource.p95_latency_micros,
            resource.p99_latency_micros,
            resource.transient_allocation_bytes,
            resource.checkpoint_bytes,
        ] {
            payload.extend_from_slice(&value.to_be_bytes());
        }
        payload.extend_from_slice(&resource.write_amplification_ppm.to_be_bytes());

        Ok(FinalUseBinding {
            subject_id: input.subject_id.as_str().to_owned(),
            destination_id: "neuron.runtime.tick.v1".to_owned(),
            request_sha256: *request.input_digest.as_array(),
            scope_sha256: *Digest32::of_bytes(&scope).as_array(),
            payload_sha256: *Digest32::of_bytes(&payload).as_array(),
        })
    }

    /// The only product-facing tick entrypoint. The independent authority
    /// authenticates the exact NDU/current generation and durably claims its
    /// nonce. The effect guard revalidates and fences revocation across the model/journal call.
    pub fn tick_authorized(
        &mut self,
        authority: &FinalUseAuthority,
        signed: &SignedFinalUseGrant,
        model: &mut impl NeuronModelPort,
        input: NeuronTickInputV1,
    ) -> Result<NeuronRuntimeOutputV1, NeuronRuntimeError> {
        let expected = self.final_use_binding(&input)?;
        let token = claim_final_use(authority, signed, &expected)?;
        authority
            .with_verified_effect(token, &expected, || self.tick(model, input))
            .map_err(NeuronRuntimeError::FinalUse)?
    }

    /// Internal replay mechanism only; product callers must not bypass final-use.
    pub(crate) fn tick(
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
        let active_indices = checkpoint
            .activation_q24()
            .iter()
            .enumerate()
            .filter(|(_, value)| **value > 0)
            .map(|(index, _)| u32::try_from(index).map_err(|_| NeuronRuntimeError::Arithmetic))
            .collect::<Result<Vec<_>, _>>()?;
        let activation_digest = checkpoint.activation_digest();
        let threshold_digest = checkpoint.threshold_digest();
        let eligibility_digest = checkpoint.eligibility_digest();
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
            temporal_state_digest: checkpoint.temporal_state_digest(),
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
