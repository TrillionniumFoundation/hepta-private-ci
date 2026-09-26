use std::time::Instant;

use codex_hepta_automation::AutomationStore;
use codex_hepta_automation::CircuitEdgeV1;
use codex_hepta_automation::CircuitNodeRoleV1;
use codex_hepta_automation::CircuitNodeV1;
use codex_hepta_automation::NeuralCircuitCandidateV1;
use codex_hepta_automation::TaskFlowFence;
use codex_hepta_automation::ThresholdCircuitDispositionV1;
use codex_hepta_automation::ThresholdCircuitInvocationV1;
use codex_hepta_automation::ThresholdDecisionCellParametersV1;
use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_fleet::AgentManifest;
use codex_hepta_fleet::FleetRegistry;
use codex_hepta_fleet::ResourceBudget;
use codex_hepta_fleet::WorkspaceBinding;
use codex_hepta_paths::HeptaAgentLayout;
use codex_hepta_paths::HeptaFleetRoot;
use pretty_assertions::assert_eq;

const AGENT_ID: &str = "018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12";
const RUNS: usize = 256;

struct Fixture {
    _temp: tempfile::TempDir,
    layout: HeptaAgentLayout,
}

impl Fixture {
    fn new() -> Self {
        let temp = tempfile::tempdir().expect("ordinary disk temp root");
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
        "qualification.threshold-circuit",
        generation,
        generation,
        format!("qualification-threshold-fence-{generation}"),
    )
    .expect("fence")
}

fn fixture_contract() -> (NeuralCircuitCandidateV1, ThresholdDecisionCellParametersV1) {
    let parameters = ThresholdDecisionCellParametersV1::new(
        "qualification.threshold-cell",
        1,
        None,
        0,
        "accepted",
        "rejected",
    )
    .expect("parameters");
    let candidate =
        NeuralCircuitCandidateV1::new(codex_hepta_automation::NeuralCircuitDefinitionV1 {
            circuit_id: ("qualification.threshold-circuit").into(),
            version: 1,
            predecessor_digest: None,
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
            route_policy_digest: Sha256Digest::for_bytes(b"qualification-route-policy"),
            parameter_bundle_digest: parameters.parameter_digest.clone(),
            resource_profile_digest: Sha256Digest::for_bytes(
                b"qualification-bounded-resource-profile",
            ),
        })
        .expect("candidate");
    (candidate, parameters)
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn ordinary_disk_capacity_retains_256_exact_choices_across_reopen() {
    let fixture = Fixture::new();
    let store = AutomationStore::open(&fixture.layout).await.expect("store");
    let (candidate, parameters) = fixture_contract();
    let started = Instant::now();
    let mut succeeded = 0_usize;
    let mut failed = 0_usize;
    for index in 0..RUNS {
        let input_value_ppm = if index % 2 == 0 { 100_000 } else { -100_000 };
        let invocation = ThresholdCircuitInvocationV1 {
            operation_id: format!("qualification-threshold-operation-{index:04}"),
            candidate: candidate.clone(),
            parameters: parameters.clone(),
            input_value_ppm,
        };
        let decision = store
            .run_threshold_circuit_v1(
                &invocation,
                &fence(1),
                1_000 + u64::try_from(index).expect("index"),
                60_000,
            )
            .await
            .expect("threshold decision");
        match decision.disposition {
            ThresholdCircuitDispositionV1::Succeeded => succeeded += 1,
            ThresholdCircuitDispositionV1::Failed => failed += 1,
        }
    }
    let elapsed = started.elapsed();
    assert_eq!((succeeded, failed), (RUNS / 2, RUNS / 2));
    store.close().await;

    let reopened = AutomationStore::open(&fixture.layout)
        .await
        .expect("reopen store");
    for index in [0_usize, RUNS / 2, RUNS - 1] {
        let operation_id = format!("qualification-threshold-operation-{index:04}");
        let decision = reopened
            .threshold_circuit_decision_by_operation(&operation_id)
            .await
            .expect("exact decision lookup")
            .expect("durable decision");
        assert_eq!(decision.operation_id, operation_id);
    }
    eprintln!(
        "AUTOMATION_TASKFLOW_CAPACITY runs={RUNS} succeeded={succeeded} failed={failed} elapsed_ms={}",
        elapsed.as_millis()
    );
}
