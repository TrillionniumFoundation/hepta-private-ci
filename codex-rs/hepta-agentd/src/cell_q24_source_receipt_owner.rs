//! Original Observer receipts for the material-already-frozen Q24 profile.
//! Experience requires a sealed Dataset containing the real triggering A.
//! This is not an ordinary Experience -> Dataset scheduler or Root bootstrap.
//! The host transfers enrolled roles, original files and independent witnesses.
//! Dataset reads the actual Experience owner; it never issues missing evidence.

use std::fs::File;
use std::sync::Arc;

use codex_hepta_intelligence_eval::ProductEvaluationExecutionKeyV1;
use codex_hepta_intelligence_eval::ProductEvaluationExecutionStoreErrorV1;
use codex_hepta_learning_artifacts::FrozenLearningScopeV2;
use codex_hepta_learning_artifacts::LearningIterationCoordinatorV1;
use codex_hepta_learning_artifacts::LearningIterationError;
use codex_hepta_learning_artifacts::LearningIterationObservationV1;
use codex_hepta_learning_artifacts::LearningIterationReceiptV1;
use codex_hepta_learning_artifacts::LearningIterationSnapshotV1;
use codex_hepta_learning_artifacts::LearningIterationStageV1;
use codex_hepta_learning_artifacts::learning_iteration_receipt_signing_bytes_v1;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_learning_ledger::LedgerWriter;
use codex_hepta_learning_ledger::ProductionLedgerError;
use codex_hepta_learning_ledger::SignedEvidenceError;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_learning_ledger::TrustedLearningSignerV1;
use codex_hepta_neuron::AnchorWitnessStore;
use codex_hepta_types::Digest32;
use ed25519_dalek::SigningKey;

use super::OriginalCellQ24DatasetErrorV1;
use super::OriginalCellQ24DatasetV1;
use super::recovery;
use crate::AgentdIdentity;
use crate::CircuitTaskSourceReadbackV1;
use crate::learning_owner_evidence;
use crate::learning_owner_journal::LearningOriginalOwnerErrorV1;
use crate::learning_owner_journal::LearningOwnerJournalV1;

#[path = "cell_q24_source_receipt_derivation.rs"]
mod derivation;
use derivation::OriginalSource;
#[path = "cell_q24_source_receipt_signing.rs"]
mod signing;
use signing::evidence_id;
use signing::now;
use signing::sign_original;
use signing::validate_config;

#[derive(Debug, thiserror::Error)]
pub enum OriginalCellQ24SourceReceiptErrorV1 {
    #[error("original source receipt binding: {0}")]
    Binding(&'static str),
    #[error("original source receipt owner: {0}")]
    Owner(#[from] LearningOriginalOwnerErrorV1),
    #[error("original source material: {0}")]
    Source(#[from] OriginalCellQ24DatasetErrorV1),
    #[error("original source history: {0}")]
    History(#[from] recovery::OriginalCellQ24DatasetRecoveryErrorV1),
    #[error("original source ledger: {0}")]
    Ledger(#[from] ProductionLedgerError),
    #[error("original source iteration: {0}")]
    Iteration(#[from] LearningIterationError),
    #[error("original Observer evidence: {0}")]
    Evidence(#[from] SignedEvidenceError),
}
type Error = OriginalCellQ24SourceReceiptErrorV1;
type Completion = (LearningIterationReceiptV1, SignedLearningEvidenceV1);

#[derive(Clone)]
pub enum OriginalCellQ24SourcePredecessorV1 {
    /// No stage has completed. The separately sealed material already exists.
    Initial(LearningIterationSnapshotV1),
    /// Exact Experience cut and signature retained from its actual owner.
    Experience {
        snapshot: LearningIterationSnapshotV1,
        attestation: SignedLearningEvidenceV1,
    },
}
impl OriginalCellQ24SourcePredecessorV1 {
    fn snapshot(&self) -> &LearningIterationSnapshotV1 {
        match self {
            Self::Initial(snapshot) | Self::Experience { snapshot, .. } => snapshot,
        }
    }
    fn stage(&self) -> LearningIterationStageV1 {
        match self {
            Self::Initial(_) => LearningIterationStageV1::Experience,
            Self::Experience { .. } => LearningIterationStageV1::Dataset,
        }
    }
}

#[derive(Clone)]
pub struct OriginalCellQ24SourceSigningConfigV1 {
    pub predecessor: OriginalCellQ24SourcePredecessorV1,
    pub scope: FrozenLearningScopeV2,
    pub signer: TrustedLearningSignerV1,
    pub verifier: LearningEvidenceVerifierV1,
    pub maximum_signature_lifetime_seconds: u64,
}

pub struct OriginalCellQ24SourceReceiptOwnerV1<W: AnchorWitnessStore> {
    journal: LearningOwnerJournalV1<W>,
    config: OriginalCellQ24SourceSigningConfigV1,
    key: SigningKey,
    material: Arc<OriginalCellQ24DatasetV1>,
    original_material: Vec<u8>,
    saved: ProductEvaluationExecutionKeyV1,
}

impl<W: AnchorWitnessStore> OriginalCellQ24SourceReceiptOwnerV1<W> {
    pub fn create(
        file: File,
        witness: W,
        config: OriginalCellQ24SourceSigningConfigV1,
        key: SigningKey,
        material: Arc<OriginalCellQ24DatasetV1>,
    ) -> Result<Self, Error> {
        let original_material = recovery::original_material_bytes(&material)?;
        let saved = validate_config(&config, &key, &original_material)?;
        let journal = LearningOwnerJournalV1::create(file, witness, saved.binding_digest)?;
        Ok(Self {
            journal,
            config,
            key,
            material,
            original_material,
            saved,
        })
    }

    pub fn recover(
        file: File,
        witness: W,
        config: OriginalCellQ24SourceSigningConfigV1,
        key: SigningKey,
        material: Arc<OriginalCellQ24DatasetV1>,
    ) -> Result<Self, Error> {
        let original_material = recovery::original_material_bytes(&material)?;
        let saved = validate_config(&config, &key, &original_material)?;
        let journal = LearningOwnerJournalV1::recover(file, witness, saved.binding_digest)?;
        Ok(Self {
            journal,
            config,
            key,
            material,
            original_material,
            saved,
        })
    }

    pub fn attest_experience<SW: AnchorWitnessStore>(
        &mut self,
        ledger: &LedgerWriter,
        source: &CircuitTaskSourceReadbackV1<SW>,
        identity: &AgentdIdentity,
    ) -> Result<Completion, Error> {
        self.require_stage(LearningIterationStageV1::Experience)?;
        let original = derivation::read(
            &self.config,
            &self.material,
            &self.original_material,
            ledger,
            source,
            identity,
        )?;
        let retained = self.completed_or_admit()?;
        let config = &self.config;
        let material = &self.material;
        let original_material = &self.original_material;
        let key = &self.key;
        let saved = &self.saved;
        let bytes = match retained {
            Some(bytes) => bytes,
            None => self.journal.commit_once(saved, || {
                let checked = derivation::read(
                    config,
                    material,
                    original_material,
                    ledger,
                    source,
                    identity,
                )
                .map_err(|_| {
                    LearningOriginalOwnerErrorV1::Binding("Experience source after claim")
                })?;
                if checked != original {
                    return Err(LearningOriginalOwnerErrorV1::CommitUncertain);
                }
                sign_original(config, key, &original, saved.binding_digest)
            })?,
        };
        self.finish_experience(ledger, source, identity, &original, &bytes)
    }

    /// Only read the original completion: no claim, signature or time renewal.
    pub fn readback_experience<SW: AnchorWitnessStore>(
        &mut self,
        ledger: &LedgerWriter,
        source: &CircuitTaskSourceReadbackV1<SW>,
        identity: &AgentdIdentity,
    ) -> Result<Completion, Error> {
        self.require_stage(LearningIterationStageV1::Experience)?;
        let original = derivation::read(
            &self.config,
            &self.material,
            &self.original_material,
            ledger,
            source,
            identity,
        )?;
        let bytes = self.journal.read(&self.saved)?;
        self.finish_experience(ledger, source, identity, &original, &bytes)
    }

    pub fn attest_dataset<EW: AnchorWitnessStore, SW: AnchorWitnessStore>(
        &mut self,
        experience: &mut OriginalCellQ24SourceReceiptOwnerV1<EW>,
        ledger: &LedgerWriter,
        source: &CircuitTaskSourceReadbackV1<SW>,
        identity: &AgentdIdentity,
    ) -> Result<Completion, Error> {
        require_experience(
            &self.config,
            &self.original_material,
            experience,
            ledger,
            source,
            identity,
        )?;
        let original = derivation::read(
            &self.config,
            &self.material,
            &self.original_material,
            ledger,
            source,
            identity,
        )?;
        let retained = self.completed_or_admit()?;
        let config = &self.config;
        let material = &self.material;
        let original_material = &self.original_material;
        let key = &self.key;
        let saved = &self.saved;
        let bytes = match retained {
            Some(bytes) => bytes,
            None => self.journal.commit_once(saved, || {
                require_experience(
                    config,
                    original_material,
                    experience,
                    ledger,
                    source,
                    identity,
                )
                .map_err(|_| {
                    LearningOriginalOwnerErrorV1::Binding("original Experience after Dataset claim")
                })?;
                let checked = derivation::read(
                    config,
                    material,
                    original_material,
                    ledger,
                    source,
                    identity,
                )
                .map_err(|_| LearningOriginalOwnerErrorV1::Binding("Dataset source after claim"))?;
                if checked != original {
                    return Err(LearningOriginalOwnerErrorV1::CommitUncertain);
                }
                sign_original(config, key, &original, saved.binding_digest)
            })?,
        };
        let completed = self.authenticate(&original, &bytes)?;
        self.require_source(ledger, source, identity, &original)?;
        require_experience(
            &self.config,
            &self.original_material,
            experience,
            ledger,
            source,
            identity,
        )?;
        if self.journal.read(&self.saved)? != bytes {
            return Err(LearningOriginalOwnerErrorV1::CommitUncertain.into());
        }
        Ok(completed)
    }

    pub fn readback_dataset<EW: AnchorWitnessStore, SW: AnchorWitnessStore>(
        &mut self,
        experience: &mut OriginalCellQ24SourceReceiptOwnerV1<EW>,
        ledger: &LedgerWriter,
        source: &CircuitTaskSourceReadbackV1<SW>,
        identity: &AgentdIdentity,
    ) -> Result<Completion, Error> {
        require_experience(
            &self.config,
            &self.original_material,
            experience,
            ledger,
            source,
            identity,
        )?;
        let original = derivation::read(
            &self.config,
            &self.material,
            &self.original_material,
            ledger,
            source,
            identity,
        )?;
        let bytes = self.journal.read(&self.saved)?;
        let completed = self.authenticate(&original, &bytes)?;
        self.require_source(ledger, source, identity, &original)?;
        require_experience(
            &self.config,
            &self.original_material,
            experience,
            ledger,
            source,
            identity,
        )?;
        if self.journal.read(&self.saved)? != bytes {
            return Err(LearningOriginalOwnerErrorV1::CommitUncertain.into());
        }
        Ok(completed)
    }

    fn finish_experience<SW: AnchorWitnessStore>(
        &mut self,
        ledger: &LedgerWriter,
        source: &CircuitTaskSourceReadbackV1<SW>,
        identity: &AgentdIdentity,
        original: &OriginalSource,
        bytes: &[u8],
    ) -> Result<Completion, Error> {
        let completed = self.authenticate(original, bytes)?;
        self.require_source(ledger, source, identity, original)?;
        if self.journal.read(&self.saved)? != bytes {
            return Err(LearningOriginalOwnerErrorV1::CommitUncertain.into());
        }
        Ok(completed)
    }

    fn require_source<SW: AnchorWitnessStore>(
        &self,
        ledger: &LedgerWriter,
        source: &CircuitTaskSourceReadbackV1<SW>,
        identity: &AgentdIdentity,
        original: &OriginalSource,
    ) -> Result<(), Error> {
        if derivation::read(
            &self.config,
            &self.material,
            &self.original_material,
            ledger,
            source,
            identity,
        )? != *original
        {
            return Err(LearningOriginalOwnerErrorV1::CommitUncertain.into());
        }
        Ok(())
    }

    fn completed_or_admit(&mut self) -> Result<Option<Vec<u8>>, Error> {
        match self.journal.read(&self.saved) {
            Ok(bytes) => Ok(Some(bytes)),
            Err(LearningOriginalOwnerErrorV1::Store(
                ProductEvaluationExecutionStoreErrorV1::Missing,
            )) => {
                let at = now()?;
                if at
                    >= self
                        .config
                        .predecessor
                        .snapshot()
                        .request
                        .envelope
                        .expiry_unix_seconds
                {
                    return Err(Error::Binding("new Observer receipt deadline"));
                }
                self.config.verifier.require_signer_binding(
                    LearningEvidenceRoleV1::Observer,
                    &self.config.signer,
                    at,
                )?;
                Ok(None)
            }
            Err(error) => Err(error.into()),
        }
    }

    fn require_stage(&self, stage: LearningIterationStageV1) -> Result<(), Error> {
        if self.config.predecessor.stage() != stage {
            return Err(Error::Binding("original receipt stage"));
        }
        Ok(())
    }

    fn authenticate(&self, original: &OriginalSource, bytes: &[u8]) -> Result<Completion, Error> {
        let (payload, signed) = learning_owner_evidence::decode(bytes)?;
        let receipt = derivation::receipt(&self.config, original, signed.issued_at)?;
        if payload != learning_iteration_receipt_signing_bytes_v1(&receipt)? {
            return Err(Error::Binding("complete original Observer payload"));
        }
        let verified = self.config.verifier.verify(
            LearningEvidenceRoleV1::Observer,
            &signed,
            &payload,
            now()?,
        )?;
        if verified.principal() != &self.config.signer.principal
            || verified.controller_id() != &self.config.signer.controller_id
            || signed.evidence_id != evidence_id(self.saved.binding_digest)?
        {
            return Err(Error::Binding("original Observer identity"));
        }
        Ok((receipt, signed))
    }
}

fn require_experience<EW: AnchorWitnessStore, SW: AnchorWitnessStore>(
    config: &OriginalCellQ24SourceSigningConfigV1,
    original_material: &[u8],
    experience: &mut OriginalCellQ24SourceReceiptOwnerV1<EW>,
    ledger: &LedgerWriter,
    source: &CircuitTaskSourceReadbackV1<SW>,
    identity: &AgentdIdentity,
) -> Result<(), Error> {
    let OriginalCellQ24SourcePredecessorV1::Experience {
        snapshot,
        attestation,
    } = &config.predecessor
    else {
        return Err(Error::Binding("Dataset requires original Experience owner"));
    };
    let initial =
        LearningIterationCoordinatorV1::new(snapshot.request.clone(), snapshot.owners.clone())?;
    experience.require_stage(LearningIterationStageV1::Experience)?;
    if experience.config.predecessor.snapshot() != initial.snapshot()
        || experience.config.scope != config.scope
        || experience.original_material != original_material
    {
        return Err(Error::Binding("original Experience request/scope/material"));
    }
    let (receipt, original_signature) = OriginalCellQ24SourceReceiptOwnerV1::readback_experience(
        experience, ledger, source, identity,
    )?;
    if snapshot.receipts.as_slice() != std::slice::from_ref(&receipt)
        || &original_signature != attestation
    {
        return Err(Error::Binding("complete original Experience predecessor"));
    }
    Ok(())
}
