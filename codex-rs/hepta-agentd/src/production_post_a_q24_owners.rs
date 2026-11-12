//! Original non-Root signing resources. All paths must already exist, match
//! the same descriptor tracker and contain the explicitly selected lifecycle.

use std::io::Read;
use std::io::Seek;
use std::path::PathBuf;

use codex_hepta_learning_ledger::TrustedLearningSignerV1;
use codex_hepta_neuron::AnchorWitnessStore;
use codex_hepta_neuron::FileAnchorWitnessStore;
use codex_hepta_neuron::JournalScope;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use ed25519_dalek::SigningKey;
use serde::Deserialize;

use super::*;
use crate::root_historical_task_read_client::OriginalHistoricalStageAuthoritiesV1;

#[derive(Clone, Copy, Deserialize)]
#[serde(rename_all = "snake_case")]
pub(super) enum OpenMode {
    Create,
    Recover,
}

impl OpenMode {
    fn original(self) -> crate::OriginalCellQ24LearningOpenV1 {
        match self {
            Self::Create => crate::OriginalCellQ24LearningOpenV1::Create,
            Self::Recover => crate::OriginalCellQ24LearningOpenV1::Recover,
        }
    }
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct JournalData {
    journal: PathBuf,
    witness: PathBuf,
    scope: [u8; 32],
    generation: u64,
    max_records: usize,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct SigningFilesData {
    owner: JournalData,
    key: PathBuf,
    pub(super) signature_lifetime_seconds: u64,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct StageFilesData {
    mode: OpenMode,
    experience: SigningFilesData,
    dataset: SigningFilesData,
    training: JournalData,
    training_receipt: SigningFilesData,
    local: SigningFilesData,
    local_policy: LocalPolicy,
}

#[derive(Deserialize)]
#[serde(rename_all = "snake_case")]
enum LocalPolicy {
    AdoptQualified,
    RetainCurrent,
    DeferQualified,
}

struct OriginalJournal {
    journal: File,
    witness: File,
    scope: JournalScope,
    generation: Generation,
    max_records: usize,
    mode: OpenMode,
}

impl JournalData {
    fn open(
        &self,
        files: &mut OriginalFiles,
        objective: Digest32,
        mode: OpenMode,
    ) -> Result<OriginalJournal, AgentdError> {
        let scope_digest = Digest32::from_array(self.scope);
        if scope_digest.is_zero() || objective.is_zero() || !(3..=4096).contains(&self.max_records)
        {
            return Err(refused("original owner witness binding or bound"));
        }
        let generation = Generation::new(self.generation).map_err(refused)?;
        let journal = files.write(&self.journal)?;
        let witness = files.write(&self.witness)?;
        for file in [&journal, &witness] {
            let empty = file.metadata()?.len() == 0;
            if empty != matches!(mode, OpenMode::Create) {
                return Err(refused("explicit original owner lifecycle differs"));
            }
        }
        Ok(OriginalJournal {
            journal,
            witness,
            scope: JournalScope {
                scope_digest,
                objective_digest: objective,
            },
            generation,
            max_records: self.max_records,
            mode,
        })
    }
}

impl OriginalJournal {
    fn open_witness(self) -> Result<(File, FileAnchorWitnessStore), AgentdError> {
        let witness = FileAnchorWitnessStore::open(
            self.witness,
            self.scope,
            self.generation,
            self.max_records,
        )
        .map_err(refused)?;
        let anchor = witness.current().map_err(refused)?;
        if matches!(self.mode, OpenMode::Create) && anchor.is_some() {
            return Err(refused("new owner witness already has a retained anchor"));
        }
        Ok((self.journal, witness))
    }
}

impl SigningFilesData {
    fn open_original(
        &self,
        files: &mut OriginalFiles,
        signer: &TrustedLearningSignerV1,
        objective: Digest32,
        mode: OpenMode,
    ) -> Result<(OriginalJournal, SigningKey), AgentdError> {
        if !(1..=86_400).contains(&self.signature_lifetime_seconds) {
            return Err(refused("original signature lifetime exceeds bound"));
        }
        let mut file = files.read(&self.key)?;
        if file.metadata()?.len() != 32 {
            return Err(refused("original 32-byte signing key required"));
        }
        let mut before = [0_u8; 32];
        file.read_exact(&mut before)?;
        file.rewind()?;
        let mut after = [0_u8; 32];
        file.read_exact(&mut after)?;
        let key = SigningKey::from_bytes(&before);
        if before != after
            || file.metadata()?.len() != 32
            || key.verifying_key().to_bytes() != signer.verifying_key
        {
            return Err(refused("original key differs from Root-selected signer"));
        }
        Ok((self.owner.open(files, objective, mode)?, key))
    }

    pub(super) fn freeze_original(
        &self,
        phase: crate::CellQ24DatasetFreezePreparationV1,
        files: &mut OriginalFiles,
        mode: OpenMode,
    ) -> Result<crate::CellQ24PreparedLearningV1, AgentdError> {
        let config = phase
            .original_historical_freeze_config(self.signature_lifetime_seconds)
            .map_err(refused)?;
        let (journal, key) = self.open_original(
            files,
            &config.signer,
            config.verifier.objective_digest(),
            mode,
        )?;
        let (journal, witness) = journal.open_witness()?;
        let mut owner = match mode {
            OpenMode::Create => crate::OriginalCellQ24DatasetFreezeOwnerV1::create(
                journal, witness, &phase, config, key,
            ),
            OpenMode::Recover => crate::OriginalCellQ24DatasetFreezeOwnerV1::recover(
                journal, witness, &phase, config, key,
            ),
        }
        .map_err(refused)?;
        let prepared = phase
            .authorize_and_materialize(&mut owner)
            .map_err(refused)?;
        // No Arc or duplicate descriptor is retained here. Root still takes
        // actual independent shared locks, so an external writer cannot pass.
        drop(owner);
        Ok(prepared)
    }
}

impl StageFilesData {
    pub(super) fn into_original_inputs(
        self,
        prepared: Arc<crate::CellQ24PreparedLearningV1>,
        authorities: OriginalHistoricalStageAuthoritiesV1,
        files: &mut OriginalFiles,
        queue_capacity: usize,
    ) -> Result<crate::OriginalCellQ24LearningInputsV1, AgentdError> {
        prepared.revalidate_source().map_err(refused)?;
        let objective = authorities.verifier.objective_digest();
        // Validate every key, file lifecycle and physical alias before any
        // witness is initialized. Missing resources never select Create.
        let (experience, experience_key) =
            self.experience
                .open_original(files, &authorities.experience, objective, self.mode)?;
        let (dataset, dataset_key) =
            self.dataset
                .open_original(files, &authorities.dataset, objective, self.mode)?;
        let training = self.training.open(files, objective, self.mode)?;
        let (receipts, receipt_key) = self.training_receipt.open_original(
            files,
            &authorities.trainer,
            objective,
            self.mode,
        )?;
        let (local, local_key) =
            self.local
                .open_original(files, &authorities.selector, objective, self.mode)?;
        prepared.revalidate_source().map_err(refused)?;
        let (experience, experience_witness) = experience.open_witness()?;
        let (dataset, dataset_witness) = dataset.open_witness()?;
        let (training, training_witness) = training.open_witness()?;
        let (receipts, receipt_witness) = receipts.open_witness()?;
        let (local, local_witness) = local.open_witness()?;
        prepared.revalidate_source().map_err(refused)?;
        Ok(crate::OriginalCellQ24LearningInputsV1 {
            prepared,
            sources: crate::OriginalCellQ24SourceInputsV1::Files(
                crate::OriginalCellQ24SourceFilesV1 {
                    experience: crate::OriginalCellQ24SourceJournalV1 {
                        journal: experience,
                        witness: experience_witness,
                        signer: authorities.experience,
                        key: experience_key,
                        maximum_signature_lifetime_seconds: self
                            .experience
                            .signature_lifetime_seconds,
                    },
                    dataset: crate::OriginalCellQ24SourceJournalV1 {
                        journal: dataset,
                        witness: dataset_witness,
                        signer: authorities.dataset,
                        key: dataset_key,
                        maximum_signature_lifetime_seconds: self.dataset.signature_lifetime_seconds,
                    },
                },
            ),
            training: crate::OriginalCellQ24TrainingInputsV1::Files(
                crate::OriginalCellQ24TrainingFilesV1 {
                    training,
                    training_witness,
                    receipts,
                    receipt_witness,
                    signer: authorities.trainer,
                    key: receipt_key,
                    verifier: authorities.verifier.clone(),
                    maximum_signature_lifetime_seconds: self
                        .training_receipt
                        .signature_lifetime_seconds,
                },
            ),
            local: crate::OriginalCellQ24LocalDecisionFilesV1 {
                journal: local,
                witness: local_witness,
                signer: authorities.selector,
                key: local_key,
                policy: match self.local_policy {
                    LocalPolicy::AdoptQualified => crate::CellQ24LocalPolicyV1::AdoptQualified,
                    LocalPolicy::RetainCurrent => crate::CellQ24LocalPolicyV1::RetainCurrent,
                    LocalPolicy::DeferQualified => crate::CellQ24LocalPolicyV1::DeferQualified,
                },
                maximum_signature_lifetime_seconds: self.local.signature_lifetime_seconds,
                mode: self.mode.original(),
            },
            verifier: authorities.verifier,
            mode: self.mode.original(),
            queue_capacity,
        })
    }
}

#[cfg(test)]
#[path = "production_post_a_q24_owners_tests.rs"]
mod tests;
