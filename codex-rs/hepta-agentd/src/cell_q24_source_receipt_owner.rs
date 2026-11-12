//! Original Observer receipts for the admitted Q24 task and frozen Dataset.
//! Every payload comes from the retained source capability. A caller cannot
//! supply receipt fields, timestamps or an alternative Dataset to be signed.

use std::fs::File;
use std::sync::Arc;

use codex_hepta_intelligence_eval::ProductEvaluationExecutionKeyV1;
use codex_hepta_intelligence_eval::ProductEvaluationExecutionStoreErrorV1;
use codex_hepta_learning_artifacts::LearningIterationCoordinatorV1;
use codex_hepta_learning_artifacts::LearningIterationError;
use codex_hepta_learning_artifacts::LearningIterationObservationV1;
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
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use ed25519_dalek::SigningKey;

use crate::CellQ24LearningPreparationErrorV1;
use crate::CellQ24PreparedLearningV1;
use crate::cell_composed_q24_training::OriginalPreparedReadV1;
use crate::learning_owner_evidence;
use crate::learning_owner_journal::LearningOriginalOwnerErrorV1;
use crate::learning_owner_journal::LearningOwnerJournalV1;

#[path = "cell_q24_source_owner_files.rs"]
mod files;
#[path = "cell_q24_source_signature.rs"]
mod signature;
pub use files::OriginalCellQ24SourceFilesV1;
pub use files::OriginalCellQ24SourceJournalV1;
use signature::binding;
use signature::evidence_id;
use signature::now;
use signature::sign_original_source_receipt;
use signature::source_binding;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum OriginalCellQ24SourceStageV1 {
    Experience,
    Dataset,
}

impl OriginalCellQ24SourceStageV1 {
    fn stage(self) -> LearningIterationStageV1 {
        match self {
            Self::Experience => LearningIterationStageV1::Experience,
            Self::Dataset => LearningIterationStageV1::Dataset,
        }
    }

    fn domain(self) -> &'static [u8] {
        match self {
            Self::Experience => b"hepta.agentd.original-q24-experience-receipt.v1\0",
            Self::Dataset => b"hepta.agentd.original-q24-dataset-receipt.v1\0",
        }
    }
}

/// The host transfers an already enrolled Observer key, file and witness.
/// This configuration neither creates that custody nor enrolls a Root owner.
#[derive(Clone)]
pub struct OriginalCellQ24SourceSigningConfigV1 {
    pub stage: OriginalCellQ24SourceStageV1,
    pub signer: TrustedLearningSignerV1,
    pub verifier: LearningEvidenceVerifierV1,
    pub maximum_signature_lifetime_seconds: u64,
}

#[derive(Debug, thiserror::Error)]
pub enum OriginalCellQ24SourceReceiptErrorV1 {
    #[error("original source receipt owner: {0}")]
    Owner(#[from] LearningOriginalOwnerErrorV1),
    #[error("original task and Dataset source: {0}")]
    Source(#[from] CellQ24LearningPreparationErrorV1),
    #[error("original source receipt: {0}")]
    Iteration(#[from] LearningIterationError),
    #[error("original Observer evidence: {0}")]
    Evidence(#[from] SignedEvidenceError),
}

type Error = OriginalCellQ24SourceReceiptErrorV1;

/// An authenticated read of one original journal. Fields are private so a
/// caller cannot replace the Experience prefix used by the Dataset owner.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct OriginalCellQ24SourceCompletionV1 {
    receipt: LearningIterationReceiptV1,
    attestation: SignedLearningEvidenceV1,
    snapshot: LearningIterationSnapshotV1,
}

impl OriginalCellQ24SourceCompletionV1 {
    pub fn receipt(&self) -> &LearningIterationReceiptV1 {
        &self.receipt
    }

    pub fn attestation(&self) -> &SignedLearningEvidenceV1 {
        &self.attestation
    }

    pub fn snapshot(&self) -> &LearningIterationSnapshotV1 {
        &self.snapshot
    }

    pub const fn authority(&self) -> AuthorityPosture {
        AuthorityPosture::DENY_ALL
    }
}

pub struct OriginalCellQ24SourceReceiptOwnerV1<W: AnchorWitnessStore> {
    journal: LearningOwnerJournalV1<W>,
    prepared: Arc<CellQ24PreparedLearningV1>,
    config: OriginalCellQ24SourceSigningConfigV1,
    key: SigningKey,
    saved: ProductEvaluationExecutionKeyV1,
}

impl<W: AnchorWitnessStore> OriginalCellQ24SourceReceiptOwnerV1<W> {
    pub(crate) fn require_prepared(
        &self,
        prepared: &CellQ24PreparedLearningV1,
        stage: OriginalCellQ24SourceStageV1,
    ) -> Result<(), Error> {
        if self.config.stage != stage
            || self.prepared.initial() != prepared.initial()
            || self.prepared.scope() != prepared.scope()
            || !std::ptr::eq(self.prepared.as_ref(), prepared)
        {
            return Err(binding("original source handoff operation and stage"));
        }
        self.prepared.with_original_prepared_operation(|read| {
            if validate_config(&self.prepared, &self.config, &self.key, read)? != self.saved
                || validate_config(prepared, &self.config, &self.key, read)? != self.saved
            {
                return Err(binding("original source handoff capability changed"));
            }
            let original_facts = OriginalPreparedReadV1::read_validated_facts(read)?;
            let retained_facts = OriginalPreparedReadV1::read_validated_facts(read)?;
            if original_facts != retained_facts {
                return Err(binding("original source handoff facts changed"));
            }
            OriginalPreparedReadV1::require_prepared(read, &self.prepared)?;
            OriginalPreparedReadV1::require_prepared(read, prepared)?;
            Ok(())
        })?
    }

    pub fn create(
        file: File,
        witness: W,
        prepared: Arc<CellQ24PreparedLearningV1>,
        config: OriginalCellQ24SourceSigningConfigV1,
        key: SigningKey,
    ) -> Result<Self, Error> {
        let (saved, journal) =
            prepared.with_original_prepared_operation(|read| -> Result<_, Error> {
                let saved = validate_config(&prepared, &config, &key, read)?;
                let journal = LearningOwnerJournalV1::create(file, witness, saved.binding_digest)?;
                OriginalPreparedReadV1::require_prepared(read, &prepared)?;
                Ok((saved, journal))
            })??;
        Ok(Self {
            journal,
            prepared,
            config,
            key,
            saved,
        })
    }

    /// Reopen the original journal and witness. Pending stays unresolved, and
    /// reading a completed receipt never renews its signature or observation.
    pub fn recover(
        file: File,
        witness: W,
        prepared: Arc<CellQ24PreparedLearningV1>,
        config: OriginalCellQ24SourceSigningConfigV1,
        key: SigningKey,
    ) -> Result<Self, Error> {
        let (saved, journal) =
            prepared.with_original_prepared_operation(|read| -> Result<_, Error> {
                let saved = validate_config(&prepared, &config, &key, read)?;
                let journal = LearningOwnerJournalV1::recover(file, witness, saved.binding_digest)?;
                OriginalPreparedReadV1::require_prepared(read, &prepared)?;
                Ok((saved, journal))
            })??;
        Ok(Self {
            journal,
            prepared,
            config,
            key,
            saved,
        })
    }

    pub fn attest_experience(&mut self) -> Result<OriginalCellQ24SourceCompletionV1, Error> {
        if self.config.stage != OriginalCellQ24SourceStageV1::Experience {
            return Err(binding("original Experience owner"));
        }
        let prepared = Arc::clone(&self.prepared);
        prepared
            .with_original_prepared_operation(|read| self.attest_at(prepared.initial(), read))?
    }

    pub fn read_experience(&mut self) -> Result<OriginalCellQ24SourceCompletionV1, Error> {
        if self.config.stage != OriginalCellQ24SourceStageV1::Experience {
            return Err(binding("original Experience owner"));
        }
        let prepared = Arc::clone(&self.prepared);
        prepared.with_original_prepared_operation(|read| self.read_at(prepared.initial(), read))?
    }

    /// Borrow the actual predecessor owner, not a cached receipt. Its live
    /// journal and witness are checked on both sides of the Dataset action.
    pub fn attest_dataset<EW: AnchorWitnessStore>(
        &mut self,
        experience: &mut OriginalCellQ24SourceReceiptOwnerV1<EW>,
    ) -> Result<OriginalCellQ24SourceCompletionV1, Error> {
        self.with_original_experience(experience, Self::attest_at)
    }

    /// No claim, signature, training or deadline extension occurs on readback.
    pub fn read_dataset<EW: AnchorWitnessStore>(
        &mut self,
        experience: &mut OriginalCellQ24SourceReceiptOwnerV1<EW>,
    ) -> Result<OriginalCellQ24SourceCompletionV1, Error> {
        self.with_original_experience(experience, Self::read_at)
    }

    fn attest_at(
        &mut self,
        prefix: &LearningIterationSnapshotV1,
        read: &OriginalPreparedReadV1<'_>,
    ) -> Result<OriginalCellQ24SourceCompletionV1, Error> {
        let (observation, evidence_digest) = self.original_observation(read)?;
        match self.journal.read(&self.saved) {
            Ok(bytes) => return self.authenticate_completed(prefix, &bytes, read),
            Err(LearningOriginalOwnerErrorV1::Store(
                ProductEvaluationExecutionStoreErrorV1::Missing,
            )) => {}
            Err(error) => return Err(error.into()),
        }
        let observed_at = now()?;
        source_receipt(
            &self.prepared,
            &self.config,
            prefix,
            &observation,
            evidence_digest,
            observed_at,
        )?;
        self.config.verifier.require_signer_binding(
            LearningEvidenceRoleV1::Observer,
            &self.config.signer,
            observed_at,
        )?;
        let config = &self.config;
        let key = &self.key;
        let prepared: &CellQ24PreparedLearningV1 = &self.prepared;
        let saved = &self.saved;
        let bytes = self.journal.commit_once(saved, || {
            OriginalPreparedReadV1::require_prepared(read, prepared).map_err(source_binding)?;
            let receipt = source_receipt(
                prepared,
                config,
                prefix,
                &observation,
                evidence_digest,
                now()?,
            )
            .map_err(|_| LearningOriginalOwnerErrorV1::Binding("original source receipt"))?;
            let payload = learning_iteration_receipt_signing_bytes_v1(&receipt)
                .map_err(|_| LearningOriginalOwnerErrorV1::Binding("original source bytes"))?;
            let signed = sign_original_source_receipt(
                config,
                key,
                &receipt,
                &payload,
                saved.binding_digest,
            )?;
            OriginalPreparedReadV1::require_prepared(read, prepared).map_err(source_binding)?;
            learning_owner_evidence::encode(&payload, &signed)
        })?;
        self.authenticate_completed(prefix, &bytes, read)
    }

    fn read_at(
        &mut self,
        prefix: &LearningIterationSnapshotV1,
        read: &OriginalPreparedReadV1<'_>,
    ) -> Result<OriginalCellQ24SourceCompletionV1, Error> {
        let prepared: &CellQ24PreparedLearningV1 = &self.prepared;
        OriginalPreparedReadV1::require_prepared(read, prepared)?;
        let bytes = self.journal.read(&self.saved)?;
        self.authenticate_completed(prefix, &bytes, read)
    }

    fn with_original_experience(
        &mut self,
        experience: &mut OriginalCellQ24SourceReceiptOwnerV1<impl AnchorWitnessStore>,
        operation: impl FnOnce(
            &mut Self,
            &LearningIterationSnapshotV1,
            &OriginalPreparedReadV1<'_>,
        ) -> Result<OriginalCellQ24SourceCompletionV1, Error>,
    ) -> Result<OriginalCellQ24SourceCompletionV1, Error> {
        if self.config.stage != OriginalCellQ24SourceStageV1::Dataset
            || experience.config.stage != OriginalCellQ24SourceStageV1::Experience
            || !Arc::ptr_eq(&self.prepared, &experience.prepared)
        {
            return Err(binding("original Dataset and Experience owners"));
        }
        let prepared = Arc::clone(&self.prepared);
        prepared.with_original_prepared_operation(|read| {
            let before = experience.read_at(prepared.initial(), read)?;
            OriginalPreparedReadV1::require_prepared(read, &self.prepared)?;
            let facts = OriginalPreparedReadV1::read_validated_facts(read)?;
            let initial = self.prepared.initial();
            let receipt = &before.receipt;
            if receipt.operation_id != initial.request.operation_id
                || receipt.predecessor != initial.head_digest
                || receipt.actor_id != initial.owners.experience
                || &receipt.observation != facts.experience()
                || receipt.evidence_digest != facts.experience_evidence_digest()
                || receipt.observed_unix_seconds != before.attestation.issued_at
            {
                return Err(binding("original Experience predecessor"));
            }
            let payload = learning_iteration_receipt_signing_bytes_v1(receipt)?;
            let verified = self.config.verifier.verify(
                LearningEvidenceRoleV1::Observer,
                &before.attestation,
                &payload,
                now()?,
            )?;
            if verified.principal().principal_id != initial.owners.experience {
                return Err(binding("original Experience Observer"));
            }
            let mut coordinator = LearningIterationCoordinatorV1::from_snapshot(initial.clone())?;
            coordinator.record(receipt.clone(), receipt.observed_unix_seconds)?;
            self.prepared
                .scope()
                .validate_snapshot(coordinator.snapshot())?;
            if coordinator.snapshot() != &before.snapshot {
                return Err(binding("original Experience checkpoint"));
            }
            let completed = operation(self, &before.snapshot, read)?;
            if experience.read_at(prepared.initial(), read)? != before {
                return Err(LearningOriginalOwnerErrorV1::CommitUncertain.into());
            }
            Ok(completed)
        })?
    }

    fn original_observation(
        &self,
        read: &OriginalPreparedReadV1<'_>,
    ) -> Result<(LearningIterationObservationV1, Digest32), Error> {
        OriginalPreparedReadV1::require_prepared(read, &self.prepared)?;
        let facts = OriginalPreparedReadV1::read_validated_facts(read)?;
        Ok(match self.config.stage {
            OriginalCellQ24SourceStageV1::Experience => (
                facts.experience().clone(),
                facts.experience_evidence_digest(),
            ),
            OriginalCellQ24SourceStageV1::Dataset => {
                (facts.dataset().clone(), facts.dataset_evidence_digest())
            }
        })
    }

    fn authenticate_completed(
        &mut self,
        prefix: &LearningIterationSnapshotV1,
        bytes: &[u8],
        read: &OriginalPreparedReadV1<'_>,
    ) -> Result<OriginalCellQ24SourceCompletionV1, Error> {
        let (payload, signed) = learning_owner_evidence::decode(bytes)?;
        let (observation, evidence_digest) = self.original_observation(read)?;
        let receipt = source_receipt(
            &self.prepared,
            &self.config,
            prefix,
            &observation,
            evidence_digest,
            signed.issued_at,
        )?;
        if payload != learning_iteration_receipt_signing_bytes_v1(&receipt)? {
            return Err(binding("changed original source payload"));
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
            return Err(binding("original source Observer identity"));
        }
        let mut coordinator = LearningIterationCoordinatorV1::from_snapshot(prefix.clone())?;
        coordinator.record(receipt.clone(), receipt.observed_unix_seconds)?;
        self.prepared
            .scope()
            .validate_snapshot(coordinator.snapshot())?;
        if self.original_observation(read)? != (observation, evidence_digest)
            || self.journal.read(&self.saved)? != bytes
        {
            return Err(LearningOriginalOwnerErrorV1::CommitUncertain.into());
        }
        Ok(OriginalCellQ24SourceCompletionV1 {
            receipt,
            attestation: signed,
            snapshot: coordinator.snapshot().clone(),
        })
    }
}

fn validate_config(
    prepared: &CellQ24PreparedLearningV1,
    config: &OriginalCellQ24SourceSigningConfigV1,
    key: &SigningKey,
    read: &OriginalPreparedReadV1<'_>,
) -> Result<ProductEvaluationExecutionKeyV1, Error> {
    OriginalPreparedReadV1::require_prepared(read, prepared)?;
    let initial = prepared.initial();
    let coordinator = LearningIterationCoordinatorV1::from_snapshot(initial.clone())?;
    prepared.scope().validate_snapshot(initial)?;
    if !initial.receipts.is_empty()
        || coordinator.next_stage() != Some(LearningIterationStageV1::Experience)
        || key.verifying_key().to_bytes() != config.signer.verifying_key
        || &config.signer.principal.principal_id != initial.owners.owner(config.stage.stage())
        || initial.owners.evidence_trust_digest != config.verifier.trust_digest()
        || initial.request.envelope.objective_digest != config.verifier.objective_digest()
        || !(1..=86_400).contains(&config.maximum_signature_lifetime_seconds)
    {
        return Err(binding("original source Observer capability"));
    }
    config.verifier.require_signer_binding(
        LearningEvidenceRoleV1::Observer,
        &config.signer,
        now()?,
    )?;
    Ok(ProductEvaluationExecutionKeyV1 {
        plan_id: initial.request.operation_id.clone(),
        binding_digest: Digest32::of_parts(&[
            config.stage.domain(),
            initial.head_digest.as_array(),
            prepared.scope().binding().as_array(),
            config.verifier.trust_digest().as_array(),
            config.signer.principal.principal_id.as_str().as_bytes(),
            &config.signer.verifying_key,
            &config.maximum_signature_lifetime_seconds.to_be_bytes(),
        ]),
    })
}

fn source_receipt(
    prepared: &CellQ24PreparedLearningV1,
    config: &OriginalCellQ24SourceSigningConfigV1,
    prefix: &LearningIterationSnapshotV1,
    observation: &LearningIterationObservationV1,
    evidence_digest: Digest32,
    observed_unix_seconds: u64,
) -> Result<LearningIterationReceiptV1, Error> {
    if observation.stage() != config.stage.stage() || evidence_digest.is_zero() {
        return Err(binding("original source stage observation"));
    }
    let receipt = LearningIterationReceiptV1 {
        operation_id: prepared.initial().request.operation_id.clone(),
        predecessor: prefix.head_digest,
        actor_id: config.signer.principal.principal_id.clone(),
        evidence_digest,
        observed_unix_seconds,
        observation: observation.clone(),
    };
    let mut coordinator = LearningIterationCoordinatorV1::from_snapshot(prefix.clone())?;
    coordinator.record(receipt.clone(), observed_unix_seconds)?;
    prepared.scope().validate_snapshot(coordinator.snapshot())?;
    Ok(receipt)
}
