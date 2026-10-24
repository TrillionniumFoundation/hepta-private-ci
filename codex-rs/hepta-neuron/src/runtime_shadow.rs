//! Shadow admission shares the canonical journal/witness transaction.

use super::*;

impl<W: AnchorWitnessStore> NeuronRuntime<W> {
    pub fn bootstrap_shadow(
        file: File,
        native: SparseConfig,
        scope: JournalScope,
        max_records: usize,
        config: NeuronShadowConfigV1,
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
        Ok(Self { config, calibrated: None, journal, witness, pending: None })
    }

    /// Recovery requires an independently retained exact anchor; the caller
    /// must also bind the profile/source namespace durably before supplying it.
    pub fn recover_shadow(
        file: File,
        native: SparseConfig,
        scope: JournalScope,
        max_records: usize,
        config: NeuronShadowConfigV1,
        anchor: JournalAnchor,
        mut witness: W,
    ) -> Result<Self, NeuronRuntimeError> {
        config.validate_native(&native)?;
        if witness.current()? != Some(anchor) {
            return Err(NeuronRuntimeError::RecoveryWitnessMismatch);
        }
        let journal = SparseJournal::open_anchored(file, native, scope, max_records, anchor)?;
        let recovered = journal.current()?.map(|checkpoint| JournalAnchor {
            sequence: checkpoint.sequence(), checkpoint_digest: checkpoint.digest(),
        }).ok_or(NeuronRuntimeError::RecoveryWitnessMismatch)?;
        if recovered.sequence < anchor.sequence {
            return Err(NeuronRuntimeError::RecoveryWitnessMismatch);
        }
        if recovered != anchor { witness.compare_and_swap(Some(anchor), recovered)?; }
        Ok(Self { config, calibrated: None, journal, witness, pending: None })
    }

    pub fn tick(
        &mut self,
        model: &mut impl NeuronModelPort,
        input: NeuronTickInputV1,
    ) -> Result<NeuronRuntimeOutputV1, NeuronRuntimeError> {
        if self.calibrated.is_none() { return Err(NeuronRuntimeError::InvalidCalibration); }
        match self.tick_profile(model, input)? {
            ProfileOutput::Calibrated(output) => Ok(output),
            ProfileOutput::Shadow(_) => Err(NeuronRuntimeError::InvalidCalibration),
        }
    }

    /// Execute and persist an uncalibrated observation without producing a
    /// canonical signal receipt. The output always abstains and denies effects.
    pub fn tick_shadow(
        &mut self,
        model: &mut impl NeuronModelPort,
        input: NeuronTickInputV1,
    ) -> Result<NeuronShadowOutputV1, NeuronRuntimeError> {
        if self.calibrated.is_some() { return Err(NeuronRuntimeError::InvalidConfig); }
        match self.tick_profile(model, input)? {
            ProfileOutput::Shadow(output) => Ok(output),
            ProfileOutput::Calibrated(_) => Err(NeuronRuntimeError::InvalidConfig),
        }
    }

    pub fn shadow_profile(&self) -> Result<&NeuronShadowConfigV1, NeuronRuntimeError> {
        if self.calibrated.is_some() { return Err(NeuronRuntimeError::InvalidConfig); }
        Ok(&self.config)
    }
}
