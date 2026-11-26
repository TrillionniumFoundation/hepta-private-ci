//! Qualification includes complete independently adjudicated delivered evidence.
//! Rollback restores prior bytes at a newer route generation and must retain the
//! predecessor's own still-current citation gate; successor evidence is not reuse.
use std::collections::BTreeSet;

use codex_hepta_intelligence_eval::VerifiedMemoryCitationGateV1;
use codex_hepta_intelligence_eval::VerifiedSelfEvolutionRollbackV1;
use codex_hepta_intelligence_eval::VerifiedSelfEvolutionSelectionV1;
use codex_hepta_learning_artifacts::ArtifactManifest;
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;

use super::SharedMemoryTrainingError;

#[derive(Clone, Debug)]
enum Decision {
    Selected(VerifiedSelfEvolutionSelectionV1),
    Rollback(VerifiedSelfEvolutionRollbackV1),
}

/// No unchecked enum variant, Default or deserialization can bypass the census.
#[derive(Clone, Debug)]
pub struct MemoryServingQualificationV1 {
    decision: Decision,
    citations: VerifiedMemoryCitationGateV1,
}
impl MemoryServingQualificationV1 {
    pub fn selected(
        selection: VerifiedSelfEvolutionSelectionV1,
        citations: VerifiedMemoryCitationGateV1,
    ) -> Result<Self, SharedMemoryTrainingError> {
        if citations.decision_digest() != selection.selection_digest()
            || citations.candidate_digest() != selection.receipt().candidate_artifact_digest
            || citations.objective_digest() != selection.receipt().objective_digest
            || citations.dataset_digest() != selection.receipt().dataset_digest
        {
            return Err(SharedMemoryTrainingError::Invalid(
                "citation selection binding",
            ));
        }
        Ok(Self {
            decision: Decision::Selected(selection),
            citations,
        })
    }

    pub fn rollback(
        rollback: VerifiedSelfEvolutionRollbackV1,
        predecessor_citations: VerifiedMemoryCitationGateV1,
    ) -> Result<Self, SharedMemoryTrainingError> {
        let receipt = rollback.selection().receipt();
        if predecessor_citations.candidate_digest() != receipt.predecessor_artifact_digest
            || predecessor_citations.objective_digest() != receipt.objective_digest
        {
            return Err(SharedMemoryTrainingError::Invalid(
                "citation rollback binding",
            ));
        }
        Ok(Self {
            decision: Decision::Rollback(rollback),
            citations: predecessor_citations,
        })
    }

    pub(crate) fn route_generation(&self) -> Generation {
        match &self.decision {
            Decision::Selected(value) => value.receipt().candidate_generation,
            Decision::Rollback(value) => value.rollback_generation(),
        }
    }
    pub(crate) fn digest(&self) -> Digest32 {
        let decision = match &self.decision {
            Decision::Selected(value) => value.selection_digest(),
            Decision::Rollback(value) => value.rollback_digest(),
        };
        let mut bytes = b"hepta.memory-serving.qualification+citation.v1\0".to_vec();
        bytes.extend_from_slice(decision.as_array());
        bytes.extend_from_slice(self.citations.digest().as_array());
        Digest32::of_bytes(&bytes)
    }
    pub(crate) fn matches(&self, manifest: &ArtifactManifest) -> bool {
        if self.citations.candidate_digest() != manifest.content_digest
            || self.citations.dataset_digest() != manifest.support_digest
            || self.citations.objective_digest() != manifest.objective_digest
        {
            return false;
        }
        match &self.decision {
            Decision::Selected(value) => {
                let receipt = value.receipt();
                receipt.minimum_dataset_records >= 200
                    && manifest.artifact_id == receipt.candidate_id
                    && manifest.content_digest == receipt.candidate_artifact_digest
                    && manifest.generation == receipt.candidate_generation
                    && manifest.objective_digest == receipt.objective_digest
                    && manifest.support_digest == receipt.dataset_digest
            }
            Decision::Rollback(value) => {
                let receipt = value.selection().receipt();
                receipt.minimum_dataset_records >= 200
                    && manifest.artifact_id == receipt.predecessor_id
                    && manifest.content_digest == receipt.predecessor_artifact_digest
                    && manifest.generation == receipt.predecessor_generation
                    && manifest.objective_digest == receipt.objective_digest
                    && value.rollback_generation() > receipt.candidate_generation
            }
        }
    }
    pub(crate) fn revalidate_current(
        &self,
        verifier: &LearningEvidenceVerifierV1,
        withdrawn_audit_roots: &BTreeSet<Digest32>,
        now: u64,
    ) -> Result<(), SharedMemoryTrainingError> {
        let result = match &self.decision {
            Decision::Selected(value) => value.revalidate_current(verifier, now),
            Decision::Rollback(value) => value.revalidate_current(verifier, now),
        };
        result.map_err(|_| SharedMemoryTrainingError::Invalid("stale memory qualification"))?;
        self.citations
            .revalidate_current(verifier, withdrawn_audit_roots, now)
            .map_err(|_| SharedMemoryTrainingError::Invalid("stale memory citation evidence"))
    }
}
