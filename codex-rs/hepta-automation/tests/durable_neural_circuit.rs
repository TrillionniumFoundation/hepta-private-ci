#![allow(clippy::expect_used, reason = "durable Circuit integration fixtures")]

use std::cell::Cell;

use codex_hepta_automation::AutomationStore;
use codex_hepta_automation::CircuitDecisionCellV1;
use codex_hepta_automation::CircuitDecisionRequestV1;
use codex_hepta_automation::CircuitDecisionV1;
use codex_hepta_automation::CircuitEdgeV1;
use codex_hepta_automation::CircuitEffectResolutionStateV1;
use codex_hepta_automation::CircuitEffectResolutionV1;
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
use codex_hepta_automation::CircuitTerminalStateV1;
use codex_hepta_automation::CircuitWaitJoinPortV1;
use codex_hepta_automation::CircuitWaitReceiptV1;
use codex_hepta_automation::CircuitWaitRequestV1;
use codex_hepta_automation::CircuitWaitStateV1;
use codex_hepta_automation::DurableCircuitCommitStatusV1;
use codex_hepta_automation::DurableCircuitRunStateV1;
use codex_hepta_automation::DurableNeuralCircuitError;
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
use codex_hepta_paths::HeptaAgentLayout;
use codex_hepta_paths::HeptaFleetRoot;
use pretty_assertions::assert_eq;

const AGENT_ID: &str = "018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12";
const THREAD_ID: &str = "019153a4-3088-7e03-a56a-9b1964f75ddd";

struct Fixture {
    _temp: tempfile::TempDir,
    layout: HeptaAgentLayout,
}

impl Fixture {
    fn new() -> Self {
        let temp = tempfile::tempdir().expect("temporary root");
        let root = temp.path().canonicalize().expect("canonical root");
        let fleet_root = HeptaFleetRoot::parse(root.join("fleet")).expect("fleet root");
        let registry = FleetRegistry::initialize(fleet_root.clone()).expect("registry");
        let workspace = root.join("workspace");
        std::fs::create_dir(&workspace).expect("workspace");
        let manifest = AgentManifest::new(
            AgentId::parse(AGENT_ID).expect("agent"),
            WorkspaceBinding::new(workspace, &fleet_root).expect("workspace binding"),
            ResourceBudget::local_default(),
        )
        .expect("manifest");
        Self {
            _temp: temp,
            layout: registry.register(manifest).expect("register").layout,
        }
    }
}

fn digest(label: impl AsRef<[u8]>) -> Sha256Digest {
    Sha256Digest::for_bytes(label.as_ref())
}

fn fence() -> TaskFlowFence {
    TaskFlowFence::new(
        AgentId::parse(AGENT_ID).expect("agent"),
        "durable-circuit-owner",
        1,
        1,
        "durable-circuit-fence",
    )
    .expect("fence")
}

fn event() -> CircuitEventIngressV1 {
    CircuitEventIngressV1::new("event-1", digest("payload"), None).expect("event")
}

fn wait_candidate(id: &str) -> NeuralCircuitCandidateV1 {
    let mut organ = CircuitNodeV1::new("organ", CircuitNodeRoleV1::OrganCall);
    organ.capability = Some("memory.retrieval".to_string());
    let mut wait = CircuitNodeV1::new("wait", CircuitNodeRoleV1::WaitJoin);
    wait.wait_timeout_ms = Some(1_000);
    NeuralCircuitCandidateV1::new(
        id,
        1,
        None,
        "observe",
        vec![
            CircuitNodeV1::new("observe", CircuitNodeRoleV1::Observe),
            CircuitNodeV1::new("decide", CircuitNodeRoleV1::Decide),
            organ,
            wait,
            CircuitNodeV1::new("success", CircuitNodeRoleV1::ExitSuccess),
            CircuitNodeV1::new("failure", CircuitNodeRoleV1::ExitFailure),
        ],
        vec![
            CircuitEdgeV1::new("observe", "decide"),
            CircuitEdgeV1::new("decide", "organ"),
            CircuitEdgeV1::new("decide", "failure"),
            CircuitEdgeV1::new("organ", "wait"),
            CircuitEdgeV1::new("wait", "success"),
        ],
        vec!["memory.retrieval".to_string()],
        digest("route-policy"),
        digest("parameters"),
        digest("resources"),
    )
    .expect("candidate")
}

fn effect_candidate() -> NeuralCircuitCandidateV1 {
    NeuralCircuitCandidateV1::new(
        "durable-effect",
        1,
        None,
        "observe",
        vec![
            CircuitNodeV1::new("observe", CircuitNodeRoleV1::Observe),
            CircuitNodeV1::effect("effect", "network.http", "effect/{run}"),
            CircuitNodeV1::new("success", CircuitNodeRoleV1::ExitSuccess),
            CircuitNodeV1::new("failure", CircuitNodeRoleV1::ExitFailure),
        ],
        vec![
            CircuitEdgeV1::new("observe", "effect"),
            CircuitEdgeV1::new("effect", "success"),
            CircuitEdgeV1::new("effect", "failure"),
        ],
        vec!["network.http".to_string()],
        digest("effect-route-policy"),
        digest("effect-parameters"),
        digest("effect-resources"),
    )
    .expect("candidate")
}

struct RouteOrgan {
    calls: Cell<u32>,
    fail: bool,
}

impl RouteOrgan {
    fn healthy() -> Self {
        Self {
            calls: Cell::new(0),
            fail: false,
        }
    }

    fn failing() -> Self {
        Self {
            calls: Cell::new(0),
            fail: true,
        }
    }
}

impl CircuitDecisionCellV1 for RouteOrgan {
    fn decide(
        &mut self,
        _request: &CircuitDecisionRequestV1,
    ) -> Result<CircuitDecisionV1, NeuralCircuitRuntimeError> {
        self.calls.set(self.calls.get() + 1);
        if self.fail {
            return Err(NeuralCircuitRuntimeError::Port(
                "decision owner response was lost".to_string(),
            ));
        }
        Ok(CircuitDecisionV1::Route {
            next_node: "organ".to_string(),
            cost_units: 2,
            decision_digest: digest("decision"),
        })
    }
}

struct CountingOrgan {
    calls: Cell<u32>,
}

impl CircuitOrganPortV1 for CountingOrgan {
    fn call(
        &mut self,
        _request: &CircuitOrganRequestV1,
    ) -> Result<CircuitOrganReceiptV1, NeuralCircuitRuntimeError> {
        self.calls.set(self.calls.get() + 1);
        Ok(CircuitOrganReceiptV1 {
            output_digest: digest("organ-output"),
            cost_units: 3,
        })
    }
}

struct WaitPort {
    calls: Cell<u32>,
    state: CircuitWaitStateV1,
}

impl CircuitWaitJoinPortV1 for WaitPort {
    fn wait(
        &mut self,
        _request: &CircuitWaitRequestV1,
    ) -> Result<CircuitWaitReceiptV1, NeuralCircuitRuntimeError> {
        self.calls.set(self.calls.get() + 1);
        Ok(CircuitWaitReceiptV1 {
            state: self.state,
            observation_digest: digest(format!("wait-{}", self.calls.get())),
            cost_units: 1,
        })
    }
}

struct LostWait;

impl CircuitWaitJoinPortV1 for LostWait {
    fn wait(
        &mut self,
        _request: &CircuitWaitRequestV1,
    ) -> Result<CircuitWaitReceiptV1, NeuralCircuitRuntimeError> {
        Err(NeuralCircuitRuntimeError::Port(
            "wait owner outcome was lost".to_string(),
        ))
    }
}

struct PanicDecision;

impl CircuitDecisionCellV1 for PanicDecision {
    fn decide(
        &mut self,
        _request: &CircuitDecisionRequestV1,
    ) -> Result<CircuitDecisionV1, NeuralCircuitRuntimeError> {
        panic!("committed DecisionCell must not be replayed")
    }
}

struct PanicOrgan;

impl CircuitOrganPortV1 for PanicOrgan {
    fn call(
        &mut self,
        _request: &CircuitOrganRequestV1,
    ) -> Result<CircuitOrganReceiptV1, NeuralCircuitRuntimeError> {
        panic!("committed organ call must not be replayed")
    }
}

#[tokio::test]
async fn terminal_outcome_reopens_without_reexecuting_ports() {
    let fixture = Fixture::new();
    let store = AutomationStore::open(&fixture.layout).await.expect("store");
    let candidate = wait_candidate("durable-terminal");
    let profile = CircuitRuntimeProfileV1::default();
    let ingress = event();
    let mut decision = RouteOrgan::healthy();
    let mut organ = CountingOrgan {
        calls: Cell::new(0),
    };
    let mut wait = WaitPort {
        calls: Cell::new(0),
        state: CircuitWaitStateV1::Ready,
    };
    let first = store
        .execute_durable_neural_circuit_v1(
            "run-terminal",
            THREAD_ID,
            &candidate,
            &ingress,
            &profile,
            &fence(),
            10,
            &mut decision,
            &mut organ,
            &mut wait,
            &NeverCancelled,
        )
        .await
        .expect("execute");
    assert_eq!(first.status, DurableCircuitCommitStatusV1::Committed);
    assert_eq!(first.state, DurableCircuitRunStateV1::Terminal);
    assert!(matches!(
        first.outcome,
        CircuitRuntimeOutcomeV1::Terminal(ref receipt)
            if receipt.state == CircuitTerminalStateV1::Succeeded
    ));
    assert_eq!(decision.calls.get(), 1);
    assert_eq!(organ.calls.get(), 1);
    store.close().await;

    let reopened = AutomationStore::open(&fixture.layout)
        .await
        .expect("reopen");
    let mut decision = PanicDecision;
    let mut organ = PanicOrgan;
    let mut wait = WaitPort {
        calls: Cell::new(0),
        state: CircuitWaitStateV1::Ready,
    };
    let replay = reopened
        .execute_durable_neural_circuit_v1(
            "run-terminal",
            THREAD_ID,
            &candidate,
            &ingress,
            &profile,
            &fence(),
            20,
            &mut decision,
            &mut organ,
            &mut wait,
            &NeverCancelled,
        )
        .await
        .expect("replay");
    assert_eq!(replay.status, DurableCircuitCommitStatusV1::AlreadyCommitted);
    assert_eq!(replay.outcome_digest, first.outcome_digest);
    assert_eq!(wait.calls.get(), 0);
    reopened.close().await;
}

#[tokio::test]
async fn wait_checkpoint_resumes_without_repeating_decision_or_organ() {
    let fixture = Fixture::new();
    let store = AutomationStore::open(&fixture.layout).await.expect("store");
    let candidate = wait_candidate("durable-wait");
    let profile = CircuitRuntimeProfileV1::default();
    let ingress = event();
    let mut decision = RouteOrgan::healthy();
    let mut organ = CountingOrgan {
        calls: Cell::new(0),
    };
    let mut pending = WaitPort {
        calls: Cell::new(0),
        state: CircuitWaitStateV1::Pending,
    };
    let first = store
        .execute_durable_neural_circuit_v1(
            "run-wait",
            THREAD_ID,
            &candidate,
            &ingress,
            &profile,
            &fence(),
            10,
            &mut decision,
            &mut organ,
            &mut pending,
            &NeverCancelled,
        )
        .await
        .expect("pending");
    assert_eq!(first.state, DurableCircuitRunStateV1::Waiting);
    store.close().await;

    let reopened = AutomationStore::open(&fixture.layout)
        .await
        .expect("reopen");
    let mut decision = PanicDecision;
    let mut organ = PanicOrgan;
    let mut ready = WaitPort {
        calls: Cell::new(0),
        state: CircuitWaitStateV1::Ready,
    };
    let resumed = reopened
        .resume_durable_neural_circuit_wait_v1(
            "run-wait",
            &candidate,
            &ingress,
            &profile,
            &fence(),
            20,
            &mut decision,
            &mut organ,
            &mut ready,
            &NeverCancelled,
        )
        .await
        .expect("resume");
    assert_eq!(resumed.state, DurableCircuitRunStateV1::Terminal);
    assert_eq!(resumed.activation_seq, 2);
    assert_eq!(ready.calls.get(), 1);
    reopened.close().await;
}

#[tokio::test]
async fn effect_result_continues_only_from_a_committed_effect_boundary() {
    let fixture = Fixture::new();
    let store = AutomationStore::open(&fixture.layout).await.expect("store");
    let candidate = effect_candidate();
    let profile = CircuitRuntimeProfileV1::default();
    let ingress = event();
    let mut decision = PanicDecision;
    let mut organ = PanicOrgan;
    let mut wait = WaitPort {
        calls: Cell::new(0),
        state: CircuitWaitStateV1::Ready,
    };
    let pending = store
        .execute_durable_neural_circuit_v1(
            "run-effect",
            THREAD_ID,
            &candidate,
            &ingress,
            &profile,
            &fence(),
            10,
            &mut decision,
            &mut organ,
            &mut wait,
            &NeverCancelled,
        )
        .await
        .expect("effect boundary");
    assert_eq!(pending.state, DurableCircuitRunStateV1::EffectPending);
    assert!(matches!(
        pending.outcome,
        CircuitRuntimeOutcomeV1::EffectPending(_)
    ));
    store.close().await;

    let reopened = AutomationStore::open(&fixture.layout)
        .await
        .expect("reopen");
    let resolution = CircuitEffectResolutionV1 {
        state: CircuitEffectResolutionStateV1::Succeeded,
        observation_digest: digest("provider-terminal-receipt"),
        cost_units: 4,
    };
    let resolved = reopened
        .resolve_durable_neural_circuit_effect_v1(
            "run-effect",
            &candidate,
            &ingress,
            &profile,
            &resolution,
            &fence(),
            20,
            &mut decision,
            &mut organ,
            &mut wait,
            &NeverCancelled,
        )
        .await
        .expect("resolve effect");
    assert_eq!(resolved.state, DurableCircuitRunStateV1::Terminal);
    assert!(matches!(
        resolved.outcome,
        CircuitRuntimeOutcomeV1::Terminal(ref receipt)
            if receipt.state == CircuitTerminalStateV1::Succeeded
    ));
    reopened.close().await;
}

#[tokio::test]
async fn second_activation_loss_never_relabels_the_previous_outcome_as_committed() {
    let fixture = Fixture::new();
    let store = AutomationStore::open(&fixture.layout).await.expect("store");
    let candidate = wait_candidate("durable-second-activation-loss");
    let profile = CircuitRuntimeProfileV1::default();
    let ingress = event();
    let mut decision = RouteOrgan::healthy();
    let mut organ = CountingOrgan {
        calls: Cell::new(0),
    };
    let mut pending = WaitPort {
        calls: Cell::new(0),
        state: CircuitWaitStateV1::Pending,
    };
    let first = store
        .execute_durable_neural_circuit_v1(
            "run-second-activation-loss",
            THREAD_ID,
            &candidate,
            &ingress,
            &profile,
            &fence(),
            10,
            &mut decision,
            &mut organ,
            &mut pending,
            &NeverCancelled,
        )
        .await
        .expect("first wait boundary");
    assert_eq!(first.activation_seq, 1);
    assert_eq!(first.state, DurableCircuitRunStateV1::Waiting);

    let mut panic_decision = PanicDecision;
    let mut panic_organ = PanicOrgan;
    assert!(matches!(
        store
            .resume_durable_neural_circuit_wait_v1(
                "run-second-activation-loss",
                &candidate,
                &ingress,
                &profile,
                &fence(),
                20,
                &mut panic_decision,
                &mut panic_organ,
                &mut LostWait,
                &NeverCancelled,
            )
            .await,
        Err(DurableNeuralCircuitError::Runtime(
            NeuralCircuitRuntimeError::Port(_)
        ))
    ));

    let snapshot = store
        .durable_neural_circuit_snapshot_v1("run-second-activation-loss")
        .await
        .expect("snapshot")
        .expect("run");
    assert_eq!(snapshot.activation_seq, 2);
    assert_eq!(snapshot.state, DurableCircuitRunStateV1::Executing);

    assert!(matches!(
        store
            .resume_durable_neural_circuit_wait_v1(
                "run-second-activation-loss",
                &candidate,
                &ingress,
                &profile,
                &fence(),
                30,
                &mut panic_decision,
                &mut panic_organ,
                &mut LostWait,
                &NeverCancelled,
            )
            .await,
        Err(DurableNeuralCircuitError::RecoveryRequired)
    ));
    store.close().await;
}

struct RecoveryObserver {
    outcome: Option<CircuitRuntimeOutcomeV1>,
    observed_input: Option<Sha256Digest>,
}

impl CircuitRuntimeRecoveryObserverV1 for RecoveryObserver {
    fn observe(
        &mut self,
        request: &CircuitRuntimeRecoveryRequestV1,
    ) -> Result<Option<CircuitRuntimeRecoveredOutcomeV1>, NeuralCircuitRuntimeError> {
        self.observed_input = Some(request.input_digest.clone());
        Ok(self
            .outcome
            .take()
            .map(|outcome| CircuitRuntimeRecoveredOutcomeV1 {
                outcome,
                evidence_digest: digest("independent-owner-observation"),
            }))
    }
}

#[tokio::test]
async fn lost_owner_response_blocks_rerun_until_identity_bound_recovery() {
    let fixture = Fixture::new();
    let store = AutomationStore::open(&fixture.layout).await.expect("store");
    let candidate = wait_candidate("durable-recovery");
    let profile = CircuitRuntimeProfileV1::default();
    let ingress = event();
    let mut failing = RouteOrgan::failing();
    let mut organ = CountingOrgan {
        calls: Cell::new(0),
    };
    let mut wait = WaitPort {
        calls: Cell::new(0),
        state: CircuitWaitStateV1::Ready,
    };
    assert!(matches!(
        store
            .execute_durable_neural_circuit_v1(
                "run-recovery",
                THREAD_ID,
                &candidate,
                &ingress,
                &profile,
                &fence(),
                10,
                &mut failing,
                &mut organ,
                &mut wait,
                &NeverCancelled,
            )
            .await,
        Err(DurableNeuralCircuitError::Runtime(
            NeuralCircuitRuntimeError::Port(_)
        ))
    ));
    store.close().await;

    let reopened = AutomationStore::open(&fixture.layout)
        .await
        .expect("reopen");
    let mut decision = RouteOrgan::healthy();
    assert!(matches!(
        reopened
            .execute_durable_neural_circuit_v1(
                "run-recovery",
                THREAD_ID,
                &candidate,
                &ingress,
                &profile,
                &fence(),
                20,
                &mut decision,
                &mut organ,
                &mut wait,
                &NeverCancelled,
            )
            .await,
        Err(DurableNeuralCircuitError::RecoveryRequired)
    ));
    assert_eq!(decision.calls.get(), 0);

    let observed_outcome = run_neural_circuit_v1(
        &candidate,
        &ingress,
        &profile,
        &mut RouteOrgan::healthy(),
        &mut CountingOrgan {
            calls: Cell::new(0),
        },
        &mut WaitPort {
            calls: Cell::new(0),
            state: CircuitWaitStateV1::Ready,
        },
        &NeverCancelled,
    )
    .expect("owner outcome");
    let mut observer = RecoveryObserver {
        outcome: Some(observed_outcome),
        observed_input: None,
    };
    let recovered = reopened
        .recover_durable_neural_circuit_activation_v1(
            "run-recovery",
            &candidate,
            &ingress,
            &profile,
            &fence(),
            30,
            &mut observer,
        )
        .await
        .expect("recover")
        .expect("owner observation");
    assert_eq!(recovered.status, DurableCircuitCommitStatusV1::Recovered);
    assert_eq!(recovered.state, DurableCircuitRunStateV1::Terminal);
    assert!(observer.observed_input.is_some());
    reopened.close().await;
}
