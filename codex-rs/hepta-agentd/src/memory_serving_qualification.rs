//! Promotion and rollback are different signed admissions. Restoring old tensor
//! bytes advances the SERVICE generation without rewriting training provenance.
use codex_hepta_intelligence_eval::VerifiedSelfEvolutionRollbackV1;
use codex_hepta_intelligence_eval::VerifiedSelfEvolutionSelectionV1;
use codex_hepta_learning_artifacts::ArtifactManifest;
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;

use super::SharedMemoryTrainingError;

#[derive(Clone, Debug)]
pub enum MemoryServingQualificationV1 {
    Selected(VerifiedSelfEvolutionSelectionV1),
    Rollback(VerifiedSelfEvolutionRollbackV1),
}
impl MemoryServingQualificationV1 {
    pub(crate) fn route_generation(&self) -> Generation {
        match self {
            Self::Selected(value) => value.receipt().candidate_generation,
            Self::Rollback(value) => value.rollback_generation(),
        }
    }
    pub(crate) fn digest(&self) -> Digest32 {
        match self {
            Self::Selected(value) => value.selection_digest(),
            Self::Rollback(value) => value.rollback_digest(),
        }
    }
    pub(crate) fn matches(&self, manifest: &ArtifactManifest) -> bool {
        match self {
            Self::Selected(value) => {
                let receipt = value.receipt();
                receipt.minimum_dataset_records >= 200
                    && manifest.artifact_id == receipt.candidate_id
                    && manifest.content_digest == receipt.candidate_artifact_digest
                    && manifest.generation == receipt.candidate_generation
                    && manifest.objective_digest == receipt.objective_digest
                    && manifest.support_digest == receipt.dataset_digest
            }
            Self::Rollback(value) => {
                let receipt = value.selection().receipt();
                receipt.minimum_dataset_records >= 200
                    && manifest.artifact_id == receipt.predecessor_id
                    && manifest.content_digest == receipt.predecessor_artifact_digest
                    && manifest.generation == receipt.predecessor_generation
                    && manifest.objective_digest == receipt.objective_digest
                    && value.rollback_generation() > receipt.candidate_generation
                // The predecessor's own dataset is checked by selected load and
                // the actual source/ledger owners, not replaced by successor data.
            }
        }
    }
    pub(crate) fn revalidate_current(&self, verifier: &LearningEvidenceVerifierV1, now: u64) -> Result<(), SharedMemoryTrainingError> {
        let result = match self {
            Self::Selected(value) => value.revalidate_current(verifier, now),
            Self::Rollback(value) => value.revalidate_current(verifier, now),
        };
        result.map_err(|_| SharedMemoryTrainingError::Invalid("stale memory qualification"))
    }
}
