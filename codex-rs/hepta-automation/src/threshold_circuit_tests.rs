use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_fleet::AgentManifest;
use codex_hepta_fleet::FleetRegistry;
use codex_hepta_fleet::ResourceBudget;
use codex_hepta_fleet::WorkspaceBinding;
use codex_hepta_paths::HeptaAgentLayout;
use codex_hepta_paths::HeptaFleetRoot;
use pretty_assertions::assert_eq;

use super::*;
use crate::CircuitEdgeV1;
use crate::CircuitNodeRoleV1;
use crate::CircuitNodeV1;
use crate::TaskFlowCommand;
use crate::TaskFlowRunState;
use crate::TaskFlowTransition;
use crate::threshold_circuit_model::threshold_decision;
use crate::threshold_circuit_model::threshold_run_id;

const AGENT_ID: &str = "018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12";

struct Fixture {
    _temp: tempfile::TempDir,
    layout: HeptaAgentLayout,
}

impl Fixture {
    fn new() -> Self {
        let temp = tempfile::tempdir().expect("temp root");
        let root = temp.path().canonicalize().expect("canonical temp root");
        let fleet_root = HeptaFleetRoot::parse(root.join("fleet")).expect("fleet root");
        let registry = FleetRegistry::initialize(fleet_root.clone()).expect("fleet registry");
        let workspace = root.join("workspace");
        std::fs::create_dir(&workspace).expect("workspace");
        let workspace = workspace.canonicalize().expect("canonical workspace");
        let manifest = AgentManifest::new(
            AgentId::parse(AGENT_ID).expect("agent id"),
            WorkspaceBinding::new(workspace, &fleet_root).expect("workspace binding"),
            ResourceBudget::local_default(),
        )
        .expect("manifest");
        let layout = registry.register(manifest).expect("register agent").layout;
        Self {
            _temp: temp,
            layout,
        }
    }
}

fn fence(generation: u64) -> TaskFlowFence {
    TaskFlowFence::new(
        AgentId::parse(AGENT_ID).expect("agent id"),
        "agentd.automation-threshold-circuit",
        generation,
        generation,
        format!("threshold-fence-{generation}"),
    )
    .expect("fence")
}

fn parameters(
    version: u32,
    predecessor: Option<Sha256Digest>,
    threshold_ppm: i32,
) -> ThresholdDecisionCellParametersV1 {
    ThresholdDecisionCellParametersV1::new(
        "decision-cell:threshold",
        version,
        predecessor,
        threshold_ppm,
        "accepted",
        "rejected",
    )
    .expect("parameters")
}

fn candidate(
    version: u32,
    predecessor: Option<Sha256Digest>,
    parameters: &ThresholdDecisionCellParametersV1,
) -> NeuralCircuitCandidateV1 {
    NeuralCircuitCandidateV1::new(crate::NeuralCircuitDefinitionV1 {
        circuit_id: ("minimal-threshold-circuit").into(),
        version: version,
        predecessor_digest: predecessor,
        entry_node: ("decide").into(),
        nodes: vec![
            CircuitNodeV1::new("decide", CircuitNodeRoleV1::Decide),
            CircuitNodeV1::new("accepted", CircuitNodeRoleV1::ExitSuccess),
            CircuitNodeV1::new("rejected", CircuitNodeRoleV1::ExitFailure),
        ],
        edges: vec![
            CircuitEdgeV1::new("decide", "accepted"),
            CircuitEdgeV1::new("decide", "rejected"),
        ],
        capability_set: Vec::new(),
        route_policy_digest: Sha256Digest::for_bytes(format!("route-policy-{version}").as_bytes()),
        parameter_bundle_digest: parameters.parameter_digest.clone(),
        resource_profile_digest: Sha256Digest::for_bytes(b"bounded-threshold-resource-profile"),
    })
    .expect("candidate")
}

fn invocation(
    operation_id: &str,
    candidate: NeuralCircuitCandidateV1,
    parameters: ThresholdDecisionCellParametersV1,
    input_value_ppm: i32,
) -> ThresholdCircuitInvocationV1 {
    ThresholdCircuitInvocationV1 {
        operation_id: operation_id.to_string(),
        candidate,
        parameters,
        input_value_ppm,
    }
}

#[tokio::test]
async fn durable_choice_recovers_after_restart_before_route_projection() {
    let fixture = Fixture::new();
    let store = AutomationStore::open(&fixture.layout).await.expect("store");
    let parameters = parameters(1, None, 100_000);
    let candidate = candidate(1, None, &parameters);
    let invocation = invocation(
        "threshold-operation:crash-cut",
        candidate.clone(),
        parameters.clone(),
        250_000,
    );
    validate_invocation(&invocation).expect("valid invocation");
    let definition = store
        .register_threshold_candidate(&candidate, 100)
        .await
        .expect("candidate");
    store
        .register_threshold_parameters(&parameters, 100)
        .await
        .expect("parameters");
    store
        .register_taskflow_definition(&definition, &fence(1), 100)
        .await
        .expect("definition");
    let run_id = threshold_run_id(AGENT_ID, &invocation.operation_id);
    let run = store
        .create_taskflow_run(
            &run_id,
            &definition.workflow_id,
            definition.version,
            definition.definition_digest(),
            &run_id,
            100,
        )
        .await
        .expect("run");
    let claimed = store
        .claim_taskflow_run(&run_id, &fence(1), 100, 10)
        .await
        .expect("claim");
    store
        .apply_taskflow_command(
            &TaskFlowCommand::new(
                &run_id,
                "threshold-test:start",
                fence(1),
                claimed.revision,
                TaskFlowTransition::Start,
                101,
            )
            .expect("start command"),
        )
        .await
        .expect("start");
    let loaded = store
        .threshold_parameters_by_digest(&parameters.parameter_digest)
        .await
        .expect("load parameters")
        .expect("parameters exist");
    let decision = threshold_decision(&invocation, &loaded, &run_id, 102).expect("durable choice");
    store
        .insert_threshold_decision(&decision)
        .await
        .expect("persist choice before route");
    let before_crash = store.taskflow_run(&run_id).await.unwrap().unwrap();
    assert_eq!(before_crash.state, TaskFlowRunState::Running);
    assert_eq!(before_crash.current_node, "decide");
    store.close().await;

    let reopened = AutomationStore::open(&fixture.layout)
        .await
        .expect("reopen store");
    let recovered = reopened
        .run_threshold_circuit_v1(&invocation, &fence(2), 1_000, 60_000)
        .await
        .expect("recover exact recorded choice");
    assert_eq!(recovered, decision);
    let terminal = reopened.taskflow_run(&run_id).await.unwrap().unwrap();
    assert_eq!(terminal.state, TaskFlowRunState::Succeeded);
    assert_eq!(terminal.current_node, "accepted");
}

#[tokio::test]
async fn parameter_and_circuit_successors_change_new_runs_without_rewriting_history() {
    let fixture = Fixture::new();
    let store = AutomationStore::open(&fixture.layout).await.expect("store");
    let parameters_v1 = parameters(1, None, 100_000);
    let candidate_v1 = candidate(1, None, &parameters_v1);
    let invocation_v1 = invocation(
        "threshold-operation:v1",
        candidate_v1.clone(),
        parameters_v1.clone(),
        200_000,
    );
    let decision_v1 = store
        .run_threshold_circuit_v1(&invocation_v1, &fence(1), 100, 60_000)
        .await
        .expect("run v1");
    assert_eq!(
        decision_v1.disposition,
        ThresholdCircuitDispositionV1::Succeeded
    );
    assert_eq!(decision_v1.selected_node, "accepted");

    let parameters_v2 = parameters(2, Some(parameters_v1.parameter_digest.clone()), 300_000);
    let candidate_v2 = candidate(2, Some(candidate_v1.circuit_digest.clone()), &parameters_v2);
    let invocation_v2 = invocation(
        "threshold-operation:v2",
        candidate_v2,
        parameters_v2,
        200_000,
    );
    let decision_v2 = store
        .run_threshold_circuit_v1(&invocation_v2, &fence(2), 1_000, 60_000)
        .await
        .expect("run v2");
    assert_eq!(
        decision_v2.disposition,
        ThresholdCircuitDispositionV1::Failed
    );
    assert_eq!(decision_v2.selected_node, "rejected");
    assert_ne!(decision_v1.choice_digest, decision_v2.choice_digest);
    store.close().await;

    let reopened = AutomationStore::open(&fixture.layout)
        .await
        .expect("reopen store");
    assert_eq!(
        reopened
            .threshold_circuit_decision_by_operation("threshold-operation:v1")
            .await
            .unwrap()
            .unwrap(),
        decision_v1
    );
    assert_eq!(
        reopened
            .threshold_circuit_decision_by_operation("threshold-operation:v2")
            .await
            .unwrap()
            .unwrap(),
        decision_v2
    );
}
