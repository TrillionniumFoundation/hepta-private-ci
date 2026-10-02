use codex_hepta_fleet::AgentLifecycle;
use codex_hepta_fleet::ReleaseId;
use pretty_assertions::assert_eq;

use super::*;
use crate::daemon_protocol::ControlStateDigest;
use crate::daemon_protocol::SupervisordControlFence;
use crate::daemon_protocol::SupervisordMatrixStatus;

fn observation(captured_at: Instant, count: u16) -> Observation {
    let epoch = SupervisorEpoch::new();
    let agents = (0..count)
        .map(|index| {
            let agent_id =
                AgentId::parse(format!("018f4f72-5f8f-7cc1-8f55-{index:012x}")).expect("agent id");
            let fence = SupervisordControlFence {
                agent_id: agent_id.clone(),
                supervisor_epoch: epoch.clone(),
                lifecycle: AgentLifecycle::Stopped,
                lifecycle_generation: 0,
                spawn_generation: None,
                runtime_generation: None,
                current_release: None,
                previous_release: None,
                release_change_pending: false,
                state_digest: ControlStateDigest::from_bytes([0; 32]),
            };
            let agent = SupervisordAgentStatus {
                agent_id: agent_id.clone(),
                lifecycle: AgentLifecycle::Stopped,
                lifecycle_generation: 0,
                active: false,
                healthy: false,
                process_id: None,
                spawn_generation: None,
                runtime_generation: None,
                current_release: None,
                previous_release: None,
                release_change_pending: false,
                control_fence: fence,
                matrix: SupervisordMatrixStatus {
                    configured: false,
                    active: false,
                    healthy: false,
                    degraded: false,
                    process_id: None,
                    attached_agent_generation: None,
                    binding_revision: None,
                    restart_attempt: 0,
                    last_error: None,
                },
            };
            (agent_id, Arc::new(agent))
        })
        .collect();
    Observation {
        captured_at,
        epoch,
        ready: true,
        agents,
        inputs: BTreeMap::new(),
    }
}

#[test]
fn all_256_observations_are_addressable_and_roster_limits_remain_exact() {
    // In-memory observation qualification, not a 256-process performance receipt.
    let now = Instant::now();
    let view = Arc::new(observation(now, /*count*/ 256));
    let cache = ReadView {
        current: RwLock::new(Some(Arc::clone(&view))),
    };
    for (agent_id, expected) in &view.agents {
        assert_eq!(
            cache.respond(
                &SupervisordMethod::Snapshot {
                    agent_id: agent_id.clone(),
                },
                now,
                /*observed_faults*/ 0,
            ),
            Some(SupervisordPayload::Agent(expected.as_ref().clone()))
        );
    }
    assert_eq!(
        cache.respond(
            &SupervisordMethod::Roster { limit: 8 },
            now,
            /*observed_faults*/ 0,
        ),
        Some(SupervisordPayload::Roster {
            agents: view
                .agents
                .values()
                .take(8)
                .map(|status| status.as_ref().clone())
                .collect(),
        })
    );
}

#[test]
fn complete_roster_with_maximum_diagnostics_fits_the_response_ceiling() {
    let now = Instant::now();
    let mut view = observation(now, /*count*/ 256);
    for status in view.agents.values_mut() {
        let status = Arc::make_mut(status);
        status.lifecycle = AgentLifecycle::Running;
        status.lifecycle_generation = u64::MAX;
        status.active = true;
        status.process_id = Some(u64::MAX);
        status.spawn_generation = Some(u64::MAX);
        status.runtime_generation = Some(u64::MAX);
        status.current_release = Some(ReleaseId::parse("c".repeat(128)).expect("release"));
        status.previous_release = Some(ReleaseId::parse("p".repeat(128)).expect("predecessor"));
        status.control_fence.lifecycle = status.lifecycle;
        status.control_fence.lifecycle_generation = status.lifecycle_generation;
        status.control_fence.spawn_generation = status.spawn_generation;
        status.control_fence.runtime_generation = status.runtime_generation;
        status.control_fence.current_release = status.current_release.clone();
        status.control_fence.previous_release = status.previous_release.clone();
        status.matrix = SupervisordMatrixStatus {
            configured: true,
            active: true,
            healthy: false,
            degraded: true,
            process_id: Some(u64::MAX),
            attached_agent_generation: Some(u64::MAX),
            binding_revision: Some(u64::MAX),
            restart_attempt: u32::MAX,
            // Quotes exercise the largest JSON escaping expansion that the
            // bounded safe diagnostic projection can emit.
            last_error: Some("\"".repeat(crate::runtime::MAX_FAULT_BYTES)),
        };
    }
    let cache = ReadView {
        current: RwLock::new(Some(Arc::new(view))),
    };
    let response = super::super::SupervisordResponse {
        schema_version: super::super::SUPERVISORD_CONTROL_SCHEMA_VERSION,
        request_id: 1,
        payload: cache
            .respond(
                &SupervisordMethod::Roster { limit: 256 },
                now,
                /*observed_faults*/ 0,
            )
            .expect("cached roster"),
    };
    let projection = crate::robrix_protocol::RobrixSupervisordResponse::try_from(response.clone())
        .expect("read-only projection");
    projection.validate(1).expect("coherent full roster");
    let wire_bytes = serde_json::to_vec(&response)
        .expect("serialize roster")
        .len() as u64
        + 1;
    assert!(wire_bytes > crate::daemon_protocol::MAX_SUPERVISORD_CONTROL_REQUEST_BYTES);
    assert!(wire_bytes <= crate::daemon_protocol::MAX_SUPERVISORD_CONTROL_FRAME_BYTES);
}

#[test]
fn expired_and_future_dated_observations_fail_closed_for_every_cached_read() {
    let captured = Instant::now() + Duration::from_millis(1);
    let observation = observation(captured, /*count*/ 1);
    let agent_id = observation.agents.keys().next().expect("one agent").clone();
    let cache = ReadView {
        current: RwLock::new(Some(Arc::new(observation))),
    };
    for now in [
        captured - Duration::from_nanos(1),
        captured + MAX_AGE + Duration::from_nanos(1),
    ] {
        for method in [
            SupervisordMethod::Health,
            SupervisordMethod::Roster { limit: 1 },
            SupervisordMethod::Snapshot {
                agent_id: agent_id.clone(),
            },
        ] {
            assert_eq!(
                cache.respond(&method, now, /*observed_faults*/ 0),
                Some(unavailable())
            );
        }
    }
}

#[test]
fn invalidation_never_serves_the_preceding_successful_view() {
    let now = Instant::now();
    let cache = ReadView {
        current: RwLock::new(Some(Arc::new(observation(now, /*count*/ 1)))),
    };
    assert!(matches!(
        cache.respond(&SupervisordMethod::Health, now, /*observed_faults*/ 0),
        Some(SupervisordPayload::Health(_))
    ));
    cache.invalidate();
    assert_eq!(
        cache.respond(&SupervisordMethod::Health, now, /*observed_faults*/ 0),
        Some(unavailable())
    );
}

#[test]
fn live_release_and_production_evidence_never_comes_from_observation_cache() {
    let now = Instant::now();
    let view = observation(now, /*count*/ 1);
    let agent_id = view.agents.keys().next().expect("one agent").clone();
    let cache = ReadView {
        current: RwLock::new(Some(Arc::new(view))),
    };
    for method in [
        SupervisordMethod::ReleaseSelection {
            agent_id: agent_id.clone(),
        },
        SupervisordMethod::ProductionMutationStatus { agent_id },
    ] {
        assert_eq!(cache.respond(&method, now, /*observed_faults*/ 0), None);
    }
}

#[test]
fn recovery_required_view_is_reachable_but_not_ready() {
    let now = Instant::now();
    let mut view = observation(now, /*count*/ 0);
    view.ready = false;
    let expected = SupervisordPayload::Health(SupervisordHealth {
        ready: false,
        supervisor_epoch: view.epoch.clone(),
        process_id: std::process::id(),
        registered_agents: 0,
        observed_faults: 9,
    });
    let cache = ReadView {
        current: RwLock::new(Some(Arc::new(view))),
    };
    assert_eq!(
        cache.respond(&SupervisordMethod::Health, now, /*observed_faults*/ 9),
        Some(expected)
    );
}
