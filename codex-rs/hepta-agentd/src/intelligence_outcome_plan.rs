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
use crate::IntelligenceLearningBindingV1;
use crate::IntelligenceLearningErrorV1;
use crate::IntelligenceLearningStatusV1;

pub trait AgentdIntelligenceOutcomeEvidenceProviderV1: Send + Sync {
    fn sign(
        &self,
        outcome: &AuthenticatedOutcomeV1,
        now: u64,
    ) -> Result<SignedLearningEvidenceV1, IntelligenceLearningErrorV1>;
}

enum OutcomeBindingSourceV1 {
    LiveDecision(AgentdIntelligenceDecisionPlanV1),
    Recovered(IntelligenceLearningBindingV1),
}

/// Host-owned append plan for one independently observed physical terminal
/// result. The Decision plan may be cloned before invocation registration; all
/// clones share the same one-time acknowledged binding publication cell. A
/// physical dispatcher may instead reopen the exact persisted binding after a
/// process restart; it never reconstructs identity from untrusted output.
pub struct AgentdIntelligenceOutcomePlanV1 {
    binding_source: OutcomeBindingSourceV1,
    evidence_provider: Arc<dyn AgentdIntelligenceOutcomeEvidenceProviderV1>,
}

impl AgentdIntelligenceOutcomePlanV1 {
    pub fn new(
        decision_plan: AgentdIntelligenceDecisionPlanV1,
        evidence_provider: Arc<dyn AgentdIntelligenceOutcomeEvidenceProviderV1>,
    ) -> Self {
        Self {
            binding_source: OutcomeBindingSourceV1::LiveDecision(decision_plan),
            evidence_provider,
        }
    }

    /// Reopen from the immutable binding that the physical dispatch owner
    /// durably retained after Decision acknowledgement. This is the restart
    /// path; no model request or Decision is replayed.
    pub fn from_acknowledged_binding(
        binding: IntelligenceLearningBindingV1,
        evidence_provider: Arc<dyn AgentdIntelligenceOutcomeEvidenceProviderV1>,
    ) -> Self {
        Self {
            binding_source: OutcomeBindingSourceV1::Recovered(binding),
            evidence_provider,
        }
    }

    pub fn acknowledged_binding(
        &self,
    ) -> Result<IntelligenceLearningBindingV1, IntelligenceLearningErrorV1> {
        match &self.binding_source {
            OutcomeBindingSourceV1::LiveDecision(plan) => plan
                .acknowledged_binding()?
                .ok_or(IntelligenceLearningErrorV1::Missing),
            OutcomeBindingSourceV1::Recovered(binding) => Ok(binding.clone()),
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
        let binding = self.acknowledged_binding()?;
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

#[cfg(test)]
mod tests {
    use super::*;
    use codex_hepta_types::StableId;

    struct NeverSigns;

    impl AgentdIntelligenceOutcomeEvidenceProviderV1 for NeverSigns {
        fn sign(
            &self,
            _outcome: &AuthenticatedOutcomeV1,
            _now: u64,
        ) -> Result<SignedLearningEvidenceV1, IntelligenceLearningErrorV1> {
            Err(IntelligenceLearningErrorV1::Invalid("unused signer"))
        }
    }

    fn id(value: &str) -> StableId {
        StableId::new(value).expect("stable id")
    }

    fn digest(value: &str) -> Digest32 {
        Digest32::of_bytes(value.as_bytes())
    }

    #[test]
    fn recovered_binding_is_exact_and_requires_no_decision_replay() {
        let run_id = id("run.recovered");
        let binding = IntelligenceLearningBindingV1::new(
            run_id.clone(),
            digest("snapshot"),
            digest("objective"),
            digest("envelope"),
            digest("candidates"),
            digest("dispatch"),
            run_id,
            id("episode.recovered"),
            id("candidate.recovered"),
        )
        .expect("binding");
        let plan = AgentdIntelligenceOutcomePlanV1::from_acknowledged_binding(
            binding.clone(),
            Arc::new(NeverSigns),
        );
        assert_eq!(plan.acknowledged_binding().expect("binding"), binding);
    }
}
