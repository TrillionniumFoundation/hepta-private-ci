use std::error::Error as StdError;
use std::fmt;
use std::sync::Arc;

use codex_hepta_contracts::AgentId;
use codex_hepta_intelligence::AuthenticatedIntuitionDecisionV2;
use codex_hepta_intelligence::IntuitionQualificationError;
use codex_hepta_intelligence::IntuitionQualificationEvidenceV2;
use codex_hepta_intelligence::decide_authenticated_intuition_v2;
use codex_hepta_intuition::AssignmentCommitmentV1;
use codex_hepta_intuition::CalibratedDecisionRequestV1;
use codex_hepta_intuition::CanonicalPolicyProfileV1;
use codex_hepta_intuition::ScoringCommitmentV1;
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_types::Digest32;

/// Historical V1 owner pins retained for compatibility qualification.
///
/// Agentd only pins identities. Model bytes, scorer behavior, learning evidence
/// and RNG state remain with their authoritative owners.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AgentdIntuitionPolicyPinsV1 {
    pub model_artifact_digest: Digest32,
    pub scorer_contract_digest: Digest32,
    pub rng_owner_digest: Option<Digest32>,
}

/// Compatibility-only host. The canonical product runner requires
/// `AgentdIntuitionPolicyHostV2` with a selected profile and current trust frontier.
pub struct AgentdIntuitionPolicyHostV1 {
    agent_id: AgentId,
    spawn_generation: u64,
    verifier: Arc<LearningEvidenceVerifierV1>,
    pins: AgentdIntuitionPolicyPinsV1,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AgentdIntuitionDecisionReceiptV1 {
    pub decision: AuthenticatedIntuitionDecisionV2,
    pub host_binding_digest: Digest32,
}

#[derive(Debug)]
pub enum AgentdIntuitionPolicyError {
    InvalidHost(&'static str),
    GenerationFence,
    ModelPinMismatch,
    ScorerPinMismatch,
    RngOwnerPinMismatch,
    Qualification(IntuitionQualificationError),
}

impl fmt::Display for AgentdIntuitionPolicyError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for AgentdIntuitionPolicyError {}

impl From<IntuitionQualificationError> for AgentdIntuitionPolicyError {
    fn from(value: IntuitionQualificationError) -> Self {
        Self::Qualification(value)
    }
}

impl AgentdIntuitionPolicyHostV1 {
    pub fn new(
        agent_id: AgentId,
        spawn_generation: u64,
        verifier: Arc<LearningEvidenceVerifierV1>,
        pins: AgentdIntuitionPolicyPinsV1,
    ) -> Result<Self, AgentdIntuitionPolicyError> {
        if spawn_generation == 0 {
            return Err(AgentdIntuitionPolicyError::GenerationFence);
        }
        if pins.model_artifact_digest.is_zero() {
            return Err(AgentdIntuitionPolicyError::InvalidHost(
                "model artifact pin",
            ));
        }
        if pins.scorer_contract_digest.is_zero() {
            return Err(AgentdIntuitionPolicyError::InvalidHost(
                "scorer contract pin",
            ));
        }
        if pins
            .rng_owner_digest
            .is_some_and(codex_hepta_types::Digest32::is_zero)
        {
            return Err(AgentdIntuitionPolicyError::InvalidHost("rng owner pin"));
        }
        Ok(Self {
            agent_id,
            spawn_generation,
            verifier,
            pins,
        })
    }

    pub fn require_identity(
        &self,
        agent_id: &AgentId,
        spawn_generation: u64,
    ) -> Result<(), AgentdIntuitionPolicyError> {
        if agent_id != &self.agent_id || spawn_generation != self.spawn_generation {
            return Err(AgentdIntuitionPolicyError::GenerationFence);
        }
        Ok(())
    }

    #[allow(clippy::too_many_arguments)]
    pub fn decide(
        &self,
        agent_id: &AgentId,
        spawn_generation: u64,
        request: CalibratedDecisionRequestV1,
        profile: CanonicalPolicyProfileV1,
        scoring: ScoringCommitmentV1,
        assignment: AssignmentCommitmentV1,
        evidence: IntuitionQualificationEvidenceV2<'_>,
        now: u64,
    ) -> Result<AgentdIntuitionDecisionReceiptV1, AgentdIntuitionPolicyError> {
        self.require_identity(agent_id, spawn_generation)?;
        if profile.scorer.model_digest != self.pins.model_artifact_digest
            || scoring.model_artifact_digest != self.pins.model_artifact_digest
        {
            return Err(AgentdIntuitionPolicyError::ModelPinMismatch);
        }
        if profile.scorer.scorer_contract_digest != self.pins.scorer_contract_digest
            || scoring.scorer_contract_digest != self.pins.scorer_contract_digest
        {
            return Err(AgentdIntuitionPolicyError::ScorerPinMismatch);
        }
        match (&assignment, self.pins.rng_owner_digest) {
            (AssignmentCommitmentV1::Deterministic, _) => {}
            (
                AssignmentCommitmentV1::CounterBased {
                    rng_owner_digest, ..
                },
                Some(expected),
            ) if *rng_owner_digest == expected => {}
            (AssignmentCommitmentV1::CounterBased { .. }, _) => {
                return Err(AgentdIntuitionPolicyError::RngOwnerPinMismatch);
            }
        }

        let decision = decide_authenticated_intuition_v2(
            request,
            profile,
            scoring,
            assignment,
            evidence,
            &self.verifier,
            now,
        )?;
        let agent = self.agent_id.to_string();
        let mut bytes = b"hepta.agentd.authenticated-intuition.v1\0".to_vec();
        bytes.extend_from_slice(&(agent.len() as u64).to_be_bytes());
        bytes.extend_from_slice(agent.as_bytes());
        bytes.extend_from_slice(&self.spawn_generation.to_be_bytes());
        bytes.extend_from_slice(self.verifier.trust_digest().as_array());
        bytes.extend_from_slice(self.pins.model_artifact_digest.as_array());
        bytes.extend_from_slice(self.pins.scorer_contract_digest.as_array());
        match self.pins.rng_owner_digest {
            Some(digest) => {
                bytes.push(1);
                bytes.extend_from_slice(digest.as_array());
            }
            None => bytes.push(0),
        }
        bytes.extend_from_slice(decision.authentication_digest.as_array());
        Ok(AgentdIntuitionDecisionReceiptV1 {
            decision,
            host_binding_digest: Digest32::of_bytes(&bytes),
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use codex_hepta_learning_ledger::AuthenticatedPrincipalV1;
    use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
    use codex_hepta_learning_ledger::LearningEvidenceTrustV1;
    use codex_hepta_learning_ledger::TrustedLearningSignerV1;
    use codex_hepta_types::StableId;
    use ed25519_dalek::SigningKey;

    fn digest(value: &str) -> Digest32 {
        Digest32::of_bytes(value.as_bytes())
    }

    fn id(value: &str) -> StableId {
        StableId::new(value).expect("stable id")
    }

    #[test]
    fn host_identity_and_owner_pins_fail_closed_before_policy_admission() {
        let agent_id = AgentId::parse("019153a4-3088-7e03-a56a-9b1964f75dde").expect("agent id");
        let key = SigningKey::from_bytes(&[7; 32]);
        let scope = digest("scope");
        let principal = AuthenticatedPrincipalV1 {
            principal_id: id("intuition-generator"),
            credential_chain_digest: digest("credentials"),
            signing_key_digest: Digest32::of_bytes(&key.verifying_key().to_bytes()),
            scope_digest: scope,
            authority_epoch: 1,
            authenticated_at: 1,
            expires_at: 100,
        };
        let verifier = Arc::new(
            LearningEvidenceVerifierV1::new(LearningEvidenceTrustV1 {
                scope_digest: scope,
                objective_digest: digest("objective"),
                authority_epoch: 1,
                signers: vec![TrustedLearningSignerV1 {
                    principal,
                    controller_id: id("intuition-generator-controller"),
                    verifying_key: key.verifying_key().to_bytes(),
                    roles: vec![LearningEvidenceRoleV1::Generator],
                    revoked_at: None,
                }],
            })
            .expect("host trust"),
        );
        let host = AgentdIntuitionPolicyHostV1::new(
            agent_id.clone(),
            7,
            verifier,
            AgentdIntuitionPolicyPinsV1 {
                model_artifact_digest: digest("model"),
                scorer_contract_digest: digest("scorer"),
                rng_owner_digest: Some(digest("rng-owner")),
            },
        )
        .expect("host");
        assert!(host.require_identity(&agent_id, 7).is_ok());
        assert!(matches!(
            host.require_identity(&agent_id, 8),
            Err(AgentdIntuitionPolicyError::GenerationFence)
        ));
    }
}
