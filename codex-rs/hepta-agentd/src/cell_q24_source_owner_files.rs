//! Consume both original Observer resources at the production assembly boundary.
//! Files, witnesses and enrolled keys come from their existing host custodians.

use codex_hepta_neuron::FileAnchorWitnessStore;

use super::*;

pub struct OriginalCellQ24SourceJournalV1 {
    pub journal: File,
    pub witness: FileAnchorWitnessStore,
    pub signer: TrustedLearningSignerV1,
    pub key: SigningKey,
    pub maximum_signature_lifetime_seconds: u64,
}

pub struct OriginalCellQ24SourceFilesV1 {
    pub experience: OriginalCellQ24SourceJournalV1,
    pub dataset: OriginalCellQ24SourceJournalV1,
}

type Source = OriginalCellQ24SourceReceiptOwnerV1<FileAnchorWitnessStore>;

#[derive(Clone, Copy)]
enum Mode {
    Create,
    Recover,
}

impl OriginalCellQ24SourceFilesV1 {
    /// Both signers are validated against the original source before the first
    /// journal mutation. A later I/O failure remains an explicit owner error.
    pub fn create(
        self,
        prepared: Arc<CellQ24PreparedLearningV1>,
        verifier: LearningEvidenceVerifierV1,
    ) -> Result<(Source, Source), Error> {
        self.open(prepared, verifier, Mode::Create)
    }

    /// Recovery consumes the retained files and witnesses. It never creates a
    /// missing owner, changes a role or extends an original signature window.
    pub fn recover(
        self,
        prepared: Arc<CellQ24PreparedLearningV1>,
        verifier: LearningEvidenceVerifierV1,
    ) -> Result<(Source, Source), Error> {
        self.open(prepared, verifier, Mode::Recover)
    }

    fn open(
        self,
        prepared: Arc<CellQ24PreparedLearningV1>,
        verifier: LearningEvidenceVerifierV1,
        mode: Mode,
    ) -> Result<(Source, Source), Error> {
        let experience = self
            .experience
            .config(OriginalCellQ24SourceStageV1::Experience, verifier.clone());
        let dataset = self
            .dataset
            .config(OriginalCellQ24SourceStageV1::Dataset, verifier);
        validate_config(&prepared, &experience, &self.experience.key)?;
        validate_config(&prepared, &dataset, &self.dataset.key)?;
        let experience = self
            .experience
            .open(Arc::clone(&prepared), experience, mode)?;
        let dataset = self.dataset.open(Arc::clone(&prepared), dataset, mode)?;
        prepared.revalidate_source()?;
        Ok((experience, dataset))
    }
}

impl OriginalCellQ24SourceJournalV1 {
    fn config(
        &self,
        stage: OriginalCellQ24SourceStageV1,
        verifier: LearningEvidenceVerifierV1,
    ) -> OriginalCellQ24SourceSigningConfigV1 {
        OriginalCellQ24SourceSigningConfigV1 {
            stage,
            signer: self.signer.clone(),
            verifier,
            maximum_signature_lifetime_seconds: self.maximum_signature_lifetime_seconds,
        }
    }

    fn open(
        self,
        prepared: Arc<CellQ24PreparedLearningV1>,
        config: OriginalCellQ24SourceSigningConfigV1,
        mode: Mode,
    ) -> Result<Source, Error> {
        match mode {
            Mode::Create => OriginalCellQ24SourceReceiptOwnerV1::create(
                self.journal,
                self.witness,
                prepared,
                config,
                self.key,
            ),
            Mode::Recover => OriginalCellQ24SourceReceiptOwnerV1::recover(
                self.journal,
                self.witness,
                prepared,
                config,
                self.key,
            ),
        }
    }
}
