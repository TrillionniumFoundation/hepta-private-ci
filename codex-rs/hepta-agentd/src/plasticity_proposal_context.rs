//! References already owned by the existing plasticity host. No stores, grants
//! or execution paths are created by grouping these former function arguments.
use crate::AgentdPlasticityAnchorStoreV1;
use crate::PlasticityOwnerEvidencePolicyV1;
use crate::PlasticityOwnerEvidenceResolverV1;
use codex_hepta_intelligence::AnchoredPlasticityWriterV1;
use codex_hepta_learning_artifacts::ArtifactRegistry;
use codex_hepta_learning_ledger::DurableLedger;
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;

pub struct AgentdPlasticityProposalContextV1<'a> {
    pub artifacts: &'a ArtifactRegistry,
    pub ledger: &'a DurableLedger,
    pub owner_evidence_resolver: &'a dyn PlasticityOwnerEvidenceResolverV1,
    pub owner_evidence_policy: &'a PlasticityOwnerEvidencePolicyV1,
    pub verifier: &'a LearningEvidenceVerifierV1,
    pub writer: &'a mut AnchoredPlasticityWriterV1,
    pub anchor_store: &'a mut AgentdPlasticityAnchorStoreV1,
}
