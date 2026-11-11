//! Original Selector receipts for a completed Q24 Model adoption.
//! This owner only observes original SourceBound Training, Model, independent
//! Evaluation and an already authorized publication. It cannot publish, mint
//! FinalUse, run a holdout or turn eligibility into an adoption grant.
//!
//! The original host must supply the retained capabilities below. Ordinary
//! Root Model routing and cross-process custody handoff remain separate work.

use std::fs::File;

use codex_hepta_intelligence_eval::IndependentEvaluationBundleV1;
use codex_hepta_intelligence_eval::OriginalProductEvaluationExecutionEvidenceV1;
use codex_hepta_intelligence_eval::ProductEvaluationError;
use codex_hepta_intelligence_eval::ProductEvaluationExecutionKeyV1;
use codex_hepta_intelligence_eval::ProductEvaluationExecutionStoreErrorV1;
use codex_hepta_intelligence_eval::SignedEvaluationEvidenceV1;
use codex_hepta_learning_artifacts::FrozenLearningScopeV2;
use codex_hepta_learning_artifacts::LearningIterationError;
use codex_hepta_learning_artifacts::LearningIterationObservationV1;
use codex_hepta_learning_artifacts::LearningIterationReceiptV1;
use codex_hepta_learning_artifacts::LearningIterationSnapshotV1;
use codex_hepta_learning_artifacts::learning_iteration_receipt_signing_bytes_v1;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_learning_ledger::SignedEvidenceError;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_learning_ledger::TrustedLearningSignerV1;
use codex_hepta_learning_ledger::verify_signed_actor_separation;
use codex_hepta_neuron::AnchorWitnessStore;
use ed25519_dalek::SigningKey;
use tokio::runtime::Handle;

use crate::AgentdError;
use crate::CellEvaluationErrorV1;
use crate::CellEvaluationQualificationV1;
use crate::CellEvaluationReceiptV1;
use crate::LearningIterationRuntimeErrorV1;
use crate::OriginalCellQ24TrainingStageErrorV1;
use crate::learning_owner_evidence;
use crate::learning_owner_journal::LearningOriginalOwnerErrorV1 as OwnerError;
use crate::learning_owner_journal::LearningOwnerJournalV1;

#[path = "circuit_model_selection_receipt_binding.rs"]
mod binding;
#[path = "circuit_model_selection_receipt_sources.rs"]
mod sources;
pub use sources::OriginalCircuitModelSelectionEvaluationSourcesV1;
pub use sources::OriginalCircuitModelSelectionReceiptSourcesV1;

#[derive(Debug, thiserror::Error)]
pub enum OriginalCircuitModelSelectionReceiptErrorV1 {
    #[error("original Model Selector owner: {0}")]
    Owner(#[from] OwnerError),
    #[error("original published Model selection: {0}")]
    Observation(#[from] AgentdError),
    #[error("original learning iteration: {0}")]
    Iteration(#[from] LearningIterationError),
    #[error("original source-bound Model lane: {0}")]
    Model(#[from] OriginalCellQ24TrainingStageErrorV1),
    #[error("original Cell execution: {0}")]
    Cell(#[from] CellEvaluationErrorV1),
    #[error("original independent qualification: {0}")]
    Product(#[from] ProductEvaluationError),
    #[error("original predecessor connection: {0}")]
    Connection(#[from] LearningIterationRuntimeErrorV1),
    #[error("original role evidence: {0}")]
    Evidence(#[from] SignedEvidenceError),
}
type Error = OriginalCircuitModelSelectionReceiptErrorV1;

/// Exact five-stage Candidate / Qualified / Model Proposal decision. All
/// original stage, product and execution signatures are retained in full.
/// A validly renewed signature cannot replace any of these during recovery.
#[derive(Clone)]
pub struct OriginalCircuitModelSelectionReceiptConfigV1 {
    pub decision: LearningIterationSnapshotV1,
    pub scope: FrozenLearningScopeV2,
    pub signer: TrustedLearningSignerV1,
    pub verifier: LearningEvidenceVerifierV1,
    pub training_evidence: SignedLearningEvidenceV1,
    pub evaluation_evidence: SignedLearningEvidenceV1,
    pub evaluation: CellEvaluationReceiptV1,
    pub qualification: CellEvaluationQualificationV1,
    pub product_evidence: SignedEvaluationEvidenceV1,
    pub execution_evidence: OriginalProductEvaluationExecutionEvidenceV1,
    pub maximum_signature_lifetime_seconds: u64,
}

pub struct OriginalCircuitModelSelectionReceiptOwnerV1<W: AnchorWitnessStore> {
    journal: LearningOwnerJournalV1<W>,
    config: OriginalCircuitModelSelectionReceiptConfigV1,
    key: SigningKey,
    saved: ProductEvaluationExecutionKeyV1,
    training: LearningIterationSnapshotV1,
    runtime: Handle,
    fenced: bool,
}

#[derive(Clone, Debug, Eq, PartialEq)]
struct Prepared {
    observation: LearningIterationObservationV1,
    bundle: IndependentEvaluationBundleV1,
}

#[derive(Clone, Copy)]
enum Use {
    NewAttestation,
    Readback,
}

impl<W: AnchorWitnessStore> OriginalCircuitModelSelectionReceiptOwnerV1<W> {
    /// Construct while entered in the host's retained runtime, then call the
    /// synchronous methods only from its bounded blocking lane. No runtime,
    /// files, evidence owners, signing keys or witnesses are provisioned here.
    pub fn create(
        file: File,
        witness: W,
        config: OriginalCircuitModelSelectionReceiptConfigV1,
        key: SigningKey,
    ) -> Result<Self, Error> {
        let (saved, training) = binding::validate_config(&config, &key)?;
        let runtime = Handle::try_current()
            .map_err(|_| OwnerError::Binding("original Model owner runtime"))?;
        let journal = LearningOwnerJournalV1::create(file, witness, saved.binding_digest)?;
        Ok(Self {
            journal,
            config,
            key,
            saved,
            training,
            runtime,
            fenced: false,
        })
    }

    /// Recover only the exact original witness, evidence and key. Pending stays
    /// unresolved and every completed signature retains its original window.
    pub fn recover(
        file: File,
        witness: W,
        config: OriginalCircuitModelSelectionReceiptConfigV1,
        key: SigningKey,
    ) -> Result<Self, Error> {
        let (saved, training) = binding::validate_config(&config, &key)?;
        let runtime = Handle::try_current()
            .map_err(|_| OwnerError::Binding("original Model owner runtime"))?;
        let journal = LearningOwnerJournalV1::recover(file, witness, saved.binding_digest)?;
        Ok(Self {
            journal,
            config,
            key,
            saved,
            training,
            runtime,
            fenced: false,
        })
    }

    /// Observe and attest an already committed positive Model publication.
    /// Call only in the host's bounded blocking lane, never an async worker.
    /// A missing result may claim once. NoUpdate has a different concrete owner.
    pub fn attest_original_selection<
        C: AnchorWitnessStore,
        TW: AnchorWitnessStore + Send + 'static,
        RW: AnchorWitnessStore + Send + 'static,
        MW: AnchorWitnessStore,
        S: codex_hepta_intelligence_eval::FinalHoldoutCasStoreV1,
        EC: AnchorWitnessStore,
        EF: AnchorWitnessStore,
        EW: AnchorWitnessStore,
    >(
        &mut self,
        mut source: OriginalCircuitModelSelectionReceiptSourcesV1<'_, C, TW, RW, MW, S, EC, EF, EW>,
    ) -> Result<(LearningIterationReceiptV1, SignedLearningEvidenceV1), Error> {
        let started_at = binding::now()?;
        if self.fenced {
            return Err(OwnerError::CommitUncertain.into());
        }
        if source.snapshot.receipts.len() > self.config.decision.receipts.len() {
            return self.read_original(&mut source, started_at);
        }
        match self.journal.read(&self.saved) {
            Ok(_) => return self.read_original(&mut source, started_at),
            Err(OwnerError::Store(ProductEvaluationExecutionStoreErrorV1::Missing)) => {}
            Err(error) => return Err(error.into()),
        }
        binding::new_work_time(&self.config, started_at, binding::now()?)?;
        let prepared = source.prepare(&self.config, &self.training, &mut self.fenced)?;
        let evidence = source.predecessors(&self.config, &self.runtime)?;
        if source.prepare(&self.config, &self.training, &mut self.fenced)? != prepared {
            self.fenced = true;
            return Err(OwnerError::CommitUncertain.into());
        }
        let claim_at = binding::now()?;
        binding::new_work_time(&self.config, started_at, claim_at)?;
        binding::authenticate(
            &self.config,
            &prepared,
            source.evaluation.timing(),
            &evidence,
            claim_at,
        )?;
        let config = &self.config;
        let key = &self.key;
        let identity = self.saved.binding_digest;
        let bytes = self.journal.commit_once(&self.saved, || {
            let issued_at = binding::now()?;
            binding::new_work_time(config, started_at, issued_at)?;
            let (training, evaluation) = binding::authenticate(
                config,
                &prepared,
                source.evaluation.timing(),
                &evidence,
                issued_at,
            )
            .map_err(|_| OwnerError::Binding("current original Model predecessors"))?;
            let receipt = binding::receipt(config, &prepared.observation, issued_at)
                .map_err(|_| OwnerError::Binding("original Model Selection receipt"))?;
            let payload = learning_iteration_receipt_signing_bytes_v1(&receipt)
                .map_err(|_| OwnerError::Binding("original Model Selection bytes"))?;
            let signed = binding::sign_original(config, key, &payload, identity, issued_at)?;
            let verified = config.verifier.verify(
                LearningEvidenceRoleV1::Selector,
                &signed,
                &payload,
                issued_at,
            )?;
            verify_signed_actor_separation(&training, &verified, issued_at)?;
            verify_signed_actor_separation(&evaluation, &verified, issued_at)?;
            learning_owner_evidence::encode(&payload, &signed)
        })?;
        self.authenticate_completed(
            &mut source,
            &prepared,
            &bytes,
            started_at,
            Use::NewAttestation,
        )
    }

    /// Read the original result after live Model, execution, evidence and
    /// publication checks. This cannot claim, sign, select, fit or publish.
    /// An expired work deadline allows only an already completed original result.
    pub fn readback<
        C: AnchorWitnessStore,
        TW: AnchorWitnessStore + Send + 'static,
        RW: AnchorWitnessStore + Send + 'static,
        MW: AnchorWitnessStore,
        S: codex_hepta_intelligence_eval::FinalHoldoutCasStoreV1,
        EC: AnchorWitnessStore,
        EF: AnchorWitnessStore,
        EW: AnchorWitnessStore,
    >(
        &mut self,
        mut source: OriginalCircuitModelSelectionReceiptSourcesV1<'_, C, TW, RW, MW, S, EC, EF, EW>,
    ) -> Result<(LearningIterationReceiptV1, SignedLearningEvidenceV1), Error> {
        let started_at = binding::now()?;
        if self.fenced {
            return Err(OwnerError::CommitUncertain.into());
        }
        self.read_original(&mut source, started_at)
    }

    fn read_original<
        C: AnchorWitnessStore,
        TW: AnchorWitnessStore + Send + 'static,
        RW: AnchorWitnessStore + Send + 'static,
        MW: AnchorWitnessStore,
        S: codex_hepta_intelligence_eval::FinalHoldoutCasStoreV1,
        EC: AnchorWitnessStore,
        EF: AnchorWitnessStore,
        EW: AnchorWitnessStore,
    >(
        &mut self,
        source: &mut OriginalCircuitModelSelectionReceiptSourcesV1<
            '_,
            C,
            TW,
            RW,
            MW,
            S,
            EC,
            EF,
            EW,
        >,
        started_at: u64,
    ) -> Result<(LearningIterationReceiptV1, SignedLearningEvidenceV1), Error> {
        let bytes = self.journal.read(&self.saved)?;
        let prepared = source.prepare(&self.config, &self.training, &mut self.fenced)?;
        self.authenticate_completed(source, &prepared, &bytes, started_at, Use::Readback)
    }

    fn authenticate_completed<
        C: AnchorWitnessStore,
        TW: AnchorWitnessStore + Send + 'static,
        RW: AnchorWitnessStore + Send + 'static,
        MW: AnchorWitnessStore,
        S: codex_hepta_intelligence_eval::FinalHoldoutCasStoreV1,
        EC: AnchorWitnessStore,
        EF: AnchorWitnessStore,
        EW: AnchorWitnessStore,
    >(
        &mut self,
        source: &mut OriginalCircuitModelSelectionReceiptSourcesV1<
            '_,
            C,
            TW,
            RW,
            MW,
            S,
            EC,
            EF,
            EW,
        >,
        prepared: &Prepared,
        bytes: &[u8],
        started_at: u64,
        use_kind: Use,
    ) -> Result<(LearningIterationReceiptV1, SignedLearningEvidenceV1), Error> {
        let (payload, signed) = learning_owner_evidence::decode(bytes)?;
        let receipt = binding::receipt(&self.config, &prepared.observation, signed.issued_at)?;
        if payload != learning_iteration_receipt_signing_bytes_v1(&receipt)?
            || source
                .snapshot
                .receipts
                .get(self.config.decision.receipts.len())
                .is_some_and(|original| original != &receipt)
        {
            return Err(OwnerError::Binding("changed original Model Selection receipt").into());
        }
        let evidence = source.predecessors(&self.config, &self.runtime)?;
        if source.prepare(&self.config, &self.training, &mut self.fenced)? != *prepared
            || self.journal.read(&self.saved)? != bytes
        {
            self.fenced = true;
            return Err(OwnerError::CommitUncertain.into());
        }
        let current = binding::now()?;
        if current < started_at {
            return Err(
                OwnerError::Binding("original Model Selector clock moved backwards").into(),
            );
        }
        if matches!(use_kind, Use::NewAttestation) {
            binding::new_work_time(&self.config, started_at, current)?;
        }
        // No physical I/O follows this fresh verification of all original
        // stage, product and execution signatures, including their old windows.
        let (training, evaluation) = binding::authenticate(
            &self.config,
            prepared,
            source.evaluation.timing(),
            &evidence,
            current,
        )?;
        let verified = self.config.verifier.verify(
            LearningEvidenceRoleV1::Selector,
            &signed,
            &payload,
            current,
        )?;
        if verified.principal() != &self.config.signer.principal
            || verified.controller_id() != &self.config.signer.controller_id
            || signed.evidence_id != binding::evidence_id(self.saved.binding_digest)?
            || signed.expires_at != binding::signature_expiry(&self.config, signed.issued_at)?
        {
            return Err(OwnerError::Binding("original Model Selector identity").into());
        }
        verify_signed_actor_separation(&training, &verified, current)?;
        verify_signed_actor_separation(&evaluation, &verified, current)?;
        Ok((receipt, signed))
    }
}
