use codex_extension_api::ToolPolicyDecision;
use codex_extension_api::ToolPolicyError;
use codex_extension_api::ToolPolicyInput;
use codex_hepta_contracts::GovernanceDecision;
use codex_hepta_contracts::GovernanceDecisionRecord;
use codex_hepta_contracts::PolicyPhase;
use codex_hepta_evidence::AppendDisposition;
use codex_hepta_evidence::HeptaEvidenceStore;

use crate::binding::bootstrap_policy_stamp;
use crate::binding::core_decision;
use crate::binding::tool_action;
use crate::state::GovernanceState;

impl GovernanceState {
    pub(crate) async fn evaluate(
        &self,
        input: ToolPolicyInput<'_>,
        phase: PolicyPhase,
    ) -> Result<ToolPolicyDecision, ToolPolicyError> {
        if !self.enabled {
            return Ok(ToolPolicyDecision::Allow);
        }
        let action = tool_action(&input)?;
        let record = GovernanceDecisionRecord::new(
            action,
            phase,
            self.mode,
            bootstrap_policy_stamp(),
            GovernanceDecision::NotEvaluated,
        );
        let evidence = match self.evidence.as_ref() {
            Ok(evidence) => evidence,
            Err(detail) => return self.unavailable_or_shadow(detail),
        };
        let override_decision = match phase {
            PolicyPhase::Admission => self.admit(evidence, &record, input.attempt_id).await?,
            PolicyPhase::Authorization => {
                self.authorize(evidence, &record, input.attempt_id).await?
            }
        };
        if let Some(decision) = override_decision {
            return Ok(decision);
        }
        core_decision(self.mode, &record.decision)
    }

    async fn admit(
        &self,
        evidence: &HeptaEvidenceStore,
        record: &GovernanceDecisionRecord,
        attempt_id: &str,
    ) -> Result<Option<ToolPolicyDecision>, ToolPolicyError> {
        let disposition = match evidence.append_decision(record).await {
            Ok(disposition) => disposition,
            Err(error) => {
                return self.storage_failure_or_shadow(error.to_string()).map(Some);
            }
        };
        match disposition {
            AppendDisposition::Inserted => {
                let mut claims = match self.claims.lock() {
                    Ok(claims) => claims,
                    Err(_) => {
                        return self
                            .integrity_failure_or_shadow(
                                "hepta_governance_state_poisoned",
                                "in-process governance claim lock is poisoned",
                            )
                            .map(Some);
                    }
                };
                if claims
                    .owned
                    .insert(record.action.action_id.clone(), attempt_id.to_string())
                    .is_some()
                {
                    return self
                        .integrity_failure_or_shadow(
                            "hepta_admission_claim_conflict",
                            "one process claimed the same durable action more than once",
                        )
                        .map(Some);
                }
                Ok(None)
            }
            AppendDisposition::AlreadyPresent => self
                .replay_or_shadow(&record.action.action_id, attempt_id, PolicyPhase::Admission)
                .map(Some),
        }
    }
}
