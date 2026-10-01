//! Recovery across enrolled roots and independently acknowledged segment chains.

use super::*;

impl<W: AnchorWitnessStore> NeuronRuntime<W> {
    /// Recover a root in a multi-segment chain. If the independent witness lies
    /// beyond it, the root must have its exact sealed quota length before replay
    /// can mutate anything; its successor then binds the exact final checkpoint.
    pub fn recover_chain_root(
        file: File,
        native: SparseConfig,
        scope: JournalScope,
        max_records: usize,
        config: NeuronRuntimeConfigV1,
        witness: W,
    ) -> Result<Self, NeuronRuntimeError> {
        config.validate_native(&native)?;
        Self::require_witness_config(&config, scope, &witness)?;
        let latest = witness
            .current()?
            .ok_or(NeuronRuntimeError::RecoveryWitnessMismatch)?;
        if latest.sequence <= max_records as u64 {
            return Self::recover(file, native, scope, max_records, config, latest, witness);
        }
        let journal = SparseJournal::open_complete(file, native.clone(), scope, max_records)?;
        Ok(Self {
            config,
            native,
            scope,
            journal,
            witness,
            pending: None,
        })
    }

    /// Recover a successor of a full segment. An intermediate segment before
    /// the witness must be sealed and is never repaired. The segment containing
    /// the witness validates its exact anchor before repairing a later tail.
    pub fn recover_next_segment(
        &mut self,
        file: File,
        max_records: usize,
    ) -> Result<(), NeuronRuntimeError> {
        Self::require_witness_config(&self.config, self.scope, &self.witness)?;
        if self.pending.is_some() {
            return Err(NeuronRuntimeError::PendingReconciliation);
        }
        if self.journal.remaining_capacity()? != 0 {
            return Err(NeuronRuntimeError::SegmentNotFull);
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
        let next = if latest.sequence <= segment_end {
            self.journal.recover_successor(file, max_records, latest)?
        } else {
            self.journal.recover_complete_successor(file, max_records)?
        };
        if latest.sequence <= segment_end {
            let recovered = next
                .current_anchor()?
                .ok_or(NeuronRuntimeError::RecoveryWitnessMismatch)?;
            if recovered != latest {
                self.witness.compare_and_swap(Some(latest), recovered)?;
            }
        }
        self.journal = next;
        Ok(())
    }

    /// Reopen an existing root whose independently enrolled witness has never
    /// acknowledged a tick. A header-only root remains at the initial frontier;
    /// a complete first tick is durably reconciled without invoking the model.
    ///
    /// This is not enrollment or an alternative to anchored recovery. The host
    /// must authenticate the existing witness identity and its empty frontier.
    /// Missing/empty files, successor segments, and already acknowledged witness
    /// history cannot use this entry point. Partial unacknowledged frame bytes
    /// may be repaired only after complete configuration/context admission.
    pub fn recover_unacknowledged(
        file: File,
        native: SparseConfig,
        scope: JournalScope,
        max_records: usize,
        config: NeuronRuntimeConfigV1,
        mut witness: W,
    ) -> Result<Self, NeuronRuntimeError> {
        config.validate_native(&native)?;
        Self::require_witness_config(&config, scope, &witness)?;
        if witness.current()?.is_some() {
            return Err(NeuronRuntimeError::RecoveryWitnessMismatch);
        }
        if file.metadata().map_err(JournalError::from)?.len() == 0 {
            return Err(NeuronRuntimeError::Journal(JournalError::Corrupt));
        }
        let journal = SparseJournal::open_existing(file, native.clone(), scope, max_records)?;
        if let Some(recovered) = journal.current_anchor()? {
            if recovered.sequence != 1 {
                return Err(NeuronRuntimeError::Witness(
                    WitnessStoreError::InvalidAnchor,
                ));
            }
            witness.compare_and_swap(None, recovered)?;
        }
        Ok(Self {
            config,
            native,
            scope,
            journal,
            witness,
            pending: None,
        })
    }
}
