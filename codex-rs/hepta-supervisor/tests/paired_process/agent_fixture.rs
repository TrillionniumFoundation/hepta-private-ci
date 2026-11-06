use codex_hepta_agent_protocol::AGENTD_CONTROL_SCHEMA_VERSION;
use codex_hepta_agent_protocol::AgentdMethod;
use codex_hepta_agent_protocol::AgentdPayload;
use codex_hepta_agent_protocol::AgentdRequest;
use codex_hepta_agent_protocol::DrainSnapshot;
use codex_hepta_agent_protocol::HealthSnapshot;
use codex_hepta_fleet::AgentLifecycle;

pub(super) fn payload(
    request: &AgentdRequest,
    spawn_generation: u64,
    current_generation: u64,
    health: HealthSnapshot,
) -> AgentdPayload {
    if request.schema_version != AGENTD_CONTROL_SCHEMA_VERSION
        || request.spawn_generation != spawn_generation
    {
        return rejected();
    }
    match &request.method {
        AgentdMethod::Health => AgentdPayload::Health(health),
        AgentdMethod::Drain
            if health.lifecycle == AgentLifecycle::Draining
                && spawn_generation.checked_add(2) == Some(current_generation)
                && !health.fenced =>
        {
            // This process fixture never admits App Server turns. A zero-work
            // drain is valid only after its persisted lifecycle enters the
            // exact draining generation; a health reply is never a drain ACK.
            AgentdPayload::Drain(DrainSnapshot {
                admission_closed: true,
                running_turns: 0,
                drained: true,
                lifecycle: health.lifecycle,
                fenced: false,
            })
        }
        _ => rejected(),
    }
}

fn rejected() -> AgentdPayload {
    AgentdPayload::Error {
        code: "fixture_control_rejected".to_string(),
        message: "request does not match this fixture's control state".to_string(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn health(lifecycle: AgentLifecycle) -> HealthSnapshot {
        HealthSnapshot {
            promotion_ready: true,
            ready: lifecycle == AgentLifecycle::Running,
            fenced: false,
            lifecycle,
            process_id: std::process::id(),
            workspace: "/fixture/workspace".into(),
            home_root: "/fixture/home".into(),
            run_root: "/fixture/run".into(),
        }
    }

    #[test]
    fn exact_request_selects_health_or_zero_work_drain() {
        let request = AgentdRequest::health(/*request_id*/ 17, /*spawn_generation*/ 7);
        assert!(matches!(
            payload(
                &request,
                /*spawn_generation*/ 7,
                /*current_generation*/ 8,
                health(AgentLifecycle::Running),
            ),
            AgentdPayload::Health(_)
        ));
        let request = AgentdRequest::drain(/*request_id*/ 18, /*spawn_generation*/ 7);
        assert_eq!(
            payload(
                &request,
                /*spawn_generation*/ 7,
                /*current_generation*/ 9,
                health(AgentLifecycle::Draining),
            ),
            AgentdPayload::Drain(DrainSnapshot {
                admission_closed: true,
                running_turns: 0,
                drained: true,
                lifecycle: AgentLifecycle::Draining,
                fenced: false,
            })
        );
    }

    #[test]
    fn stale_unsupported_or_non_draining_requests_never_acknowledge() {
        let request = AgentdRequest::drain(/*request_id*/ 17, /*spawn_generation*/ 7);
        let mut bad_schema = request.clone();
        bad_schema.schema_version = AGENTD_CONTROL_SCHEMA_VERSION + 1;
        for invalid in [
            bad_schema,
            AgentdRequest::drain(/*request_id*/ 17, /*spawn_generation*/ 6),
            AgentdRequest::capabilities(/*request_id*/ 17, /*spawn_generation*/ 7),
        ] {
            assert!(matches!(
                payload(
                    &invalid,
                    /*spawn_generation*/ 7,
                    /*current_generation*/ 9,
                    health(AgentLifecycle::Draining),
                ),
                AgentdPayload::Error { .. }
            ));
        }
        for (generation, lifecycle) in [
            (8, AgentLifecycle::Running),
            (8, AgentLifecycle::Draining),
            (10, AgentLifecycle::Stopped),
        ] {
            assert!(matches!(
                payload(&request, /*spawn_generation*/ 7, generation, health(lifecycle)),
                AgentdPayload::Error { .. }
            ));
        }
        let mut fenced = health(AgentLifecycle::Draining);
        fenced.fenced = true;
        assert!(matches!(
            payload(&request, /*spawn_generation*/ 7, /*current_generation*/ 9, fenced),
            AgentdPayload::Error { .. }
        ));
        let overflow = AgentdRequest::drain(/*request_id*/ 17, u64::MAX);
        assert!(matches!(
            payload(
                &overflow,
                u64::MAX,
                /*current_generation*/ 1,
                health(AgentLifecycle::Draining),
            ),
            AgentdPayload::Error { .. }
        ));
    }
}
