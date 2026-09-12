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
        Ok(())
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
