use codex_hepta_automation::AutomationStore;
use codex_hepta_automation::CircuitActivationCompletionV2;
use codex_hepta_automation::CircuitDecisionReceiptV2;
use codex_hepta_automation::CircuitDefinitionV2;
use codex_hepta_automation::CircuitEdgeV2;
use codex_hepta_automation::CircuitFleetLeaseRefV1;
use codex_hepta_automation::CircuitJoinReceiptV2;
use codex_hepta_automation::CircuitNodeRoleV2;
use codex_hepta_automation::CircuitNodeV2;
use codex_hepta_automation::CircuitPortV2;
use codex_hepta_automation::CircuitRunStateV2;
use codex_hepta_automation::TaskFlowFence;
use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_fleet::AgentManifest;
use codex_hepta_fleet::FleetRegistry;
use codex_hepta_fleet::ResourceBudget;
use codex_hepta_fleet::WorkspaceBinding;
use codex_hepta_paths::HeptaFleetRoot;

const AGENT_ID: &str = "018f4f72-5f8f-7cc1-8f55-df9fb3aa2c52";

struct Fixture {
    _temp: tempfile::TempDir,
    layout: codex_hepta_paths::HeptaAgentLayout,
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
        Self {
            _temp: temp,
            layout: registry.register(manifest).expect("register agent").layout,
        }
    }
}

fn digest(label: &str) -> Sha256Digest {
    Sha256Digest::for_bytes(label.as_bytes())
}

fn port(name: &str, schema: &Sha256Digest) -> CircuitPortV2 {
    CircuitPortV2::new(name, schema.clone()).expect("port")
}

fn definition() -> CircuitDefinitionV2 {
    let schema = digest("circuit-v2-signal");
    let nodes = vec![
        CircuitNodeV2::new("observe", CircuitNodeRoleV2::Observe)
            .with_ports(vec![], vec![port("out", &schema)]),
        CircuitNodeV2::new("decide", CircuitNodeRoleV2::Decide)
            .with_ports(vec![port("in", &schema)], vec![port("out", &schema)]),
        CircuitNodeV2::new("guard", CircuitNodeRoleV2::TransformGuard)
            .with_ports(vec![port("in", &schema)], vec![port("out", &schema)]),
        CircuitNodeV2::new("child", CircuitNodeRoleV2::OrganCall)
            .with_ports(vec![port("in", &schema)], vec![port("out", &schema)])
            .with_capability("organ.retrieval"),
        CircuitNodeV2::new("effect", CircuitNodeRoleV2::Effect)
            .with_ports(vec![port("in", &schema)], vec![port("out", &schema)])
            .with_capability("provider.deliver")
            .with_idempotency_template("taskflow-logical-effect-v1"),
        CircuitNodeV2::new("wait", CircuitNodeRoleV2::Wait)
            .with_ports(vec![port("in", &schema)], vec![port("out", &schema)]),
        CircuitNodeV2::new("join", CircuitNodeRoleV2::Join)
            .with_ports(vec![port("in", &schema)], vec![port("out", &schema)]),
        CircuitNodeV2::new("success", CircuitNodeRoleV2::ExitSuccess)
            .with_ports(vec![port("in", &schema)], vec![]),
    ];
    let edges = vec![
        CircuitEdgeV2::new("e-observe-decide", "observe", "out", "decide", "in"),
        CircuitEdgeV2::new("e-decide-guard", "decide", "out", "guard", "in"),
        CircuitEdgeV2::new("e-guard-child", "guard", "out", "child", "in")
            .conditioned(digest("guard-approved")),
        CircuitEdgeV2::new("e-child-effect", "child", "out", "effect", "in"),
        CircuitEdgeV2::new("e-effect-wait", "effect", "out", "wait", "in"),
        CircuitEdgeV2::new("e-wait-join", "wait", "out", "join", "in"),
        CircuitEdgeV2::new("e-join-success", "join", "out", "success", "in"),
    ];
    CircuitDefinitionV2::new(
        "retrieval-delivery-circuit",
        2,
        None,
        None,
        "observe",
        nodes,
        edges,
        vec!["organ.retrieval".to_string(), "provider.deliver".to_string()],
        digest("route-policy-v2"),
        digest("parameter-bundle-v2"),
        digest("resource-profile-v2"),
        4,
        32,
    )
    .expect("definition")
}

fn fleet_lease(definition: &CircuitDefinitionV2) -> CircuitFleetLeaseRefV1 {
    CircuitFleetLeaseRefV1 {
        allocation_id: "fleet-allocation-circuit-1".to_string(),
        host_id: "host-a".to_string(),
        host_generation: 1,
        authority_epoch: 7,
        lease_generation: 1,
        expires_at_ms: 100_000,
        semantic_digest: digest("fleet-semantic"),
        verified_use_witness_digest: digest("fleet-authority-witness"),
        resource_profile_digest: definition.resource_profile_digest.clone(),
        remaining_projection_digest: digest("fleet-remaining-projection"),
    }
}

fn fence() -> TaskFlowFence {
    TaskFlowFence::new(
        AgentId::parse(AGENT_ID).expect("agent id"),
        "circuit-v2-owner",
        1,
        1,
        "circuit-v2-fence",
    )
    .expect("fence")
}

fn completion(
    id: &str,
    selected: Option<&str>,
    node: CircuitNodeRoleV2,
    route_policy_digest: &Sha256Digest,
) -> CircuitActivationCompletionV2 {
    let decision_receipt = (node == CircuitNodeRoleV2::Decide).then(|| {
        CircuitDecisionReceiptV2 {
            candidate_set_digest: digest("candidate-set"),
            policy_digest: route_policy_digest.clone(),
            model_receipt_digest: digest("model-receipt"),
            selected_edge_id: selected.expect("decision edge").to_string(),
            propensity_micros: Some(500_000),
        }
    });
    let join_receipts = if node == CircuitNodeRoleV2::Join {
        vec![
            CircuitJoinReceiptV2 {
                source_id: "branch-a".to_string(),
                receipt_digest: digest("join-a"),
            },
            CircuitJoinReceiptV2 {
                source_id: "branch-b".to_string(),
                receipt_digest: digest("join-b"),
            },
        ]
    } else {
        Vec::new()
    };
    CircuitActivationCompletionV2 {
        completion_id: id.to_string(),
        output_digest: digest(&format!("{id}-output")),
        receipt_digest: digest(&format!("{id}-receipt")),
        selected_edge_id: selected.map(str::to_string),
        decision_receipt,
        join_receipts,
        child_run_id: (node == CircuitNodeRoleV2::OrganCall)
            .then(|| "child-circuit-run-1".to_string()),
        effect_step_id: (node == CircuitNodeRoleV2::Effect)
            .then(|| "taskflow-effect-step-1".to_string()),
    }
}

#[tokio::test]
async fn circuit_v2_persists_choice_before_effect_and_recovers_mid_run() {
    let fixture = Fixture::new();
    let store = AutomationStore::open(&fixture.layout)
        .await
        .expect("automation store");
    let definition = definition();
    let plan = definition.compile_plan().expect("plan");
    assert!(!plan.authority_granted);
    assert_eq!(
        plan.topological_order,
        [
            "observe",
            "decide",
            "guard",
            "child",
            "effect",
            "wait",
            "join",
            "success"
        ]
    );
    store
        .register_circuit_definition_v2(&definition, 100)
        .await
        .expect("register V2");
    store
        .start_circuit_run_v2(
            "circuit-run-1",
            &definition,
            &digest("initial-signal"),
            &fleet_lease(&definition),
            101,
        )
        .await
        .expect("start V2 run");
    let owner = fence();

    let observe = store
        .claim_next_circuit_activation_v2("circuit-run-1", &owner, 102, 10_000)
        .await
        .expect("claim observe")
        .expect("observe activation");
    assert_eq!(observe.node_id, "observe");
    store
        .complete_circuit_activation_v2(
            "circuit-run-1",
            observe.activation_id,
            &owner,
            &completion(
                "observe-complete",
                Some("e-observe-decide"),
                CircuitNodeRoleV2::Observe,
                &definition.route_policy_digest,
            ),
            103,
        )
        .await
        .expect("complete observe");

    let decide = store
        .claim_next_circuit_activation_v2("circuit-run-1", &owner, 104, 10_000)
        .await
        .expect("claim decide")
        .expect("decide activation");
    let advance = store
        .complete_circuit_activation_v2(
            "circuit-run-1",
            decide.activation_id,
            &owner,
            &completion(
                "decide-complete",
                Some("e-decide-guard"),
                CircuitNodeRoleV2::Decide,
                &definition.route_policy_digest,
            ),
            105,
        )
        .await
        .expect("commit durable decision");
    assert_eq!(
        advance
            .completed
            .completion
            .as_ref()
            .and_then(|value| value.decision_receipt.as_ref())
            .map(|value| value.selected_edge_id.as_str()),
        Some("e-decide-guard")
    );

    let guard = store
        .claim_next_circuit_activation_v2("circuit-run-1", &owner, 106, 10_000)
        .await
        .expect("claim guard")
        .expect("guard activation");
    store
        .complete_circuit_activation_v2(
            "circuit-run-1",
            guard.activation_id,
            &owner,
            &completion(
                "guard-complete",
                Some("e-guard-child"),
                CircuitNodeRoleV2::TransformGuard,
                &definition.route_policy_digest,
            ),
            107,
        )
        .await
        .expect("complete guard");

    let child = store
        .claim_next_circuit_activation_v2("circuit-run-1", &owner, 108, 10_000)
        .await
        .expect("claim child")
        .expect("child activation");
    store
        .complete_circuit_activation_v2(
            "circuit-run-1",
            child.activation_id,
            &owner,
            &completion(
                "child-complete",
                Some("e-child-effect"),
                CircuitNodeRoleV2::OrganCall,
                &definition.route_policy_digest,
            ),
            109,
        )
        .await
        .expect("complete child");

    // Reopen after the branch and child receipts are durable. The next effect
    // activation must be recovered from SQLite, not recomputed from a newer
    // policy or child result.
    store.close().await;
    let reopened = AutomationStore::open(&fixture.layout)
        .await
        .expect("reopen automation store");
    let effect = reopened
        .claim_next_circuit_activation_v2("circuit-run-1", &owner, 110, 10_000)
        .await
        .expect("claim effect after reopen")
        .expect("effect activation");
    assert_eq!(effect.node_id, "effect");
    assert_eq!(
        effect.predecessor_activation_id,
        Some(child.activation_id),
        "effect preserves the durable choice/child predecessor"
    );
    reopened
        .complete_circuit_activation_v2(
            "circuit-run-1",
            effect.activation_id,
            &owner,
            &completion(
                "effect-terminal",
                Some("e-effect-wait"),
                CircuitNodeRoleV2::Effect,
                &definition.route_policy_digest,
            ),
            111,
        )
        .await
        .expect("effect advances only with a referenced TaskFlow step receipt");

    let wait = reopened
        .claim_next_circuit_activation_v2("circuit-run-1", &owner, 112, 10_000)
        .await
        .expect("claim wait")
        .expect("wait activation");
    reopened
        .complete_circuit_activation_v2(
            "circuit-run-1",
            wait.activation_id,
            &owner,
            &completion(
                "wait-observed",
                Some("e-wait-join"),
                CircuitNodeRoleV2::Wait,
                &definition.route_policy_digest,
            ),
            113,
        )
        .await
        .expect("complete wait");

    let join = reopened
        .claim_next_circuit_activation_v2("circuit-run-1", &owner, 114, 10_000)
        .await
        .expect("claim join")
        .expect("join activation");
    reopened
        .complete_circuit_activation_v2(
            "circuit-run-1",
            join.activation_id,
            &owner,
            &completion(
                "join-complete",
                Some("e-join-success"),
                CircuitNodeRoleV2::Join,
                &definition.route_policy_digest,
            ),
            115,
        )
        .await
        .expect("complete join");

    let exit = reopened
        .claim_next_circuit_activation_v2("circuit-run-1", &owner, 116, 10_000)
        .await
        .expect("claim exit")
        .expect("exit activation");
    let terminal = reopened
        .complete_circuit_activation_v2(
            "circuit-run-1",
            exit.activation_id,
            &owner,
            &completion(
                "exit-success",
                None,
                CircuitNodeRoleV2::ExitSuccess,
                &definition.route_policy_digest,
            ),
            117,
        )
        .await
        .expect("complete exit");
    assert_eq!(terminal.run_state, CircuitRunStateV2::Succeeded);
    assert_eq!(
        reopened
            .circuit_run_v2("circuit-run-1")
            .await
            .expect("read run")
            .expect("run")
            .state,
        CircuitRunStateV2::Succeeded
    );
}
