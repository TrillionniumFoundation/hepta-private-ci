use anyhow::Result;
use codex_hepta_agent_protocol::AGENTD_CONTROL_SCHEMA_VERSION;
use codex_hepta_agent_protocol::AgentdMethod;
use codex_hepta_agent_protocol::AgentdPayload;
use codex_hepta_agent_protocol::DrainSnapshot;
use codex_hepta_agent_protocol::HealthSnapshot;
use codex_hepta_fleet::AgentLifecycle;
use pretty_assertions::assert_eq;

use super::FixtureAgentRequest;
use super::payload;

fn request(method: AgentdMethod, spawn_generation: u64) -> Result<FixtureAgentRequest> {
    Ok(FixtureAgentRequest {
        schema_version: AGENTD_CONTROL_SCHEMA_VERSION,
        request_id: 17,
        spawn_generation,
        method: serde_json::to_value(method)?,
    })
}

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
fn exact_request_selects_health_or_zero_work_drain() -> Result<()> {
    let mut admission_closed = false;
    assert_eq!(
        payload(
            &request(AgentdMethod::Health, /*spawn_generation*/ 7)?,
            /*spawn_generation*/ 7,
            /*current_generation*/ 8,
            health(AgentLifecycle::Running),
            &mut admission_closed,
        ),
        AgentdPayload::Health(health(AgentLifecycle::Running))
    );
    assert!(!admission_closed);
    assert_eq!(
        payload(
            &request(AgentdMethod::Drain, /*spawn_generation*/ 7)?,
            /*spawn_generation*/ 7,
            /*current_generation*/ 9,
            health(AgentLifecycle::Draining),
            &mut admission_closed,
        ),
        AgentdPayload::Drain(DrainSnapshot {
            admission_closed: true,
            running_turns: 0,
            drained: true,
            lifecycle: AgentLifecycle::Draining,
            fenced: false,
        })
    );
    assert!(admission_closed);
    Ok(())
}

#[test]
fn successful_drain_keeps_admission_closed_across_later_health_requests() -> Result<()> {
    let mut admission_closed = false;
    assert!(matches!(
        payload(
            &request(AgentdMethod::Drain, /*spawn_generation*/ 7)?,
            /*spawn_generation*/ 7,
            /*current_generation*/ 9,
            health(AgentLifecycle::Draining),
            &mut admission_closed,
        ),
        AgentdPayload::Drain(_)
    ));
    let mut closed_health = health(AgentLifecycle::Running);
    closed_health.ready = false;
    assert_eq!(
        payload(
            &request(AgentdMethod::Health, /*spawn_generation*/ 7)?,
            /*spawn_generation*/ 7,
            /*current_generation*/ 8,
            health(AgentLifecycle::Running),
            &mut admission_closed,
        ),
        AgentdPayload::Health(closed_health)
    );
    assert!(admission_closed);
    Ok(())
}

#[test]
fn invalid_envelopes_and_unsupported_methods_keep_fixed_errors() -> Result<()> {
    let mut bad_schema = request(AgentdMethod::Drain, /*spawn_generation*/ 7)?;
    bad_schema.schema_version = AGENTD_CONTROL_SCHEMA_VERSION + 1;
    for invalid in [
        bad_schema,
        request(AgentdMethod::Drain, /*spawn_generation*/ 6)?,
    ] {
        for initial_closed in [false, true] {
            let mut admission_closed = initial_closed;
            assert_eq!(
                payload(
                    &invalid,
                    /*spawn_generation*/ 7,
                    /*current_generation*/ 9,
                    health(AgentLifecycle::Draining),
                    &mut admission_closed,
                ),
                AgentdPayload::Error {
                    code: "invalid_fixture_envelope".to_string(),
                    message: "fixture request schema or spawn generation does not match"
                        .to_string(),
                }
            );
            assert_eq!(admission_closed, initial_closed);
        }
    }
    for method in [
        serde_json::to_value(AgentdMethod::Capabilities)?,
        serde_json::json!({"type": "unrecognized_method"}),
    ] {
        let invalid = FixtureAgentRequest {
            method,
            ..request(AgentdMethod::Health, /*spawn_generation*/ 7)?
        };
        let mut admission_closed = false;
        assert_eq!(
            payload(
                &invalid,
                /*spawn_generation*/ 7,
                /*current_generation*/ 9,
                health(AgentLifecycle::Draining),
                &mut admission_closed,
            ),
            AgentdPayload::Error {
                code: "unsupported_fixture_method".to_string(),
                message: "controlled fixture supports only health and drain".to_string(),
            }
        );
        assert!(!admission_closed);
    }
    Ok(())
}

#[test]
fn wrong_generation_non_draining_fenced_and_overflow_never_acknowledge() -> Result<()> {
    for (generation, lifecycle, fenced) in [
        (8, AgentLifecycle::Running, false),
        (8, AgentLifecycle::Draining, false),
        (10, AgentLifecycle::Draining, false),
        (10, AgentLifecycle::Stopped, false),
        (9, AgentLifecycle::Draining, true),
    ] {
        let mut snapshot = health(lifecycle);
        snapshot.fenced = fenced;
        let mut admission_closed = false;
        assert_eq!(
            payload(
                &request(AgentdMethod::Drain, /*spawn_generation*/ 7)?,
                /*spawn_generation*/ 7,
                generation,
                snapshot,
                &mut admission_closed,
            ),
            AgentdPayload::Error {
                code: "invalid_fixture_lifecycle".to_string(),
                message: "fixture drain requires the persisted draining lifecycle".to_string(),
            }
        );
        assert!(!admission_closed);
    }
    let mut admission_closed = false;
    assert!(matches!(
        payload(
            &request(AgentdMethod::Drain, u64::MAX)?,
            u64::MAX,
            /*current_generation*/ 1,
            health(AgentLifecycle::Draining),
            &mut admission_closed,
        ),
        AgentdPayload::Error { .. }
    ));
    assert!(!admission_closed);
    Ok(())
}

#[test]
fn raw_envelope_still_rejects_unknown_fields_before_dispatch() {
    let raw = serde_json::json!({
        "schema_version": AGENTD_CONTROL_SCHEMA_VERSION,
        "request_id": 17,
        "spawn_generation": 7,
        "method": {"type": "health"},
        "unknown_field": true
    });
    assert!(serde_json::from_value::<FixtureAgentRequest>(raw).is_err());
}
