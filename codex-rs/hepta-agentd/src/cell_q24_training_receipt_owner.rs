//! Original Generator receipts for an anchored Q24 training completion.
//! The host supplies its enrolled key, frozen Dataset cut, file and independent
//! witness. Only the original native training owner supplies observation bytes.
//! This port neither trains nor assembles the other learning stage owners.

use std::fs::File;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_intelligence_eval::ProductEvaluationExecutionKeyV1;
use codex_hepta_learning_artifacts::FrozenLearningScopeV2;
use codex_hepta_learning_artifacts::LearningIterationCoordinatorV1;
use codex_hepta_learning_artifacts::LearningIterationError;
use codex_hepta_learning_artifacts::LearningIterationReceiptV1;
use codex_hepta_learning_artifacts::LearningIterationSnapshotV1;
use codex_hepta_learning_artifacts::LearningIterationStageV1;
use codex_hepta_learning_artifacts::learning_iteration_receipt_signing_bytes_v1;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_learning_ledger::SignedEvidenceError;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_learning_ledger::TrustedLearningSignerV1;
use codex_hepta_neuron::AnchorWitnessStore;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;

use crate::CellQ24TrainingObservationV2;
use crate::CellQ24TrainingOwnerErrorV1;
use crate::CellQ24TrainingOwnerV1;
use crate::cell_composed_q24::OriginalQ24DatasetReadV1;
use crate::cell_composed_q24::OriginalQ24OwnerReadV1;
use crate::learning_owner_evidence;
use crate::learning_owner_journal::LearningOriginalOwnerErrorV1;
use crate::learning_owner_journal::LearningOwnerJournalV1;

#[derive(Debug, thiserror::Error)]
pub enum OriginalCellQ24TrainingReceiptErrorV1 {
    #[error("original training receipt owner: {0}")]
    Owner(#[from] LearningOriginalOwnerErrorV1),
    #[error("original native training observation: {0}")]
    Training(#[from] CellQ24TrainingOwnerErrorV1),
    #[error("original training receipt: {0}")]
    Iteration(#[from] LearningIterationError),
    #[error("original Generator evidence: {0}")]
    Evidence(#[from] SignedEvidenceError),
}

type Error = OriginalCellQ24TrainingReceiptErrorV1;

#[path = "cell_q24_training_stage.rs"]
mod stage;
pub use stage::OriginalCellQ24TrainingCompletionV1;
pub use stage::OriginalCellQ24TrainingStageErrorV1;
pub use stage::OriginalCellQ24TrainingStageV1;
#[cfg(target_os = "linux")]
pub(crate) use stage::OriginalQ24TrainingOperationEvidenceV1;
#[cfg(target_os = "linux")]
pub(crate) use stage::OriginalQ24TrainingOperationV1;

/// Original host configuration, fixed before requesting a training signature.
/// Structural validation cannot manufacture Dataset custody or Root enrollment.
#[derive(Clone)]
pub struct OriginalCellQ24TrainingSigningConfigV1 {
    pub dataset: LearningIterationSnapshotV1,
    pub scope: FrozenLearningScopeV2,
    pub signer: TrustedLearningSignerV1,
    pub verifier: LearningEvidenceVerifierV1,
    pub maximum_signature_lifetime_seconds: u64,
}

pub struct OriginalCellQ24TrainingReceiptOwnerV1<W: AnchorWitnessStore> {
    journal: LearningOwnerJournalV1<W>,
    config: OriginalCellQ24TrainingSigningConfigV1,
    key: SigningKey,
    saved: ProductEvaluationExecutionKeyV1,
}

impl<W: AnchorWitnessStore> OriginalCellQ24TrainingReceiptOwnerV1<W> {
    pub fn create(
        file: File,
        witness: W,
        config: OriginalCellQ24TrainingSigningConfigV1,
        key: SigningKey,
    ) -> Result<Self, Error> {
        let saved = validate_config(&config, &key)?;
        let journal = LearningOwnerJournalV1::create(file, witness, saved.binding_digest)?;
        Ok(Self {
            journal,
            config,
            key,
            saved,
        })
    }

    /// Reopen the same signature journal and independent witness. A persisted
    /// Pending claim remains unresolved; recovery never signs or trains.
    pub fn recover(
        file: File,
        witness: W,
        config: OriginalCellQ24TrainingSigningConfigV1,
        key: SigningKey,
    ) -> Result<Self, Error> {
        let saved = validate_config(&config, &key)?;
        let journal = LearningOwnerJournalV1::recover(file, witness, saved.binding_digest)?;
        Ok(Self {
            journal,
            config,
            key,
            saved,
        })
    }

    /// Sign only a completed observation read from its actual original owner.
    /// No caller-supplied receipt, timestamp, outcome or payload is accepted.
    /// An existing completion retains its original signature and validity window.
    pub fn attest_original_completion(
        &mut self,
        training: &mut CellQ24TrainingOwnerV1<impl AnchorWitnessStore>,
    ) -> Result<(LearningIterationReceiptV1, SignedLearningEvidenceV1), Error> {
        self.attest_completion_with_source(training, &OriginalQ24OwnerReadV1)
    }

    pub(crate) fn attest_completion_with_source(
        &mut self,
        training: &mut CellQ24TrainingOwnerV1<impl AnchorWitnessStore>,
        source: &impl OriginalQ24DatasetReadV1,
    ) -> Result<(LearningIterationReceiptV1, SignedLearningEvidenceV1), Error> {
        let observation =
            training.read_learning_observation_with_source(&self.config.dataset, source)?;
        require_observation(&self.config, &observation)?;
        let config = &self.config;
        let key = &self.key;
        let saved = &self.saved;
        let bytes = self.journal.commit_once(saved, || {
            let receipt = training_receipt(config, &observation, now()?)
                .map_err(|_| LearningOriginalOwnerErrorV1::Binding("original Training receipt"))?;
            let payload = learning_iteration_receipt_signing_bytes_v1(&receipt)
                .map_err(|_| LearningOriginalOwnerErrorV1::Binding("original Training bytes"))?;
            let signed = sign_original(config, key, &receipt, &payload, saved.binding_digest)?;
            learning_owner_evidence::encode(&payload, &signed)
        })?;
        self.authenticate_completed(training, &observation, &bytes, source)
    }

    /// Read the original receipt against the original training owner's current
    /// anchored completion. This cannot claim work, fit, sign or renew time.
    pub fn readback(
        &mut self,
        training: &mut CellQ24TrainingOwnerV1<impl AnchorWitnessStore>,
    ) -> Result<(LearningIterationReceiptV1, SignedLearningEvidenceV1), Error> {
        self.readback_with_source(training, &OriginalQ24OwnerReadV1)
    }

    pub(crate) fn readback_with_source(
        &mut self,
        training: &mut CellQ24TrainingOwnerV1<impl AnchorWitnessStore>,
        source: &impl OriginalQ24DatasetReadV1,
    ) -> Result<(LearningIterationReceiptV1, SignedLearningEvidenceV1), Error> {
        let observation =
            training.read_learning_observation_with_source(&self.config.dataset, source)?;
        require_observation(&self.config, &observation)?;
        let bytes = self.journal.read(&self.saved)?;
        self.authenticate_completed(training, &observation, &bytes, source)
    }

    fn authenticate_completed(
        &mut self,
        training: &mut CellQ24TrainingOwnerV1<impl AnchorWitnessStore>,
        observation: &CellQ24TrainingObservationV2,
        bytes: &[u8],
        source: &impl OriginalQ24DatasetReadV1,
    ) -> Result<(LearningIterationReceiptV1, SignedLearningEvidenceV1), Error> {
        let (payload, signed) = learning_owner_evidence::decode(bytes)?;
        let receipt = training_receipt(&self.config, observation, signed.issued_at)?;
        if payload != learning_iteration_receipt_signing_bytes_v1(&receipt)? {
            return Err(
                LearningOriginalOwnerErrorV1::Binding("changed original Training payload").into(),
            );
        }
        let verified = self.config.verifier.verify(
            LearningEvidenceRoleV1::Generator,
            &signed,
            &payload,
            now()?,
        )?;
        if verified.principal() != &self.config.signer.principal
            || verified.controller_id() != &self.config.signer.controller_id
            || signed.evidence_id != evidence_id(self.saved.binding_digest)?
        {
            return Err(
                LearningOriginalOwnerErrorV1::Binding("original Generator identity").into(),
            );
        }
        if training.read_learning_observation_with_source(&self.config.dataset, source)?
            != *observation
            || self.journal.read(&self.saved)? != bytes
        {
            return Err(LearningOriginalOwnerErrorV1::CommitUncertain.into());
        }
        Ok((receipt, signed))
    }
}

fn validate_config(
    config: &OriginalCellQ24TrainingSigningConfigV1,
    key: &SigningKey,
) -> Result<ProductEvaluationExecutionKeyV1, Error> {
    let coordinator = LearningIterationCoordinatorV1::from_snapshot(config.dataset.clone())?;
    config.scope.validate_snapshot(&config.dataset)?;
    if coordinator.next_stage() != Some(LearningIterationStageV1::Training)
        || key.verifying_key().to_bytes() != config.signer.verifying_key
        || config.signer.principal.principal_id != config.dataset.owners.trainer
        || config.dataset.owners.evidence_trust_digest != config.verifier.trust_digest()
        || config.dataset.request.envelope.objective_digest != config.verifier.objective_digest()
        || !(1..=86_400).contains(&config.maximum_signature_lifetime_seconds)
    {
        return Err(LearningOriginalOwnerErrorV1::Binding("original Generator capability").into());
    }
    config.verifier.require_signer_binding(
        LearningEvidenceRoleV1::Generator,
        &config.signer,
        now()?,
    )?;
    Ok(ProductEvaluationExecutionKeyV1 {
        plan_id: config.dataset.request.operation_id.clone(),
        binding_digest: Digest32::of_parts(&[
            b"hepta.agentd.original-q24-training-receipt.v1\0",
            config.dataset.head_digest.as_array(),
            config.scope.binding().as_array(),
            config.verifier.trust_digest().as_array(),
            config.signer.principal.principal_id.as_str().as_bytes(),
            &config.signer.verifying_key,
            &config.maximum_signature_lifetime_seconds.to_be_bytes(),
        ]),
    })
}

fn require_observation(
    config: &OriginalCellQ24TrainingSigningConfigV1,
    observation: &CellQ24TrainingObservationV2,
) -> Result<(), Error> {
    if observation.iteration_head() != config.dataset.head_digest
        || observation.scope_binding() != config.scope.binding()
        || observation.evidence_digest().is_zero()
    {
        return Err(
            LearningOriginalOwnerErrorV1::Binding("original frozen Training observation").into(),
        );
    }
    config
        .scope
        .validate_observation(observation.observation())?;
    Ok(())
}

fn training_receipt(
    config: &OriginalCellQ24TrainingSigningConfigV1,
    observation: &CellQ24TrainingObservationV2,
    observed_unix_seconds: u64,
) -> Result<LearningIterationReceiptV1, Error> {
    require_observation(config, observation)?;
    let receipt = LearningIterationReceiptV1 {
        operation_id: config.dataset.request.operation_id.clone(),
        predecessor: config.dataset.head_digest,
        actor_id: config.dataset.owners.trainer.clone(),
        evidence_digest: observation.evidence_digest(),
        observed_unix_seconds,
        observation: observation.observation().clone(),
    };
    let mut coordinator = LearningIterationCoordinatorV1::from_snapshot(config.dataset.clone())?;
    coordinator.record(receipt.clone(), observed_unix_seconds)?;
    config.scope.validate_snapshot(coordinator.snapshot())?;
    Ok(receipt)
}

fn sign_original(
    config: &OriginalCellQ24TrainingSigningConfigV1,
    key: &SigningKey,
    receipt: &LearningIterationReceiptV1,
    payload: &[u8],
    identity: Digest32,
) -> Result<SignedLearningEvidenceV1, LearningOriginalOwnerErrorV1> {
    let issued_at = receipt.observed_unix_seconds;
    config.verifier.require_signer_binding(
        LearningEvidenceRoleV1::Generator,
        &config.signer,
        issued_at,
    )?;
    let expires_at = issued_at
        .checked_add(config.maximum_signature_lifetime_seconds)
        .ok_or(LearningOriginalOwnerErrorV1::Binding(
            "signature deadline overflow",
        ))?
        .min(config.signer.principal.expires_at);
    let mut signed = SignedLearningEvidenceV1 {
        evidence_id: evidence_id(identity)?,
        principal_id: config.signer.principal.principal_id.clone(),
        role: LearningEvidenceRoleV1::Generator,
        trust_digest: config.verifier.trust_digest(),
        scope_digest: config.verifier.scope_digest(),
        objective_digest: config.verifier.objective_digest(),
        authority_epoch: config.signer.principal.authority_epoch,
        issued_at,
        expires_at,
        payload_digest: Digest32::of_bytes(payload),
        signature: [0; 64],
    };
    signed.signature = key.sign(&signed.signing_bytes()).to_bytes();
    config.verifier.verify(
        LearningEvidenceRoleV1::Generator,
        &signed,
        payload,
        issued_at,
    )?;
    Ok(signed)
}

fn evidence_id(identity: Digest32) -> Result<StableId, LearningOriginalOwnerErrorV1> {
    StableId::new(format!("original-training:{identity}"))
        .map_err(|_| LearningOriginalOwnerErrorV1::Binding("evidence id"))
}

fn now() -> Result<u64, LearningOriginalOwnerErrorV1> {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_secs())
        .map_err(|_| LearningOriginalOwnerErrorV1::Binding("original owner clock"))
}
