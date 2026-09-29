#![allow(clippy::expect_used, reason = "durable recovery integration fixture")]

use codex_hepta_automation::AutomationStore;
use codex_hepta_automation::CircuitDecisionCellV1;
use codex_hepta_automation::CircuitDecisionRequestV1;
use codex_hepta_automation::CircuitDecisionV1;
use codex_hepta_automation::CircuitEdgeV1;
use codex_hepta_automation::CircuitEventIngressV1;
use codex_hepta_automation::CircuitNodeRoleV1;
use codex_hepta_automation::CircuitNodeV1;
use codex_hepta_automation::CircuitOrganPortV1;
use codex_hepta_automation::CircuitOrganReceiptV1;
use codex_hepta_automation::CircuitOrganRequestV1;
use codex_hepta_automation::CircuitRuntimeOutcomeV1;
use codex_hepta_automation::CircuitRuntimeProfileV1;
use codex_hepta_automation::CircuitRuntimeRecoveredOutcomeV1;
use codex_hepta_automation::CircuitRuntimeRecoveryObserverV1;
use codex_hepta_automation::CircuitRuntimeRecoveryRequestV1;
use codex_hepta_automation::CircuitWaitJoinPortV1;
use codex_hepta_automation::CircuitWaitReceiptV1;
use codex_hepta_automation::CircuitWaitRequestV1;
use codex_hepta_automation::CircuitWaitStateV1;
use codex_hepta_automation::DurableCircuitCommitStatusV1;
use codex_hepta_automation::DurableCircuitRunStateV1;
use codex_hepta_automation::NeuralCircuitCandidateV1;
use codex_hepta_automation::NeuralCircuitRuntimeError;
use codex_hepta_automation::NeverCancelled;
use codex_hepta_automation::TaskFlowFence;
use codex_hepta_automation::run_neural_circuit_v1;
use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_fleet::AgentManifest;
use codex_hepta_fleet::FleetRegistry;
use codex_hepta_fleet::ResourceBudget;
use codex_hepta_fleet::WorkspaceBinding;
use codex_hepta_paths::HeptaFleetRoot;
use pretty_assertions::assert_eq;

const AGENT_ID: &str = "018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12";
const THREAD_ID: &str = "019153a4-3088-7e03-a56a-9b1964f75ddd";

fn digest(value: impl AsRef<[u8]>) -> Sha256Digest {
    Sha256Digest::for_bytes(value.as_ref())
}

fn candidate() -> NeuralCircuitCandidateV1 {
    let mut wait = CircuitNodeV1::new("wait", CircuitNodeRoleV1::WaitJoin);
    wait.wait_timeout_ms = Some(1_000);
    NeuralCircuitCandidateV1::new(
        "recovery-required-resume",
        1,
        None,
        "observe",
        vec![
            CircuitNodeV1::new("observe", CircuitNodeRoleV1::Observe),
            wait,
            CircuitNodeV1::new("success", CircuitNodeRoleV1::ExitSuccess),
            CircuitNodeV1::new("failure", CircuitNodeRoleV1::ExitFailure),
        ],
        vec![
            CircuitEdgeV1::new("observe", "wait"),
            CircuitEdgeV1::new("wait", "success"),
            CircuitEdgeV1::new("wait", "failure"),
        ],
        Vec::new(),
        digest("route-policy"),
        digest("parameter-bundle"),
        digest("resource-profile"),
    )
    .expect("candidate")
}

fn event() -> CircuitEventIngressV1 {
    CircuitEventIngressV1::new("recovery-event", digest("payload"), None).expect("event")
}

fn fence() -> TaskFlowFence {
    TaskFlowFence::new(
        AgentId::parse(AGENT_ID).expect("agent"),
        "recovery-owner",
        1,
        1,
        "recovery-fence",
    )
    .expect("fence")
}

struct UnusedDecision;

impl CircuitDecisionCellV1 for UnusedDecision {
    fn decide(
        &mut self,
        _request: &CircuitDecisionRequestV1,
    ) -> Result<CircuitDecisionV1, NeuralCircuitRuntimeError> {
        panic!("candidate has no Decision node")
    }
}

struct UnusedOrgan;

impl CircuitOrganPortV1 for UnusedOrgan {
    fn call(
        &mut self,
        _request: &CircuitOrganRequestV1,
    ) -> Result<CircuitOrganReceiptV1, NeuralCircuitRuntimeError> {
        panic!("candidate has no Organ node")
    }
}

struct LostWait;

impl CircuitWaitJoinPortV1 for LostWait {
    fn wait(
        &mut self,
        _request: &CircuitWaitRequestV1,
    ) -> Result<CircuitWaitReceiptV1, NeuralCircuitRuntimeError> {
        Err(NeuralCircuitRuntimeError::Port(
            "wait owner outcome is unknown".to_string(),
        ))
    }
}

struct ReadyWait;

impl CircuitWaitJoinPortV1 for ReadyWait {
    fn wait(
        &mut self,
        _request: &CircuitWaitRequestV1,
    ) -> Result<CircuitWaitReceiptV1, NeuralCircuitRuntimeError> {
        Ok(CircuitWaitReceiptV1 {
            state: CircuitWaitStateV1::Ready,
            observation_digest: digest("wait-ready"),
            cost_units: 1,
        })
    }
}

struct Observer {
    outcome: Option<CircuitRuntimeOutcomeV1>,
}

impl CircuitRuntimeRecoveryObserverV1 for Observer {
    fn observe(
        &mut self,
        _request: &CircuitRuntimeRecoveryRequestV1,
    ) -> Result<Option<CircuitRuntimeRecoveredOutcomeV1>, NeuralCircuitRuntimeError> {
        Ok(self
            .outcome
            .take()
            .map(|outcome| CircuitRuntimeRecoveredOutcomeV1 {
                outcome,
                evidence_digest: digest("owner-terminal-observation"),
            }))
    }
}

#[tokio::test]
async fn recovery_required_can_settle_later_without_reexecuting_the_wait_owner() {
    let temp = tempfile::tempdir().expect("temp");
    let root = temp.path().canonicalize().expect("root");
    let fleet_root = HeptaFleetRoot::parse(root.join("fleet")).expect("fleet root");
    let registry = FleetRegistry::initialize(fleet_root.clone()).expect("registry");
    let workspace = root.join("workspace");
    std::fs::create_dir(&workspace).expect("workspace");
    let manifest = AgentManifest::new(
        AgentId::parse(AGENT_ID).expect("agent"),
        WorkspaceBinding::new(workspace, &fleet_root).expect("binding"),
        ResourceBudget::local_default(),
    )
    .expect("manifest");
    let layout = registry.register(manifest).expect("register").layout;
    let store = AutomationStore::open(&layout).await.expect("store");
    let candidate = candidate();
    let event = event();
    let profile = CircuitRuntimeProfileV1::default();

    let mut decision = UnusedDecision;
    let mut organ = UnusedOrgan;
    let mut lost_wait = LostWait;
    assert!(matches!(
        store
            .execute_durable_neural_circuit_v1(
                "run-recovery-required",
                THREAD_ID,
                &candidate,
                &event,
                &profile,
                &fence(),
                10,
                &mut decision,
                &mut organ,
                &mut lost_wait,
                &NeverCancelled,
            )
            .await,
        Err(codex_hepta_automation::DurableNeuralCircuitError::Runtime(
            NeuralCircuitRuntimeError::Port(_)
        ))
    ));

    let mut no_observation = Observer { outcome: None };
    assert!(
        store
            .recover_durable_neural_circuit_activation_v1(
                "run-recovery-required",
                &candidate,
                &event,
                &profile,
                &fence(),
                20,
                &mut no_observation,
            )
            .await
            .expect("quarantine")
            .is_none()
    );
    assert_eq!(
        store
            .durable_neural_circuit_snapshot_v1("run-recovery-required")
            .await
            .expect("snapshot")
            .expect("run")
            .state,
        DurableCircuitRunStateV1::RecoveryRequired
    );

    let wrong_event = CircuitEventIngressV1::new(
        "different-recovery-event",
        digest("different-payload"),
        None,
    )
    .expect("different event");
    let mut must_not_observe = Observer { outcome: None };
    assert!(matches!(
        store
            .settle_durable_neural_circuit_recovery_v1(
                "run-recovery-required",
                &candidate,
                &wrong_event,
                &profile,
                &fence(),
                25,
                &mut must_not_observe,
            )
            .await,
        Err(codex_hepta_automation::DurableNeuralCircuitError::Conflict(_))
    ));
    let still_quarantined = store
        .durable_neural_circuit_snapshot_v1("run-recovery-required")
        .await
        .expect("snapshot after wrong input")
        .expect("run after wrong input");
    assert_eq!(
        still_quarantined.state,
        DurableCircuitRunStateV1::RecoveryRequired
    );
    assert_eq!(still_quarantined.reserved_cost_units, 0);

    let observed = run_neural_circuit_v1(
        &candidate,
        &event,
        &profile,
        &mut decision,
        &mut organ,
        &mut ReadyWait,
        &NeverCancelled,
    )
    .expect("observed owner outcome");
    let mut observer = Observer {
        outcome: Some(observed),
    };
    let receipt = store
        .settle_durable_neural_circuit_recovery_v1(
            "run-recovery-required",
            &candidate,
            &event,
            &profile,
            &fence(),
            30,
            &mut observer,
        )
        .await
        .expect("settle")
        .expect("receipt");
    assert_eq!(receipt.status, DurableCircuitCommitStatusV1::Recovered);
    assert_eq!(receipt.state, DurableCircuitRunStateV1::Terminal);
    store.close().await;
}
