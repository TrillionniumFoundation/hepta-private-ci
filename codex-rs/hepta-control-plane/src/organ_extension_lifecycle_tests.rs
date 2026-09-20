//! Real in-process component execution, not production activation or a durable
//! recovery claim. The 41st component transforms routed bytes through reviewed
//! factories. Every generation uses the existing public host and dispatch API.

use std::collections::BTreeSet;
use std::sync::Arc;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;

use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use crate::*;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("valid fixture identity")
}

fn generation(value: u64) -> Generation {
    Generation::new(value).expect("positive fixture generation")
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn graph(epoch: u64, feature: bool) -> OrganGraphsV1 {
    let count = if feature { 41 } else { 40 };
    let organs = (0..count)
        .map(|index| {
            let name = if index == 40 {
                "feature.41".to_owned()
            } else {
                format!("core.{index}")
            };
            let inputs = match index {
                0 => vec![],
                40 => vec![id("feature.v1")],
                _ => vec![id("message.v1")],
            };
            let outputs = if index == 0 {
                if feature {
                    vec![id("message.v1"), id("feature.v1")]
                } else {
                    vec![id("message.v1")]
                }
            } else {
                vec![]
            };
            OrganNodeV1 {
                id: id(&name),
                owner: id("test.owner"),
                role: OrganRole::Other,
                inputs,
                outputs,
                effect_scope: BTreeSet::new(),
                terminal: FallbackTerminal::SafeState(digest("safe-state")),
            }
        })
        .collect();
    OrganGraphsV1 {
        generation: generation(epoch),
        organs,
        initialization: (1..count).map(|to| OrganEdge { from: 0, to }).collect(),
        runtime: (1..count)
            .map(|target| RuntimeLinkV1 {
                output: OutputPort {
                    organ: 0,
                    port: if target == 40 { 1 } else { 0 },
                },
                input: InputPort {
                    organ: target,
                    port: 0,
                },
                timing: DataflowTiming::Buffered,
            })
            .collect(),
        feedback: vec![],
        fallback: vec![],
        failure_domains: (0..count)
            .map(|organ| FailureDomainV1 {
                organ,
                // Truthfully one process: callback containment is not a sandbox.
                process: id("test.process"),
                host: id("test.host"),
            })
            .collect(),
    }
}

#[derive(Clone, Copy, Debug)]
enum Mode {
    Echo,
    Reverse,
    Uppercase,
    StartPanic,
    StopPanic,
}

#[derive(Debug)]
struct ExecutableHandler {
    id: StableId,
    mode: Mode,
    started: bool,
    stops: Option<Arc<AtomicUsize>>,
}

impl TrustedReadOnlyOrganV1 for ExecutableHandler {
    fn id(&self) -> &StableId {
        &self.id
    }

    fn start(&mut self) -> Result<(), OrganHandlerFaultV1> {
        self.started = true;
        if matches!(self.mode, Mode::StartPanic) {
            panic!("injected start panic");
        }
        Ok(())
    }

    fn handle(
        &mut self,
        input_port: usize,
        payload: &[u8],
    ) -> Result<Vec<u8>, OrganHandlerFaultV1> {
        assert!(self.started);
        assert_eq!(input_port, 0);
        if !matches!(self.mode, Mode::Echo) && payload == b"panic" {
            panic!("injected optional callback panic");
        }
        Ok(match self.mode {
            Mode::Reverse => payload.iter().rev().copied().collect(),
            Mode::Uppercase => payload.to_ascii_uppercase(),
            _ => payload.to_vec(),
        })
    }

    fn stop(&mut self) -> Result<(), OrganHandlerFaultV1> {
        if let Some(stops) = &self.stops {
            stops.fetch_add(1, Ordering::SeqCst);
        }
        self.started = false;
        if matches!(self.mode, Mode::StopPanic) {
            panic!("injected stop panic");
        }
        Ok(())
    }
}

fn handler(organ: &StableId, mode: Mode) -> Box<dyn TrustedReadOnlyOrganV1> {
    Box::new(ExecutableHandler {
        id: organ.clone(),
        mode,
        started: false,
        stops: None,
    })
}

fn echo(organ: &StableId) -> Result<Box<dyn TrustedReadOnlyOrganV1>, OrganHandlerFaultV1> {
    Ok(handler(organ, Mode::Echo))
}

fn reverse(organ: &StableId) -> Result<Box<dyn TrustedReadOnlyOrganV1>, OrganHandlerFaultV1> {
    Ok(handler(organ, Mode::Reverse))
}

fn uppercase(organ: &StableId) -> Result<Box<dyn TrustedReadOnlyOrganV1>, OrganHandlerFaultV1> {
    Ok(handler(organ, Mode::Uppercase))
}

fn start_panic(organ: &StableId) -> Result<Box<dyn TrustedReadOnlyOrganV1>, OrganHandlerFaultV1> {
    Ok(handler(organ, Mode::StartPanic))
}

fn factory_panic(_: &StableId) -> Result<Box<dyn TrustedReadOnlyOrganV1>, OrganHandlerFaultV1> {
    panic!("injected factory panic");
}

fn registry() -> OrganHandlerRegistryV1 {
    let mut registry = OrganHandlerRegistryV1::new();
    for (name, factory) in [
        ("echo", echo as OrganHandlerFactoryV1),
        ("reverse", reverse as OrganHandlerFactoryV1),
        ("uppercase", uppercase as OrganHandlerFactoryV1),
        ("start-panic", start_panic as OrganHandlerFactoryV1),
        ("factory-panic", factory_panic as OrganHandlerFactoryV1),
    ] {
        registry
            .register(id(name), digest(name), factory)
            .expect("register");
    }
    registry
}

fn bindings(graph: &OrganGraphsV1, feature_driver: &str) -> Vec<OrganDriverBindingV1> {
    graph
        .organs
        .iter()
        .map(|organ| {
            let driver = if organ.id == id("feature.41") {
                feature_driver
            } else {
                "echo"
            };
            OrganDriverBindingV1 {
                organ: organ.id.clone(),
                driver: id(driver),
                implementation_digest: digest(driver),
            }
        })
        .collect()
}

fn live_host(registry: &OrganHandlerRegistryV1, feature: bool) -> OrganHostV1 {
    let graph = graph(1, feature);
    let selected = bindings(&graph, "reverse");
    let mut host = registry.create_host(graph, &selected).expect("construct");
    host.start_all().expect("start");
    host
}

fn replace(
    registry: &OrganHandlerRegistryV1,
    host: &mut OrganHostV1,
    epoch: u64,
    feature: bool,
    driver: &str,
) -> Result<(), OrganHandlerRegistryError> {
    let next = graph(epoch, feature);
    let selected = bindings(&next, driver);
    let previous = host.generation();
    registry.replace_host(host, previous, next, &selected)
}

fn core_still_serves(host: &mut OrganHostV1) {
    let delivered = host
        .dispatch_once(host.generation(), &id("core.0"), 0, b"core-request")
        .expect("core remains available");
    assert_eq!(delivered.len(), 39);
    assert!(delivered.iter().all(|row| row.output == b"core-request"));
    assert!(delivered.iter().all(|row| !row.authority.grants_any()));
}

fn feature_output(host: &mut OrganHostV1, payload: &[u8]) -> Vec<u8> {
    let delivered = host
        .dispatch_once(host.generation(), &id("core.0"), 1, payload)
        .expect("feature executes");
    assert_eq!(delivered.len(), 1);
    assert_eq!(delivered[0].target, id("feature.41"));
    assert!(!delivered[0].authority.grants_any());
    delivered[0].output.clone()
}

fn assert_fenced(host: &mut OrganHostV1, previous: Generation) {
    assert!(matches!(
        host.dispatch_once(previous, &id("core.0"), 0, b"stale"),
        Err(OrganRuntimeError::GenerationMismatch { .. })
    ));
}

#[test]
fn forty_first_executable_feature_add_replace_fault_retire_uses_one_registry() {
    let registry = registry();
    let mut host = live_host(&registry, false);
    core_still_serves(&mut host);
    for (epoch, driver, expected) in [(2, "reverse", b"cba"), (3, "uppercase", b"ABC")] {
        let previous = host.generation();
        replace(&registry, &mut host, epoch, true, driver).expect("cutover");
        assert_eq!(feature_output(&mut host, b"abc"), expected);
        assert_fenced(&mut host, previous);
        core_still_serves(&mut host);
    }
    assert!(matches!(
        host.dispatch_once(generation(3), &id("core.0"), 1, b"panic"),
        Err(OrganRuntimeError::HandleFailed { delivered: 0, .. })
    ));
    assert_eq!(host.statuses()[40].state, HostedOrganStateV1::Quarantined);
    core_still_serves(&mut host);
    assert!(matches!(
        host.dispatch_once(generation(3), &id("core.0"), 1, b"abc"),
        Err(OrganRuntimeError::OrganNotReady { .. })
    ));
    replace(&registry, &mut host, 4, false, "reverse")
        .expect("faulted read-only feature stops before retirement");
    assert_eq!(host.statuses().len(), 40);
    assert!(host.statuses().iter().all(|row| row.id != id("feature.41")));
    assert!(matches!(
        host.dispatch_once(generation(4), &id("core.0"), 1, b"retired"),
        Err(OrganRuntimeError::InvalidOutputPort { .. })
    ));
    core_still_serves(&mut host);
}

#[test]
fn repeated_executable_add_and_retire_fences_every_previous_generation() {
    let registry = registry();
    let mut host = live_host(&registry, false);
    for epoch in 2..=130 {
        let feature = epoch % 2 == 0;
        let previous = host.generation();
        replace(&registry, &mut host, epoch, feature, "reverse").expect("same lifecycle entry point");
        assert_eq!(host.statuses().len(), if feature { 41 } else { 40 });
        assert_fenced(&mut host, previous);
        core_still_serves(&mut host);
        if feature {
            assert_eq!(feature_output(&mut host, b"12345"), b"54321");
        }
    }
    host.stop_all().expect("final drain");
    assert!(
        host.statuses()
            .iter()
            .all(|row| row.state == HostedOrganStateV1::Stopped)
    );
}

#[test]
fn factory_or_start_panic_never_replaces_the_serving_generation() {
    let registry = registry();
    let mut host = live_host(&registry, false);
    for driver in ["factory-panic", "start-panic"] {
        let error =
            replace(&registry, &mut host, 2, true, driver).expect_err("candidate must fail");
        match driver {
            "factory-panic" => {
                assert!(matches!(error, OrganHandlerRegistryError::Factory { .. }));
            }
            _ => {
                assert!(matches!(
                    error,
                    OrganHandlerRegistryError::Runtime(OrganRuntimeError::StartFailed { .. })
                ));
            }
        }
        assert_eq!(host.generation(), generation(1));
        core_still_serves(&mut host);
    }
}

#[test]
fn port_digest_and_stale_generation_reject_before_factory_execution() {
    let registry = registry();
    let mut host = live_host(&registry, false);
    let mut next = graph(2, true);
    let selected = bindings(&next, "factory-panic");
    next.organs[40].inputs = vec![id("incompatible.v2")];
    assert!(matches!(
        registry.replace_host(&mut host, generation(1), next, &selected),
        Err(OrganHandlerRegistryError::Runtime(OrganRuntimeError::Graph(
            _
        )))
    ));
    let next = graph(2, true);
    let mut selected = bindings(&next, "factory-panic");
    selected[40].implementation_digest = digest("unreviewed-code");
    assert!(matches!(
        registry.replace_host(&mut host, generation(1), next, &selected),
        Err(OrganHandlerRegistryError::DriverDigestMismatch { .. })
    ));
    let next = graph(3, true);
    let selected = bindings(&next, "factory-panic");
    assert!(matches!(
        registry.replace_host(&mut host, generation(2), next, &selected),
        Err(OrganHandlerRegistryError::Runtime(
            OrganRuntimeError::GenerationMismatch { .. }
        ))
    ));
    core_still_serves(&mut host);
}

#[test]
fn stop_panic_blocks_cutover_and_is_not_retried_by_drop() {
    let stops = Arc::new(AtomicUsize::new(0));
    let initial = graph(1, true);
    let handlers = initial
        .organs
        .iter()
        .map(|organ| {
            if organ.id == id("feature.41") {
                Box::new(ExecutableHandler {
                    id: organ.id.clone(),
                    mode: Mode::StopPanic,
                    started: false,
                    stops: Some(Arc::clone(&stops)),
                }) as Box<dyn TrustedReadOnlyOrganV1>
            } else {
                handler(&organ.id, Mode::Echo)
            }
        })
        .collect();
    let mut host = OrganHostV1::new(initial, handlers).expect("construct");
    host.start_all().expect("start");
    let registry = registry();
    assert!(matches!(
        replace(&registry, &mut host, 2, false, "reverse"),
        Err(OrganHandlerRegistryError::Runtime(
            OrganRuntimeError::ReplacementStopFailed { .. }
        ))
    ));
    assert_eq!(host.generation(), generation(1));
    assert_eq!(stops.load(Ordering::SeqCst), 1);
    assert!(matches!(
        replace(&registry, &mut host, 2, false, "reverse"),
        Err(OrganHandlerRegistryError::Runtime(
            OrganRuntimeError::OrganNotReady { .. }
        ))
    ));
    drop(host);
    assert_eq!(stops.load(Ordering::SeqCst), 1);
}

struct OwnerMigration {
    value: u64,
    fail_rollback: bool,
    fail_snapshot: bool,
}

impl OrganStateMigrationV1 for OwnerMigration {
    fn snapshot(&mut self, _: Generation) -> Result<Vec<u8>, OrganMigrationError> {
        assert!(!self.fail_snapshot, "snapshot panic");
        Ok(self.value.to_le_bytes().to_vec())
    }

    fn migrate(
        &mut self,
        _: &[u8],
        _: Generation,
        _: Generation,
    ) -> Result<(), OrganMigrationError> {
        self.value = 999;
        panic!("migration failed after mutation");
    }

    fn rollback(
        &mut self,
        snapshot: &[u8],
        _: Generation,
        _: Generation,
    ) -> Result<(), OrganMigrationError> {
        assert!(!self.fail_rollback, "rollback panic");
        self.value = u64::from_le_bytes(snapshot.try_into().expect("owner snapshot"));
        Ok(())
    }
}

fn owner_candidate_handlers(next: &OrganGraphsV1) -> Vec<Box<dyn TrustedReadOnlyOrganV1>> {
    next.organs
        .iter()
        .map(|organ| handler(&organ.id, Mode::Echo))
        .collect()
}

#[test]
fn migration_panic_restores_owner_state_before_resuming_predecessor() {
    let registry = registry();
    let mut host = live_host(&registry, false);
    let next = graph(2, false);
    let handlers = owner_candidate_handlers(&next);
    let mut owner = OwnerMigration {
        value: 7,
        fail_rollback: false,
        fail_snapshot: false,
    };
    assert!(matches!(
        host.replace_read_only_generation_with_migration(generation(1), next, handlers, &mut owner),
        Err(OrganRuntimeError::CandidateMigrationFailed {
            rollback_error: None,
            ..
        })
    ));
    assert_eq!(owner.value, 7);
    assert_eq!(host.generation(), generation(1));
    core_still_serves(&mut host);
}

#[test]
fn uncertain_snapshot_or_rollback_never_uses_dispatch_fault_recovery() {
    for fail_snapshot in [false, true] {
        let registry = registry();
        let mut host = live_host(&registry, false);
        let next = graph(2, false);
        let handlers = owner_candidate_handlers(&next);
        let mut owner = OwnerMigration {
            value: 7,
            fail_rollback: true,
            fail_snapshot,
        };
        let result = host.replace_read_only_generation_with_migration(
            generation(1),
            next,
            handlers,
            &mut owner,
        );
        assert!(result.is_err());
        assert!(
            host.statuses()
                .iter()
                .all(|row| row.state == HostedOrganStateV1::Quarantined)
        );
        assert!(matches!(
            host.dispatch_once(generation(1), &id("core.0"), 0, b"not-safe"),
            Err(OrganRuntimeError::OrganNotReady { .. })
        ));
        assert!(matches!(
            replace(&registry, &mut host, 2, false, "reverse"),
            Err(OrganHandlerRegistryError::Runtime(
                OrganRuntimeError::OrganNotReady { .. }
            ))
        ));
    }
}
