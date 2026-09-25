use codex_extension_api::ToolCallOutcome;
use codex_extension_api::ToolPolicyError;
use codex_extension_api::ToolPolicyTerminalInput;
use codex_hepta_contracts::ActionId;
use codex_hepta_contracts::GovernanceMode;
use codex_hepta_contracts::GovernanceReceipt;
use codex_hepta_evidence::AppendDisposition;

use crate::binding::handler_outcome;
use crate::binding::terminal_matches_action;
use crate::state::GovernanceState;

impl GovernanceState {
    pub(crate) async fn terminal(
        &self,
        input: ToolPolicyTerminalInput<'_>,
    ) -> Result<(), ToolPolicyError> {
        if !self.enabled {
            return Ok(());
        }
        let action_id =
            ActionId::for_tool_call(input.thread_store.level_id(), input.turn_id, input.call_id);
        if matches!(input.outcome, ToolCallOutcome::Blocked)
            && self.consume_blocked_replay(&action_id, input.attempt_id)?
        {
            return Ok(());
        }
        let owns_action = match self.owns_action(&action_id, input.attempt_id) {
            Ok(owns_action) => owns_action,
            Err(error) => {
                return match self.mode {
                    GovernanceMode::Enforce => Err(error),
                    GovernanceMode::Shadow => {
                        tracing::warn!(
                            reason_code = error.reason_code(),
                            detail = error.detail(),
                            "shadow governance terminal claim check failed"
                        );
                        Ok(())
                    }
                };
            }
        };
        if !owns_action {
            // A replay or a storage failure never owns the original action's
            // terminal material. Leaving a durable pending action untouched is
            // safer than minting a false receipt.
            return Ok(());
        }
        let evidence = match self.evidence.as_ref() {
            Ok(evidence) => evidence,
            Err(detail) => {
                return self.terminal_unavailable_or_shadow(detail, &action_id, input.attempt_id);
            }
        };
        let stored = match evidence.get_action_evidence(&action_id).await {
            Ok(stored) => stored,
            Err(error) => {
                return self.terminal_storage_failure_or_shadow_with_action(
                    error.to_string(),
                    &action_id,
                    input.attempt_id,
                );
            }
        };
        if stored.receipt.is_some() {
            self.release_action_for_mode(&action_id, input.attempt_id)?;
            return Ok(());
        }
        let Some(admission) = stored.admission else {
            return self.terminal_integrity_failure_or_shadow(
                "hepta_terminal_without_admission",
                "terminal callback has no durable admission decision",
                &action_id,
                input.attempt_id,
            );
        };
        if !terminal_matches_action(&input, &admission.action) {
            return self.terminal_integrity_failure_or_shadow(
                "hepta_terminal_binding_drift",
                "terminal callback does not bind the admitted tool identity",
                &action_id,
                input.attempt_id,
            );
        }
        let outcome = handler_outcome(input.outcome, stored.authorization.is_some());
        let receipt = GovernanceReceipt::new(
            admission,
            stored.authorization,
            input.host_accepted,
            outcome,
        );
        match evidence.append_receipt(&receipt).await {
            Ok(AppendDisposition::Inserted | AppendDisposition::AlreadyPresent) => {
                self.release_action_for_mode(&action_id, input.attempt_id)?;
                Ok(())
            }
            Err(error) => self.terminal_storage_failure_or_shadow_with_action(
                error.to_string(),
                &action_id,
                input.attempt_id,
            ),
        }
    }
}
