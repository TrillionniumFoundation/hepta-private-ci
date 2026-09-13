use super::*;
use std::sync::Arc;
use std::sync::Mutex;

use codex_hepta_types::AuthorityPosture;

use crate::BodyGraphBindingV1;
use crate::CompiledOrganAdmissionV2;
use crate::DataflowTiming;
use crate::FailureDomainV1;
use crate::FallbackTerminal;
use crate::InputPort;
use crate::MAX_ORGAN_MESSAGE_BYTES;
use crate::NativeHandoffProtocolAdmissionV1;
use crate::NativeHandoffProtocolRegistryV1;
use crate::OrganEdge;
use crate::OrganFaultRecordV1;
use crate::OrganHandlerFaultV1;
use crate::OrganManifestBindingV1;
use crate::OrganNodeV1;
use crate::OrganRole;
use crate::OutputPort;
use crate::RuntimeLinkV1;
use crate::TrustedReadOnlyOrganV1;
use crate::admit_compiled_body_graph_v2;
use crate::compiled_body_graph_digest_v2;
use crate::encode_compiled_body_graph_v2;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("valid test identity")
}

#[derive(Debug)]
struct Driver {
    id: StableId,
    events: Arc<Mutex<Vec<String>>>,
    marker: u8,
    fail: bool,
}

impl TrustedReadOnlyOrganV1 for Driver {
    fn id(&self) -> &StableId {
        &self.id
    }

    fn start(&mut self) -> Result<(), OrganHandlerFaultV1> {
        self.events.lock().unwrap().push(format!("start:{}", self.id));
        Ok(())
    }

    fn handle(&mut self, port: usize, payload: &[u8]) -> Result<Vec<u8>, OrganHandlerFaultV1> {
        self.events.lock().unwrap().push(format!("handle:{}", self.id));
        if self.fail || port != 0 {
            return Err(OrganHandlerFaultV1::new(id("driver.failed")));
        }
        let mut output = vec![self.marker];
        output.extend_from_slice(payload);
        Ok(output)
    }

    fn stop(&mut self) -> Result<(), OrganHandlerFaultV1> {
        self.events.lock().unwrap().push(format!("stop:{}", self.id));
        Ok(())
    }
}

struct Fixture {
    body: BodyGraphBindingV1,
    graph: OrganGraphsV1,
    hierarchy: CnsHierarchyV1,
    catalog: Vec<CompiledOrganDriverV1>,
    events: Arc<Mutex<Vec<String>>>,
}

impl Fixture {
    fn host(self) -> Result<CnsOrganHostV1, CnsHierarchyError> {
        let bytes = encode_compiled_body_graph_v2(&self.body, &self.graph)
            .map_err(CnsHierarchyError::Wire)?;
        let admission = CompiledOrganAdmissionV2 {
            expected_digest: compiled_body_graph_digest_v2(&bytes)
                .map_err(CnsHierarchyError::Wire)?,
            generation: self.graph.generation,
            process: id("test.process"),
            host: id("test.host"),
        };
        let (verified, _) = admit_compiled_body_graph_v2(
            &bytes,
            &admission,
            &NativeHandoffProtocolAdmissionV1::canonical().unwrap(),
            &NativeHandoffProtocolRegistryV1::canonical().unwrap(),
        )
        .map_err(CnsHierarchyError::Wire)?;
        verified.into_hierarchical_host(self.hierarchy, self.catalog)
    }

    fn rebind_graph(&mut self) {
        self.body.generation = self.graph.generation;
        self.hierarchy.generation = self.graph.generation;
        self.hierarchy.body_graph_digest = compiled_body_graph_digest_v2(
            &encode_compiled_body_graph_v2(&self.body, &self.graph).unwrap(),
        )
        .unwrap();
    }
}

fn fixture() -> Fixture {
    let generation = Generation::new(/*value*/ 7).unwrap();
    let names = ["ingress", "status", "health"];
    let graph = OrganGraphsV1 {
        generation,
        organs: names
            .iter()
            .enumerate()
            .map(|(index, name)| OrganNodeV1 {
                id: id(name),
                owner: id("test.owner"),
                role: OrganRole::Other,
                inputs: if index == 0 { vec![] } else { vec![id("status.v1")] },
                outputs: if index == 0 { vec![id("status.v1")] } else { vec![] },
                effect_scope: BTreeSet::new(),
                terminal: FallbackTerminal::SafeState(Digest32::of_bytes(b"unavailable")),
            })
            .collect(),
        initialization: vec![OrganEdge { from: 0, to: 1 }, OrganEdge { from: 0, to: 2 }],
        runtime: (1..3)
            .map(|organ| RuntimeLinkV1 {
                output: OutputPort { organ: 0, port: 0 },
                input: InputPort { organ, port: 0 },
                timing: DataflowTiming::Buffered,
            })
            .collect(),
        feedback: vec![],
        fallback: vec![],
        failure_domains: (0..3)
            .map(|organ| FailureDomainV1 {
                organ,
                process: id("test.process"),
                host: id("test.host"),
            })
            .collect(),
    };
    let body = BodyGraphBindingV1 {
        generation,
        organ_manifests: graph.organs.iter().map(|node| OrganManifestBindingV1 {
            organ_id: node.id.clone(),
            manifest_digest: Digest32::of_bytes(node.id.as_str().as_bytes()),
            organ_class: node.role,
            input_ports: node.inputs.clone(),
            output_ports: node.outputs.clone(),
        }).collect(),
        dependency_edges: graph.initialization.clone(),
        fallback_edges: graph.fallback.clone(),
        topological_order: graph.validate().unwrap().initialization_order,
        snapshot_digest: Digest32::of_bytes(b"test.body.provenance"),
    };
    let bindings: Vec<_> = names.iter().map(|name| OrganDriverBindingV1 {
        organ: id(name),
        driver: id(&format!("driver.{name}")),
        implementation_digest: Digest32::of_bytes(format!("implementation:{name}").as_bytes()),
    }).collect();
    let events = Arc::new(Mutex::new(Vec::new()));
    let catalog = bindings.iter().enumerate().map(|(index, binding)| CompiledOrganDriverV1 {
        binding: binding.clone(),
        compiled: CompiledOrganHandlerV2 {
            manifest_digest: body.organ_manifests[index].manifest_digest,
            handler: Box::new(Driver {
                id: binding.organ.clone(),
                events: Arc::clone(&events),
                marker: index as u8,
                fail: false,
            }),
        },
    }).collect();
    let hierarchy = CnsHierarchyV1 {
        cns: id("test.cns"),
        generation,
        body_graph_digest: compiled_body_graph_digest_v2(
            &encode_compiled_body_graph_v2(&body, &graph).unwrap(),
        ).unwrap(),
        systems: vec![
            OrganSystemV1 { id: id("control"), organs: vec![id("ingress")] },
            OrganSystemV1 { id: id("observation"), organs: vec![id("status"), id("health")] },
        ],
        drivers: bindings,
    };
    Fixture { body, graph, hierarchy, catalog, events }
}

fn route(host: &CnsOrganHostV1) -> CnsRouteV1 {
    host.route(&id("control"), &id("ingress"), /*output_port*/ 0).unwrap()
}

#[test]
fn actual_dispatch_preserves_all_levels_and_driver_outputs() {
    let fixture = fixture();
    let events = Arc::clone(&fixture.events);
    let mut host = fixture.host().unwrap();
    let route = route(&host);
    assert!(host.dispatch_once(&route, b"request").is_err());
    assert!(events.lock().unwrap().is_empty());
    host.start_all().unwrap();
    let expected: Vec<_> = ["status", "health"].iter().enumerate().map(|(index, name)| {
        let mut output = vec![(index + 1) as u8];
        output.extend_from_slice(b"request");
        CnsDeliveryV1 {
            cns: route.cns.clone(),
            generation: route.generation,
            hierarchy_digest: route.hierarchy_digest,
            source: route.source.clone(),
            target: OrganPathV1 {
                system: id("observation"), organ: id(name), driver: id(&format!("driver.{name}")),
            },
            execution: OrganDeliveryV1 {
                source: id("ingress"), target: id(name), input_port: 0, output,
                authority: AuthorityPosture::DENY_ALL,
            },
        }
    }).collect();
    assert_eq!(host.dispatch_once(&route, b"request").unwrap(), expected);
    host.stop_all().unwrap();
    assert_eq!(*events.lock().unwrap(), vec![
        "start:ingress", "start:status", "start:health", "handle:status", "handle:health",
        "stop:health", "stop:status", "stop:ingress",
    ]);
}

#[test]
fn edited_routes_are_rejected_before_any_driver_callback() {
    let fixture = fixture();
    let events = Arc::clone(&fixture.events);
    let mut host = fixture.host().unwrap();
    host.start_all().unwrap();
    let current = route(&host);
    for case in 0..10 {
        let mut changed = current.clone();
        match case {
            0 => changed.cns = id("other.cns"),
            1 => changed.generation = changed.generation.next().unwrap(),
            2 => changed.hierarchy_digest = Digest32::of_bytes(b"other"),
            3 => changed.source.system = id("other.system"),
            4 => changed.source.organ = id("other.organ"),
            5 => changed.source.driver = id("other.driver"),
            6 => changed.output_port = 1,
            7 => changed.targets.reverse(),
            8 => { changed.targets.pop(); }
            9 => changed.targets[0].driver = id("other.target.driver"),
            _ => unreachable!(),
        }
        let before = events.lock().unwrap().clone();
        assert!(host.dispatch_once(&changed, b"request").is_err(), "case {case}");
        assert_eq!(*events.lock().unwrap(), before);
    }
    assert!(host.route(&id("wrong"), &id("ingress"), /*output_port*/ 0).is_err());
    assert_eq!(host.dispatch_once(&current, b"valid").unwrap().len(), 2);
}

#[test]
fn invalid_system_memberships_never_start_handlers() {
    for case in 0..5 {
        let mut fixture = fixture();
        let events = Arc::clone(&fixture.events);
        match case {
            0 => fixture.hierarchy.systems[1].id = id("control"),
            1 => fixture.hierarchy.systems[1].organs[0] = id("ingress"),
            2 => { fixture.hierarchy.systems[1].organs.pop(); }
            3 => fixture.hierarchy.systems[1].organs[0] = id("unknown"),
            4 => fixture.hierarchy.systems[1].organs.clear(),
            _ => unreachable!(),
        }
        assert!(fixture.host().is_err(), "case {case}");
        assert!(events.lock().unwrap().is_empty());
    }
}

#[test]
fn independent_driver_catalog_and_manifest_are_required() {
    for case in 0..6 {
        let mut fixture = fixture();
        let events = Arc::clone(&fixture.events);
        match case {
            0 => fixture.hierarchy.drivers[1].driver = id("unregistered.driver"),
            1 => fixture.hierarchy.drivers[1].implementation_digest = Digest32::of_bytes(b"changed"),
            2 => fixture.hierarchy.drivers[1].driver = fixture.hierarchy.drivers[0].driver.clone(),
            3 => { fixture.catalog.pop(); }
            4 => fixture.catalog[1].binding = fixture.catalog[0].binding.clone(),
            5 => fixture.catalog[1].compiled.manifest_digest = Digest32::of_bytes(b"wrong.manifest"),
            _ => unreachable!(),
        }
        assert!(fixture.host().is_err(), "case {case}");
        assert!(events.lock().unwrap().is_empty());
    }
}

#[test]
fn hierarchy_binds_full_graph_and_generation_not_just_source_provenance() {
    for case in 0..3 {
        let mut fixture = fixture();
        let events = Arc::clone(&fixture.events);
        match case {
            0 => fixture.hierarchy.generation = fixture.hierarchy.generation.next().unwrap(),
            1 => fixture.hierarchy.body_graph_digest = fixture.body.snapshot_digest,
            2 => fixture.graph.runtime[0].timing = DataflowTiming::Synchronous,
            _ => unreachable!(),
        }
        assert_eq!(fixture.host().unwrap_err(), CnsHierarchyError::GraphBinding);
        assert!(events.lock().unwrap().is_empty());
    }
}

#[test]
fn declaration_order_does_not_change_route_identity() {
    let first = fixture().host().unwrap();
    let mut reordered = fixture();
    reordered.hierarchy.systems.reverse();
    reordered.hierarchy.systems[0].organs.reverse();
    reordered.hierarchy.drivers.reverse();
    reordered.catalog.reverse();
    let second = reordered.host().unwrap();
    assert_eq!(route(&first), route(&second));
}

#[test]
fn system_or_driver_replacement_invalidates_old_routes() {
    let first = fixture().host().unwrap();
    let previous = route(&first);
    for case in 0..3 {
        let mut fixture = fixture();
        match case {
            0 => fixture.hierarchy.systems[1].id = id("new.observation"),
            1 => {
                let binding = &mut fixture.hierarchy.drivers[1];
                binding.driver = id("replacement.driver");
                binding.implementation_digest = Digest32::of_bytes(b"replacement.implementation");
                fixture.catalog[1].binding = binding.clone();
                fixture.catalog[1].compiled.handler = Box::new(Driver {
                    id: id("status"), events: Arc::clone(&fixture.events), marker: 9, fail: false,
                });
            }
            2 => {
                fixture.graph.generation = fixture.graph.generation.next().unwrap();
                fixture.rebind_graph();
            }
            _ => unreachable!(),
        }
        let mut host = fixture.host().unwrap();
        host.start_all().unwrap();
        assert_eq!(host.dispatch_once(&previous, b"old"), Err(CnsHierarchyError::RouteMismatch));
        let current = route(&host);
        assert_ne!(current.hierarchy_digest, previous.hierarchy_digest);
        let delivered = host.dispatch_once(&current, b"new").unwrap();
        if case == 1 {
            assert_eq!(delivered[0].execution.output, b"\x09new");
        }
    }
}

#[test]
fn partial_failure_retains_host_quarantine_and_never_uses_direct_fallback() {
    let mut fixture = fixture();
    let events = Arc::clone(&fixture.events);
    fixture.catalog[2].compiled.handler = Box::new(Driver {
        id: id("health"), events: Arc::clone(&events), marker: 2, fail: true,
    });
    let mut host = fixture.host().unwrap();
    host.start_all().unwrap();
    let route = route(&host);
    assert_eq!(host.dispatch_once(&route, b"request"), Err(CnsHierarchyError::Runtime(
        OrganRuntimeError::HandleFailed {
            fault: OrganFaultRecordV1 { organ: id("health"), code: id("driver.failed") },
            delivered: 1,
        }
    )));
    let before = events.lock().unwrap().clone();
    assert!(host.dispatch_once(&route, b"retry").is_err());
    assert_eq!(*events.lock().unwrap(), before);
}

#[test]
fn stopped_and_oversized_requests_preserve_existing_host_checks() {
    let fixture = fixture();
    let events = Arc::clone(&fixture.events);
    let mut host = fixture.host().unwrap();
    host.start_all().unwrap();
    let route = route(&host);
    let before = events.lock().unwrap().clone();
    assert!(host.dispatch_once(&route, &vec![0; MAX_ORGAN_MESSAGE_BYTES + 1]).is_err());
    assert_eq!(*events.lock().unwrap(), before);
    host.stop_all().unwrap();
    let stopped = events.lock().unwrap().clone();
    assert!(host.dispatch_once(&route, b"after.stop").is_err());
    assert_eq!(*events.lock().unwrap(), stopped);
}
