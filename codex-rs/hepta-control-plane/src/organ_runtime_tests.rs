use std::collections::BTreeSet;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::MutexGuard;

use pretty_assertions::assert_eq;

use super::*;
use crate::DataflowTiming;
use crate::FailureDomainV1;
use crate::FallbackTerminal;
use crate::InputPort;
use crate::OrganEdge;
use crate::OrganNodeV1;
use crate::OrganRole;
use crate::OutputPort;
use crate::RuntimeLinkV1;
use codex_hepta_types::Digest32;

fn id(value: &str) -> StableId {
    match StableId::new(value) {
        Ok(id) => id,
        Err(error) => panic!("fixture identifier: {error}"),
    }
}

fn generation(value: u64) -> Generation {
    match Generation::new(value) {
        Ok(generation) => generation,
        Err(error) => panic!("fixture generation: {error}"),
    }
}

fn event_log(events: &Arc<Mutex<Vec<String>>>) -> MutexGuard<'_, Vec<String>> {
    match events.lock() {
        Ok(events) => events,
        Err(_) => panic!("event lock poisoned"),
    }
}

fn new_host(graph: OrganGraphsV1, handlers: Vec<Box<dyn TrustedReadOnlyOrganV1>>) -> OrganHostV1 {
    match OrganHostV1::new(graph, handlers) {
        Ok(host) => host,
        Err(error) => panic!("valid host: {error}"),
    }
}

fn start_host(host: &mut OrganHostV1) {
    if let Err(error) = host.start_all() {
        panic!("start host: {error}");
    }
}

fn graph() -> OrganGraphsV1 {
    let port = id("message.v1");
    let safe = FallbackTerminal::SafeState(Digest32::of_bytes(b"safe"));
    OrganGraphsV1 {
        generation: generation(7),
        organs: vec![
            OrganNodeV1 {
                id: id("source"),
                owner: id("owner"),
                role: OrganRole::Other,
                inputs: vec![],
                outputs: vec![port.clone()],
                effect_scope: BTreeSet::new(),
                terminal: FallbackTerminal::None,
            },
            OrganNodeV1 {
                id: id("target.a"),
                owner: id("owner"),
                role: OrganRole::Other,
                inputs: vec![port.clone()],
                outputs: vec![],
                effect_scope: BTreeSet::new(),
                terminal: FallbackTerminal::None,
            },
            OrganNodeV1 {
                id: id("target.b"),
                owner: id("owner"),
                role: OrganRole::Other,
                inputs: vec![port],
                outputs: vec![],
                effect_scope: BTreeSet::new(),
                terminal: safe,
            },
        ],
        initialization: vec![OrganEdge { from: 0, to: 1 }, OrganEdge { from: 1, to: 2 }],
        runtime: vec![
            RuntimeLinkV1 {
                output: OutputPort { organ: 0, port: 0 },
                input: InputPort { organ: 1, port: 0 },
                timing: DataflowTiming::Buffered,
            },
            RuntimeLinkV1 {
                output: OutputPort { organ: 0, port: 0 },
                input: InputPort { organ: 2, port: 0 },
                timing: DataflowTiming::Buffered,
            },
        ],
        feedback: vec![],
        fallback: vec![OrganEdge { from: 0, to: 2 }, OrganEdge { from: 1, to: 2 }],
        failure_domains: (0..3)
            .map(|organ| FailureDomainV1 {
                organ,
                process: id(&format!("process.{organ}")),
                host: id("host"),
            })
            .collect(),
    }
}

#[derive(Debug)]
struct FixtureOrgan {
    id: StableId,
    events: Arc<Mutex<Vec<String>>>,
    start_fault: bool,
    handle_fault: bool,
    stop_fault: bool,
    output_bytes: usize,
}

impl TrustedReadOnlyOrganV1 for FixtureOrgan {
    fn id(&self) -> &StableId {
        &self.id
    }

    fn start(&mut self) -> Result<(), OrganHandlerFaultV1> {
        self.record("start");
        if self.start_fault {
            Err(self.fault("start"))
        } else {
            Ok(())
        }
    }

    fn handle(
        &mut self,
        input_port: usize,
        payload: &[u8],
    ) -> Result<Vec<u8>, OrganHandlerFaultV1> {
        self.record(&format!("handle:{input_port}:{}", payload.len()));
        if self.handle_fault {
            Err(self.fault("handle"))
        } else {
            Ok(vec![self.id.as_str().as_bytes()[0]; self.output_bytes])
        }
    }

    fn stop(&mut self) -> Result<(), OrganHandlerFaultV1> {
        self.record("stop");
        if self.stop_fault {
            Err(self.fault("stop"))
        } else {
            Ok(())
        }
    }
}

impl FixtureOrgan {
    fn new(name: &str, events: Arc<Mutex<Vec<String>>>) -> Self {
        Self {
            id: id(name),
            events,
            start_fault: false,
            handle_fault: false,
            stop_fault: false,
            output_bytes: 1,
        }
    }

    fn record(&self, event: &str) {
        event_log(&self.events).push(format!("{event}:{}", self.id));
    }

    fn fault(&self, phase: &str) -> OrganHandlerFaultV1 {
        OrganHandlerFaultV1::new(id(&format!("{phase}.fault")))
    }
}

fn handlers(events: &Arc<Mutex<Vec<String>>>) -> Vec<Box<dyn TrustedReadOnlyOrganV1>> {
    ["source", "target.a", "target.b"]
        .into_iter()
        .map(|name| {
            Box::new(FixtureOrgan::new(name, Arc::clone(events))) as Box<dyn TrustedReadOnlyOrganV1>
        })
        .collect()
}

#[derive(Default)]
struct MigrationFixture {
    snapshots: Vec<Generation>,
    migrations: Vec<(Generation, Generation, Vec<u8>)>,
    rollbacks: Vec<(Generation, Generation, Vec<u8>)>,
    fail_migrate: bool,
    fail_rollback: bool,
    events: Option<Arc<Mutex<Vec<String>>>>,
}

impl OrganStateMigrationV1 for MigrationFixture {
    fn snapshot(&mut self, predecessor: Generation) -> Result<Vec<u8>, OrganMigrationError> {
        self.snapshots.push(predecessor);
        Ok(b"state-v1".to_vec())
    }

    fn migrate(
        &mut self,
        snapshot: &[u8],
        predecessor: Generation,
        candidate: Generation,
    ) -> Result<(), OrganMigrationError> {
        self.migrations
            .push((predecessor, candidate, snapshot.to_vec()));
        if let Some(events) = &self.events {
            event_log(events).push("migrate".to_owned());
        }
        if self.fail_migrate {
            Err(OrganMigrationError::Callback(id("migration.failed")))
        } else {
            Ok(())
        }
    }

    fn rollback(
        &mut self,
        snapshot: &[u8],
        predecessor: Generation,
        candidate: Generation,
    ) -> Result<(), OrganMigrationError> {
        self.rollbacks
            .push((predecessor, candidate, snapshot.to_vec()));
        if let Some(events) = &self.events {
            event_log(events).push("rollback".to_owned());
        }
        if self.fail_rollback {
            Err(OrganMigrationError::Callback(id("rollback.failed")))
        } else {
            Ok(())
        }
    }
}

#[test]
fn abi_and_local_fallback_status_are_generation_bound_and_deny_all() {
    let events = Arc::new(Mutex::new(Vec::new()));
    let mut host = new_host(graph(), handlers(&events));
    start_host(&mut host);

    let abi = host.abi();
    assert_eq!(abi.len(), 3);
    assert!(abi.iter().all(|entry| entry.generation == generation(7)));
    assert_eq!(abi[0].input_ports, Vec::<StableId>::new());
    assert_eq!(abi[0].output_ports, vec![id("message.v1")]);
    assert!(abi.iter().all(|entry| entry.effect_scope.is_empty()));

    let fallback = host.local_fallback_status();
    assert_eq!(fallback.len(), 3);
    assert!(
        fallback
            .iter()
            .all(|entry| entry.generation == generation(7))
    );
    assert!(fallback.iter().all(|entry| entry.available));
    assert_eq!(fallback[0].fallback_targets, vec![id("target.b")]);
    assert_eq!(host.fallback_status(), fallback);
}

#[test]
fn migration_callback_runs_before_successor_publication() {
    let events = Arc::new(Mutex::new(Vec::new()));
    let mut host = new_host(graph(), handlers(&events));
    start_host(&mut host);
    let mut next = graph();
    next.generation = generation(8);
    let mut migration = MigrationFixture::default();

    host.replace_read_only_generation_with_migration(
        generation(7),
        next,
        handlers(&events),
        &mut migration,
    )
    .expect("migration and cutover");
    assert_eq!(migration.snapshots, vec![generation(7)]);
    assert_eq!(migration.migrations.len(), 1);
    assert_eq!(migration.migrations[0].0, generation(7));
    assert_eq!(migration.migrations[0].1, generation(8));
    assert!(migration.rollbacks.is_empty());
    assert_eq!(host.generation(), generation(8));
}

#[test]
fn migration_failure_rolls_back_and_preserves_predecessor() {
    let events = Arc::new(Mutex::new(Vec::new()));
    let mut host = new_host(graph(), handlers(&events));
    start_host(&mut host);
    let before = host.statuses();
    let mut next = graph();
    next.generation = generation(8);
    let mut migration = MigrationFixture {
        fail_migrate: true,
        ..MigrationFixture::default()
    };

    let error = host
        .replace_read_only_generation_with_migration(
            generation(7),
            next,
            handlers(&events),
            &mut migration,
        )
        .expect_err("migration must fail");
    assert!(matches!(
        error,
        OrganRuntimeError::CandidateMigrationFailed {
            rollback_error: None,
            candidate_cleanup_faults: ref faults,
            ..
        } if faults.is_empty()
    ));
    assert_eq!(migration.rollbacks.len(), 1);
    assert_eq!(host.generation(), generation(7));
    assert_eq!(host.statuses(), before);
    assert!(
        host.dispatch_once(generation(7), &id("source"), 0, b"still-live")
            .is_ok()
    );
}

#[test]
fn candidate_start_failure_rolls_back_the_snapshot_before_publication() {
    let events = Arc::new(Mutex::new(Vec::new()));
    let mut host = new_host(graph(), handlers(&events));
    start_host(&mut host);
    let before = host.statuses();
    let mut next = graph();
    next.generation = generation(8);
    let mut failing = FixtureOrgan::new("target.a", Arc::clone(&events));
    failing.start_fault = true;
    let next_handlers: Vec<Box<dyn TrustedReadOnlyOrganV1>> = vec![
        Box::new(FixtureOrgan::new("source", Arc::clone(&events))),
        Box::new(failing),
        Box::new(FixtureOrgan::new("target.b", Arc::clone(&events))),
    ];
    let mut migration = MigrationFixture::default();

    let error = host
        .replace_read_only_generation_with_migration(
            generation(7),
            next,
            next_handlers,
            &mut migration,
        )
        .expect_err("candidate startup must fail");
    assert!(matches!(
        error,
        OrganRuntimeError::CandidateStartFailed {
            rollback_error: None,
            ..
        }
    ));
    assert_eq!(migration.rollbacks.len(), 1);
    assert_eq!(host.generation(), generation(7));
    assert_eq!(host.statuses(), before);
}

#[test]
fn successor_generation_replaces_a_read_only_organ_and_fences_old_dispatch() {
    let events = Arc::new(Mutex::new(Vec::new()));
    let mut host = new_host(graph(), handlers(&events));
    start_host(&mut host);
    let mut next = graph();
    next.generation = generation(8);
    next.organs[2].id = id("target.c");
    let next_handlers = ["source", "target.a", "target.c"]
        .into_iter()
        .map(|name| {
            Box::new(FixtureOrgan::new(name, Arc::clone(&events)))
                as Box<dyn TrustedReadOnlyOrganV1>
        })
        .collect();
    host.replace_read_only_generation(generation(7), next, next_handlers)
        .expect("cutover");
    assert_eq!(host.generation(), generation(8));
    assert_eq!(
        host.dispatch_once(generation(7), &id("source"), 0, b"old"),
        Err(OrganRuntimeError::GenerationMismatch {
            expected: generation(8),
            actual: generation(7)
        }),
    );
    let deliveries = host
        .dispatch_once(generation(8), &id("source"), 0, b"new")
        .expect("new route");
    assert_eq!(
        deliveries
            .iter()
            .map(|delivery| delivery.target.clone())
            .collect::<Vec<_>>(),
        vec![id("target.a"), id("target.c")]
    );
}

#[test]
fn candidate_start_failure_preserves_the_predecessor() {
    let events = Arc::new(Mutex::new(Vec::new()));
    let mut host = new_host(graph(), handlers(&events));
    start_host(&mut host);
    let before = host.statuses();
    let mut next = graph();
    next.generation = generation(8);
    let mut failing = FixtureOrgan::new("target.a", Arc::clone(&events));
    failing.start_fault = true;
    let next_handlers: Vec<Box<dyn TrustedReadOnlyOrganV1>> = vec![
        Box::new(FixtureOrgan::new("source", Arc::clone(&events))),
        Box::new(failing),
        Box::new(FixtureOrgan::new("target.b", Arc::clone(&events))),
    ];
    assert!(matches!(
        host.replace_read_only_generation(generation(7), next, next_handlers),
        Err(OrganRuntimeError::StartFailed { .. })
    ));
    assert_eq!(host.statuses(), before);
    assert!(
        host.dispatch_once(generation(7), &id("source"), 0, b"still-live")
            .is_ok()
    );
}

#[test]
fn predecessor_stop_failure_blocks_publication_and_records_cleanup_faults() {
    let events = Arc::new(Mutex::new(Vec::new()));
    let mut old = FixtureOrgan::new("target.a", Arc::clone(&events));
    old.stop_fault = true;
    let old_handlers: Vec<Box<dyn TrustedReadOnlyOrganV1>> = vec![
        Box::new(FixtureOrgan::new("source", Arc::clone(&events))),
        Box::new(old),
        Box::new(FixtureOrgan::new("target.b", Arc::clone(&events))),
    ];
    let mut host = new_host(graph(), old_handlers);
    start_host(&mut host);
    let mut next = graph();
    next.generation = generation(8);
    assert_eq!(
        host.replace_read_only_generation(generation(7), next, handlers(&events)),
        Err(OrganRuntimeError::ReplacementStopFailed {
            predecessor_faults: vec![OrganFaultRecordV1 {
                organ: id("target.a"),
                code: id("stop.fault")
            }],
            candidate_cleanup_faults: vec![],
        }),
    );
    assert_eq!(host.generation(), generation(7));
    assert_eq!(
        host.statuses()
            .iter()
            .map(|status| status.state)
            .collect::<Vec<_>>(),
        vec![
            HostedOrganStateV1::Stopped,
            HostedOrganStateV1::Quarantined,
            HostedOrganStateV1::Stopped
        ]
    );
    assert!(matches!(
        host.dispatch_once(generation(7), &id("source"), 0, b"cannot-route"),
        Err(OrganRuntimeError::OrganNotReady { .. })
    ));
}

#[test]
fn starts_routes_and_stops_in_graph_order_without_authority() {
    let events = Arc::new(Mutex::new(Vec::new()));
    let mut host = new_host(graph(), handlers(&events));
    start_host(&mut host);

    let deliveries = match host.dispatch_once(generation(7), &id("source"), 0, b"request") {
        Ok(deliveries) => deliveries,
        Err(error) => panic!("dispatch: {error}"),
    };
    assert_eq!(
        deliveries
            .iter()
            .map(|delivery| delivery.target.as_str())
            .collect::<Vec<_>>(),
        ["target.a", "target.b"]
    );
    assert!(
        deliveries
            .iter()
            .all(|delivery| !delivery.authority.grants_any())
    );
    if let Err(error) = host.stop_all() {
        panic!("stop host: {error}");
    }
    let before_drop = event_log(&events).clone();
    drop(host);
    assert_eq!(*event_log(&events), before_drop);
}

#[test]
fn rejects_effect_scope_and_requires_an_exact_handler_set() {
    let events = Arc::new(Mutex::new(Vec::new()));
    let mut effect_graph = graph();
    effect_graph.organs[0]
        .effect_scope
        .insert(id("external.effect"));
    assert!(matches!(
        OrganHostV1::new(effect_graph, handlers(&events)),
        Err(OrganRuntimeError::ReadOnlyEffectScope { .. })
    ));

    let mut incomplete = handlers(&events);
    incomplete.pop();
    let Err(error) = OrganHostV1::new(graph(), incomplete) else {
        panic!("incomplete handler set was accepted");
    };
    assert_eq!(
        error,
        OrganRuntimeError::HandlerCount {
            expected: 3,
            actual: 2,
        }
    );
}

#[test]
fn handler_fault_quarantines_and_next_dispatch_preflights_every_target() {
    let events = Arc::new(Mutex::new(Vec::new()));
    let mut configured = handlers(&events);
    configured[2] = Box::new(FixtureOrgan {
        handle_fault: true,
        ..FixtureOrgan::new("target.b", Arc::clone(&events))
    });
    let mut host = new_host(graph(), configured);
    start_host(&mut host);
    let before = event_log(&events).clone();

    assert!(matches!(
        host.dispatch_once(generation(8), &id("source"), 0, b"request"),
        Err(OrganRuntimeError::GenerationMismatch { .. })
    ));
    assert!(matches!(
        host.dispatch_once(
            generation(7),
            &id("source"),
            0,
            &vec![0; MAX_ORGAN_MESSAGE_BYTES + 1],
        ),
        Err(OrganRuntimeError::InputTooLarge { .. })
    ));
    assert_eq!(*event_log(&events), before);

    assert!(matches!(
        host.dispatch_once(generation(7), &id("source"), 0, b"request"),
        Err(OrganRuntimeError::HandleFailed { delivered: 1, .. })
    ));
    let after_fault = event_log(&events).clone();
    assert_eq!(host.statuses()[2].state, HostedOrganStateV1::Quarantined);
    assert!(matches!(
        host.dispatch_once(generation(7), &id("source"), 0, b"request"),
        Err(OrganRuntimeError::OrganNotReady { .. })
    ));
    assert_eq!(*event_log(&events), after_fault);
}

#[test]
fn start_failure_quarantines_fault_and_cleans_up_in_reverse() {
    let events = Arc::new(Mutex::new(Vec::new()));
    let mut configured = handlers(&events);
    configured[1] = Box::new(FixtureOrgan {
        start_fault: true,
        ..FixtureOrgan::new("target.a", Arc::clone(&events))
    });
    let mut host = new_host(graph(), configured);

    assert!(matches!(
        host.start_all(),
        Err(OrganRuntimeError::StartFailed {
            cleanup_faults,
            ..
        }) if cleanup_faults.is_empty()
    ));
    assert_eq!(
        host.statuses(),
        [
            HostedOrganStatusV1 {
                id: id("source"),
                state: HostedOrganStateV1::Stopped
            },
            HostedOrganStatusV1 {
                id: id("target.a"),
                state: HostedOrganStateV1::Quarantined
            },
            HostedOrganStatusV1 {
                id: id("target.b"),
                state: HostedOrganStateV1::Registered
            },
        ]
    );
    assert_eq!(
        *event_log(&events),
        [
            "start:source",
            "start:target.a",
            "stop:target.a",
            "stop:source"
        ]
    );
}

#[test]
fn oversized_output_quarantines_the_handler() {
    let events = Arc::new(Mutex::new(Vec::new()));
    let mut configured = handlers(&events);
    configured[1] = Box::new(FixtureOrgan {
        output_bytes: MAX_ORGAN_MESSAGE_BYTES + 1,
        ..FixtureOrgan::new("target.a", Arc::clone(&events))
    });
    let mut host = new_host(graph(), configured);
    start_host(&mut host);

    assert_eq!(
        host.dispatch_once(generation(7), &id("source"), 0, b"request"),
        Err(OrganRuntimeError::OutputTooLarge {
            organ: id("target.a"),
            actual: MAX_ORGAN_MESSAGE_BYTES + 1,
            delivered: 0,
        })
    );
    assert_eq!(host.statuses()[1].state, HostedOrganStateV1::Quarantined);
}

#[test]
fn failed_stop_is_quarantined_and_never_retried_by_drop() {
    let events = Arc::new(Mutex::new(Vec::new()));
    let mut configured = handlers(&events);
    configured[2] = Box::new(FixtureOrgan {
        stop_fault: true,
        ..FixtureOrgan::new("target.b", Arc::clone(&events))
    });
    let mut host = new_host(graph(), configured);
    start_host(&mut host);

    assert!(matches!(
        host.stop_all(),
        Err(OrganRuntimeError::StopFailed { faults }) if faults.len() == 1
    ));
    assert_eq!(host.statuses()[2].state, HostedOrganStateV1::Quarantined);
    let before_drop = event_log(&events).clone();
    drop(host);
    assert_eq!(*event_log(&events), before_drop);
}

#[test]
fn failed_state_restoration_quarantines_predecessor_dispatch() {
    let events = Arc::new(Mutex::new(Vec::new()));
    let mut host = new_host(graph(), handlers(&events));
    start_host(&mut host);
    let mut next = graph();
    next.generation = generation(8);
    let mut migration = MigrationFixture {
        fail_migrate: true,
        fail_rollback: true,
        ..MigrationFixture::default()
    };
    let error = host
        .replace_read_only_generation_with_migration(
            generation(7),
            next,
            handlers(&events),
            &mut migration,
        )
        .expect_err("failed restoration must not leave old state dispatchable");
    assert!(matches!(
        error,
        OrganRuntimeError::CandidateMigrationFailed {
            rollback_error: Some(_),
            ..
        }
    ));
    assert!(
        host.statuses()
            .iter()
            .all(|s| s.state == HostedOrganStateV1::Quarantined)
    );
    assert!(matches!(
        host.dispatch_once(generation(7), &id("source"), 0, b"no"),
        Err(OrganRuntimeError::OrganNotReady { .. })
    ));
    assert_eq!(migration.rollbacks.len(), 1);
}

#[test]
fn invalid_successor_does_not_invoke_state_owner() {
    let events = Arc::new(Mutex::new(Vec::new()));
    let mut host = new_host(graph(), handlers(&events));
    start_host(&mut host);
    let mut next = graph();
    next.generation = generation(8);
    let mut migration = MigrationFixture::default();
    assert!(
        host.replace_read_only_generation_with_migration(
            generation(7),
            next,
            Vec::new(),
            &mut migration,
        )
        .is_err()
    );
    assert!(migration.snapshots.is_empty());
    assert!(migration.rollbacks.is_empty());
}

#[test]
fn failed_predecessor_stop_preserves_the_rollback_error() {
    let events = Arc::new(Mutex::new(Vec::new()));
    let mut failing = FixtureOrgan::new("target.a", Arc::clone(&events));
    failing.stop_fault = true;
    let old_handlers: Vec<Box<dyn TrustedReadOnlyOrganV1>> = vec![
        Box::new(FixtureOrgan::new("source", Arc::clone(&events))),
        Box::new(failing),
        Box::new(FixtureOrgan::new("target.b", Arc::clone(&events))),
    ];
    let mut host = new_host(graph(), old_handlers);
    start_host(&mut host);
    let mut next = graph();
    next.generation = generation(8);
    let mut migration = MigrationFixture {
        fail_rollback: true,
        ..MigrationFixture::default()
    };
    assert!(matches!(
        host.replace_read_only_generation_with_migration(
            generation(7),
            next,
            handlers(&events),
            &mut migration,
        ),
        Err(OrganRuntimeError::MigrationReplacementStopFailed {
            rollback_error: Some(_),
            ..
        })
    ));
    assert_eq!(host.generation(), generation(7));
    assert!(
        host.dispatch_once(generation(7), &id("source"), 0, b"no")
            .is_err()
    );
}

#[test]
fn candidate_cleanup_precedes_state_restoration_even_when_callbacks_fail() {
    for (cleanup_fails, rollback_fails) in
        [(false, false), (true, false), (false, true), (true, true)]
    {
        let predecessor_events = Arc::new(Mutex::new(Vec::new()));
        let mut host = new_host(graph(), handlers(&predecessor_events));
        start_host(&mut host);
        let before = host.statuses();
        let candidate_events = Arc::new(Mutex::new(Vec::new()));
        let mut candidate_handlers = handlers(&candidate_events);
        let mut target = FixtureOrgan::new("target.b", Arc::clone(&candidate_events));
        target.stop_fault = cleanup_fails;
        candidate_handlers[2] = Box::new(target);
        let mut next = graph();
        next.generation = generation(8);
        let mut migration = MigrationFixture {
            fail_migrate: true,
            fail_rollback: rollback_fails,
            events: Some(Arc::clone(&candidate_events)),
            ..MigrationFixture::default()
        };

        let error = host
            .replace_read_only_generation_with_migration(
                generation(7),
                next,
                candidate_handlers,
                &mut migration,
            )
            .expect_err("the candidate migration was rejected");
        assert_eq!(
            *event_log(&candidate_events),
            vec![
                "start:source",
                "start:target.a",
                "start:target.b",
                "migrate",
                "stop:target.b",
                "stop:target.a",
                "stop:source",
                "rollback",
            ],
        );
        assert_eq!(
            error,
            OrganRuntimeError::CandidateMigrationFailed {
                error: OrganMigrationError::Callback(id("migration.failed")),
                rollback_error: rollback_fails
                    .then(|| OrganMigrationError::Callback(id("rollback.failed"))),
                candidate_cleanup_faults: if cleanup_fails {
                    vec![OrganFaultRecordV1 {
                        organ: id("target.b"),
                        code: id("stop.fault"),
                    }]
                } else {
                    Vec::new()
                },
            },
        );
        assert_eq!(host.generation(), generation(7));
        assert_eq!(
            migration.rollbacks,
            vec![(generation(7), generation(8), b"state-v1".to_vec())]
        );
        if rollback_fails {
            assert!(
                host.statuses()
                    .iter()
                    .all(|status| status.state == HostedOrganStateV1::Quarantined)
            );
        } else {
            assert_eq!(host.statuses(), before);
        }
        drop(host);
        assert_eq!(event_log(&candidate_events).len(), 8);
    }
}

#[test]
fn repeated_read_only_add_replace_retire_preserves_dispatch_and_generation_fences() {
    let events = Arc::new(Mutex::new(Vec::new()));
    let mut host = new_host(graph(), handlers(&events));
    start_host(&mut host);
    let mut retired = graph();
    retired.organs.remove(1);
    retired.initialization = vec![OrganEdge { from: 0, to: 1 }];
    retired.runtime = vec![RuntimeLinkV1 {
        output: OutputPort { organ: 0, port: 0 },
        input: InputPort { organ: 1, port: 0 },
        timing: DataflowTiming::Buffered,
    }];
    retired.fallback = vec![OrganEdge { from: 0, to: 1 }];
    retired.failure_domains.remove(1);
    retired.failure_domains[1].organ = 1;

    for number in 8..18 {
        let mut next = if number % 2 == 0 {
            retired.clone()
        } else {
            graph()
        };
        next.generation = generation(number);
        let implementations = next
            .organs
            .iter()
            .map(|organ| {
                let mut implementation = FixtureOrgan::new(organ.id.as_str(), Arc::clone(&events));
                implementation.output_bytes = number as usize;
                Box::new(implementation) as Box<dyn TrustedReadOnlyOrganV1>
            })
            .collect();
        host.replace_read_only_generation(generation(number - 1), next, implementations)
            .expect("compatible read-only topology succeeds");
        let expected_targets = if number % 2 == 0 {
            vec![id("target.b")]
        } else {
            vec![id("target.a"), id("target.b")]
        };
        let deliveries = host
            .dispatch_once(
                generation(number),
                &id("source"),
                /*output_port*/ 0,
                b"request",
            )
            .expect("current generation dispatches to the exact module set");
        assert_eq!(
            deliveries
                .iter()
                .map(|item| item.target.clone())
                .collect::<Vec<_>>(),
            expected_targets
        );
        assert!(
            deliveries
                .iter()
                .all(|item| item.output.len() == number as usize
                    && item.authority == AuthorityPosture::DENY_ALL)
        );
        assert_eq!(host.abi().len(), deliveries.len() + 1);
        assert_eq!(
            host.dispatch_once(
                generation(number - 1),
                &id("source"),
                /*output_port*/ 0,
                b"stale"
            ),
            Err(OrganRuntimeError::GenerationMismatch {
                expected: generation(number),
                actual: generation(number - 1)
            }),
        );
        if number % 2 == 0 {
            assert_eq!(
                host.dispatch_once(
                    generation(number),
                    &id("target.a"),
                    /*output_port*/ 0,
                    b"retired"
                ),
                Err(OrganRuntimeError::UnknownSource {
                    organ: id("target.a")
                }),
            );
        }
    }
    host.stop_all().expect("the final generation drains");
}


#[cfg(unix)]
#[derive(Debug)]
struct StatefulAcceptanceOwner {
    schema: u64,
    value: u64,
    retired: bool,
    fail_candidate: Option<Generation>,
    retire_candidate: Option<Generation>,
}

#[cfg(unix)]
impl StatefulAcceptanceOwner {
    fn new() -> Self {
        Self {
            schema: 1,
            value: 0,
            retired: false,
            fail_candidate: None,
            retire_candidate: None,
        }
    }

    fn record(&mut self, delta: u64) {
        assert!(!self.retired);
        self.value = self.value.checked_add(delta).expect("bounded fixture history");
    }

    fn decode(snapshot: &[u8]) -> Result<(u64, u64, bool), OrganMigrationError> {
        if snapshot.len() != 17 {
            return Err(OrganMigrationError::Rejected);
        }
        let mut schema = [0_u8; 8];
        schema.copy_from_slice(&snapshot[..8]);
        let mut value = [0_u8; 8];
        value.copy_from_slice(&snapshot[8..16]);
        let retired = match snapshot[16] {
            0 => false,
            1 => true,
            _ => return Err(OrganMigrationError::Rejected),
        };
        Ok((
            u64::from_be_bytes(schema),
            u64::from_be_bytes(value),
            retired,
        ))
    }
}

#[cfg(unix)]
impl OrganStateMigrationV1 for StatefulAcceptanceOwner {
    fn snapshot(&mut self, _predecessor: Generation) -> Result<Vec<u8>, OrganMigrationError> {
        let mut bytes = Vec::with_capacity(17);
        bytes.extend_from_slice(&self.schema.to_be_bytes());
        bytes.extend_from_slice(&self.value.to_be_bytes());
        bytes.push(u8::from(self.retired));
        Ok(bytes)
    }

    fn migrate(
        &mut self,
        snapshot: &[u8],
        _predecessor: Generation,
        candidate: Generation,
    ) -> Result<(), OrganMigrationError> {
        let (schema, value, retired) = Self::decode(snapshot)?;
        self.schema = schema.checked_add(1).ok_or(OrganMigrationError::Rejected)?;
        self.value = value;
        self.retired = retired;
        if self.fail_candidate == Some(candidate) {
            self.value = self.value.saturating_add(1_000_000);
            return Err(OrganMigrationError::Callback(id("stateful.migration.failed")));
        }
        if self.retire_candidate == Some(candidate) {
            self.retired = true;
        }
        Ok(())
    }

    fn rollback(
        &mut self,
        snapshot: &[u8],
        _predecessor: Generation,
        _candidate: Generation,
    ) -> Result<(), OrganMigrationError> {
        let (schema, value, retired) = Self::decode(snapshot)?;
        self.schema = schema;
        self.value = value;
        self.retired = retired;
        Ok(())
    }
}

#[cfg(unix)]
fn acceptance_authority(
    operation: &codex_hepta_operations::OperationIntentV1,
    nonce: u8,
) -> (
    codex_hepta_contracts::FinalUseAuthority,
    codex_hepta_contracts::SignedFinalUseGrant,
    tempfile::TempDir,
) {
    use codex_hepta_contracts::FinalUseGrant;
    use codex_hepta_contracts::FinalUseRevocations;
    use codex_hepta_contracts::SignedFinalUseGrant;
    use ed25519_dalek::Signer;
    use ed25519_dalek::SigningKey;
    use std::os::unix::fs::PermissionsExt;
    use std::time::SystemTime;
    use std::time::UNIX_EPOCH;

    let signing = SigningKey::from_bytes(&[61; 32]);
    let now = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .expect("clock")
        .as_millis() as u64;
    let grant = FinalUseGrant {
        schema_version: 1,
        signer_id: "architecture-acceptance-owner".to_owned(),
        authority_epoch: 11,
        grant_id: format!("architecture-acceptance-{nonce}"),
        nonce: [nonce; 32],
        binding: operation.final_use_binding(),
        not_before_unix_ms: now.saturating_sub(1_000),
        expires_at_unix_ms: now + 30_000,
    };
    let signature = signing
        .sign(&grant.signing_bytes().expect("signing bytes"))
        .to_bytes()
        .to_vec();
    let directory = tempfile::tempdir().expect("authority tempdir");
    std::fs::set_permissions(directory.path(), std::fs::Permissions::from_mode(0o700))
        .expect("authority directory permissions");
    let authority = codex_hepta_contracts::FinalUseAuthority::open_state_dir(
        directory.path(),
        "architecture-acceptance-owner".to_owned(),
        signing.verifying_key().to_bytes(),
        FinalUseRevocations {
            authority_epoch: 11,
            revision: 1,
            revoked_grant_ids: BTreeSet::new(),
        },
    )
    .expect("authority");
    (
        authority,
        SignedFinalUseGrant { grant, signature },
        directory,
    )
}

#[cfg(unix)]
#[tokio::test]
async fn stateful_feature_history_replace_failure_retire_preserves_effect_idempotency() {
    use codex_hepta_operations::DispatchEffect;
    use codex_hepta_operations::DurableOperationError;
    use codex_hepta_operations::DurableOperationState;
    use codex_hepta_operations::DurableOperationStore;
    use codex_hepta_operations::OperationIntentV1;
    use codex_hepta_operations::PrepareDisposition;
    use codex_hepta_operations::ReconciliationOutcome;
    use codex_hepta_operations::ReconciliationReceiptV1;
    use std::time::Duration;

    let events = Arc::new(Mutex::new(Vec::new()));
    let mut host = new_host(graph(), handlers(&events));
    start_host(&mut host);
    let baseline = host
        .dispatch_once(generation(7), &id("source"), 0, b"baseline")
        .expect("baseline dispatch");
    let baseline_unrelated = baseline
        .iter()
        .find(|delivery| delivery.target == id("target.b"))
        .expect("unrelated target")
        .output
        .clone();

    let mut state = StatefulAcceptanceOwner::new();
    for _ in 0..256 {
        state.record(1);
    }
    assert_eq!(state.value, 256);

    let mut generation_8 = graph();
    generation_8.generation = generation(8);
    host.replace_read_only_generation_with_migration(
        generation(7),
        generation_8,
        handlers(&events),
        &mut state,
    )
    .expect("stateful v2 cutover");
    assert_eq!(state.schema, 2);
    assert_eq!(state.value, 256);
    assert!(!state.retired);

    let mut failed_generation_9 = graph();
    failed_generation_9.generation = generation(9);
    state.fail_candidate = Some(generation(9));
    assert!(matches!(
        host.replace_read_only_generation_with_migration(
            generation(8),
            failed_generation_9,
            handlers(&events),
            &mut state,
        ),
        Err(OrganRuntimeError::CandidateMigrationFailed {
            rollback_error: None,
            ..
        })
    ));
    assert_eq!(host.generation(), generation(8));
    assert_eq!(state.schema, 2);
    assert_eq!(state.value, 256);
    assert!(
        host.dispatch_once(generation(8), &id("source"), 0, b"after-failed-upgrade")
            .is_ok()
    );

    state.fail_candidate = None;
    let mut generation_9 = graph();
    generation_9.generation = generation(9);
    host.replace_read_only_generation_with_migration(
        generation(8),
        generation_9,
        handlers(&events),
        &mut state,
    )
    .expect("stateful v3 cutover");
    assert_eq!(state.schema, 3);
    assert_eq!(state.value, 256);

    let directory = tempfile::tempdir().expect("operation tempdir");
    let path = directory.path().join("architecture-lifecycle.sqlite3");
    let effect_path = directory.path().join("effect.log");
    let operation = OperationIntentV1 {
        scope_id: id("scope:architecture.acceptance"),
        operation_id: id("operation:stateful-feature:publish"),
        expected_predecessor: None,
        destination: id("stateful.feature.effect"),
        payload_digest: Digest32::of_bytes(b"state-value-256"),
        owner_generation: generation(9),
    };
    let store = DurableOperationStore::open(&path).await.expect("operation store");
    let prepared = store.prepare_intent(&operation).await.expect("prepare effect");
    assert_eq!(prepared.disposition, PrepareDisposition::Inserted);
    assert_eq!(
        store
            .prepare_intent(&operation)
            .await
            .expect("idempotent prepare")
            .disposition,
        PrepareDisposition::AlreadyPresent
    );
    let claim = store
        .claim_next(
            &operation.destination,
            &id("worker:architecture.acceptance"),
            generation(9),
            Duration::from_secs(30),
        )
        .await
        .expect("claim effect")
        .expect("effect row");

    let mut forged = operation.clone();
    forged.payload_digest = Digest32::of_bytes(b"forged-payload");
    let (wrong_authority, wrong_grant, _wrong_dir) = acceptance_authority(&forged, 31);
    assert!(
        store
            .authorize_dispatch(&wrong_authority, &wrong_grant, &claim)
            .await
            .is_err(),
        "a grant bound to different payload bytes must not cross the effect boundary"
    );
    assert_eq!(
        store
            .operation(&operation.scope_id, &operation.operation_id)
            .await
            .expect("operation after denied grant")
            .expect("operation row")
            .state,
        DurableOperationState::Prepared
    );

    let (authority, grant, _authority_dir) = acceptance_authority(&operation, 32);
    let authorized = store
        .authorize_dispatch(&authority, &grant, &claim)
        .await
        .expect("authorized effect");
    let effect_target = effect_path.clone();
    store
        .execute_authorized(authorized, move |_| {
            std::fs::write(&effect_target, b"applied-once\n").expect("effect write");
            DispatchEffect::Indeterminate {
                value: (),
                reason_digest: Digest32::of_bytes(b"ack-lost-after-effect"),
            }
        })
        .await
        .expect("unknown effect classification");
    assert_eq!(
        std::fs::read(&effect_path).expect("effect bytes"),
        b"applied-once\n"
    );
    assert_eq!(
        store
            .operation(&operation.scope_id, &operation.operation_id)
            .await
            .expect("unknown lookup")
            .expect("unknown row")
            .state,
        DurableOperationState::Indeterminate
    );
    store.close().await;

    let reopened = DurableOperationStore::open(&path).await.expect("reopen after unknown effect");
    assert!(
        reopened
            .claim_next(
                &operation.destination,
                &id("worker:must-not-redeliver"),
                generation(10),
                Duration::from_secs(1),
            )
            .await
            .expect("post-crash claim query")
            .is_none(),
        "unknown effects must never be blindly redispatched"
    );
    assert_eq!(
        std::fs::read(&effect_path).expect("effect after reopen"),
        b"applied-once\n"
    );

    let terminal = ReconciliationReceiptV1 {
        outcome: ReconciliationOutcome::Applied,
        evidence_digest: Digest32::of_bytes(b"destination-observed-applied"),
        observer_id: id("observer:architecture.acceptance"),
        observer_generation: generation(9),
    };
    let settled = reopened
        .observe_terminal(&operation.scope_id, &operation.operation_id, &terminal)
        .await
        .expect("terminal reconciliation");
    assert_eq!(settled.state, DurableOperationState::Applied);
    assert_eq!(
        reopened
            .observe_terminal(&operation.scope_id, &operation.operation_id, &terminal)
            .await
            .expect("idempotent terminal reconciliation"),
        settled
    );
    let metrics = reopened.backlog_metrics().await.expect("backlog metrics");
    assert_eq!(metrics.active_operations, 0);
    assert_eq!(metrics.terminal_operations, 1);
    assert_eq!(reopened.prune_terminal(u64::MAX, 1).await.expect("prune"), 1);
    assert!(matches!(
        reopened.prepare_intent(&operation).await,
        Err(DurableOperationError::Retired(_))
    ));
    reopened.close().await;

    let mut retired = graph();
    retired.generation = generation(10);
    retired.organs.remove(1);
    retired.initialization = vec![OrganEdge { from: 0, to: 1 }];
    retired.runtime = vec![RuntimeLinkV1 {
        output: OutputPort { organ: 0, port: 0 },
        input: InputPort { organ: 1, port: 0 },
        timing: DataflowTiming::Buffered,
    }];
    retired.fallback = vec![OrganEdge { from: 0, to: 1 }];
    retired.failure_domains.remove(1);
    retired.failure_domains[1].organ = 1;
    let retired_handlers: Vec<Box<dyn TrustedReadOnlyOrganV1>> = ["source", "target.b"]
        .into_iter()
        .map(|name| {
            Box::new(FixtureOrgan::new(name, Arc::clone(&events))) as Box<dyn TrustedReadOnlyOrganV1>
        })
        .collect();
    state.retire_candidate = Some(generation(10));
    host.replace_read_only_generation_with_migration(
        generation(9),
        retired,
        retired_handlers,
        &mut state,
    )
    .expect("retire stateful feature");
    assert_eq!(state.schema, 4);
    assert_eq!(state.value, 256);
    assert!(state.retired);

    assert_eq!(
        host.dispatch_once(generation(9), &id("source"), 0, b"stale-generation"),
        Err(OrganRuntimeError::GenerationMismatch {
            expected: generation(10),
            actual: generation(9),
        })
    );
    assert_eq!(
        host.dispatch_once(generation(10), &id("target.a"), 0, b"retired"),
        Err(OrganRuntimeError::UnknownSource {
            organ: id("target.a"),
        })
    );
    let current = host
        .dispatch_once(generation(10), &id("source"), 0, b"after-retirement")
        .expect("unrelated module remains live");
    assert_eq!(current.len(), 1);
    assert_eq!(current[0].target, id("target.b"));
    assert_eq!(current[0].output, baseline_unrelated);
    assert_eq!(current[0].authority, AuthorityPosture::DENY_ALL);
}
