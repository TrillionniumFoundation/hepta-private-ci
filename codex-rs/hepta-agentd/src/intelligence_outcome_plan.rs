//! Product Outcome closure for canonical intelligence.
//!
//! A physical observer may describe and sign a terminal or censored Outcome,
//! but it cannot choose the run, episode, selected candidate, envelope or
//! dispatch identity. Those fields are inherited from the immutable binding
//! published only after the canonical Decision was durably acknowledged.

use std::sync::Arc;

use codex_hepta_learning_ledger::AuthenticatedOutcomeV1;
use codex_hepta_learning_ledger::OutcomeTerminalityV1;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_types::Digest32;

use crate::AgentdIntelligenceDecisionPlanV1;
use crate::AgentdIntelligenceLearningHostV1;
use crate::IntelligenceLearningErrorV1;
use crate::IntelligenceLearningStatusV1;

pub trait AgentdIntelligenceOutcomeEvidenceProviderV1: Send + Sync {
    fn sign(
        &self,
        outcome: &AuthenticatedOutcomeV1,
        now: u64,
    ) -> Result<SignedLearningEvidenceV1, IntelligenceLearningErrorV1>;
}

/// Host-owned append plan for one independently observed physical terminal
/// result. The Decision plan may be cloned before invocation registration; all
/// clones share the same one-time acknowledged binding publication cell.
pub struct AgentdIntelligenceOutcomePlanV1 {
    decision_plan: AgentdIntelligenceDecisionPlanV1,
    evidence_provider: Arc<dyn AgentdIntelligenceOutcomeEvidenceProviderV1>,
}

impl AgentdIntelligenceOutcomePlanV1 {
    pub fn new(
        decision_plan: AgentdIntelligenceDecisionPlanV1,
        evidence_provider: Arc<dyn AgentdIntelligenceOutcomeEvidenceProviderV1>,
    ) -> Self {
        Self {
            decision_plan,
            evidence_provider,
        }
    }

    /// Append an exact terminal/censored Outcome through the durable product
    /// outbox. Pending observations are not terminal facts and are rejected.
    ///
    /// `terminal_observation_digest` must be computed over the real physical
    /// terminal observation/receipt by the observer owner. It is mixed with the
    /// acknowledged Decision binding to form the Outcome support digest.
    pub fn append(
        &self,
        learning_host: &AgentdIntelligenceLearningHostV1,
        expected_predecessor: Digest32,
        terminal_observation_digest: Digest32,
        mut outcome: AuthenticatedOutcomeV1,
        now: u64,
    ) -> Result<IntelligenceLearningStatusV1, IntelligenceLearningErrorV1> {
        if terminal_observation_digest.is_zero()
            || now == 0
            || outcome.watermark.terminality == OutcomeTerminalityV1::Pending
        {
            return Err(IntelligenceLearningErrorV1::Invalid(
                "physical terminal Outcome",
            ));
        }
        let binding = self
            .decision_plan
            .acknowledged_binding()?
            .ok_or(IntelligenceLearningErrorV1::Missing)?;
        outcome.episode_id = binding.episode_id().clone();
        outcome.support_digest = binding.outcome_support_digest(terminal_observation_digest);
        let evidence = self.evidence_provider.sign(&outcome, now)?;
        learning_host.enqueue_outcome(
            binding,
            expected_predecessor,
            terminal_observation_digest,
            outcome,
            evidence,
            now,
        )
    }
}
