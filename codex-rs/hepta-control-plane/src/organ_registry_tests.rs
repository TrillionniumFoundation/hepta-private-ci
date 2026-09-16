use std::collections::BTreeSet;

use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use pretty_assertions::assert_eq;

use crate::*;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("valid fixture identity")
}

fn graph() -> OrganGraphsV1 {
    let port = id("message.v1");
    OrganGraphsV1 {
        generation: Generation::new(1).expect("valid generation"),
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
                id: id("target"),
                owner: id("owner"),
                role: OrganRole::Other,
                inputs: vec![port],
                outputs: vec![],
                effect_scope: BTreeSet::new(),
                terminal: FallbackTerminal::SafeState(Digest32::of_bytes(b"safe")),
            },
        ],
        initialization: vec![OrganEdge { from: 0, to: 1 }],
        runtime: vec![RuntimeLinkV1 {
            output: OutputPort { organ: 0, port: 0 },
            input: InputPort { organ: 1, port: 0 },
            timing: DataflowTiming::Buffered,
        }],
        feedback: vec![],
        fallback: vec![OrganEdge { from: 0, to: 1 }],
        failure_domains: vec![
            FailureDomainV1 {
                organ: 0,
                process: id("process.source"),
                host: id("host"),
            },
            FailureDomainV1 {
                organ: 1,
                process: id("process.target"),
                host: id("host"),
            },
        ],
    }
}

#[derive(Debug)]
struct FixtureHandler {
    id: StableId,
}

impl TrustedReadOnlyOrganV1 for FixtureHandler {
    fn id(&self) -> &StableId {
        &self.id
    }

    fn start(&mut self) -> Result<(), OrganHandlerFaultV1> {
        Ok(())
    }

    fn handle(
        &mut self,
        _input_port: usize,
        _payload: &[u8],
    ) -> Result<Vec<u8>, OrganHandlerFaultV1> {
        Ok(vec![1])
    }

    fn stop(&mut self) -> Result<(), OrganHandlerFaultV1> {
        Ok(())
    }
}

fn fixture_factory(
    organ: &StableId,
) -> Result<Box<dyn TrustedReadOnlyOrganV1>, OrganHandlerFaultV1> {
    Ok(Box::new(FixtureHandler { id: organ.clone() }))
}

fn unused_factory(
    _organ: &StableId,
) -> Result<Box<dyn TrustedReadOnlyOrganV1>, OrganHandlerFaultV1> {
    panic!("unselected factory must not be called")
}

fn digest(name: &str) -> Digest32 {
    Digest32::of_bytes(name.as_bytes())
}

fn bindings() -> Vec<OrganDriverBindingV1> {
    vec![
        OrganDriverBindingV1 {
            organ: id("source"),
            driver: id("driver.source"),
            implementation_digest: digest("source"),
        },
        OrganDriverBindingV1 {
            organ: id("target"),
            driver: id("driver.target"),
            implementation_digest: digest("target"),
        },
    ]
}

#[test]
fn creates_only_selected_handlers_from_a_superset_registry() {
    let mut registry = OrganHandlerRegistryV1::new();
    registry
        .register(id("driver.source"), digest("source"), fixture_factory)
        .expect("register source");
    registry
        .register(id("driver.target"), digest("target"), fixture_factory)
        .expect("register target");
    registry
        .register(id("driver.unused"), digest("unused"), unused_factory)
        .expect("register unused");

    let host = registry
        .create_host(graph(), &bindings())
        .expect("create host");
    assert_eq!(host.statuses().len(), 2);
    assert_eq!(registry.len(), 3);
}

#[test]
fn one_driver_implementation_can_back_multiple_organ_instances() {
    let mut registry = OrganHandlerRegistryV1::new();
    registry
        .register(id("driver.shared"), digest("shared"), fixture_factory)
        .expect("register shared implementation");
    let bindings = vec![
        OrganDriverBindingV1 {
            organ: id("source"),
            driver: id("driver.shared"),
            implementation_digest: digest("shared"),
        },
        OrganDriverBindingV1 {
            organ: id("target"),
            driver: id("driver.shared"),
            implementation_digest: digest("shared"),
        },
    ];

    let host = registry
        .create_host(graph(), &bindings)
        .expect("create host from one implementation and two instances");
    assert_eq!(host.statuses().len(), 2);
    assert_eq!(registry.len(), 1);
    assert_eq!(host.statuses()[0].id, id("source"));
    assert_eq!(host.statuses()[1].id, id("target"));
}

#[test]
fn rejects_duplicate_or_unknown_bindings_before_factory_calls() {
    let mut registry = OrganHandlerRegistryV1::new();
    registry
        .register(id("driver.source"), digest("source"), fixture_factory)
        .expect("register source");
    registry
        .register(id("driver.target"), digest("target"), fixture_factory)
        .expect("register target");

    let mut duplicate = bindings();
    duplicate[1].organ = duplicate[0].organ.clone();
    assert!(matches!(
        registry.create_host(graph(), &duplicate),
        Err(OrganHandlerRegistryError::DuplicateOrgan(organ)) if organ == id("source")
    ));

    let mut unknown = bindings();
    unknown[1].driver = id("driver.unknown");
    assert!(matches!(
        registry.create_host(graph(), &unknown),
        Err(OrganHandlerRegistryError::UnknownDriver(driver)) if driver == id("driver.unknown")
    ));
}

#[test]
fn rejects_handler_identity_drift() {
    fn wrong_factory(
        _organ: &StableId,
    ) -> Result<Box<dyn TrustedReadOnlyOrganV1>, OrganHandlerFaultV1> {
        Ok(Box::new(FixtureHandler { id: id("wrong") }))
    }

    let mut registry = OrganHandlerRegistryV1::new();
    registry
        .register(id("driver.source"), digest("source"), wrong_factory)
        .expect("register source");
    registry
        .register(id("driver.target"), digest("target"), fixture_factory)
        .expect("register target");
    assert!(matches!(
        registry.create_host(graph(), &bindings()),
        Err(OrganHandlerRegistryError::HandlerIdentityMismatch { expected, actual })
            if expected == id("source") && actual == id("wrong")
    ));
}
