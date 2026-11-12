//! Original durable Qualification publication over already completed execution.
//! The host transfers a separate file and independent witness. This owner has
//! no signing key or holdout provider. Original Product declarations remain
//! prerequisites supplied by their separately enrolled owners.
//!
//! Recovery is read-only, including an empty or Pending original journal.
//! A fresh instance admits at most one new dispatch; uncertain effects never
//! cause another claim, execution, signature or holdout release. Joint rollback
//! of original files and witnesses remains outside this boundary.

use std::fs::File;

use codex_hepta_intelligence_eval::IndependentEvaluationBundleV1;
use codex_hepta_intelligence_eval::LockedFileFinalHoldoutCasStoreV1;
use codex_hepta_intelligence_eval::OriginalProductEvaluationExecutionEvidenceV1;
use codex_hepta_intelligence_eval::ProductEvaluationError;
use codex_hepta_intelligence_eval::ProductEvaluationExecutionKeyV1;
use codex_hepta_intelligence_eval::ProductEvaluationExecutionStateV1;
use codex_hepta_intelligence_eval::ProductEvaluationExecutionStoreErrorV1;
use codex_hepta_intelligence_eval::ProductEvaluationExecutionStoreV1;
use codex_hepta_intelligence_eval::ProductQualificationContextV1;
use codex_hepta_intelligence_eval::ProductTimingEvidenceV1;
use codex_hepta_intelligence_eval::SignedEvaluationEvidenceV1;
use codex_hepta_learning_artifacts::FrozenLearningScopeV2;
use codex_hepta_learning_artifacts::LearningIterationError;
use codex_hepta_learning_artifacts::LearningIterationSnapshotV1;
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_learning_ledger::SignedEvidenceError;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_neuron::AnchorWitnessStore;

use crate::CellEvaluationErrorV1;
use crate::CellEvaluationPlanV1;
use crate::CellEvaluationQualificationRequestV1;
use crate::CellEvaluationQualificationV1;
use crate::CellEvaluationReceiptV1;
use crate::CellEvaluationRunnerV1;
use crate::LearningIterationRuntimeErrorV1;
use crate::OriginalCellEvaluationExecutionStoreErrorV1;
use crate::OriginalCellEvaluationExecutionStoreV1;

#[path = "neuron_cell_evaluation_qualification_binding.rs"]
mod binding;
#[path = "neuron_cell_evaluation_qualification_persist.rs"]
mod persist;
#[path = "neuron_cell_evaluation_qualification_readback.rs"]
mod readback;
#[path = "neuron_cell_evaluation_qualification_sources.rs"]
mod sources;
pub use sources::OriginalCellEvaluationQualificationSourcesV1;

#[path = "neuron_cell_evaluation_panel.rs"]
mod panel;
pub use panel::OriginalCellEvaluationPanelErrorV1;
pub use panel::OriginalCellEvaluationPanelMemberOwnersV1;
pub use panel::OriginalCellEvaluationPanelMemberReadbackV1;
pub use panel::OriginalCellEvaluationPanelOwnerV1;
pub use panel::OriginalCellEvaluationPanelReadbackV1;
pub use panel::OriginalCellEvaluationPanelRegistrationV1;
pub use panel::OriginalCellEvaluationPanelTaskV1;

#[derive(Debug, thiserror::Error)]
pub enum OriginalCellEvaluationQualificationErrorV1 {
    #[error("original Qualification binding: {0}")]
    Binding(&'static str),
    #[error("original Qualification is pending")]
    Pending,
    #[error("original Qualification outcome is uncertain")]
    CommitUncertain,
    #[error("original Qualification file and witness: {0}")]
    Owner(#[from] OriginalCellEvaluationExecutionStoreErrorV1),
    #[error("original Qualification record: {0}")]
    Store(#[from] ProductEvaluationExecutionStoreErrorV1),
    #[error("original Cell execution: {0}")]
    Cell(#[from] CellEvaluationErrorV1),
    #[error("original Product evidence: {0}")]
    Product(#[from] ProductEvaluationError),
    #[error("original Training cut: {0}")]
    Iteration(#[from] LearningIterationError),
    #[error("original Trainer connection: {0}")]
    Trainer(#[from] LearningIterationRuntimeErrorV1),
    #[error("original role evidence: {0}")]
    Evidence(#[from] SignedEvidenceError),
}
type Error = OriginalCellEvaluationQualificationErrorV1;
type StoreError = ProductEvaluationExecutionStoreErrorV1;
type State = ProductEvaluationExecutionStateV1;

/// A single original Qualification profile. All predecessor signatures are
/// pinned in full, including their original windows. Longitudinal evidence is
/// deliberately not synthesized from this profile.
#[derive(Clone)]
pub struct OriginalCellEvaluationQualificationConfigV1 {
    pub training: LearningIterationSnapshotV1,
    pub scope: FrozenLearningScopeV2,
    pub plan: CellEvaluationPlanV1,
    pub execution_namespace: codex_hepta_types::Digest32,
    pub qualification_namespace: codex_hepta_types::Digest32,
    pub context: ProductQualificationContextV1,
    pub training_evidence: SignedLearningEvidenceV1,
    pub product_evidence: SignedEvaluationEvidenceV1,
    pub execution_evidence: OriginalProductEvaluationExecutionEvidenceV1,
    pub verifier: LearningEvidenceVerifierV1,
}

/// No writable store, witness, sink or signing capability can be extracted.
pub struct OriginalCellEvaluationQualificationOwnerV1<W: AnchorWitnessStore> {
    journal: OriginalCellEvaluationExecutionStoreV1<W>,
    config: OriginalCellEvaluationQualificationConfigV1,
    saved: ProductEvaluationExecutionKeyV1,
    fresh_dispatch: bool,
    fenced: bool,
}

#[derive(Clone, Debug, Eq, PartialEq)]
struct Prepared {
    evaluation: CellEvaluationReceiptV1,
    bundle: IndependentEvaluationBundleV1,
}

impl<W: AnchorWitnessStore> OriginalCellEvaluationQualificationOwnerV1<W> {
    /// Initialize only the original empty Qualification file and empty witness.
    /// Partial initialization is retained for original-host reconciliation;
    /// recovery never creates or advances a missing or lagging witness.
    pub fn create(
        file: File,
        witness: W,
        config: OriginalCellEvaluationQualificationConfigV1,
    ) -> Result<Self, Error> {
        let saved = binding::validate_config(&config)?;
        let journal =
            OriginalCellEvaluationExecutionStoreV1::create(file, witness, saved.binding_digest)?;
        Ok(Self {
            journal,
            config,
            saved,
            fresh_dispatch: true,
            fenced: false,
        })
    }

    /// Strict exact-CURRENT recovery. This instance can only read existing
    /// Completed bytes; Missing and Pending never acquire a new effect.
    pub fn recover(
        file: File,
        witness: W,
        config: OriginalCellEvaluationQualificationConfigV1,
    ) -> Result<Self, Error> {
        let saved = binding::validate_config(&config)?;
        let journal =
            OriginalCellEvaluationExecutionStoreV1::recover(file, witness, saved.binding_digest)?;
        Ok(Self {
            journal,
            config,
            saved,
            fresh_dispatch: false,
            fenced: false,
        })
    }

    /// Persist the original independent decision once, or read its exact
    /// original Completed publication. No execution or signing interface is
    /// accepted. All work uses this owner's fixed original configuration.
    pub async fn qualify_or_readback(
        &mut self,
        mut source: OriginalCellEvaluationQualificationSourcesV1<
            '_,
            impl AnchorWitnessStore,
            impl AnchorWitnessStore,
            impl AnchorWitnessStore,
        >,
    ) -> Result<CellEvaluationQualificationV1, Error> {
        let started_at = binding::now()?;
        match self.state() {
            Ok(State::Completed(bytes)) => {
                return self.read_completed(&mut source, &bytes, started_at).await;
            }
            Ok(State::Pending) => return Err(Error::Pending),
            Err(Error::Store(StoreError::Missing)) => {}
            Err(error) => return Err(error),
        }
        if !self.fresh_dispatch {
            return Err(StoreError::Missing.into());
        }
        self.fresh_dispatch = false;
        let result = self.publish_once(&mut source, started_at).await;
        if result.is_err() {
            self.fenced = true;
        }
        result
    }

    async fn publish_once(
        &mut self,
        source: &mut OriginalCellEvaluationQualificationSourcesV1<
            '_,
            impl AnchorWitnessStore,
            impl AnchorWitnessStore,
            impl AnchorWitnessStore,
        >,
        started_at: u64,
    ) -> Result<CellEvaluationQualificationV1, Error> {
        binding::new_work_time(&self.config, started_at, binding::now()?)?;
        let prepared = source.prepare(&self.config, started_at).await?;
        let current = binding::now()?;
        binding::new_work_time(&self.config, started_at, current)?;
        binding::authenticate(&self.config, &prepared, current)?;
        let mut sink = persist::PersistPort {
            journal: &mut self.journal,
            config: &self.config,
            key: &self.saved,
            prepared: &prepared,
            started_at,
            used: false,
            error: None,
        };
        let runner: &CellEvaluationRunnerV1<LockedFileFinalHoldoutCasStoreV1> = source.runner;
        let result = runner.qualify_and_persist(
            &prepared.evaluation,
            CellEvaluationQualificationRequestV1 {
                context: &self.config.context,
                evidence: &self.config.product_evidence,
                timing: ProductTimingEvidenceV1::Qualification,
                verifier: &self.config.verifier,
                now: current,
            },
            &mut sink,
        );
        if let Some(error) = sink.error.take() {
            return Err(error);
        }
        let qualification = result?;
        drop(sink);
        let bytes = self.completed_bytes()?;
        let restored = self
            .finish_readback(source, &prepared, &bytes, started_at, true)
            .await?;
        if restored != qualification {
            return Err(Error::CommitUncertain);
        }
        Ok(restored)
    }

    fn state(&mut self) -> Result<State, Error> {
        if self.fenced {
            return Err(Error::CommitUncertain);
        }
        match ProductEvaluationExecutionStoreV1::readback(&mut self.journal, &self.saved) {
            Err(
                error @ (StoreError::Unavailable | StoreError::Indeterminate | StoreError::Corrupt),
            ) => {
                self.fenced = true;
                Err(error.into())
            }
            result => result.map_err(Error::from),
        }
    }

    fn completed_bytes(&mut self) -> Result<Vec<u8>, Error> {
        match self.state()? {
            State::Pending => Err(Error::Pending),
            State::Completed(bytes) => Ok(bytes),
        }
    }
}

pub use panel::OriginalCellEvaluationCommandClientV1;
pub use panel::OriginalCellEvaluationCommandConnectionV1;
pub use panel::OriginalCellEvaluationCommandErrorV1;
pub use panel::OriginalCellEvaluationCommandReceiptV1;
pub use panel::OriginalCellEvaluationHostV1;

pub use panel::OriginalCellEvaluationModelMaterialV1;
pub use panel::OriginalCellEvaluationModelMaterialConnectionV1;
pub use panel::OriginalCellEvaluationModelMaterialClientV1;
pub(crate) use panel::OriginalCellEvaluationModelInputV1;
