use codex_hepta_intelligence::AnchoredPlasticityWriterV1;
use codex_hepta_learning_artifacts::ArtifactRegistry;
use codex_hepta_learning_ledger::DurableLedger;
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;

use super::AgentdPlasticityAnchorStoreV1;
use super::PlasticityOwnerEvidencePolicyV1;
use super::PlasticityOwnerEvidenceResolverV1;

/// Current owner stores and authority inputs used to admit one proposal.
/// The host revalidates their frontiers before the authenticated product adapter
/// can commit through the retained writer and anchor store.
pub struct AgentdPlasticityProposalContextV1<'a> {
    pub artifacts: &'a ArtifactRegistry,
    pub ledger: &'a DurableLedger,
    pub owner_evidence_resolver: &'a dyn PlasticityOwnerEvidenceResolverV1,
    pub owner_evidence_policy: &'a PlasticityOwnerEvidencePolicyV1,
    pub verifier: &'a LearningEvidenceVerifierV1,
    pub writer: &'a mut AnchoredPlasticityWriterV1,
    pub anchor_store: &'a mut AgentdPlasticityAnchorStoreV1,
}
