//! Concrete original Observer custody for Experience and Dataset.
//! Both enrolled keys, already authorized files and independent witnesses come
//! from the host. Observations are reconstructed from the original TaskSource,
//! Ledger and the same signed freeze. There is no arbitrary signing API.

use std::fs::File;
#[cfg(target_os = "linux")]
use std::sync::Arc;

use codex_hepta_intelligence_eval::ProductEvaluationExecutionKeyV1;
use codex_hepta_intelligence_eval::ProductEvaluationExecutionStoreErrorV1;
use codex_hepta_learning_artifacts::FrozenLearningScopeV2;
use codex_hepta_learning_artifacts::LearningIterationCoordinatorV1;
use codex_hepta_learning_artifacts::LearningIterationError;
use codex_hepta_learning_artifacts::LearningIterationReceiptV1;
use codex_hepta_learning_artifacts::LearningIterationSnapshotV1;
use codex_hepta_learning_artifacts::LearningIterationStageV1;
use codex_hepta_learning_artifacts::learning_iteration_receipt_signing_bytes_v1;
use codex_hepta_learning_ledger::DatasetFreezePlanV2;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_learning_ledger::LedgerWriter;
use codex_hepta_learning_ledger::SignedEvidenceError;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_learning_ledger::TrustedLearningSignerV1;
use codex_hepta_neuron::AnchorWitnessStore;
use codex_hepta_types::Digest32;
use ed25519_dalek::SigningKey;

use crate::AgentdIdentity;
use crate::CellQ24DatasetErrorV1;
use crate::CellQ24DatasetReaderV1;
use crate::CellQ24DatasetRuleV1;
use crate::CircuitTaskSourceReadbackV1;
use crate::LoadedCellQ24ModelV1;
use crate::OriginalCellQ24DatasetV1;
#[cfg(target_os = "linux")]
use crate::OriginalCircuitOnPolicyPanelPolicyV2;
use crate::learning_owner_evidence;
use crate::learning_owner_journal::LearningOriginalOwnerErrorV1;
use crate::learning_owner_journal::LearningOwnerJournalV1;

#[path = "cell_q24_material_receipt_binding.rs"]
mod binding;
#[cfg(target_os = "linux")]
#[path = "cell_q24_material_pair_readback.rs"]
mod paired_readback;

#[derive(Debug, thiserror::Error)]
pub enum OriginalCellQ24MaterialReceiptErrorV1 {
    #[error("original material receipt owner: {0}")]
    Owner(#[from] LearningOriginalOwnerErrorV1),
    #[error("original source material: {0}")]
    Material(#[from] CellQ24DatasetErrorV1),
    #[error("original material iteration: {0}")]
    Iteration(#[from] LearningIterationError),
    #[error("original Observer evidence: {0}")]
    Evidence(#[from] SignedEvidenceError),
}

type Error = OriginalCellQ24MaterialReceiptErrorV1;

/// Exact original operation and freeze, supplied before either Observer claim.
/// These are two explicit enrolled roles; their actors and keys may differ.
/// The scope is received from its original owner, never registered here.
#[derive(Clone)]
pub struct OriginalCellQ24MaterialReceiptConfigV1 {
    pub initial: LearningIterationSnapshotV1,
    pub scope: FrozenLearningScopeV2,
    pub rule: CellQ24DatasetRuleV1,
    pub freeze_plan: DatasetFreezePlanV2,
    pub freeze_evidence: SignedLearningEvidenceV1,
    pub experience_signer: TrustedLearningSignerV1,
    pub dataset_signer: TrustedLearningSignerV1,
    pub verifier: LearningEvidenceVerifierV1,
    pub maximum_signature_lifetime_seconds: u64,
}

/// Explicit immutable panel metadata for the original Material operation.
/// This declaration does not supply custody or authorize either Observer claim.
#[cfg(target_os = "linux")]
#[derive(Clone)]
pub struct OriginalCellQ24MaterialReceiptConfigV2 {
    original: OriginalCellQ24MaterialReceiptConfigV1,
    panel: Arc<OriginalCircuitOnPolicyPanelPolicyV2>,
}

#[cfg(target_os = "linux")]
impl OriginalCellQ24MaterialReceiptConfigV2 {
    pub fn from_original(
        original: OriginalCellQ24MaterialReceiptConfigV1,
        panel: Arc<OriginalCircuitOnPolicyPanelPolicyV2>,
    ) -> Result<Self, Error> {
        binding::require_panel_initial(&original, Some(panel.as_ref()))?;
        Ok(Self { original, panel })
    }
}

/// Original descriptors, not paths or authority to create/enroll replacements.
/// Creation is not atomic: Experience may initialize before Dataset fails.
/// Retain both original files and witnesses for the host to reconcile that
/// partial state. This API does not finish partial initialization. recover
/// requires both original owners already initialized; it never creates a
/// missing Dataset journal/witness or substitutes new custody.
pub struct OriginalCellQ24MaterialReceiptFilesV1<EW: AnchorWitnessStore, DW: AnchorWitnessStore> {
    pub experience: File,
    pub experience_witness: EW,
    pub dataset: File,
    pub dataset_witness: DW,
}

/// The original mutable ledger is borrowed exclusively throughout each call.
/// A cached batch, caller-provided label or receipt cannot replace these owners.
pub struct OriginalCellQ24MaterialReceiptSourcesV1<'a, SW: AnchorWitnessStore> {
    pub snapshot: &'a LearningIterationSnapshotV1,
    pub source: &'a CircuitTaskSourceReadbackV1<SW>,
    pub identity: &'a AgentdIdentity,
    pub ledger: &'a mut LedgerWriter,
    pub baseline: &'a LoadedCellQ24ModelV1,
}

/// A new current read and the exact original Observer receipt. The material is
/// not a retained authorization lease; Training must re-read through this owner.
pub struct OriginalCellQ24MaterialCompletionV1 {
    pub receipt: LearningIterationReceiptV1,
    pub attestation: SignedLearningEvidenceV1,
    pub material: OriginalCellQ24DatasetV1,
}

#[cfg(target_os = "linux")]
enum OriginalMaterialCommandOriginV1 {
    FreshCreate,
    Recovered,
}

pub struct OriginalCellQ24MaterialReceiptOwnersV1<EW: AnchorWitnessStore, DW: AnchorWitnessStore> {
    experience: LearningOwnerJournalV1<EW>,
    dataset: LearningOwnerJournalV1<DW>,
    config: OriginalCellQ24MaterialReceiptConfigV1,
    #[cfg(target_os = "linux")]
    panel: Option<Arc<OriginalCircuitOnPolicyPanelPolicyV2>>,
    experience_key: SigningKey,
    dataset_key: SigningKey,
    experience_saved: ProductEvaluationExecutionKeyV1,
    dataset_binding: Digest32,
    #[cfg(target_os = "linux")]
    command_origin: OriginalMaterialCommandOriginV1,
}

impl<EW: AnchorWitnessStore, DW: AnchorWitnessStore>
    OriginalCellQ24MaterialReceiptOwnersV1<EW, DW>
{
    pub fn create(
        files: OriginalCellQ24MaterialReceiptFilesV1<EW, DW>,
        config: OriginalCellQ24MaterialReceiptConfigV1,
        experience_key: SigningKey,
        dataset_key: SigningKey,
    ) -> Result<Self, Error> {
        let (experience_saved, dataset_binding) =
            binding::validate_config(&config, &experience_key, &dataset_key)?;
        let experience = LearningOwnerJournalV1::create(
            files.experience,
            files.experience_witness,
            experience_saved.binding_digest,
        )?;
        let dataset =
            LearningOwnerJournalV1::create(files.dataset, files.dataset_witness, dataset_binding)?;
        Ok(Self {
            experience,
            dataset,
            config,
            experience_key,
            dataset_key,
            experience_saved,
            dataset_binding,
            #[cfg(target_os = "linux")]
            panel: None,
            #[cfg(target_os = "linux")]
            command_origin: OriginalMaterialCommandOriginV1::FreshCreate,
        })
    }

    /// Validate the explicit panel before either original journal is created.
    #[cfg(target_os = "linux")]
    pub fn create_v2(
        files: OriginalCellQ24MaterialReceiptFilesV1<EW, DW>,
        config: OriginalCellQ24MaterialReceiptConfigV2,
        experience_key: SigningKey,
        dataset_key: SigningKey,
    ) -> Result<Self, Error> {
        let OriginalCellQ24MaterialReceiptConfigV2 { original, panel } = config;
        binding::validate_config(&original, &experience_key, &dataset_key)?;
        binding::require_panel_initial(&original, Some(panel.as_ref()))?;
        let mut owner = Self::create(files, original, experience_key, dataset_key)?;
        owner.panel = Some(panel);
        Ok(owner)
    }

    /// Reopen these same already initialized journals and witnesses. Pending
    /// never signs. A partially initialized pair is rejected, without creating
    /// or finishing the missing owner. The original freeze/signers/validity
    /// policy remain part of both bindings.
    pub fn recover(
        files: OriginalCellQ24MaterialReceiptFilesV1<EW, DW>,
        config: OriginalCellQ24MaterialReceiptConfigV1,
        experience_key: SigningKey,
        dataset_key: SigningKey,
    ) -> Result<Self, Error> {
        let (experience_saved, dataset_binding) =
            binding::validate_config(&config, &experience_key, &dataset_key)?;
        let experience = LearningOwnerJournalV1::recover(
            files.experience,
            files.experience_witness,
            experience_saved.binding_digest,
        )?;
        let dataset =
            LearningOwnerJournalV1::recover(files.dataset, files.dataset_witness, dataset_binding)?;
        Ok(Self {
            experience,
            dataset,
            config,
            experience_key,
            dataset_key,
            experience_saved,
            dataset_binding,
            #[cfg(target_os = "linux")]
            panel: None,
            #[cfg(target_os = "linux")]
            command_origin: OriginalMaterialCommandOriginV1::Recovered,
        })
    }

    /// Recheck the same explicit panel before recovering the original journals.
    #[cfg(target_os = "linux")]
    pub fn recover_v2(
        files: OriginalCellQ24MaterialReceiptFilesV1<EW, DW>,
        config: OriginalCellQ24MaterialReceiptConfigV2,
        experience_key: SigningKey,
        dataset_key: SigningKey,
    ) -> Result<Self, Error> {
        let OriginalCellQ24MaterialReceiptConfigV2 { original, panel } = config;
        binding::validate_config(&original, &experience_key, &dataset_key)?;
        binding::require_panel_initial(&original, Some(panel.as_ref()))?;
        let mut owner = Self::recover(files, original, experience_key, dataset_key)?;
        owner.panel = Some(panel);
        Ok(owner)
    }

    /// Move this pair into its original role host's readback-only producer.
    /// No key or source capability is serialized or transferred to Agentd.
    #[cfg(target_os = "linux")]
    pub fn into_evidence_readback_owner<SW: AnchorWitnessStore>(
        self,
        source: CircuitTaskSourceReadbackV1<SW>,
        identity: AgentdIdentity,
        ledger: std::sync::Arc<std::sync::Mutex<LedgerWriter>>,
        baseline: std::sync::Arc<LoadedCellQ24ModelV1>,
    ) -> Result<
        crate::OriginalCellQ24MaterialEvidenceOwnerV1<EW, DW, SW>,
        crate::OriginalCellQ24MaterialEvidenceErrorV1,
    > {
        let config = self.config.clone();
        crate::learning_iteration_evidence_client::OriginalCellQ24MaterialEvidenceOwnerV1::from_original_owners(
            self, config, source, identity, ledger, baseline,
        )
    }

    /// Explicit original dual-role command bootstrap consumes this pair once.
    /// This cannot be called on a previously handed-out readback owner. Fresh
    /// creation admits each stage once; recovery serves only original readback.
    #[cfg(target_os = "linux")]
    pub fn into_command_owner<SW: AnchorWitnessStore>(
        self,
        source: CircuitTaskSourceReadbackV1<SW>,
        identity: AgentdIdentity,
        ledger: std::sync::Arc<std::sync::Mutex<LedgerWriter>>,
        baseline: std::sync::Arc<LoadedCellQ24ModelV1>,
    ) -> Result<
        crate::OriginalCellQ24MaterialCommandOwnerV1<EW, DW, SW>,
        crate::OriginalCellQ24MaterialCommandErrorV1,
    > {
        let allow_new_commands = matches!(
            self.command_origin,
            OriginalMaterialCommandOriginV1::FreshCreate
        );
        let config = self.config.clone();
        crate::OriginalCellQ24MaterialCommandOwnerV1::from_original_pair(
            self,
            config,
            source,
            identity,
            ledger,
            baseline,
            allow_new_commands,
        )
    }

    /// Claim only a genuinely missing Experience. The observation comes from a
    /// fresh original Dataset read, never from caller-supplied evidence bytes.
    pub fn attest_experience(
        &mut self,
        mut sources: OriginalCellQ24MaterialReceiptSourcesV1<'_, impl AnchorWitnessStore>,
    ) -> Result<OriginalCellQ24MaterialCompletionV1, Error> {
        let started_at = binding::now()?;
        binding::validate_snapshot(&self.config, sources.snapshot)?;
        #[cfg(target_os = "linux")]
        binding::require_panel_initial(&self.config, self.panel.as_deref())?;
        match self.experience.read(&self.experience_saved) {
            Ok(bytes) => return self.authenticate_experience(&mut sources, &bytes, started_at),
            Err(LearningOriginalOwnerErrorV1::Store(
                ProductEvaluationExecutionStoreErrorV1::Missing,
            )) => {}
            Err(error) => return Err(error.into()),
        }
        if sources.snapshot != &self.config.initial {
            return Err(binding::invalid("exact new Experience cut"));
        }
        binding::require_new_work(&self.config, started_at)?;
        let material = binding::read_material(&self.config, &mut sources, false)?;
        binding::require_new_work(&self.config, started_at)?;
        let config = &self.config;
        let key = &self.experience_key;
        let saved = &self.experience_saved;
        let bytes = self.experience.commit_once(saved, || {
            let issued_at = binding::new_work_time(config, started_at)?;
            binding::verify_freeze(config, sources.ledger, &material, issued_at)
                .map_err(|_| binding::owner_invalid("original freeze at Experience claim"))?;
            let receipt = binding::receipt(config, None, &material, issued_at)
                .map_err(|_| binding::owner_invalid("original Experience receipt"))?;
            binding::signed_bytes(
                config,
                &config.experience_signer,
                key,
                &receipt,
                saved.binding_digest,
            )
        })?;
        let completed = self.authenticate_experience(&mut sources, &bytes, started_at)?;
        binding::require_same_material(&material, &completed.material)?;
        binding::require_new_work(&self.config, started_at)?;
        Ok(completed)
    }

    /// Read only an already completed Experience, retaining its exact original
    /// signature. Work expiry cannot create a new claim or renew this evidence.
    pub fn readback_experience(
        &mut self,
        mut sources: OriginalCellQ24MaterialReceiptSourcesV1<'_, impl AnchorWitnessStore>,
    ) -> Result<OriginalCellQ24MaterialCompletionV1, Error> {
        let started_at = binding::now()?;
        self.read_experience(&mut sources, started_at)
    }

    /// Dataset is signed only after reading this pair's original Experience
    /// journal. Its complete original signature is bound into the Dataset key.
    pub fn attest_dataset(
        &mut self,
        mut sources: OriginalCellQ24MaterialReceiptSourcesV1<'_, impl AnchorWitnessStore>,
    ) -> Result<OriginalCellQ24MaterialCompletionV1, Error> {
        let started_at = binding::now()?;
        let experience = self.read_experience(&mut sources, started_at)?;
        let saved = binding::dataset_saved(&self.config, self.dataset_binding, &experience)?;
        match self.dataset.read(&saved) {
            Ok(bytes) => {
                return self.authenticate_dataset(
                    &mut sources,
                    &experience,
                    &saved,
                    &bytes,
                    started_at,
                );
            }
            Err(LearningOriginalOwnerErrorV1::Store(
                ProductEvaluationExecutionStoreErrorV1::Missing,
            )) => {}
            Err(error) => return Err(error.into()),
        }
        if sources.snapshot != &binding::experience_prefix(&self.config, &experience.receipt)? {
            return Err(binding::invalid("exact new Dataset cut"));
        }
        binding::require_new_work(&self.config, started_at)?;
        let config = &self.config;
        let key = &self.dataset_key;
        let experience_binding = self.experience_saved.binding_digest;
        let bytes = self.dataset.commit_once(&saved, || {
            let issued_at = binding::new_work_time(config, started_at)?;
            binding::verify_freeze(config, sources.ledger, &experience.material, issued_at)
                .map_err(|_| binding::owner_invalid("original freeze at Dataset claim"))?;
            binding::verify_original(
                config,
                &config.experience_signer,
                &experience.receipt,
                &experience.attestation,
                experience_binding,
                issued_at,
            )
            .map_err(|_| binding::owner_invalid("original Experience at Dataset claim"))?;
            let receipt = binding::receipt(
                config,
                Some(&experience.receipt),
                &experience.material,
                issued_at,
            )
            .map_err(|_| binding::owner_invalid("original Dataset receipt"))?;
            binding::signed_bytes(
                config,
                &config.dataset_signer,
                key,
                &receipt,
                saved.binding_digest,
            )
        })?;
        let completed =
            self.authenticate_dataset(&mut sources, &experience, &saved, &bytes, started_at)?;
        binding::require_new_work(&self.config, started_at)?;
        Ok(completed)
    }

    /// Both journals, the original source/ledger and the same original freeze
    /// are checked. No signer, timestamp, current head or result is replaced.
    pub fn readback_dataset(
        &mut self,
        mut sources: OriginalCellQ24MaterialReceiptSourcesV1<'_, impl AnchorWitnessStore>,
    ) -> Result<OriginalCellQ24MaterialCompletionV1, Error> {
        let started_at = binding::now()?;
        let experience = self.read_experience(&mut sources, started_at)?;
        let saved = binding::dataset_saved(&self.config, self.dataset_binding, &experience)?;
        let bytes = self.dataset.read(&saved)?;
        self.authenticate_dataset(&mut sources, &experience, &saved, &bytes, started_at)
    }

    fn read_experience(
        &mut self,
        sources: &mut OriginalCellQ24MaterialReceiptSourcesV1<'_, impl AnchorWitnessStore>,
        started_at: u64,
    ) -> Result<OriginalCellQ24MaterialCompletionV1, Error> {
        binding::validate_snapshot(&self.config, sources.snapshot)?;
        #[cfg(target_os = "linux")]
        binding::require_panel_initial(&self.config, self.panel.as_deref())?;
        let bytes = self.experience.read(&self.experience_saved)?;
        self.authenticate_experience(sources, &bytes, started_at)
    }

    fn authenticate_experience(
        &mut self,
        sources: &mut OriginalCellQ24MaterialReceiptSourcesV1<'_, impl AnchorWitnessStore>,
        bytes: &[u8],
        started_at: u64,
    ) -> Result<OriginalCellQ24MaterialCompletionV1, Error> {
        binding::validate_snapshot(&self.config, sources.snapshot)?;
        let (payload, attestation) = learning_owner_evidence::decode(bytes)?;
        // This readback-only path is reached after the original journal was
        // physically read as Completed. It cannot bypass a new-work deadline.
        let material = binding::read_material(&self.config, sources, true)?;
        let receipt = binding::receipt(&self.config, None, &material, attestation.issued_at)?;
        if payload != learning_iteration_receipt_signing_bytes_v1(&receipt)? {
            return Err(binding::invalid("original Experience payload"));
        }
        binding::require_snapshot_receipt(sources.snapshot, 0, &receipt)?;
        if self.experience.read(&self.experience_saved)? != bytes {
            return Err(LearningOriginalOwnerErrorV1::CommitUncertain.into());
        }
        let fresh_now = binding::fresh_time(started_at)?;
        binding::verify_freeze(&self.config, sources.ledger, &material, fresh_now)?;
        binding::verify_original(
            &self.config,
            &self.config.experience_signer,
            &receipt,
            &attestation,
            self.experience_saved.binding_digest,
            fresh_now,
        )?;
        Ok(OriginalCellQ24MaterialCompletionV1 {
            receipt,
            attestation,
            material,
        })
    }

    fn authenticate_dataset(
        &mut self,
        sources: &mut OriginalCellQ24MaterialReceiptSourcesV1<'_, impl AnchorWitnessStore>,
        original_experience: &OriginalCellQ24MaterialCompletionV1,
        saved: &ProductEvaluationExecutionKeyV1,
        bytes: &[u8],
        started_at: u64,
    ) -> Result<OriginalCellQ24MaterialCompletionV1, Error> {
        let (payload, attestation) = learning_owner_evidence::decode(bytes)?;
        let experience = self.read_experience(sources, started_at)?;
        if experience.receipt != original_experience.receipt
            || experience.attestation != original_experience.attestation
            || binding::dataset_saved(&self.config, self.dataset_binding, &experience)? != *saved
        {
            return Err(LearningOriginalOwnerErrorV1::CommitUncertain.into());
        }
        binding::require_same_material(&experience.material, &original_experience.material)?;
        let receipt = binding::receipt(
            &self.config,
            Some(&experience.receipt),
            &experience.material,
            attestation.issued_at,
        )?;
        if payload != learning_iteration_receipt_signing_bytes_v1(&receipt)? {
            return Err(binding::invalid("original Dataset payload"));
        }
        binding::require_snapshot_receipt(sources.snapshot, 1, &receipt)?;
        let original_experience_bytes = learning_owner_evidence::encode(
            &learning_iteration_receipt_signing_bytes_v1(&experience.receipt)?,
            &experience.attestation,
        )?;
        if self.dataset.read(saved)? != bytes
            || self.experience.read(&self.experience_saved)? != original_experience_bytes
        {
            return Err(LearningOriginalOwnerErrorV1::CommitUncertain.into());
        }
        let fresh_now = binding::fresh_time(started_at)?;
        binding::verify_freeze(
            &self.config,
            sources.ledger,
            &experience.material,
            fresh_now,
        )?;
        binding::verify_original(
            &self.config,
            &self.config.experience_signer,
            &experience.receipt,
            &experience.attestation,
            self.experience_saved.binding_digest,
            fresh_now,
        )?;
        binding::verify_original(
            &self.config,
            &self.config.dataset_signer,
            &receipt,
            &attestation,
            saved.binding_digest,
            fresh_now,
        )?;
        Ok(OriginalCellQ24MaterialCompletionV1 {
            receipt,
            attestation,
            material: experience.material,
        })
    }
}

#[cfg(test)]
#[path = "cell_q24_material_receipt_owner_tests.rs"]
mod tests;

#[cfg(all(test, target_os = "linux"))]
pub(crate) use tests::ReadbackServiceFixture;

#[cfg(all(test, target_os = "linux"))]
pub(crate) use tests::MaterialCommandFixture;
#[cfg(all(test, target_os = "linux"))]
pub(crate) use tests::assert_dataset_pending;
#[cfg(all(test, target_os = "linux"))]
pub(crate) use tests::interrupt_dataset_claim;
