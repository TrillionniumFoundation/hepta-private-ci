//! Stateful host lifecycle for canonical neuron ticks.

use std::fs::File;

use codex_hepta_types::Digest32;

use crate::JournalAnchor;
use crate::JournalError;
use crate::JournalScope;
use crate::NeuronDeletionRebuildPlanV1;
use crate::NeuronDeletionRebuildReceiptV1;
use crate::SparseConfig;
use crate::SparseJournal;
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

#[path = "runtime_tick.rs"]
mod transaction;

#[cfg(test)]
#[path = "runtime_tests.rs"]
mod tests;
