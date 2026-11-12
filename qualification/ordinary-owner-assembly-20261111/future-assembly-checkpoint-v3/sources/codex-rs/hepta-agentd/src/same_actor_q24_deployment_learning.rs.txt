//! Concrete fresh causal-ledger custody for the ordinary phase.
//! Root-approved signed trust is activated once. No existing history is
//! reopened under an empty trust predecessor or substituted with a new ledger.

use std::sync::Arc;
use std::sync::Mutex;

use codex_hepta_learning_ledger::DurableLedger;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_learning_ledger::LedgerWitnessStore;
use codex_hepta_learning_ledger::LedgerWriter;
use codex_hepta_learning_ledger::TrustedLearningSignerV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use serde::Deserialize;
use serde::Serialize;

use crate::AgentdError;
use crate::CircuitQ24TaskOpenModeV1;
use crate::OriginalCellQ24TaskDatasetFreezeInputsV1;
use crate::OriginalCellQ24DatasetFreezeSigningConfigV1;
use crate::OriginalCellQ24TaskLedgerConfigV1;
use crate::OriginalCellQ24TaskLedgerInputsV1;

use super::deployment_error;
use super::deployment_refused;
use super::files::MutableFileData;
use super::files::OriginalDeploymentFiles;
use super::files::PinnedFileData;
use super::learning_data::LearningAuthorityData;
use super::witness::OriginalWitnessData;
use super::witness::require_fresh_original_file;

#[path = "same_actor_q24_deployment_learning_owners.rs"]
mod owners;
pub(super) use owners::OriginalLearningOwnersData;

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct OriginalSignedOwnerFilesData {
    pub journal: MutableFileData,
    pub witness: OriginalWitnessData,
    pub principal: String,
    pub key: PinnedFileData,
    pub maximum_signature_lifetime_seconds: u64,
}

impl OriginalSignedOwnerFilesData {
    fn require_fresh(&self) -> Result<(), AgentdError> {
        require_fresh_original_file(&self.journal)?;
        require_fresh_original_file(&self.witness.file)?;
        Ok(())
    }
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct OriginalTaskLedgerData {
    pub signatures: OriginalSignedOwnerFilesData,
    pub observer: String,
    pub episode_id: String,
    pub candidate_set_id: String,
    pub generator_code_digest: [u8; 32],
    pub grammar_digest: [u8; 32],
    pub hard_filter_digest: [u8; 32],
    pub truncation_digest: [u8; 32],
    pub outcome_record_id: String,
    pub outcome_id: String,
    pub unit_profile_digest: [u8; 32],
    pub expected_delay_profile_digest: [u8; 32],
    pub claim_deadline_unix_seconds: u64,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct OriginalLearningMaterialsData {
    pub authority: LearningAuthorityData,
    pub ledger: MutableFileData,
    pub witness: MutableFileData,
    pub ledger_binding: [u8; 32],
    pub maximum_records: usize,
    pub original_a: OriginalTaskLedgerData,
    pub original_c: OriginalTaskLedgerData,
    pub freeze: OriginalSignedOwnerFilesData,
    pub owners: OriginalLearningOwnersData,
}

/// The verifier and all named principals are taken from the single activated
/// original distribution that owns this same real LedgerWriter.
pub(super) struct OriginalDeploymentLearning {
    ledger: Arc<Mutex<LedgerWriter>>,
    verifier: LearningEvidenceVerifierV1,
    signers: Vec<TrustedLearningSignerV1>,
    data: OriginalLearningMaterialsData,
}

impl OriginalDeploymentLearning {
    pub(super) fn open_original(
        data: OriginalLearningMaterialsData,
        files: &mut OriginalDeploymentFiles,
        now: u64,
    ) -> Result<(Self, OriginalCellQ24TaskLedgerInputsV1), AgentdError> {
        require_fresh_original_file(&data.ledger)?;
        require_fresh_original_file(&data.witness)?;
        data.original_a.signatures.require_fresh()?;
        data.original_c.signatures.require_fresh()?;
        data.freeze.require_fresh()?;
        data.owners.require_fresh()?;
        files.require_original_context()?;
        let authority = data.authority.activate_original(now)?;
        // These checks resolve real enrolled principals, not role labels
        // asserted by a caller. Every later signing owner validates them again.
        authority.original_signer(
            &data.original_a.signatures.principal, LearningEvidenceRoleV1::Generator,
        )?;
        authority.original_signer(
            &data.original_a.observer, LearningEvidenceRoleV1::Observer,
        )?;
        let (activated, signers) = authority.into_original_parts();
        let verifier = activated.verifier().clone();
        let binding = Digest32::from_array(data.ledger_binding);
        let (ledger_file, ledger_directory) =
            files.open_original_owner_with_directory(&data.ledger)?;
        let (witness_file, witness_directory) =
            files.open_original_owner_with_directory(&data.witness)?;
        files.require_original_context()?;
        let ledger = DurableLedger::create(ledger_file, binding, data.maximum_records)
            .map_err(deployment_error)?;
        files.require_original_context()?;
        let witness = LedgerWitnessStore::create(witness_file, binding)
            .map_err(deployment_error)?;
        files.require_original_context()?;
        let ledger = LedgerWriter::from_durable(
            ledger, witness, activated, &ledger_directory, &witness_directory,
        )
        .map_err(deployment_error)?;
        files.require_original_context()?;
        let original = Self {
            ledger: Arc::new(Mutex::new(ledger)), verifier, signers, data,
        };
        let inputs = original.open_original_task(&original.data.original_a, files, now)?;
        Ok((original, inputs))
    }

    pub(super) fn original_a_claim_deadline(&self) -> u64 {
        self.data.original_a.claim_deadline_unix_seconds
    }

    pub(super) fn original_c_claim_deadline(&self) -> u64 {
        self.data.original_c.claim_deadline_unix_seconds
    }

    pub(super) fn verifier(&self) -> &LearningEvidenceVerifierV1 {
        &self.verifier
    }

    pub(super) fn require_original_signer(
        &self,
        principal: &str,
        role: LearningEvidenceRoleV1,
        now: u64,
    ) -> Result<TrustedLearningSignerV1, AgentdError> {
        let id = StableId::new(principal).map_err(deployment_error)?;
        let signer = self.signers.iter()
            .find(|signer| signer.principal.principal_id == id && signer.roles.contains(&role))
            .cloned()
            .ok_or_else(|| deployment_refused("actual enrolled Learning signer is absent"))?;
        self.verifier.require_signer_binding(role, &signer, now)
            .map_err(deployment_error)?;
        Ok(signer)
    }

    pub(super) fn open_original_freeze(
        &self,
        files: &mut OriginalDeploymentFiles,
        now: u64,
    ) -> Result<OriginalCellQ24TaskDatasetFreezeInputsV1, AgentdError> {
        let data = &self.data.freeze;
        data.require_fresh()?;
        let signer = self.require_original_signer(
            &data.principal, LearningEvidenceRoleV1::Evaluator, now,
        )?;
        let key = files.read_original_signing_key(&data.key)?;
        require_original_key(&signer, &key)?;
        let journal = files.open_original_owner(&data.journal)?;
        let witness = data.witness.open_original(files)?;
        files.require_original_context()?;
        Ok(OriginalCellQ24TaskDatasetFreezeInputsV1 {
            journal, witness, open_mode: CircuitQ24TaskOpenModeV1::Create,
            signing: OriginalCellQ24DatasetFreezeSigningConfigV1 {
                signer, verifier: self.verifier.clone(),
                maximum_signature_lifetime_seconds: data.maximum_signature_lifetime_seconds,
            },
            evaluator_key: key,
        })
    }

    pub(super) fn open_original_c_task(
        &self,
        files: &mut OriginalDeploymentFiles,
        now: u64,
    ) -> Result<OriginalCellQ24TaskLedgerInputsV1, AgentdError> {
        self.open_original_task(&self.data.original_c, files, now)
    }

    fn open_original_task(
        &self,
        data: &OriginalTaskLedgerData,
        files: &mut OriginalDeploymentFiles,
        now: u64,
    ) -> Result<OriginalCellQ24TaskLedgerInputsV1, AgentdError> {
        data.signatures.require_fresh()?;
        let generator = self.require_original_signer(
            &data.signatures.principal, LearningEvidenceRoleV1::Generator, now,
        )?;
        let observer = self.require_original_signer(
            &data.observer, LearningEvidenceRoleV1::Observer, now,
        )?;
        let key = files.read_original_signing_key(&data.signatures.key)?;
        require_original_key(&generator, &key)?;
        let config = OriginalCellQ24TaskLedgerConfigV1 {
            episode_id: StableId::new(&data.episode_id).map_err(deployment_error)?,
            candidate_set_id: StableId::new(&data.candidate_set_id).map_err(deployment_error)?,
            generator_code_digest: Digest32::from_array(data.generator_code_digest),
            grammar_digest: Digest32::from_array(data.grammar_digest),
            hard_filter_digest: Digest32::from_array(data.hard_filter_digest),
            truncation_digest: Digest32::from_array(data.truncation_digest),
            generator,
            observer,
            outcome_record_id: StableId::new(&data.outcome_record_id).map_err(deployment_error)?,
            outcome_id: StableId::new(&data.outcome_id).map_err(deployment_error)?,
            unit_profile_digest: Digest32::from_array(data.unit_profile_digest),
            expected_delay_profile_digest: Digest32::from_array(data.expected_delay_profile_digest),
            claim_deadline_unix_seconds: data.claim_deadline_unix_seconds,
            maximum_signature_lifetime_seconds:
                data.signatures.maximum_signature_lifetime_seconds,
        };
        let signature_journal = files.open_original_owner(&data.signatures.journal)?;
        let signature_witness = data.signatures.witness.open_original(files)?;
        files.require_original_context()?;
        Ok(OriginalCellQ24TaskLedgerInputsV1 {
            ledger: Arc::clone(&self.ledger), signature_journal, signature_witness,
            open_mode: CircuitQ24TaskOpenModeV1::Create, config, generator_key: key,
        })
    }
}

fn require_original_key(
    signer: &TrustedLearningSignerV1,
    key: &ed25519_dalek::SigningKey,
) -> Result<(), AgentdError> {
    if signer.verifying_key != key.verifying_key().to_bytes() {
        return Err(deployment_refused("supplied key differs from the actual enrolled signer"));
    }
    Ok(())
}
