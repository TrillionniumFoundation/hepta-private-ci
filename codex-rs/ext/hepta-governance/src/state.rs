use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::sync::Arc;
use std::sync::Mutex;

use codex_extension_api::ToolPolicyDecision;
use codex_extension_api::ToolPolicyError;
use codex_hepta_contracts::ActionId;
use codex_hepta_contracts::GovernanceMode;
use codex_hepta_contracts::PolicyPhase;
use codex_hepta_evidence::HeptaEvidenceStore;

#[derive(Default)]
pub(crate) struct InProcessClaims {
    /// Actions whose first durable admission insert was won by this process.
    ///
    /// This is deliberately only an execution witness. The SQLite evidence is
    /// authoritative for the decision and receipt material.
    pub(crate) owned: BTreeMap<ActionId, String>,
    /// Policy blocks caused by a replay must not finalize the original action.
    pub(crate) blocked_replays: BTreeSet<(ActionId, String)>,
}

pub struct GovernanceState {
    pub(crate) enabled: bool,
    pub(crate) mode: GovernanceMode,
    pub(crate) evidence: Result<Arc<HeptaEvidenceStore>, Arc<str>>,
    pub(crate) claims: Mutex<InProcessClaims>,
}

impl GovernanceState {
    pub(crate) fn disabled() -> Self {
        Self {
            enabled: false,
            mode: GovernanceMode::Shadow,
            evidence: Err(Arc::from("governance disabled")),
            claims: Mutex::new(InProcessClaims::default()),
        }
    }

    pub(crate) fn enabled(
        mode: GovernanceMode,
        evidence: Result<Arc<HeptaEvidenceStore>, Arc<str>>,
    ) -> Self {
        Self {
            enabled: true,
            mode,
            evidence,
            claims: Mutex::new(InProcessClaims::default()),
        }
    }
    pub(crate) fn owns_action(
        &self,
        action_id: &ActionId,
        attempt_id: &str,
    ) -> Result<bool, ToolPolicyError> {
        self.claims
            .lock()
            .map(|claims| {
                claims
                    .owned
                    .get(action_id)
                    .is_some_and(|owned_attempt| owned_attempt == attempt_id)
            })
            .map_err(|_| {
                ToolPolicyError::new(
                    "hepta_governance_state_poisoned",
                    "in-process governance claim lock is poisoned",
                )
            })
    }

    fn release_action(
        &self,
        action_id: &ActionId,
        attempt_id: &str,
    ) -> Result<(), ToolPolicyError> {
        self.claims
            .lock()
            .map(|mut claims| {
                if claims
                    .owned
                    .get(action_id)
                    .is_some_and(|owned_attempt| owned_attempt == attempt_id)
                {
                    claims.owned.remove(action_id);
                }
            })
            .map_err(|_| {
                ToolPolicyError::new(
                    "hepta_governance_state_poisoned",
                    "in-process governance claim lock is poisoned",
                )
            })
    }

    pub(crate) fn release_action_for_mode(
        &self,
        action_id: &ActionId,
        attempt_id: &str,
    ) -> Result<(), ToolPolicyError> {
        match self.release_action(action_id, attempt_id) {
            Ok(()) => Ok(()),
            Err(error) if self.mode == GovernanceMode::Shadow => {
                tracing::warn!(
                    reason_code = error.reason_code(),
                    detail = error.detail(),
                    "shadow governance could not release an in-process claim"
                );
                Ok(())
            }
            Err(error) => Err(error),
        }
    }

    pub(crate) fn replay_or_shadow(
        &self,
        action_id: &ActionId,
        attempt_id: &str,
        phase: PolicyPhase,
    ) -> Result<ToolPolicyDecision, ToolPolicyError> {
        let reason_code = match phase {
            PolicyPhase::Admission => "hepta_action_replay",
            PolicyPhase::Authorization => "hepta_authorization_replay",
        };
        match self.mode {
            GovernanceMode::Shadow => {
                tracing::warn!(
                    action_id = action_id.as_str(),
                    phase = phase.as_str(),
                    "shadow governance observed a durable action replay"
                );
                Ok(ToolPolicyDecision::Allow)
            }
            GovernanceMode::Enforce => {
                let mut claims = self.claims.lock().map_err(|_| {
                    ToolPolicyError::new(
                        "hepta_governance_state_poisoned",
                        "in-process governance claim lock is poisoned",
                    )
                })?;
                if !claims
                    .blocked_replays
                    .insert((action_id.clone(), attempt_id.to_string()))
                {
                    return Err(ToolPolicyError::new(
                        "hepta_replay_attempt_conflict",
                        "one policy attempt tried to claim the same replay twice",
                    ));
                }
                Ok(ToolPolicyDecision::Block {
                    reason_code: reason_code.to_string(),
                    message: "Hepta blocked a replay of an existing durable tool action"
                        .to_string(),
                })
            }
        }
    }

    pub(crate) fn consume_blocked_replay(
        &self,
        action_id: &ActionId,
        attempt_id: &str,
    ) -> Result<bool, ToolPolicyError> {
        let mut claims = self.claims.lock().map_err(|_| {
            ToolPolicyError::new(
                "hepta_governance_state_poisoned",
                "in-process governance claim lock is poisoned",
            )
        })?;
        Ok(claims
            .blocked_replays
            .remove(&(action_id.clone(), attempt_id.to_string())))
    }

    pub(crate) fn unavailable_or_shadow(
        &self,
        detail: &Arc<str>,
    ) -> Result<ToolPolicyDecision, ToolPolicyError> {
        match self.mode {
            GovernanceMode::Enforce => Err(ToolPolicyError::new(
                "hepta_evidence_unavailable",
                detail.to_string(),
            )),
            GovernanceMode::Shadow => {
                tracing::warn!(%detail, "shadow governance evidence backend is unavailable");
                Ok(ToolPolicyDecision::Allow)
            }
        }
    }

    pub(crate) fn storage_failure_or_shadow(
        &self,
        detail: String,
    ) -> Result<ToolPolicyDecision, ToolPolicyError> {
        match self.mode {
            GovernanceMode::Enforce => {
                Err(ToolPolicyError::new("hepta_evidence_write_failed", detail))
            }
            GovernanceMode::Shadow => {
                tracing::warn!(%detail, "shadow governance evidence write failed");
                Ok(ToolPolicyDecision::Allow)
            }
        }
    }

    pub(crate) fn integrity_failure_or_shadow(
        &self,
        reason_code: &'static str,
        detail: &'static str,
    ) -> Result<ToolPolicyDecision, ToolPolicyError> {
        match self.mode {
            GovernanceMode::Enforce => Err(ToolPolicyError::new(reason_code, detail)),
            GovernanceMode::Shadow => {
                tracing::warn!(
                    reason_code,
                    detail,
                    "shadow governance integrity check failed"
                );
                Ok(ToolPolicyDecision::Allow)
            }
        }
    }

    pub(crate) fn terminal_unavailable_or_shadow(
        &self,
        detail: &Arc<str>,
        action_id: &ActionId,
        attempt_id: &str,
    ) -> Result<(), ToolPolicyError> {
        match self.mode {
            GovernanceMode::Enforce => Err(ToolPolicyError::new(
                "hepta_evidence_unavailable",
                detail.to_string(),
            )),
            GovernanceMode::Shadow => {
                tracing::warn!(%detail, "shadow governance terminal evidence is unavailable");
                self.release_action_for_mode(action_id, attempt_id)?;
                Ok(())
            }
        }
    }

    pub(crate) fn terminal_storage_failure_or_shadow_with_action(
        &self,
        detail: String,
        action_id: &ActionId,
        attempt_id: &str,
    ) -> Result<(), ToolPolicyError> {
        match self.mode {
            GovernanceMode::Enforce => {
                // Retain the in-process claim. The durable authorized decision
                // remains pending and any replay is blocked on the next admit.
                Err(ToolPolicyError::new("hepta_evidence_write_failed", detail))
            }
            GovernanceMode::Shadow => {
                tracing::warn!(%detail, "shadow governance terminal evidence write failed");
                self.release_action_for_mode(action_id, attempt_id)?;
                Ok(())
            }
        }
    }

    pub(crate) fn terminal_integrity_failure_or_shadow(
        &self,
        reason_code: &'static str,
        detail: &'static str,
        action_id: &ActionId,
        attempt_id: &str,
    ) -> Result<(), ToolPolicyError> {
        match self.mode {
            GovernanceMode::Enforce => Err(ToolPolicyError::new(reason_code, detail)),
            GovernanceMode::Shadow => {
                tracing::warn!(
                    reason_code,
                    detail,
                    "shadow terminal integrity check failed"
                );
                self.release_action_for_mode(action_id, attempt_id)?;
                Ok(())
            }
        }
    }
}
