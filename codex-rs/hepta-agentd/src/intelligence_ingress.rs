//! Host-owned canonical intelligence invocation at the existing ObjectiveStart boundary.
//!
//! The daemon wire carries the authenticated objective. It never carries the
//! seven owners' internal profiles, model state, current artifacts, trust
//! material, policy evidence, or ledger predecessor. A composition owner derives
//! those inputs from the already-durable RunStart record and the current owner
//! generation.

use codex_hepta_intelligence::CanonicalIntelligenceRunRequestV1;
use codex_hepta_intelligence::IntuitionQualificationEvidenceV2;
use codex_hepta_intuition::AssignmentCommitmentV2;
use codex_hepta_intuition::CanonicalPolicyProfileV1;
use codex_hepta_intuition::ScoringCommitmentV2;
use codex_hepta_learning_ledger::RunStartRecordV1;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_types::Digest32;

use crate::AgentdError;
use crate::AgentdIdentity;
use crate::AgentdIntelligenceOwnerInputsV1;

/// Host-owned authenticated product material for the intuition stage.
///
/// This value is built by the same trusted invocation provider that supplies the
/// seven canonical owner inputs. Request/wire callers cannot choose a policy
/// profile, signer evidence, assignment draw, or learning-ledger predecessor.
pub struct AgentdIntuitionProductInvocationV1 {
    pub profile: CanonicalPolicyProfileV1,
    pub scoring: ScoringCommitmentV2,
    pub assignment: AssignmentCommitmentV2,
    pub completeness_evidence: SignedLearningEvidenceV1,
    pub profile_qualification_evidence: SignedLearningEvidenceV1,
    pub runtime_evidence: SignedLearningEvidenceV1,
    pub expected_ledger_head: Digest32,
    pub decision_evidence: Option<SignedLearningEvidenceV1>,
}

impl AgentdIntuitionProductInvocationV1 {
    #[must_use]
    pub fn qualification(&self) -> IntuitionQualificationEvidenceV2<'_> {
        IntuitionQualificationEvidenceV2 {
            completeness: &self.completeness_evidence,
            profile_qualification: &self.profile_qualification_evidence,
            runtime: &self.runtime_evidence,
        }
    }
}

pub struct AgentdIntelligenceInvocationV1 {
    pub request: CanonicalIntelligenceRunRequestV1,
    pub inputs: AgentdIntelligenceOwnerInputsV1,
    /// `None` is explicit compatibility mode and is accepted only when no
    /// intuition product host is attached to Agentd.
    pub intuition_product: Option<AgentdIntuitionProductInvocationV1>,
}

impl AgentdIntelligenceInvocationV1 {
    pub(crate) fn validate(
        &self,
        identity: &AgentdIdentity,
        record: &RunStartRecordV1,
    ) -> Result<(), AgentdError> {
        let snapshot = &record.snapshot;
        if self.request.run_id != snapshot.run_id
            || self.request.snapshot.objective_digest() != snapshot.objective_digest
            || self.request.snapshot.authority_epoch() != snapshot.authority_epoch
            || self.request.snapshot.body_generation().get() != snapshot.generation
            || self.request.legal_candidates.state_digest != snapshot.objective_digest
            || snapshot.generation != identity.spawn_generation
        {
            return Err(AgentdError::Invalid(
                "canonical intelligence invocation does not match the durable RunStart identity"
                    .to_string(),
            ));
        }

        if let Some(product) = &self.intuition_product {
            let request = &self.inputs.intuition_request;
            if request.objective_digest != snapshot.objective_digest
                || product.profile.policy_digest != request.policy_digest
                || product.scoring.policy_digest != request.policy_digest
                || product.profile.objective_class_digest != request.objective_class_digest
                || product.profile.generation != request.policy_generation
                || product.scoring.policy_generation.get() != request.policy_generation
                || product.profile.calibration_artifact_digest
                    != request.calibration.artifact_digest
                || product.profile.ood_artifact_digest != request.ood.artifact_digest
            {
                return Err(AgentdError::Invalid(
                    "intuition product material does not match the durable canonical invocation"
                        .to_string(),
                ));
            }
            for evidence in [
                &product.completeness_evidence,
                &product.profile_qualification_evidence,
                &product.runtime_evidence,
            ] {
                if evidence.objective_digest != request.objective_digest {
                    return Err(AgentdError::Invalid(
                        "intuition qualification evidence does not match the durable objective"
                            .to_string(),
                    ));
                }
            }
            if product
                .decision_evidence
                .as_ref()
                .is_some_and(|evidence| evidence.objective_digest != request.objective_digest)
            {
                return Err(AgentdError::Invalid(
                    "intuition Decision evidence does not match the durable objective".to_string(),
                ));
            }
        }
        Ok(())
    }
}

/// Composition seam for the seven canonical intelligence owners.
///
/// Implementations are host-owned and must derive current stage inputs from
/// their authoritative owners. Request/wire callers cannot provide this object
/// and therefore cannot substitute policy, model, artifact, trust, currentness,
/// signer evidence, or learning-ledger predecessor inputs.
pub trait AgentdIntelligenceInvocationProviderV1: Send + Sync {
    fn build(
        &self,
        identity: &AgentdIdentity,
        record: &RunStartRecordV1,
    ) -> Result<AgentdIntelligenceInvocationV1, AgentdError>;
}
