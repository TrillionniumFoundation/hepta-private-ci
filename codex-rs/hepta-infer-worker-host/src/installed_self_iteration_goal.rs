//! Distinguish actual subsequent Goal scopes while retaining the original
//! first Goal identifier used by already persisted installed rounds.
use codex_hepta_agentd::AgentdError;
use codex_hepta_agentd::AgentdNeuronGoalScopeV3;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

pub(super) fn from_scope(scope: &AgentdNeuronGoalScopeV3) -> Result<StableId, AgentdError> {
    if scope.ordinal == 0
        || scope.identity.model_generation == 0
        || [
            scope.identity.subject_scope_digest,
            scope.identity.objective_digest,
            scope.identity.runtime_configuration_digest,
            scope.identity.body_bundle_digest,
        ]
        .into_iter()
        .any(Digest32::is_zero)
    {
        return Err(super::invalid(
            "complete actual installed Goal scope absent",
        ));
    }
    let digest = if scope.ordinal == 1 {
        scope.identity.subject_scope_digest
    } else {
        let mut bytes = b"hepta.installed.self-iteration.goal-scope.v1\0".to_vec();
        bytes.extend_from_slice(&serde_json::to_vec(scope)?);
        Digest32::of_bytes(&bytes)
    };
    StableId::new(format!("goal.{digest}")).map_err(super::invalid)
}

#[cfg(test)]
#[path = "installed_self_iteration_goal_tests.rs"]
mod tests;
