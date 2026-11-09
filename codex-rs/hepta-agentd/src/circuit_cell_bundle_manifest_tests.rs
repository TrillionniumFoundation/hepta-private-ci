//! Composition and reducer checks, not a model-quality or batching benchmark.

use codex_hepta_automation::BoundedCircuitDefinitionV2;
use codex_hepta_automation::CircuitCompletionV2;
use codex_hepta_automation::CircuitEdgeV2;
use codex_hepta_automation::CircuitEventV2;
use codex_hepta_automation::CircuitExitV2;
use codex_hepta_automation::CircuitRunV2;
use codex_hepta_automation::CircuitStartV2;
use codex_hepta_automation::TaskFlowFence;
use codex_hepta_contracts::AgentId;
use pretty_assertions::assert_eq;

use super::*;
use crate::CircuitCellRegistryV1;
use crate::circuit_cell::tests::configuration;
use crate::circuit_cell::tests::support::checked;
use crate::circuit_cell::tests::support::d;
use crate::circuit_cell::tests::support::id;
use crate::circuit_cell::tests::support::input;
use crate::circuit_cell::tests::support::scope;
use crate::circuit_cell_operation_id_v1;
use crate::circuit_cell_route_policy_digest_v1;
use crate::circuit_cell_scope_digest_v1;

fn private_heads() -> (BoundedCircuitDefinitionV2, Vec<CircuitCellBindingV1>) {
    let (mut definition, mut bindings) = configuration();
    let mut second = bindings[0].clone();
    second.node_id = "decide-second".into();
    second.cell.cell_id = id("second-cell");
    second.cell.bundle_digest = d("second-private-bundle");
    second.cell.native.model_digest = d("second-private-head");
    second.cell.runtime.head_digest = second.cell.native.model_digest;
    second.cell.runtime.weights_digest = d("second-composed-weights");
    second.cell.runtime.native_config_digest = checked(second.cell.native.digest());
    second.routes[0].selected_edges = vec!["done-second".into()];
    second.routes[1].selected_edges = vec!["slow-second".into()];
    let program = &mut definition.programs[0];
    for edge in &mut program.edges {
        edge.to = second.node_id.clone();
    }
    let mut node = program.nodes[0].clone();
    node.node_id = second.node_id.clone();
    node.input_schema = node.output_schema.clone();
    program.nodes.push(node);
    for edge_id in ["done-second", "slow-second"] {
        program.edges.push(CircuitEdgeV2 {
            edge_id: edge_id.into(),
            from: second.node_id.clone(),
            to: "success".into(),
            feedback_delay_ms: None,
        });
    }
    bindings.push(second);
    definition.parameter_bundle_digest = checked(circuit_cell_bundle_manifest_digest_v1(&bindings));
    definition.route_policy_digest = checked(circuit_cell_route_policy_digest_v1(&bindings));
    (definition, bindings)
}

#[test]
fn manifest_refuses_empty_and_oversized_inputs_before_hashing_cells() {
    assert_eq!(
        circuit_cell_bundle_manifest_digest_v1(&[]),
        Err(CircuitCellErrorV1::InvalidBinding)
    );
    let (_, bindings) = configuration();
    let mut maximum = Vec::new();
    for index in 0..MAX_CIRCUIT_CELL_BINDINGS {
        let mut binding = bindings[0].clone();
        binding.node_id = format!("node-{index}");
        maximum.push(binding);
    }
    assert_eq!(
        circuit_cell_bundle_manifest_digest_v1(&maximum),
        circuit_cell_bundle_manifest_digest_v1(&bindings)
    );
    maximum.push(bindings[0].clone());
    maximum[0].cell.native.model_digest = d("invalid-native-binding");
    assert_eq!(
        circuit_cell_bundle_manifest_digest_v1(&maximum),
        Err(CircuitCellErrorV1::InvalidBinding)
    );
}

#[test]
fn private_heads_require_explicit_manifest_and_legacy_composition_stays_strict() {
    let (legacy, bindings) = configuration();
    assert!(CircuitCellRegistryV1::new(legacy.clone(), bindings.clone()).is_ok());
    assert!(matches!(
        CircuitCellRegistryV1::new_with_bundle_manifest(legacy, bindings),
        Err(CircuitCellErrorV1::InvalidBinding)
    ));
    let (definition, bindings) = private_heads();
    assert!(matches!(
        CircuitCellRegistryV1::new(definition.clone(), bindings.clone()),
        Err(CircuitCellErrorV1::InvalidBinding)
    ));
    let registry = checked(CircuitCellRegistryV1::new_with_bundle_manifest(
        definition.clone(),
        bindings,
    ));
    assert_eq!(registry.definition(), &definition);
    assert_eq!(
        registry.definition_digest(),
        &checked(definition.definition_digest())
    );
}

#[test]
fn manifest_is_order_independent_and_reused_identical_cells_contribute_once() {
    let (definition, mut bindings) = private_heads();
    let original = checked(circuit_cell_bundle_manifest_digest_v1(&bindings));
    bindings.reverse();
    assert_eq!(
        checked(circuit_cell_bundle_manifest_digest_v1(&bindings)),
        original
    );
    assert!(CircuitCellRegistryV1::new_with_bundle_manifest(definition, bindings.clone()).is_ok());
    let mut repeated = bindings[0].clone();
    repeated.node_id = "another-visit".into();
    bindings.push(repeated);
    assert_eq!(
        checked(circuit_cell_bundle_manifest_digest_v1(&bindings)),
        original
    );
}

#[test]
fn duplicate_slots_and_conflicting_cell_identities_have_no_manifest() {
    let (_, bindings) = private_heads();
    let mut duplicate = bindings.clone();
    duplicate.push(bindings[0].clone());
    assert_eq!(
        circuit_cell_bundle_manifest_digest_v1(&duplicate),
        Err(CircuitCellErrorV1::InvalidBinding)
    );
    let mut alias = bindings;
    alias[1].cell.cell_id = alias[0].cell.cell_id.clone();
    assert_eq!(
        circuit_cell_bundle_manifest_digest_v1(&alias),
        Err(CircuitCellErrorV1::InvalidBinding)
    );
}

#[test]
fn registry_requires_complete_graph_coverage_even_with_new_manifest_and_routes() {
    let (mut definition, mut bindings) = private_heads();
    bindings.pop();
    definition.parameter_bundle_digest = checked(circuit_cell_bundle_manifest_digest_v1(&bindings));
    definition.route_policy_digest = checked(circuit_cell_route_policy_digest_v1(&bindings));
    assert!(matches!(
        CircuitCellRegistryV1::new_with_bundle_manifest(definition, bindings),
        Err(CircuitCellErrorV1::InvalidBinding)
    ));
    let (mut definition, mut bindings) = private_heads();
    let mut extra = bindings[0].clone();
    extra.node_id = "unregistered-node".into();
    bindings.push(extra);
    definition.parameter_bundle_digest = checked(circuit_cell_bundle_manifest_digest_v1(&bindings));
    definition.route_policy_digest = checked(circuit_cell_route_policy_digest_v1(&bindings));
    assert!(matches!(
        CircuitCellRegistryV1::new_with_bundle_manifest(definition, bindings),
        Err(CircuitCellErrorV1::InvalidBinding)
    ));
}

#[test]
fn retained_manifest_binds_bundle_weights_encoder_and_full_cell_limits() {
    let (definition, bindings) = private_heads();
    let mut variants = vec![bindings; 4];
    variants[0][1].cell.bundle_digest = d("changed-private-bundle");
    variants[1][1].cell.runtime.weights_digest = d("changed-composed-weights");
    variants[2][1].cell.runtime.encoder_digest = d("changed-encoder");
    variants[3][1].cell.max_queue_age_micros += 1;
    for variant in variants {
        let mut changed = definition.clone();
        changed.route_policy_digest = checked(circuit_cell_route_policy_digest_v1(&variant));
        assert!(matches!(
            CircuitCellRegistryV1::new_with_bundle_manifest(changed.clone(), variant.clone()),
            Err(CircuitCellErrorV1::InvalidBinding)
        ));
        changed.parameter_bundle_digest = checked(circuit_cell_bundle_manifest_digest_v1(&variant));
        assert!(CircuitCellRegistryV1::new_with_bundle_manifest(changed, variant).is_ok());
    }
}

#[test]
fn manifest_keeps_native_state_and_candidate_route_validation() {
    let (_, mut bindings) = private_heads();
    bindings[1].cell.native.model_digest = d("unbound-native-head");
    assert!(matches!(
        circuit_cell_bundle_manifest_digest_v1(&bindings),
        Err(CircuitCellErrorV1::Cell(_))
    ));
    let (mut definition, mut bindings) = private_heads();
    bindings[1].routes[0].candidate_id = id("not-the-cell-candidate");
    definition.route_policy_digest = checked(circuit_cell_route_policy_digest_v1(&bindings));
    assert!(matches!(
        CircuitCellRegistryV1::new_with_bundle_manifest(definition, bindings),
        Err(CircuitCellErrorV1::InvalidBinding)
    ));
}

#[test]
fn manifest_composition_keeps_representation_output_schema_supported() {
    let (mut definition, bindings) = private_heads();
    let legacy = crate::circuit_cell_output_schema_v1();
    let representation = crate::circuit_cell_output_schema_v2();
    for node in &mut definition.programs[0].nodes {
        if node.input_schema == legacy {
            node.input_schema = representation.clone();
        }
        node.output_schema = representation.clone();
    }
    assert!(CircuitCellRegistryV1::new_with_bundle_manifest(definition, bindings).is_ok());
}

#[test]
fn graph_dispatches_preserve_each_private_head_and_reject_wrong_cell_or_parameter_pin() {
    let (definition, bindings) = private_heads();
    let registry = checked(CircuitCellRegistryV1::new_with_bundle_manifest(
        definition.clone(),
        bindings.clone(),
    ));
    let fence = checked(TaskFlowFence::new(
        checked(AgentId::parse(scope("run-1").agent_id.as_str())),
        "manifest-owner",
        /*owner_epoch*/ 1,
        /*generation*/ 1,
        "manifest-fence",
    ));
    let initial = checked(CircuitRunV2::prepare(
        &definition,
        &CircuitStartV2 {
            run_id: "run-1".into(),
            scope_digest: checked(circuit_cell_scope_digest_v1(&scope("run-1"))),
            input_digest: Sha256Digest::for_bytes(&input("run-1").observation),
            created_at_ms: 10,
            lease_duration_ms: 500,
        },
        &fence,
    ));
    let (run, dispatches) = checked(initial.reduce(
        &definition,
        &CircuitEventV2::Advance { quantum: 1 },
        /*now_ms*/ 20,
    ));
    let mut request = input("run-1");
    request.operation_id = checked(circuit_cell_operation_id_v1(&dispatches[0]));
    assert_eq!(
        checked(registry.bind_input(&dispatches[0], &request)),
        &bindings[0]
    );
    let observation = b"first cell output".to_vec();
    let (run, _) = checked(run.reduce(
        &definition,
        &CircuitEventV2::Complete {
            completion: CircuitCompletionV2 {
                activation_id: dispatches[0].activation_id,
                invocation_digest: dispatches[0].invocation_digest.clone(),
                output_digest: Sha256Digest::for_bytes(&observation),
                receipt_digest: Sha256Digest::for_bytes(b"controlled-reducer-receipt"),
                actual_work: 20,
                outcome: CircuitExitV2::Succeeded,
                selected_edges: vec!["done".into()],
            },
        },
        /*now_ms*/ 21,
    ));
    let (_, dispatches) = checked(run.reduce(
        &definition,
        &CircuitEventV2::Advance { quantum: 1 },
        /*now_ms*/ 22,
    ));
    request.scope.cell_id = bindings[1].cell.cell_id.clone();
    request.observation = observation;
    request.operation_id = checked(circuit_cell_operation_id_v1(&dispatches[0]));
    assert_eq!(
        checked(registry.bind_input(&dispatches[0], &request)),
        &bindings[1]
    );
    let mut wrong = dispatches[0].clone();
    wrong.parameter_bundle_digest = checked(Sha256Digest::parse(
        bindings[0].cell.bundle_digest.to_string(),
    ));
    assert_eq!(
        registry.bind_input(&wrong, &request),
        Err(CircuitCellErrorV1::InvalidBinding)
    );
    request.scope.cell_id = bindings[0].cell.cell_id.clone();
    assert_eq!(
        registry.bind_input(&dispatches[0], &request),
        Err(CircuitCellErrorV1::ScopeMismatch)
    );
}
