use codex_hepta_automation::CircuitEdgeV1;
use codex_hepta_automation::CircuitNodeRoleV1;
use codex_hepta_automation::CircuitNodeV1;
use codex_hepta_automation::NeuralCircuitCandidateV1;
use codex_hepta_automation::NeuralCircuitSpecV1; // CANONICAL_API_TYPE_IMPORT
use codex_hepta_automation::TaskFlowError;
use codex_hepta_automation::validate_circuit_successor_v1;
use codex_hepta_contracts::Sha256Digest;
use pretty_assertions::assert_eq;
use serde::Serialize;

// Inputs and exported bytes are shared verbatim with the pinned baseline harness.
struct CircuitInput {
    circuit_id: String,
    version: u32,
    predecessor_digest: Option<Sha256Digest>,
    entry_node: String,
    nodes: Vec<CircuitNodeV1>,
    edges: Vec<CircuitEdgeV1>,
    capability_set: Vec<String>,
    route_policy_digest: Sha256Digest,
    parameter_bundle_digest: Sha256Digest,
    resource_profile_digest: Sha256Digest,
}

fn construct(input: CircuitInput) -> Result<NeuralCircuitCandidateV1, TaskFlowError> {
    let CircuitInput {
        circuit_id,
        version,
        predecessor_digest,
        entry_node,
        nodes,
        edges,
        capability_set,
        route_policy_digest,
        parameter_bundle_digest,
        resource_profile_digest,
    } = input;
    // BEGIN CANONICAL_CONSTRUCTOR_ADAPTER
    NeuralCircuitCandidateV1::new(NeuralCircuitSpecV1 {
        circuit_id,
        version,
        predecessor_digest,
        entry_node,
        nodes,
        edges,
        capability_set,
        route_policy_digest,
        parameter_bundle_digest,
        resource_profile_digest,
    })
    // END CANONICAL_CONSTRUCTOR_ADAPTER
}

#[derive(Serialize)]
struct FixtureResult {
    name: &'static str,
    candidate_json_bytes: Vec<u8>,
    circuit_digest: Sha256Digest,
    taskflow_definition_digest: Sha256Digest,
    compilation_receipt_json_bytes: Vec<u8>,
}

#[derive(Serialize)]
struct CanonicalResults {
    schema: &'static str,
    fixtures: Vec<FixtureResult>,
}

#[test]
fn neural_circuit_canonical_bytes_match_constructor_contract()
-> Result<(), Box<dyn std::error::Error>> {
    let initial = construct(CircuitInput {
        circuit_id: "canonical-control".into(),
        version: 1,
        predecessor_digest: None,
        entry_node: "observe".into(),
        nodes: vec![
            CircuitNodeV1::new("success", CircuitNodeRoleV1::ExitSuccess),
            CircuitNodeV1::new("observe", CircuitNodeRoleV1::Observe),
            CircuitNodeV1::new("failure", CircuitNodeRoleV1::ExitFailure),
            CircuitNodeV1::new("decide", CircuitNodeRoleV1::Decide),
        ],
        edges: vec![
            CircuitEdgeV1::new("decide", "success"),
            CircuitEdgeV1::new("observe", "decide"),
            CircuitEdgeV1::new("decide", "failure"),
        ],
        capability_set: vec![],
        route_policy_digest: Sha256Digest::for_bytes(b"route-v1"),
        parameter_bundle_digest: Sha256Digest::for_bytes(b"parameters-v1"),
        resource_profile_digest: Sha256Digest::for_bytes(b"resources-v1"),
    })?;
    let successor = construct(CircuitInput {
        circuit_id: initial.circuit_id.clone(),
        version: 2,
        predecessor_digest: Some(initial.circuit_digest.clone()),
        entry_node: initial.entry_node.clone(),
        nodes: initial.nodes.iter().rev().cloned().collect(),
        edges: initial.edges.iter().rev().cloned().collect(),
        capability_set: initial.capability_set.clone(),
        route_policy_digest: Sha256Digest::for_bytes(b"route-v2"),
        parameter_bundle_digest: Sha256Digest::for_bytes(b"parameters-v2"),
        resource_profile_digest: initial.resource_profile_digest.clone(),
    })?;
    validate_circuit_successor_v1(&initial, &successor)?;
    assert_ne!(initial.circuit_digest, successor.circuit_digest);
    let effect = construct(CircuitInput {
        circuit_id: "canonical-effect".into(),
        version: 1,
        predecessor_digest: None,
        entry_node: "effect".into(),
        nodes: vec![
            CircuitNodeV1::new("success", CircuitNodeRoleV1::ExitSuccess),
            CircuitNodeV1::new("failure", CircuitNodeRoleV1::ExitFailure),
            CircuitNodeV1::effect("effect", "network.http", "circuit/{run}/effect"),
        ],
        edges: vec![
            CircuitEdgeV1::new("effect", "success"),
            CircuitEdgeV1::new("effect", "failure"),
        ],
        capability_set: vec!["network.http".into(), "matrix.send".into()],
        route_policy_digest: Sha256Digest::for_bytes(b"effect-route"),
        parameter_bundle_digest: Sha256Digest::for_bytes(b"effect-parameters"),
        resource_profile_digest: Sha256Digest::for_bytes(b"effect-resources"),
    })?;
    let fixtures = [
        ("unsorted-v1", initial),
        ("exact-predecessor-successor", successor),
        ("effect-capability-idempotency", effect),
    ]
    .into_iter()
    .map(|(name, circuit)| {
        let (definition, receipt) = circuit.compile_taskflow()?;
        assert!(!receipt.authority_granted);
        assert_eq!(receipt.circuit_digest, circuit.circuit_digest);
        assert_eq!(
            receipt.taskflow_definition_digest,
            *definition.definition_digest()
        );
        let candidate_json_bytes = serde_json::to_vec(&circuit)?;
        assert_eq!(
            serde_json::from_slice::<NeuralCircuitCandidateV1>(&candidate_json_bytes)?,
            circuit
        );
        Ok(FixtureResult {
            name,
            candidate_json_bytes,
            circuit_digest: circuit.circuit_digest,
            taskflow_definition_digest: definition.definition_digest().clone(),
            compilation_receipt_json_bytes: serde_json::to_vec(&receipt)?,
        })
    })
    .collect::<Result<Vec<_>, Box<dyn std::error::Error>>>()?;
    let bytes = serde_json::to_vec(&CanonicalResults {
        schema: "hepta.neural-circuit-canonical-fixtures.v1",
        fixtures,
    })?;
    // Ordinary package tests still execute every assertion. The qualification
    // driver supplies an exclusive evidence path for its native stage.
    if let Some(path) = std::env::var_os("HEPTA_CANONICAL_FIXTURE_OUTPUT") {
        use std::io::Write;
        std::fs::OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(path)?
            .write_all(&bytes)?;
    }
    Ok(())
}
