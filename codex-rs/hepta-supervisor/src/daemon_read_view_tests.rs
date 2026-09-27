use codex_hepta_fleet::AgentLifecycle;
use pretty_assertions::assert_eq;

use super::*;
use crate::daemon_protocol::ControlStateDigest;
use crate::daemon_protocol::SupervisordControlFence;
use crate::daemon_protocol::SupervisordMatrixStatus;

fn observation(captured_at: Instant, count: u16) -> Observation {
    let epoch = SupervisorEpoch::new();
    let agents = (0..count)
        .map(|index| {
            let agent_id = AgentId::parse(format!("018f4f72-5f8f-7cc1-8f55-{index:012x}"))
                .expect("agent id");
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
            (agent_id, agent)
        })
        .collect();
    Observation {
        captured_at,
        epoch,
        ready: true,
        agents,
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
            Some(SupervisordPayload::Agent(expected.clone()))
        );
    }
    assert_eq!(
        cache.respond(
            &SupervisordMethod::Roster { limit: 8 },
            now,
            /*observed_faults*/ 0,
        ),
        Some(SupervisordPayload::Roster {
            agents: view.agents.values().take(8).cloned().collect(),
        })
    );
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
