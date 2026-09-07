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
