#![allow(
    clippy::expect_used,
    reason = "test assertions use explicit failure context"
)]

use std::sync::Arc;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;

use codex_hepta_automation::AutomationStore;
use codex_hepta_automation::CircuitEdgeV1;
use codex_hepta_automation::CircuitNodeRoleV1;
use codex_hepta_automation::CircuitNodeV1;
use codex_hepta_automation::NeuralCircuitCandidateV1;
use codex_hepta_automation::NeuralCircuitDecisionCellV1;
use codex_hepta_automation::NeuralCircuitDecisionFuture;
use codex_hepta_automation::NeuralCircuitDecisionProgressV1;
use codex_hepta_automation::NeuralCircuitDecisionRequestV1;
use codex_hepta_automation::NeuralCircuitDecisionV1;
use codex_hepta_automation::NeuralCircuitIngressV1;
use codex_hepta_automation::NeuralCircuitOrganFuture;
use codex_hepta_automation::NeuralCircuitOrganObservationV1;
use codex_hepta_automation::NeuralCircuitOrganPortV1;
use codex_hepta_automation::NeuralCircuitOrganRequestV1;
use codex_hepta_automation::NeuralCircuitRuntimeBudgetV1;
use codex_hepta_automation::TaskFlowFence;
use codex_hepta_automation::TaskFlowRunState;
use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_fleet::AgentManifest;
use codex_hepta_fleet::FleetRegistry;
use codex_hepta_fleet::ResourceBudget;
use codex_hepta_fleet::WorkspaceBinding;
use codex_hepta_paths::HeptaAgentLayout;
use codex_hepta_paths::HeptaFleetRoot;

const AGENT_ID: &str = "018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12";

struct Fixture {
    _temp: tempfile::TempDir,
    layout: HeptaAgentLayout,
}

impl Fixture {
    #[allow(
        clippy::expect_used,
        reason = "test fixture construction must fail loudly"
    )]
    fn new() -> Self {
        let temp = tempfile::tempdir().expect("temp root");
        let root = temp.path().canonicalize().expect("canonical root");
        let fleet_root = HeptaFleetRoot::parse(root.join("fleet")).expect("fleet root");
        let registry = FleetRegistry::initialize(fleet_root.clone()).expect("registry");
        let workspace = root.join("workspace");
        std::fs::create_dir(&workspace).expect("workspace");
        let manifest = AgentManifest::new(
            AgentId::parse(AGENT_ID).expect("agent id"),
            WorkspaceBinding::new(
                workspace.canonicalize().expect("canonical workspace"),
                &fleet_root,
            )
            .expect("workspace binding"),
            ResourceBudget::local_default(),
        )
        .expect("manifest");
        let layout = registry.register(manifest).expect("register").layout;
        Self {
            _temp: temp,
            layout,
        }
    }
}

struct FixedDecision {
    calls: Arc<AtomicUsize>,
    selected: String,
}

impl NeuralCircuitDecisionCellV1 for FixedDecision {
    fn decide(&self, _request: NeuralCircuitDecisionRequestV1) -> NeuralCircuitDecisionFuture<'_> {
        self.calls.fetch_add(1, Ordering::SeqCst);
        let selected = self.selected.clone();
        Box::pin(async move {
            Ok(NeuralCircuitDecisionV1::Route {
                selected_node: selected,
            })
        })
    }
}

struct FixedOrgan {
    calls: Arc<AtomicUsize>,
    output: Sha256Digest,
}

impl NeuralCircuitOrganPortV1 for FixedOrgan {
    fn invoke(&self, _request: NeuralCircuitOrganRequestV1) -> NeuralCircuitOrganFuture<'_> {
        self.calls.fetch_add(1, Ordering::SeqCst);
        let output = self.output.clone();
        Box::pin(async move {
            Ok(NeuralCircuitOrganObservationV1 {
                output_digest: output,
            })
        })
    }
}

fn candidate() -> NeuralCircuitCandidateV1 {
    NeuralCircuitCandidateV1::new(
        "runtime-v1",
        1,
        None,
        "decide",
        vec![
            CircuitNodeV1::new("decide", CircuitNodeRoleV1::Decide),
            CircuitNodeV1 {
                node_id: "organ".to_string(),
                role: CircuitNodeRoleV1::OrganCall,
                capability: Some("organ.test".to_string()),
                idempotency_template: None,
                max_attempts: 1,
                wait_timeout_ms: None,
            },
            CircuitNodeV1::new("join", CircuitNodeRoleV1::WaitJoin),
            CircuitNodeV1::new("success", CircuitNodeRoleV1::ExitSuccess),
            CircuitNodeV1::new("failure", CircuitNodeRoleV1::ExitFailure),
        ],
        vec![
            CircuitEdgeV1::new("decide", "organ"),
            CircuitEdgeV1::new("decide", "failure"),
            CircuitEdgeV1::new("organ", "join"),
            CircuitEdgeV1::new("join", "success"),
        ],
        vec!["organ.test".to_string()],
        Sha256Digest::for_bytes(b"route-policy"),
        Sha256Digest::for_bytes(b"parameters"),
        Sha256Digest::for_bytes(b"resources"),
    )
    .expect("candidate")
}

fn fence(layout: &HeptaAgentLayout) -> TaskFlowFence {
    TaskFlowFence::new(
        layout.agent_id().clone(),
        "neural-runtime-owner",
        1,
        1,
        "neural-runtime-fence",
    )
    .expect("fence")
}

#[tokio::test]
async fn recorded_decision_is_replayed_without_reinvoking_cell() {
    let fixture = Fixture::new();
    let store = AutomationStore::open(&fixture.layout).await.expect("store");
    let fence = fence(&fixture.layout);
    let candidate = candidate();
    let ingress = NeuralCircuitIngressV1::new(
        "activation-1",
        "thread-1",
        Sha256Digest::for_bytes(b"input"),
    )
    .expect("ingress");
    let activation = store
        .admit_neural_circuit_activation_v1(
            &candidate,
            &ingress,
            NeuralCircuitRuntimeBudgetV1::new(8, 2).expect("budget"),
            &fence,
            10,
            30_000,
        )
        .await
        .expect("activation");
    let calls = Arc::new(AtomicUsize::new(0));
    let cell = FixedDecision {
        calls: Arc::clone(&calls),
        selected: "organ".to_string(),
    };
    let first = store
        .advance_neural_circuit_decision_v1(&candidate, &activation, "decide", &cell, &fence, 11)
        .await
        .expect("decision");
    assert!(matches!(
        first,
        NeuralCircuitDecisionProgressV1::Routed {
            ref selected_node,
            replayed: false,
            ..
        } if selected_node == "organ"
    ));
    let second = store
        .advance_neural_circuit_decision_v1(&candidate, &activation, "decide", &cell, &fence, 12)
        .await
        .expect("replay");
    assert!(matches!(
        second,
        NeuralCircuitDecisionProgressV1::Routed {
            ref selected_node,
            replayed: true,
            ..
        } if selected_node == "organ"
    ));
    assert_eq!(calls.load(Ordering::SeqCst), 1);
    store.close().await;
}

#[tokio::test]
async fn organ_wait_join_and_terminal_use_existing_taskflow_ledger() {
    let fixture = Fixture::new();
    let store = AutomationStore::open(&fixture.layout).await.expect("store");
    let fence = fence(&fixture.layout);
    let candidate = candidate();
    let ingress = NeuralCircuitIngressV1::new(
        "activation-2",
        "thread-2",
        Sha256Digest::for_bytes(b"input-2"),
    )
    .expect("ingress");
    let activation = store
        .admit_neural_circuit_activation_v1(
            &candidate,
            &ingress,
            NeuralCircuitRuntimeBudgetV1::new(8, 1).expect("budget"),
            &fence,
            20,
            30_000,
        )
        .await
        .expect("activation");
    let decision = FixedDecision {
        calls: Arc::new(AtomicUsize::new(0)),
        selected: "organ".to_string(),
    };
    store
        .advance_neural_circuit_decision_v1(
            &candidate,
            &activation,
            "decide",
            &decision,
            &fence,
            21,
        )
        .await
        .expect("decision");

    let organ_calls = Arc::new(AtomicUsize::new(0));
    let organ_output = Sha256Digest::for_bytes(b"organ-output");
    let organ = FixedOrgan {
        calls: Arc::clone(&organ_calls),
        output: organ_output.clone(),
    };
    let organ_receipt = store
        .advance_neural_circuit_organ_v1(
            &candidate,
            &activation,
            "organ",
            &Sha256Digest::for_bytes(b"organ-input"),
            &organ,
            &fence,
            22,
        )
        .await
        .expect("organ");
    assert_eq!(organ_receipt.output_digest, organ_output);
    assert_eq!(organ_receipt.run.current_node, "join");
    assert_eq!(organ_calls.load(Ordering::SeqCst), 1);

    let wait = store
        .begin_neural_circuit_wait_v1(&candidate, &activation, "join", &fence, 23)
        .await
        .expect("wait");
    assert_eq!(wait.run.state, TaskFlowRunState::Waiting);
    assert_eq!(wait.run.current_node, "success");
    let resumed = store
        .resume_neural_circuit_wait_v1(
            &candidate,
            &activation,
            &wait,
            &Sha256Digest::for_bytes(b"join-receipt"),
            &fence,
            24,
        )
        .await
        .expect("resume");
    assert_eq!(resumed.state, TaskFlowRunState::Running);
    assert_eq!(resumed.current_node, "success");

    let terminal = store
        .complete_neural_circuit_terminal_v1(
            &candidate,
            &activation,
            &Sha256Digest::for_bytes(b"terminal-output"),
            &fence,
            25,
        )
        .await
        .expect("terminal");
    assert_eq!(terminal.state, TaskFlowRunState::Succeeded);
    assert!(!terminal.authority_granted);
    store.close().await;
}
