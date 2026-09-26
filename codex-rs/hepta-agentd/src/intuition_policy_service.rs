//! Live Agentd serving seam for intuition.policy.
//!
//! Both phases revalidate the Fleet generation and normal Agentd admission
//! boundary. Commit validates the generation again after durable append; if the
//! generation changed, the receipt is returned only as an indeterminate recovery
//! token and must never be dispatched.

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_intelligence::IntuitionQualificationEvidenceV2;
use codex_hepta_intuition::AssignmentCommitmentV2;
use codex_hepta_intuition::CalibratedDecisionRequestV1;
use codex_hepta_intuition::CanonicalPolicyProfileV1;
use codex_hepta_intuition::ScoringCommitmentV2;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::AgentdError;
use crate::AgentdIntuitionDecisionReceiptV2;
use crate::AgentdIntuitionPolicyError;
use crate::PreparedAgentdIntuitionDecisionV3;
use crate::state::AgentdState;

#[derive(Debug)]
pub enum AgentdIntuitionServiceErrorV1 {
    NotConfigured,
    NotReady,
    Agentd(AgentdError),
    Policy(AgentdIntuitionPolicyError),
    GenerationChangedAfterCommit {
        receipt: AgentdIntuitionDecisionReceiptV2,
    },
}

impl AgentdIntuitionServiceErrorV1 {
    #[must_use]
    pub const fn code(&self) -> &'static str {
        match self {
            Self::NotConfigured => "agentd.intuition.service.not_configured",
            Self::NotReady => "agentd.intuition.service.not_ready",
            Self::Agentd(_) => "agentd.intuition.service.agentd_fenced",
            Self::Policy(source) => source.code(),
            Self::GenerationChangedAfterCommit { .. } => {
                "agentd.intuition.service.generation_changed_after_commit"
            }
        }
    }
}

impl fmt::Display for AgentdIntuitionServiceErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(self.code())
    }
}

impl StdError for AgentdIntuitionServiceErrorV1 {
    fn source(&self) -> Option<&(dyn StdError + 'static)> {
        match self {
            Self::Agentd(source) => Some(source),
            Self::Policy(source) => Some(source),
            _ => None,
        }
    }
}

impl From<AgentdError> for AgentdIntuitionServiceErrorV1 {
    fn from(value: AgentdError) -> Self {
        Self::Agentd(value)
    }
}

impl From<AgentdIntuitionPolicyError> for AgentdIntuitionServiceErrorV1 {
    fn from(value: AgentdIntuitionPolicyError) -> Self {
        Self::Policy(value)
    }
}

impl AgentdState {
    #[allow(clippy::too_many_arguments)]
    pub(crate) fn prepare_intuition_policy_v3(
        &self,
        request: CalibratedDecisionRequestV1,
        profile: CanonicalPolicyProfileV1,
        scoring: ScoringCommitmentV2,
        assignment: AssignmentCommitmentV2,
        qualification: IntuitionQualificationEvidenceV2<'_>,
        episode_id: StableId,
        run_snapshot_digest: Digest32,
        now: u64,
    ) -> Result<PreparedAgentdIntuitionDecisionV3, AgentdIntuitionServiceErrorV1> {
        if !self.automation_admission_ready()? {
            return Err(AgentdIntuitionServiceErrorV1::NotReady);
        }
        let host = self
            .intuition_policy
            .get()
            .ok_or(AgentdIntuitionServiceErrorV1::NotConfigured)?;
        let identity = self.identity();
        host.prepare_v3(
            &identity.agent_id,
            identity.spawn_generation,
            request,
            profile,
            scoring,
            assignment,
            qualification,
            episode_id,
            run_snapshot_digest,
            now,
        )
        .map_err(Into::into)
    }

    pub(crate) fn commit_intuition_policy_v3(
        &self,
        prepared: PreparedAgentdIntuitionDecisionV3,
        expected_ledger_head: Digest32,
        decision_evidence: Option<SignedLearningEvidenceV1>,
        now: u64,
    ) -> Result<AgentdIntuitionDecisionReceiptV2, AgentdIntuitionServiceErrorV1> {
        if !self.automation_admission_ready()? {
            return Err(AgentdIntuitionServiceErrorV1::NotReady);
        }
        let host = self
            .intuition_policy
            .get()
            .ok_or(AgentdIntuitionServiceErrorV1::NotConfigured)?;
        let identity = self.identity();
        let receipt = host.commit_v3(
            &identity.agent_id,
            identity.spawn_generation,
            prepared,
            expected_ledger_head,
            decision_evidence,
            now,
        )?;
        if !self.automation_admission_ready()? {
            return Err(AgentdIntuitionServiceErrorV1::GenerationChangedAfterCommit { receipt });
        }
        Ok(receipt)
    }
}
