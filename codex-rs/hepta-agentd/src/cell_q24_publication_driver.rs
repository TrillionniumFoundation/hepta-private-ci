//! Execute a learning decision with the existing artifact, CURRENT and FinalUse
//! owners. This embedded-host entry neither acquires those capabilities nor
//! constructs a Root publication lane. The separately purpose-bound original
//! Root handoff can supply CURRENT; all signatures remain inputs
//! from their original, separately authorized issuers.
//! Retention is not rollback. A later rollback requires a new original operation
//! and generation with its own selected artifact and exact FinalUse grant.

use std::sync::Arc;

use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_learning_artifacts::ArtifactPublicationReceiptV1;
use codex_hepta_learning_artifacts::ArtifactSelectionVerifierV1;
use codex_hepta_learning_artifacts::LearningArtifactPublishRequestV1;
use codex_hepta_learning_artifacts::LearningIterationSnapshotV1;
use codex_hepta_learning_artifacts::SignedArtifactSelectionV1;
use codex_hepta_neuron::CellBackendManifestV2;
use codex_hepta_neuron::CellDefinitionV1;
use codex_hepta_neuron::FileAnchorWitnessStore;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::AgentdError;
use crate::AgentdGenerationSelectionFilesV1;
use crate::AgentdGenerationUpdateAuthoritiesV1;
use crate::AgentdGenerationUpdatePredecessorFilesV1;
use crate::AgentdGenerationUpdateRecoveryV1;
use crate::AgentdGenerationUpdateRequestV1;
use crate::AgentdGenerationUpdateTargetV1;
use crate::AgentdIdentity;
use crate::AgentdSelectedGenerationV1;
use crate::CircuitFeaturePredecessorFilesV1;
use crate::CircuitTaskSourceInputV1;
use crate::CircuitTaskSourceReadbackV1;
use crate::LearningIterationStageOwnerPortsV1;
use crate::LoadedCellQ24ModelV1;
use crate::NeuronGenerationCurrentOwnerV1;
use crate::OriginalCellQ24LearningStageOwnersV1;
use crate::PreparedAgentdGenerationUpdateV1;
use crate::PublishedCircuitFeatureCompletionV1;
use crate::PublishedCircuitFeatureTaskV1;

#[path = "cell_q24_publication_current.rs"]
mod current;
#[path = "cell_q24_publication_validation.rs"]
pub(crate) mod validation;
use validation::Decision;
#[path = "cell_q24_publication_root_stage.rs"]
mod root_stage;
pub use root_stage::OriginalCellQ24ArtifactPublicationDriverV1;
pub use root_stage::OriginalCellQ24PublishedArtifactForRootV1;
pub use root_stage::OriginalCellQ24RetainedArtifactForRootV1;
pub use root_stage::OriginalCellQ24RootPublicationDriverV1;
pub use root_stage::OriginalCellQ24SelectedArtifactForRootV1;
pub(crate) use root_stage::OriginalSuccessorPublication;
pub(crate) use root_stage::require_successor_admission;

#[derive(Debug, thiserror::Error)]
pub enum OriginalCellQ24PublicationErrorV1 {
    #[error("original Q24 publication binding: {0}")]
    Binding(&'static str),
    #[error("original Q24 learning owner: {0}")]
    Learning(#[from] crate::LearningIterationRuntimeErrorV1),
    #[error("original publication owner: {0}")]
    Owner(#[from] AgentdError),
    #[error("original artifact publication: {0}")]
    Artifact(#[from] codex_hepta_learning_artifacts::LearningArtifactOwnerServiceError),
    #[error("publication completion is uncertain; recover the original operation")]
    CommitUncertain,
}
type Error = OriginalCellQ24PublicationErrorV1;

/// Independent selection and immutable files. A Learning Selector signature is
/// not an artifact selection; the original artifact verifier checks this input.
pub struct OriginalCellQ24SelectionInputsV1 {
    pub verifier: ArtifactSelectionVerifierV1,
    pub signed: SignedArtifactSelectionV1,
    pub files: AgentdGenerationSelectionFilesV1,
}

/// Actual completed predecessor and exact ordinary C task, frozen before any
/// generation preparation or request for a FinalUse grant. Keep a clone of the
/// actual loaded model for the later ordinary C runtime configuration.
pub struct OriginalCellQ24FeatureTargetV1 {
    pub target: AgentdGenerationUpdateTargetV1<FileAnchorWitnessStore>,
    pub definition: CellDefinitionV1,
    pub source: CircuitTaskSourceInputV1,
    pub model: Arc<LoadedCellQ24ModelV1>,
    pub previous: PublishedCircuitFeatureCompletionV1,
}

/// Cold recovery reads existing original files, not a retained completion token.
pub struct OriginalCellQ24FeatureRecoveryV1 {
    pub target: AgentdGenerationUpdateTargetV1<FileAnchorWitnessStore>,
    pub definition: CellDefinitionV1,
    pub source: CircuitTaskSourceInputV1,
    pub model: Arc<LoadedCellQ24ModelV1>,
    pub predecessor: CircuitFeaturePredecessorFilesV1<FileAnchorWitnessStore>,
    pub original_source: Arc<CircuitTaskSourceReadbackV1<FileAnchorWitnessStore>>,
    pub original_identity: AgentdIdentity,
    pub intent_digest: Digest32,
}

struct OriginalDecision {
    owners: Arc<OriginalCellQ24LearningStageOwnersV1>,
    decision: Decision,
    manifest: Option<CellBackendManifestV2>,
}

impl OriginalDecision {
    fn load_selected(
        &self,
        authorities: &AgentdGenerationUpdateAuthoritiesV1,
        input: OriginalCellQ24SelectionInputsV1,
        publication: Option<&ArtifactPublicationReceiptV1>,
    ) -> Result<AgentdSelectedGenerationV1, Error> {
        validation::signed_selection(&self.decision, &input.signed, publication)?;
        let artifacts = authorities
            .artifacts
            .writer()?
            .lock()
            .map_err(|_| Error::CommitUncertain)?;
        let selected = AgentdSelectedGenerationV1::load(
            &artifacts,
            input.verifier,
            input.signed,
            input.files,
            authorities.now()?,
        )?;
        crate::cell_composed_q24::validate_manifest(&self.decision.bundle, selected.manifest())
            .map_err(|_| Error::Binding("selected complete Q24 manifest"))?;
        Ok(selected)
    }

    async fn require_current(&self) -> Result<(), Error> {
        self.owners
            .validate_recovery(&self.decision.snapshot)
            .await?;
        if let Some(expected) = &self.manifest
            && self
                .owners
                .original_publication_manifest(&self.decision.snapshot)
                .await?
                != *expected
        {
            return Err(Error::Binding("original B full manifest changed"));
        }
        self.owners.require_current().await?;
        Ok(())
    }
}

/// Holds actual owners and a currently authenticated decision. Construction
/// from a snapshot alone is impossible. The host must already own Root CURRENT;
/// a non-Root daemon cannot manufacture it from this driver's public data.
pub struct OriginalCellQ24PublicationDriverV1 {
    original: OriginalDecision,
    current: Arc<NeuronGenerationCurrentOwnerV1>,
    authorities: AgentdGenerationUpdateAuthoritiesV1,
}

/// Artifact publication has actually completed, or the authenticated decision
/// retains the existing model. Neither branch has consumed FinalUse yet.
pub struct OriginalCellQ24SelectionDriverV1 {
    driver: OriginalCellQ24PublicationDriverV1,
    publication: Option<ArtifactPublicationReceiptV1>,
}

/// Owns the exclusive predecessor/target journals across exact grant issuance.
/// An uncertain finish consumes this value; it cannot automatically retry.
pub struct OriginalCellQ24PreparedPublicationV1 {
    original: OriginalDecision,
    prepared: PreparedAgentdGenerationUpdateV1<FileAnchorWitnessStore, FileAnchorWitnessStore>,
    definition: CellDefinitionV1,
    source: CircuitTaskSourceInputV1,
    model: Arc<LoadedCellQ24ModelV1>,
    target_manifest: CellBackendManifestV2,
    previous: PublishedCircuitFeatureCompletionV1,
}

impl OriginalCellQ24PublicationDriverV1 {
    /// Supply the checkpoint's original decision prefix, before the real
    /// Selection/NextUse receipts. Full recovery still authenticates that exact
    /// prefix through the original owners; removing a tail grants no authority.
    pub async fn from_original_owners(
        owners: Arc<OriginalCellQ24LearningStageOwnersV1>,
        snapshot: LearningIterationSnapshotV1,
        current: Arc<NeuronGenerationCurrentOwnerV1>,
        authorities: AgentdGenerationUpdateAuthoritiesV1,
    ) -> Result<Self, Error> {
        let decision = Decision::new(snapshot)?;
        owners.validate_recovery(&decision.snapshot).await?;
        let manifest = if decision.adopts() {
            Some(
                owners
                    .original_publication_manifest(&decision.snapshot)
                    .await?,
            )
        } else {
            None
        };
        let original: OriginalDecision = OriginalDecision {
            owners,
            decision,
            manifest,
        };
        original.require_current().await?;
        Ok(Self {
            original,
            current,
            authorities,
        })
    }

    /// Public signing context only; it cannot reconstruct this owner.
    pub fn artifact_operation_id(&self) -> &StableId {
        &self.original.decision.artifact_operation
    }

    /// Exact material read from original B, for its existing artifact issuer.
    /// Retention has no new artifact. Returning these bytes grants no write role.
    pub fn candidate_manifest(&self) -> Option<&CellBackendManifestV2> {
        self.original.manifest.as_ref()
    }

    pub fn selected_bundle(&self) -> &codex_hepta_learning_artifacts::CellCompatibilityBundleV1 {
        &self.original.decision.bundle
    }

    /// Exact existing CURRENT operation to retain for explicit cold recovery.
    pub fn generation_operation_id(&self) -> &StableId {
        &self.original.decision.operation
    }

    /// Execute the real immutable artifact transaction under its existing writer
    /// fence. An exact saved request uses that service's original recovery rules.
    pub async fn publish_candidate(
        self,
        mut request: LearningArtifactPublishRequestV1,
    ) -> Result<
        (
            OriginalCellQ24SelectionDriverV1,
            ArtifactPublicationReceiptV1,
        ),
        Error,
    > {
        let original: &OriginalDecision = &self.original;
        original.require_current().await?;
        self.original.decision.require_new_work()?;
        validation::artifact_request(
            &self.original.decision,
            self.original
                .manifest
                .as_ref()
                .ok_or(Error::Binding("retained model has no new artifact"))?,
            &request,
        )?;
        let owners: Arc<OriginalCellQ24LearningStageOwnersV1> = Arc::clone(&self.original.owners);
        let snapshot = self.original.decision.snapshot.clone();
        let manifest = self.original.manifest.clone();
        let (driver, receipt) = owners.with_original_publication(snapshot, manifest, move || {
            self.original.decision.require_new_work()?;
            request.now = self.authorities.now()?;
            let receipt = {
                let mut locked = self.authorities.artifacts.writer()?.lock().map_err(|_| Error::CommitUncertain)?;
                let artifacts: &mut codex_hepta_learning_artifacts::LearningArtifactOwnerService = &mut locked;
                artifacts.publish(request)?
            };
            Ok::<_, Error>((self, receipt))
        }).await?;
        Ok((
            OriginalCellQ24SelectionDriverV1 {
                driver,
                publication: Some(receipt.clone()),
            },
            receipt,
        ))
    }

    /// Keep the actual selected parent for NoUpdate, RetainParent or Defer.
    /// This does not label policy retention as an evaluator's NoUpdate result.
    pub async fn retain_current(self) -> Result<OriginalCellQ24SelectionDriverV1, Error> {
        let original: &OriginalDecision = &self.original;
        original.require_current().await?;
        self.original.decision.require_new_work()?;
        if self.original.decision.adopts() {
            return Err(Error::Binding("candidate requires actual publication"));
        }
        Ok(OriginalCellQ24SelectionDriverV1 {
            driver: self,
            publication: None,
        })
    }

    fn load_selection(
        &self,
        input: OriginalCellQ24SelectionInputsV1,
        publication: Option<&ArtifactPublicationReceiptV1>,
    ) -> Result<AgentdSelectedGenerationV1, Error> {
        self.original
            .load_selected(&self.authorities, input, publication)
    }
}

#[cfg(test)]
#[path = "cell_q24_publication_driver_tests.rs"]
mod tests;
