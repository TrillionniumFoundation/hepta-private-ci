use codex_hepta_agent_protocol::AGENTD_CONTROL_SCHEMA_VERSION;
use codex_hepta_agent_protocol::AgentdMethod;
use codex_hepta_agent_protocol::AgentdPayload;
use codex_hepta_agent_protocol::DrainSnapshot;
use codex_hepta_agent_protocol::HealthSnapshot;
use codex_hepta_fleet::AgentLifecycle;

use super::FixtureAgentRequest;

pub(super) fn payload(
    request: &FixtureAgentRequest,
    spawn_generation: u64,
    current_generation: u64,
    mut health: HealthSnapshot,
    admission_closed: &mut bool,
) -> AgentdPayload {
    if request.schema_version != AGENTD_CONTROL_SCHEMA_VERSION
        || request.spawn_generation != spawn_generation
    {
        return AgentdPayload::Error {
            code: "invalid_fixture_envelope".to_string(),
            message: "fixture request schema or spawn generation does not match".to_string(),
        };
    }
    match serde_json::from_value(request.method.clone()) {
        Ok(AgentdMethod::Health) => {
            health.ready &= !*admission_closed;
            AgentdPayload::Health(health)
        }
        Ok(AgentdMethod::Drain)
            if health.lifecycle == AgentLifecycle::Draining
                && spawn_generation.checked_add(2) == Some(current_generation)
                && !health.fenced =>
        {
            // This control-only child has no turn runner or delivery outbox;
            // every work-admission method below is rejected. Close its local
            // admission before reporting the actual empty-work drain state.
            // The persisted lifecycle must also be the exact draining
            // generation for this spawn; health is never a drain response.
            *admission_closed = true;
            AgentdPayload::Drain(DrainSnapshot {
                admission_closed: *admission_closed,
                running_turns: 0,
                drained: *admission_closed,
                lifecycle: health.lifecycle,
                fenced: false,
            })
        }
        Ok(AgentdMethod::Drain) => AgentdPayload::Error {
            code: "invalid_fixture_lifecycle".to_string(),
            message: "fixture drain requires the persisted draining lifecycle".to_string(),
        },
        Ok(_) | Err(_) => AgentdPayload::Error {
            code: "unsupported_fixture_method".to_string(),
            message: "controlled fixture supports only health and drain".to_string(),
        },
    }
}

#[cfg(test)]
#[path = "agent_fixture_tests.rs"]
mod tests;
