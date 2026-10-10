use codex_extension_api::ToolPolicyDecision;
use codex_extension_api::ToolPolicyError;
use codex_hepta_contracts::GovernanceDecision;
use codex_hepta_contracts::GovernanceDecisionRecord;
use codex_hepta_contracts::GovernanceMode;
use codex_hepta_contracts::PolicyPhase;
use codex_hepta_evidence::AppendDisposition;
use codex_hepta_evidence::HeptaEvidenceStore;

use crate::binding::same_action_identity;
use crate::state::GovernanceState;

impl GovernanceState {
    pub(crate) async fn authorize(
        &self,
        evidence: &HeptaEvidenceStore,
        record: &GovernanceDecisionRecord,
        attempt_id: &str,
    ) -> Result<Option<ToolPolicyDecision>, ToolPolicyError> {
        let owns_action = match self.owns_action(&record.action.action_id, attempt_id) {
            Ok(owns_action) => owns_action,
            Err(error) => {
                return match self.mode {
                    GovernanceMode::Enforce => Err(error),
                    GovernanceMode::Shadow => {
                        tracing::warn!(
                            reason_code = error.reason_code(),
                            detail = error.detail(),
                            "shadow governance claim check failed"
                        );
                        Ok(Some(ToolPolicyDecision::Allow))
                    }
                };
            }
        };
        if !owns_action {
            return self
                .integrity_failure_or_shadow(
                    "hepta_authorization_without_claim",
                    "authorization has no in-process durable admission claim",
                )
                .map(Some);
        }
        let stored = match evidence.get_action_evidence(&record.action.action_id).await {
            Ok(stored) => stored,
            Err(error) => {
                return self.storage_failure_or_shadow(error.to_string()).map(Some);
            }
        };
        let Some(admission) = stored.admission.as_ref() else {
            return self
                .integrity_failure_or_shadow(
                    "hepta_authorization_without_admission",
                    "authorization has no durable admission decision",
                )
                .map(Some);
        };
        if stored.receipt.is_some() {
            return self
                .replay_or_shadow(
                    &record.action.action_id,
                    attempt_id,
                    PolicyPhase::Authorization,
                )
                .map(Some);
        }
        if stored.authorization.is_some() {
            return self
                .replay_or_shadow(
                    &record.action.action_id,
                    attempt_id,
                    PolicyPhase::Authorization,
                )
                .map(Some);
        }
        if !same_action_identity(&admission.action, &record.action)
            || admission.phase != PolicyPhase::Admission
            || admission.mode != self.mode
            || admission.policy != record.policy
            || admission.decision != GovernanceDecision::NotEvaluated
        {
            return self
                .integrity_failure_or_shadow(
                    "hepta_authorization_binding_drift",
                    "authorization identity or policy drifted from durable admission",
                )
                .map(Some);
        }
        match evidence.append_decision(record).await {
            Ok(AppendDisposition::Inserted) => Ok(None),
            Ok(AppendDisposition::AlreadyPresent) => self
                .replay_or_shadow(
                    &record.action.action_id,
                    attempt_id,
                    PolicyPhase::Authorization,
                )
                .map(Some),
            Err(error) => self.storage_failure_or_shadow(error.to_string()).map(Some),
        }
    }
}
