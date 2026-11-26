use super::*;

use std::collections::BTreeSet;

use codex_hepta_types::CellBundleBindingV1;
use codex_hepta_types::CellBundleInheritanceV1;
use codex_hepta_types::CellBundleModeV1;
use codex_hepta_types::CellCachePolicyV1;
use codex_hepta_types::CellChildPortBindingV1;
use codex_hepta_types::CellChildV1;
use codex_hepta_types::CellInFlightPolicyV1;
use codex_hepta_types::CellParentDispositionV1;
use codex_hepta_types::CellParentRetirementPlanV1;
use codex_hepta_types::CellPortCompatibilityV1;
use codex_hepta_types::CellResourceDeltaV1;
use codex_hepta_types::CellRouteModeV1;
use codex_hepta_types::CellSplitEvaluationBindingV1;
use codex_hepta_types::CellSplitV1;
use codex_hepta_types::CellStateSplitPlanV1;
use codex_hepta_types::CellStateTransformKindV1;
use codex_hepta_types::CellStateTransformV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use crate::BodyGraphBindingV1;
use crate::CnsHierarchyV1;
use crate::CnsOrganHostV1;
use crate::CompiledOrganAdmissionV2;
use crate::CompiledOrganDriverV1;
use crate::CompiledOrganHandlerV2;
use crate::DataflowTiming;
use crate::FailureDomainV1;
use crate::FallbackTerminal;
use crate::InputPort;
use crate::NativeHandoffProtocolAdmissionV1;
use crate::NativeHandoffProtocolRegistryV1;
use crate::OrganEdge;
use crate::OrganHandlerFaultV1;
use crate::OrganManifestBindingV1;
use crate::OrganNodeV1;
use crate::OrganRole;
use crate::OrganSystemV1;
use crate::OutputPort;
use crate::RuntimeLinkV1;
use crate::TrustedReadOnlyOrganV1;
use crate::admit_compiled_body_graph_v2;
use crate::cns_child_port_compatibility_digest_v1;
use crate::cns_circuit_route_digest_v1;
use crate::cns_organ_abi_set_digest_v1;
use crate::cns_organ_input_port_digest_v1;
use crate::cns_organ_termination_port_digest_v1;
use crate::cns_route_digest_v1;
use crate::cns_route_port_binding_digest_v1;
use crate::compiled_body_graph_digest_v2;
use crate::encode_compiled_body_graph_v2;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("valid test identity")
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

#[derive(Debug)]
struct Driver {
    id: StableId,
}

impl TrustedReadOnlyOrganV1 for Driver {
    fn id(&self) -> &StableId {
        &self.id
    }

    fn start(&mut self) -> Result<(), OrganHandlerFaultV1> {
        Ok(())
    }

    fn handle(
        &mut self,
        _input_port: usize,
        payload: &[u8],
    ) -> Result<Vec<u8>, OrganHandlerFaultV1> {
        Ok(payload.to_vec())
    }

    fn stop(&mut self) -> Result<(), OrganHandlerFaultV1> {
        Ok(())
    }
}

fn host(generation: u64, children: &[(&str, &str)]) -> CnsOrganHostV1 {
    let generation = Generation::new(generation).unwrap();
    let mut names = Vec::new();
    let mut organs = Vec::new();
    let mut initialization = Vec::new();
    let mut runtime = Vec::new();
    if children.is_empty() {
        names.extend(["parent", "sink"]);
        organs.push(node("parent", vec![], vec!["bus"]));
        organs.push(node("sink", vec!["bus"], vec![]));
        initialization.push(OrganEdge { from: 0, to: 1 });
        runtime.push(RuntimeLinkV1 {
            output: OutputPort { organ: 0, port: 0 },
            input: InputPort { organ: 1, port: 0 },
            timing: DataflowTiming::Buffered,
        });
    } else {
        for (index, (child, sink)) in children.iter().enumerate() {
            names.push(*child);
            names.push(*sink);
            let child_index = index * 2;
            organs.push(node(child, vec![], vec![&format!("bus.{index}")]));
            organs.push(node(sink, vec![&format!("bus.{index}")], vec![]));
            initialization.push(OrganEdge {
                from: child_index,
                to: child_index + 1,
            });
            runtime.push(RuntimeLinkV1 {
                output: OutputPort {
                    organ: child_index,
                    port: 0,
                },
                input: InputPort {
                    organ: child_index + 1,
                    port: 0,
                },
                timing: DataflowTiming::Buffered,
            });
        }
    }
    let graph = crate::OrganGraphsV1 {
        generation,
        organs,
        initialization: initialization.clone(),
        runtime,
        feedback: vec![],
        fallback: vec![],
        failure_domains: (0..names.len())
            .map(|organ| FailureDomainV1 {
                organ,
                process: id("test.process"),
                host: id("test.host"),
            })
            .collect(),
    };
    let body = BodyGraphBindingV1 {
        generation,
        organ_manifests: graph
            .organs
            .iter()
            .map(|organ| OrganManifestBindingV1 {
                organ_id: organ.id.clone(),
                manifest_digest: digest(organ.id.as_str()),
                organ_class: organ.role,
                input_ports: organ.inputs.clone(),
                output_ports: organ.outputs.clone(),
            })
            .collect(),
        dependency_edges: initialization,
        fallback_edges: graph.fallback.clone(),
        topological_order: graph.validate().unwrap().initialization_order,
        snapshot_digest: digest("snapshot"),
    };
    let bindings: Vec<_> = names
        .iter()
        .map(|name| crate::OrganDriverBindingV1 {
            organ: id(name),
            driver: id(&format!("driver.{name}")),
            implementation_digest: digest(&format!("implementation:{name}")),
        })
        .collect();
    let catalog = bindings
        .iter()
        .map(|binding| CompiledOrganDriverV1 {
            binding: binding.clone(),
            compiled: CompiledOrganHandlerV2 {
                manifest_digest: digest(binding.organ.as_str()),
                handler: Box::new(Driver {
                    id: binding.organ.clone(),
                }),
            },
        })
        .collect();
    let bytes = encode_compiled_body_graph_v2(&body, &graph).unwrap();
    let graph_digest = compiled_body_graph_digest_v2(&bytes).unwrap();
    let hierarchy = CnsHierarchyV1 {
        cns: id("test.cns"),
        generation,
        body_graph_digest: graph_digest,
        systems: vec![OrganSystemV1 {
            id: id("system"),
            organs: names.iter().map(|name| id(name)).collect(),
        }],
        drivers: bindings,
    };
    let admission = CompiledOrganAdmissionV2 {
        expected_digest: graph_digest,
        generation,
        process: id("test.process"),
        host: id("test.host"),
    };
    let (verified, _) = admit_compiled_body_graph_v2(
        &bytes,
        &admission,
        &NativeHandoffProtocolAdmissionV1::canonical().unwrap(),
        &NativeHandoffProtocolRegistryV1::canonical().unwrap(),
    )
    .unwrap();
    verified.into_hierarchical_host(hierarchy, catalog).unwrap()
}

fn node(id_value: &str, inputs: Vec<&str>, outputs: Vec<&str>) -> OrganNodeV1 {
    OrganNodeV1 {
        id: id(id_value),
        owner: id("owner"),
        role: OrganRole::Other,
        inputs: inputs.into_iter().map(id).collect(),
        outputs: outputs.into_iter().map(id).collect(),
        effect_scope: BTreeSet::new(),
        terminal: FallbackTerminal::SafeState(digest("safe")),
    }
}

fn split(
    parent_host: &CnsOrganHostV1,
    parent_route: &CnsRouteV1,
    child_host: &CnsOrganHostV1,
    child_routes: &[CnsRouteV1],
) -> CellSplitV1 {
    let parent_port_digest = cns_route_port_binding_digest_v1(parent_host, parent_route).unwrap();
    let parent_input_digest =
        cns_organ_input_port_digest_v1(parent_host, &parent_route.source.organ).unwrap();
    let child_ids = child_routes
        .iter()
        .map(|route| route.source.organ.clone())
        .collect::<Vec<_>>();
    let abi_digest = cns_organ_abi_set_digest_v1(child_host, &child_ids).unwrap();
    let circuit_route_digest = cns_circuit_route_digest_v1(child_host, child_routes).unwrap();
    let parent_generation = parent_route.generation;
    let successor_generation = Generation::new(parent_generation.get() + 1).unwrap();
    let children = child_routes
        .iter()
        .map(|route| {
            let child = route.source.organ.clone();
            CellChildV1 {
                child_cell_id: child.clone(),
                child_generation: successor_generation,
                child_scope_digest: digest(&format!("scope:{child}")),
                lineage_digest: digest(&format!("lineage:{child}")),
                child_definition_digest: digest(&format!("definition:{child}")),
                child_bundle_digest: digest(&format!("bundle:{child}")),
                dataset_partition_digest: digest(&format!("dataset:{child}")),
                task_objective_digest: digest(&format!("objective:{child}")),
                route_predicate_digest: digest(&format!("predicate:{child}")),
                fallback_route_digest: digest(&format!("fallback:{child}")),
                route_mode: CellRouteModeV1::Exclusive,
            }
        })
        .collect::<Vec<_>>();
    let bindings = children
        .iter()
        .map(|child| CellBundleBindingV1 {
            child_cell_id: child.child_cell_id.clone(),
            base_digest: digest("base"),
            organ_adapter_digest: digest("organ-adapter"),
            cell_adapter_digest: digest("cell-adapter"),
            head_digest: digest("head"),
            compatibility_digest: digest("bundle-compatibility"),
        })
        .collect();
    let ports = children
        .iter()
        .zip(child_routes)
        .map(|(child, route)| CellChildPortBindingV1 {
            child_cell_id: child.child_cell_id.clone(),
            input_port_digest: cns_organ_input_port_digest_v1(child_host, &child.child_cell_id)
                .unwrap(),
            output_port_digest: cns_route_port_binding_digest_v1(child_host, route).unwrap(),
            termination_port_digest: cns_organ_termination_port_digest_v1(
                child_host,
                &child.child_cell_id,
            )
            .unwrap(),
            compatibility_digest: cns_child_port_compatibility_digest_v1(child_host, route)
                .unwrap(),
        })
        .collect();
    CellSplitV1 {
        split_id: id("split-1"),
        proposer_id: id("proposer"),
        evaluator_id: id("evaluator"),
        parent_cell_id: id("parent-cell"),
        organ_id: parent_route.source.organ.clone(),
        parent_scope_digest: digest("parent-scope"),
        predecessor_generation: parent_generation,
        successor_generation,
        parent_definition_digest: digest("parent-definition"),
        parent_bundle_digest: digest("parent-bundle"),
        children,
        inheritance: CellBundleInheritanceV1 {
            base_mode: CellBundleModeV1::SharedImmutable,
            organ_adapter_mode: CellBundleModeV1::CloneMutable,
            cell_adapter_mode: CellBundleModeV1::Reset,
            head_mode: CellBundleModeV1::Distill,
            compatibility_digest: digest("bundle-compatibility"),
            children: bindings,
        },
        state: CellStateSplitPlanV1 {
            recurrent: CellStateTransformV1 {
                kind: CellStateTransformKindV1::Partition,
                source_schema_digest: digest("recurrent-source"),
                target_schema_digest: digest("recurrent-target"),
                mapping_digest: digest("recurrent-mapping"),
            },
            eligibility: CellStateTransformV1 {
                kind: CellStateTransformKindV1::Partition,
                source_schema_digest: digest("eligibility-source"),
                target_schema_digest: digest("eligibility-target"),
                mapping_digest: digest("eligibility-mapping"),
            },
            optimizer: CellStateTransformV1 {
                kind: CellStateTransformKindV1::Reset,
                source_schema_digest: digest("optimizer-source"),
                target_schema_digest: digest("optimizer-target"),
                mapping_digest: Digest32::ZERO,
            },
            cache_policy: CellCachePolicyV1::Drop,
            in_flight_policy: CellInFlightPolicyV1::Drain,
            state_evidence_digest: digest("state-evidence"),
        },
        ports: CellPortCompatibilityV1 {
            parent_input_port_digest: parent_input_digest,
            parent_output_port_digest: parent_port_digest,
            circuit_route_digest,
            abi_digest,
            children: ports,
        },
        resources: CellResourceDeltaV1 {
            inference_latency_micros: 1,
            training_steps: 1,
            communication_bytes: 1,
            migration_bytes: 1,
            evaluation_steps: 1,
            resident_bytes: 1,
            checkpoint_bytes: 1,
        },
        retirement: CellParentRetirementPlanV1 {
            disposition: CellParentDispositionV1::Retire,
            drain_watermark_digest: digest("drain"),
            tombstone_digest: digest("tombstone"),
            deletion_lineage_digest: digest("deletion"),
            rollback_digest: digest("rollback"),
        },
        evaluation: CellSplitEvaluationBindingV1 {
            no_change_baseline_id: id("baseline"),
            evaluation_id: id("evaluation"),
            evaluator_id: id("evaluator"),
            evaluation_receipt_digest: digest("evaluation-receipt"),
            retention_receipt_digest: digest("retention-receipt"),
            negative_transfer_receipt_digest: digest("negative-transfer"),
            cost_receipt_digest: digest("cost"),
        },
        rollback_predecessor_digest: digest("rollback-predecessor"),
        evidence_digest: digest("evidence"),
    }
}

#[test]
fn cutover_fences_parent_and_emits_child_dispatch_receipt() {
    let predecessor = host(1, &[]);
    let parent_route = predecessor.route(&id("system"), &id("parent"), 0).unwrap();
    let successor = host(2, &[("child-a", "sink-a"), ("child-b", "sink-b")]);
    let child_routes = vec![
        successor.route(&id("system"), &id("child-a"), 0).unwrap(),
        successor.route(&id("system"), &id("child-b"), 0).unwrap(),
    ];
    let split = split(&predecessor, &parent_route, &successor, &child_routes);
    let old_route = parent_route.clone();
    let mut controller =
        CellSplitRouteControllerV1::new(predecessor, split.clone(), parent_route).unwrap();
    controller.start_all().unwrap();
    let (_, parent_receipt) = controller
        .dispatch_parent_once(&old_route, b"before")
        .unwrap();
    assert_eq!(parent_receipt.route_owner, CellSplitRouteOwnerV1::Parent);
    controller
        .activate_children(Generation::new(1).unwrap(), successor, child_routes.clone())
        .unwrap();
    assert_eq!(controller.phase(), CellSplitRoutePhaseV1::ChildrenActive);
    let fence = controller.route_fence_receipt().cloned().unwrap();
    assert_eq!(fence.parent_route_digest, cns_route_digest_v1(&old_route));
    assert_eq!(
        fence.split_subject_digest,
        split.evaluation_subject_digest().unwrap()
    );
    assert_eq!(fence.predecessor_generation, Generation::new(1).unwrap());
    assert_eq!(fence.successor_generation, Generation::new(2).unwrap());
    assert_eq!(fence.tombstone_digest, split.retirement.tombstone_digest);
    fence.verify(&split, &old_route).unwrap();
    let mut tampered_fence = fence.clone();
    tampered_fence.tombstone_digest = digest("different-tombstone");
    assert_eq!(
        tampered_fence.verify(&split, &old_route),
        Err(CellSplitRouteErrorV1::RouteFenceMismatch)
    );
    assert_eq!(
        controller.dispatch_parent_once(&old_route, b"stale"),
        Err(CellSplitRouteErrorV1::ParentDispatchUnavailable(
            CellSplitRoutePhaseV1::ChildrenActive
        ))
    );
    let child = &split.children[0];
    let selection = CellSplitRouteSelectionV1 {
        child_cell_id: child.child_cell_id.clone(),
        scope_digest: child.child_scope_digest,
        route_predicate_digest: child.route_predicate_digest,
        fallback_route_digest: child.fallback_route_digest,
    };
    let (_, receipt) = controller
        .dispatch_child_once(&selection, &child_routes[0], b"after")
        .unwrap();
    assert_eq!(
        receipt,
        CellSplitDispatchReceiptV1 {
            split_id: split.split_id,
            route_owner: CellSplitRouteOwnerV1::Child(child.child_cell_id.clone()),
            generation: child.child_generation,
            scope_digest: child.child_scope_digest,
            route_predicate_digest: child.route_predicate_digest,
            payload_digest: Digest32::of_bytes(b"after"),
            delivery_count: 1,
            parent_route_fenced: true,
            parent_route_fence_digest: fence.fence_digest,
        }
    );
}

#[test]
fn reopened_successor_rejects_parent_route_and_binds_tombstone_fence() {
    let predecessor = host(1, &[]);
    let parent_route = predecessor.route(&id("system"), &id("parent"), 0).unwrap();
    let successor = host(2, &[("child-a", "sink-a"), ("child-b", "sink-b")]);
    let child_routes = vec![
        successor.route(&id("system"), &id("child-a"), 0).unwrap(),
        successor.route(&id("system"), &id("child-b"), 0).unwrap(),
    ];
    let split = split(&predecessor, &parent_route, &successor, &child_routes);
    let old_route = parent_route.clone();
    let mut controller =
        CellSplitRouteControllerV1::new(predecessor, split.clone(), parent_route).unwrap();
    controller.start_all().unwrap();
    controller
        .activate_children(Generation::new(1).unwrap(), successor, child_routes)
        .unwrap();
    let fence = controller.route_fence_receipt().cloned().unwrap();

    // Reopen the successor registry in a new host object.  The old parent
    // route is absent before dispatch, so a stale process cannot resurrect it.
    let reopened_successor = host(2, &[("child-a", "sink-a"), ("child-b", "sink-b")]);
    let replay = fence
        .verify_after_restart(&split, &old_route, &reopened_successor)
        .unwrap();
    assert_eq!(replay.persisted_generation, Generation::new(2).unwrap());
    assert!(replay.predecessor_route_rejected);
    assert!(replay.parent_identity_absent);
    assert_eq!(replay.tombstone_digest, split.retirement.tombstone_digest);

    let mut resurrected = reopened_successor;
    resurrected.routes.insert(
        (old_route.source.organ.clone(), old_route.output_port),
        old_route.clone(),
    );
    assert_eq!(
        fence.verify_after_restart(&split, &old_route, &resurrected),
        Err(CellSplitRouteErrorV1::ParentRouteResurrected)
    );
}

#[test]
fn wrong_predicate_and_unbound_child_route_are_rejected_before_handler() {
    let predecessor = host(1, &[]);
    let parent_route = predecessor.route(&id("system"), &id("parent"), 0).unwrap();
    let successor = host(2, &[("child-a", "sink-a"), ("child-b", "sink-b")]);
    let child_routes = vec![
        successor.route(&id("system"), &id("child-a"), 0).unwrap(),
        successor.route(&id("system"), &id("child-b"), 0).unwrap(),
    ];
    let split = split(&predecessor, &parent_route, &successor, &child_routes);
    let mut controller =
        CellSplitRouteControllerV1::new(predecessor, split.clone(), parent_route).unwrap();
    controller.start_all().unwrap();
    controller
        .activate_children(Generation::new(1).unwrap(), successor, child_routes.clone())
        .unwrap();
    let child = &split.children[0];
    let wrong_selection = CellSplitRouteSelectionV1 {
        child_cell_id: child.child_cell_id.clone(),
        scope_digest: child.child_scope_digest,
        route_predicate_digest: digest("wrong-predicate"),
        fallback_route_digest: child.fallback_route_digest,
    };
    assert_eq!(
        controller.dispatch_child_once(&wrong_selection, &child_routes[0], b"rejected",),
        Err(CellSplitRouteErrorV1::RoutePredicateMismatch(
            child.child_cell_id.clone()
        ))
    );
    let mut stale_route = child_routes[0].clone();
    stale_route.output_port = 1;
    assert_eq!(
        controller.dispatch_child_once(
            &CellSplitRouteSelectionV1 {
                child_cell_id: child.child_cell_id.clone(),
                scope_digest: child.child_scope_digest,
                route_predicate_digest: child.route_predicate_digest,
                fallback_route_digest: child.fallback_route_digest,
            },
            &stale_route,
            b"rejected",
        ),
        Err(CellSplitRouteErrorV1::ParentRouteFenced)
    );
}

#[test]
fn invalid_child_route_does_not_publish_activation() {
    let predecessor = host(1, &[]);
    let parent_route = predecessor.route(&id("system"), &id("parent"), 0).unwrap();
    let successor = host(2, &[("child-a", "sink-a"), ("child-b", "sink-b")]);
    let all_child_routes = vec![
        successor.route(&id("system"), &id("child-a"), 0).unwrap(),
        successor.route(&id("system"), &id("child-b"), 0).unwrap(),
    ];
    let split = split(&predecessor, &parent_route, &successor, &all_child_routes);
    let child_routes = vec![all_child_routes[0].clone()];
    let mut controller =
        CellSplitRouteControllerV1::new(predecessor, split, parent_route.clone()).unwrap();
    assert_eq!(
        controller.activate_children(Generation::new(1).unwrap(), successor, child_routes),
        Err(CellSplitRouteErrorV1::ChildRouteCount)
    );
    assert_eq!(controller.phase(), CellSplitRoutePhaseV1::ParentActive);
    assert_eq!(controller.generation(), Generation::new(1).unwrap());
}

#[test]
fn abi_port_binding_mismatch_is_rejected_before_cutover() {
    let predecessor = host(1, &[]);
    let parent_route = predecessor.route(&id("system"), &id("parent"), 0).unwrap();
    let successor = host(2, &[("child-a", "sink-a"), ("child-b", "sink-b")]);
    let child_routes = vec![
        successor.route(&id("system"), &id("child-a"), 0).unwrap(),
        successor.route(&id("system"), &id("child-b"), 0).unwrap(),
    ];
    let mut split = split(&predecessor, &parent_route, &successor, &child_routes);
    split.ports.children[0].termination_port_digest = digest("wrong-termination");
    let mut controller = CellSplitRouteControllerV1::new(predecessor, split, parent_route).unwrap();
    assert_eq!(
        controller.activate_children(Generation::new(1).unwrap(), successor, child_routes),
        Err(CellSplitRouteErrorV1::ChildRoutePort(id("child-a")))
    );
    assert_eq!(controller.phase(), CellSplitRoutePhaseV1::ParentActive);
    assert_eq!(controller.generation(), Generation::new(1).unwrap());
}
