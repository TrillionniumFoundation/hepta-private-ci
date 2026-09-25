//! Host-selected authenticated intuition used by the canonical product runner.
//! Currentness input is crate-private and supplied only by the signed owner oracle.

use std::error::Error as StdError;
use std::fmt;
use std::sync::Arc;

use codex_hepta_contracts::AgentId;
use codex_hepta_intelligence::AuthenticatedIntuitionDecisionV3;
use codex_hepta_intelligence::CurrentOwnerStateV1;
use codex_hepta_intelligence::IntuitionQualificationError;
use codex_hepta_intelligence::IntuitionQualificationEvidenceV2;
use codex_hepta_intelligence::decide_authenticated_intuition_v3;
use codex_hepta_intuition::AssignmentCommitmentV1;
use codex_hepta_intuition::CalibratedDecisionRequestV1;
use codex_hepta_intuition::CanonicalPolicyProfileV1;
use codex_hepta_intuition::ScoringCommitmentV2;
use codex_hepta_intuition::canonical_policy_profile_digest_v1;
use codex_hepta_learning_ledger::ActivatedLearningTrustV1;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_types::Digest32;

#[derive(Clone, Debug)]
pub struct AgentdAuthenticatedIntuitionInputV1 {
    pub request: CalibratedDecisionRequestV1,
    pub profile: CanonicalPolicyProfileV1,
    pub scoring: ScoringCommitmentV2,
    pub assignment: AssignmentCommitmentV1,
    pub completeness: SignedLearningEvidenceV1,
    pub profile_qualification: SignedLearningEvidenceV1,
    pub runtime: SignedLearningEvidenceV1,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AgentdIntuitionPolicyPinsV2 {
    pub selected_profile_digest: Digest32,
    pub owner_implementation_digest: Digest32,
    pub policy_generation: u64,
    pub model_artifact_digest: Digest32,
    pub scorer_contract_digest: Digest32,
    pub rng_owner_digest: Option<Digest32>,
    pub trust_distribution_digest: Digest32,
    pub revocation_frontier_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub(crate) struct AgentdIntuitionCurrentBindingV1 {
    pub snapshot_digest: Digest32,
    pub authority_epoch: u64,
    pub revocation_frontier_digest: Digest32,
    pub owner: CurrentOwnerStateV1,
}

pub struct AgentdIntuitionPolicyHostV2 {
    agent_id: AgentId,
    spawn_generation: u64,
    trust: Arc<ActivatedLearningTrustV1>,
    pins: AgentdIntuitionPolicyPinsV2,
    retired: std::sync::atomic::AtomicBool,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AgentdIntuitionDecisionReceiptV2 {
    pub decision: AuthenticatedIntuitionDecisionV3,
    pub host_binding_digest: Digest32,
}

#[derive(Debug)]
pub enum AgentdIntuitionPolicyErrorV2 {
    InvalidHost(&'static str),
    GenerationFence,
    Retired,
    CurrentOwner,
    CurrentProfile,
    CurrentTrust,
    ModelPinMismatch,
    ScorerPinMismatch,
    RngOwnerPinMismatch,
    Qualification(IntuitionQualificationError),
}

impl fmt::Display for AgentdIntuitionPolicyErrorV2 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for AgentdIntuitionPolicyErrorV2 {}

impl From<IntuitionQualificationError> for AgentdIntuitionPolicyErrorV2 {
    fn from(value: IntuitionQualificationError) -> Self {
        Self::Qualification(value)
    }
}

impl AgentdIntuitionPolicyHostV2 {
    pub fn new(
        agent_id: AgentId,
        spawn_generation: u64,
        trust: Arc<ActivatedLearningTrustV1>,
        pins: AgentdIntuitionPolicyPinsV2,
    ) -> Result<Self, AgentdIntuitionPolicyErrorV2> {
        if spawn_generation == 0 {
            return Err(AgentdIntuitionPolicyErrorV2::GenerationFence);
        }
        for (label, digest) in [
            ("selected profile", pins.selected_profile_digest),
            ("owner implementation", pins.owner_implementation_digest),
            ("model artifact", pins.model_artifact_digest),
            ("scorer contract", pins.scorer_contract_digest),
            ("trust distribution", pins.trust_distribution_digest),
            (
                "selected revocation frontier",
                pins.revocation_frontier_digest,
            ),
        ] {
            if digest.is_zero() {
                return Err(AgentdIntuitionPolicyErrorV2::InvalidHost(label));
            }
        }
        if pins.policy_generation == 0
            || pins
                .rng_owner_digest
                .is_some_and(codex_hepta_types::Digest32::is_zero)
            || pins.trust_distribution_digest != trust.distribution_digest()
        {
            return Err(AgentdIntuitionPolicyErrorV2::CurrentTrust);
        }
        Ok(Self {
            agent_id,
            spawn_generation,
            trust,
            pins,
            retired: std::sync::atomic::AtomicBool::new(false),
        })
    }

    /// A signed current-owner mismatch permanently fences this host instance.
    pub(crate) fn retire(&self) {
        self.retired
            .store(true, std::sync::atomic::Ordering::SeqCst);
    }

    fn require_identity(
        &self,
        agent_id: &AgentId,
        spawn_generation: u64,
    ) -> Result<(), AgentdIntuitionPolicyErrorV2> {
        if self.retired.load(std::sync::atomic::Ordering::SeqCst) {
            return Err(AgentdIntuitionPolicyErrorV2::Retired);
        }
        if agent_id != &self.agent_id || spawn_generation != self.spawn_generation {
            return Err(AgentdIntuitionPolicyErrorV2::GenerationFence);
        }
        Ok(())
    }

    pub(crate) fn decide(
        &self,
        agent_id: &AgentId,
        spawn_generation: u64,
        current: AgentdIntuitionCurrentBindingV1,
        input: AgentdAuthenticatedIntuitionInputV1,
        now: u64,
    ) -> Result<AgentdIntuitionDecisionReceiptV2, AgentdIntuitionPolicyErrorV2> {
        self.require_identity(agent_id, spawn_generation)?;
        if current.revocation_frontier_digest != self.pins.revocation_frontier_digest {
            self.retire();
            return Err(AgentdIntuitionPolicyErrorV2::CurrentTrust);
        }
        if current.snapshot_digest.is_zero()
            || current.authority_epoch == 0
            || current.revocation_frontier_digest.is_zero()
            || current.owner.owner_id.as_str() != "intuition.policy"
            || current.owner.authority_epoch != current.authority_epoch
            || current.owner.revocation_frontier_digest != current.revocation_frontier_digest
        {
            return Err(AgentdIntuitionPolicyErrorV2::CurrentOwner);
        }
        let profile_digest = canonical_policy_profile_digest_v1(&input.profile)
            .map_err(IntuitionQualificationError::Policy)?;
        if profile_digest != self.pins.selected_profile_digest
            || input.profile.generation != self.pins.policy_generation
            || current.owner.implementation_digest != self.pins.owner_implementation_digest
            || current.owner.generation.get() != input.profile.generation
        {
            return Err(AgentdIntuitionPolicyErrorV2::CurrentProfile);
        }
        if current.owner.key_digest != self.trust.root_key_digest()
            || current.owner.key_epoch != self.trust.verifier().authority_epoch()
            || self.pins.trust_distribution_digest != self.trust.distribution_digest()
        {
            return Err(AgentdIntuitionPolicyErrorV2::CurrentTrust);
        }
        if input.profile.scorer.model_digest != self.pins.model_artifact_digest
            || input.scoring.model_artifact_digest != self.pins.model_artifact_digest
        {
            return Err(AgentdIntuitionPolicyErrorV2::ModelPinMismatch);
        }
        if input.profile.scorer.scorer_contract_digest != self.pins.scorer_contract_digest
            || input.scoring.scorer_contract_digest != self.pins.scorer_contract_digest
        {
            return Err(AgentdIntuitionPolicyErrorV2::ScorerPinMismatch);
        }
        match (&input.assignment, self.pins.rng_owner_digest) {
            (AssignmentCommitmentV1::Deterministic, _) => {}
            (
                AssignmentCommitmentV1::CounterBased {
                    rng_owner_digest, ..
                },
                Some(expected),
            ) if *rng_owner_digest == expected => {}
            (AssignmentCommitmentV1::CounterBased { .. }, _) => {
                return Err(AgentdIntuitionPolicyErrorV2::RngOwnerPinMismatch);
            }
        }

        let AgentdAuthenticatedIntuitionInputV1 {
            request,
            profile,
            scoring,
            assignment,
            completeness,
            profile_qualification,
            runtime,
        } = input;
        let decision = decide_authenticated_intuition_v3(
            request,
            profile,
            scoring,
            assignment,
            IntuitionQualificationEvidenceV2 {
                completeness: &completeness,
                profile_qualification: &profile_qualification,
                runtime: &runtime,
            },
            self.trust.verifier(),
            now,
        )?;
        self.require_identity(agent_id, spawn_generation)?;
        let agent = self.agent_id.to_string();
        let mut bytes = b"hepta.agentd.authenticated-intuition.v2\0".to_vec();
        bytes.extend_from_slice(&(agent.len() as u64).to_be_bytes());
        bytes.extend_from_slice(agent.as_bytes());
        bytes.extend_from_slice(&self.spawn_generation.to_be_bytes());
        bytes.extend_from_slice(current.snapshot_digest.as_array());
        bytes.extend_from_slice(&current.authority_epoch.to_be_bytes());
        bytes.extend_from_slice(current.revocation_frontier_digest.as_array());
        bytes.extend_from_slice(&current.owner.generation.get().to_be_bytes());
        bytes.extend_from_slice(current.owner.implementation_digest.as_array());
        bytes.extend_from_slice(current.owner.key_digest.as_array());
        bytes.extend_from_slice(&current.owner.key_epoch.to_be_bytes());
        bytes.extend_from_slice(self.trust.root_digest().as_array());
        bytes.extend_from_slice(self.trust.distribution_digest().as_array());
        bytes.extend_from_slice(&self.trust.generation().to_be_bytes());
        bytes.extend_from_slice(self.pins.selected_profile_digest.as_array());
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
        Ok(AgentdIntuitionDecisionReceiptV2 {
            decision,
            host_binding_digest: Digest32::of_bytes(&bytes),
        })
    }
}
