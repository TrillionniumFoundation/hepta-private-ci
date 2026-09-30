//! Named Agentd product host for the existing durable Neural Circuit owner.
//!
//! The host does not create a second scheduler, ledger, authority or model
//! runtime. It binds one Agent/generation/fence identity to registered owner
//! ports and delegates all durable intent, reservation, checkpoint, replay and
//! recovery semantics to `AutomationStore`.

use std::sync::Arc;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;

use codex_hepta_automation::AutomationStore;
use codex_hepta_automation::CircuitCancellationV1;
use codex_hepta_automation::CircuitDecisionCellV1;
use codex_hepta_automation::CircuitDecisionRequestV1;
use codex_hepta_automation::CircuitDecisionV1;
use codex_hepta_automation::CircuitEffectResolutionV1;
use codex_hepta_automation::CircuitEventIngressV1;
use codex_hepta_automation::CircuitOrganPortV1;
use codex_hepta_automation::CircuitOrganReceiptV1;
use codex_hepta_automation::CircuitOrganRequestV1;
use codex_hepta_automation::CircuitRuntimeProfileV1;
use codex_hepta_automation::CircuitRuntimeRecoveryObserverV1;
use codex_hepta_automation::CircuitRuntimeRecoveryRequestV1;
use codex_hepta_automation::CircuitRuntimeRecoveredOutcomeV1;
use codex_hepta_automation::CircuitWaitJoinPortV1;
use codex_hepta_automation::CircuitWaitReceiptV1;
use codex_hepta_automation::CircuitWaitRequestV1;
use codex_hepta_automation::DurableCircuitExecutionReceiptV1;
use codex_hepta_automation::DurableCircuitSnapshotV1;
use codex_hepta_automation::DurableNeuralCircuitError;
use codex_hepta_automation::NeuralCircuitCandidateV1;
use codex_hepta_automation::NeuralCircuitRuntimeError;
use codex_hepta_automation::TaskFlowFence;
use codex_hepta_contracts::AgentId;
use tokio::sync::Mutex;

#[derive(Debug, thiserror::Error)]
pub enum AgentdAutomationCircuitError {
    #[error("Agentd automation Circuit host identity is invalid")]
    InvalidHost,
    #[error("Agentd automation Circuit host generation is fenced")]
    GenerationFenced,
    #[error(transparent)]
    Durable(#[from] DurableNeuralCircuitError),
}

#[derive(Clone, Default)]
pub struct AgentdAutomationCircuitCancellationV1 {
    cancelled: Arc<AtomicBool>,
}

impl AgentdAutomationCircuitCancellationV1 {
    pub fn request(&self) {
        self.cancelled.store(true, Ordering::SeqCst);
    }

    pub fn clear(&self) {
        self.cancelled.store(false, Ordering::SeqCst);
    }
}

impl CircuitCancellationV1 for AgentdAutomationCircuitCancellationV1 {
    fn is_cancelled(&self) -> bool {
        self.cancelled.load(Ordering::SeqCst)
    }
}

struct DecisionPort(Box<dyn CircuitDecisionCellV1 + Send>);

impl CircuitDecisionCellV1 for DecisionPort {
    fn decide(
        &mut self,
        request: &CircuitDecisionRequestV1,
    ) -> Result<CircuitDecisionV1, NeuralCircuitRuntimeError> {
        self.0.decide(request)
    }
}

struct OrganPort(Box<dyn CircuitOrganPortV1 + Send>);

impl CircuitOrganPortV1 for OrganPort {
    fn call(
        &mut self,
        request: &CircuitOrganRequestV1,
    ) -> Result<CircuitOrganReceiptV1, NeuralCircuitRuntimeError> {
        self.0.call(request)
    }
}

struct WaitPort(Box<dyn CircuitWaitJoinPortV1 + Send>);

impl CircuitWaitJoinPortV1 for WaitPort {
    fn wait(
        &mut self,
        request: &CircuitWaitRequestV1,
    ) -> Result<CircuitWaitReceiptV1, NeuralCircuitRuntimeError> {
        self.0.wait(request)
    }
}

struct RecoveryPort(Box<dyn CircuitRuntimeRecoveryObserverV1 + Send>);

impl CircuitRuntimeRecoveryObserverV1 for RecoveryPort {
    fn observe(
        &mut self,
        request: &CircuitRuntimeRecoveryRequestV1,
    ) -> Result<Option<CircuitRuntimeRecoveredOutcomeV1>, NeuralCircuitRuntimeError> {
        self.0.observe(request)
    }
}

pub struct AgentdAutomationCircuitPortsV1 {
    decision: DecisionPort,
    organ: OrganPort,
    wait: WaitPort,
    recovery: RecoveryPort,
}

impl AgentdAutomationCircuitPortsV1 {
    pub fn new<D, O, W, R>(decision: D, organ: O, wait: W, recovery: R) -> Self
    where
        D: CircuitDecisionCellV1 + Send + 'static,
        O: CircuitOrganPortV1 + Send + 'static,
        W: CircuitWaitJoinPortV1 + Send + 'static,
        R: CircuitRuntimeRecoveryObserverV1 + Send + 'static,
    {
        Self {
            decision: DecisionPort(Box::new(decision)),
            organ: OrganPort(Box::new(organ)),
            wait: WaitPort(Box::new(wait)),
            recovery: RecoveryPort(Box::new(recovery)),
        }
    }
}

/// Single-generation Agentd composition for durable Neural Circuit execution.
///
/// Registered DecisionCell, organ and wait owners are serialized through this
/// host so an activation cannot race another use of mutable owner state. The
/// durable owner commits its activation intent and conserved reservation before
/// any of these ports can be called. A port error after contact leaves the exact
/// activation recoverable; this host never retries that owner call blindly.
pub struct AgentdAutomationCircuitHostV1 {
    owner_agent_id: AgentId,
    owner_id: String,
    spawn_generation: u64,
    cancellation: AgentdAutomationCircuitCancellationV1,
    ports: Mutex<AgentdAutomationCircuitPortsV1>,
}

impl AgentdAutomationCircuitHostV1 {
    pub fn new(
        owner_agent_id: AgentId,
        owner_id: impl Into<String>,
        spawn_generation: u64,
        ports: AgentdAutomationCircuitPortsV1,
    ) -> Result<Self, AgentdAutomationCircuitError> {
        let owner_id = owner_id.into();
        if owner_id.is_empty()
            || owner_id.len() > 256
            || owner_id.chars().any(char::is_control)
            || spawn_generation == 0
        {
            return Err(AgentdAutomationCircuitError::InvalidHost);
        }
        Ok(Self {
            owner_agent_id,
            owner_id,
            spawn_generation,
            cancellation: AgentdAutomationCircuitCancellationV1::default(),
            ports: Mutex::new(ports),
        })
    }

    pub fn cancellation(&self) -> AgentdAutomationCircuitCancellationV1 {
        self.cancellation.clone()
    }

    pub async fn execute(
        &self,
        store: &AutomationStore,
        run_id: &str,
        thread_id: &str,
        candidate: &NeuralCircuitCandidateV1,
        event: &CircuitEventIngressV1,
        profile: &CircuitRuntimeProfileV1,
        fence: &TaskFlowFence,
        now_ms: u64,
    ) -> Result<DurableCircuitExecutionReceiptV1, AgentdAutomationCircuitError> {
        self.require_identity(store, fence)?;
        let cancellation = self.cancellation.clone();
        let mut ports = self.ports.lock().await;
        let AgentdAutomationCircuitPortsV1 {
            decision,
            organ,
            wait,
            recovery: _,
        } = &mut *ports;
        store
            .execute_durable_neural_circuit_v1(
                run_id,
                thread_id,
                candidate,
                event,
                profile,
                fence,
                now_ms,
                decision,
                organ,
                wait,
                &cancellation,
            )
            .await
            .map_err(Into::into)
    }

    pub async fn resume_wait(
        &self,
        store: &AutomationStore,
        run_id: &str,
        candidate: &NeuralCircuitCandidateV1,
        event: &CircuitEventIngressV1,
        profile: &CircuitRuntimeProfileV1,
        fence: &TaskFlowFence,
        now_ms: u64,
    ) -> Result<DurableCircuitExecutionReceiptV1, AgentdAutomationCircuitError> {
        self.require_identity(store, fence)?;
        let cancellation = self.cancellation.clone();
        let mut ports = self.ports.lock().await;
        let AgentdAutomationCircuitPortsV1 {
            decision,
            organ,
            wait,
            recovery: _,
        } = &mut *ports;
        store
            .resume_durable_neural_circuit_wait_v1(
                run_id,
                candidate,
                event,
                profile,
                fence,
                now_ms,
                decision,
                organ,
                wait,
                &cancellation,
            )
            .await
            .map_err(Into::into)
    }

    pub async fn resolve_effect(
        &self,
        store: &AutomationStore,
        run_id: &str,
        candidate: &NeuralCircuitCandidateV1,
        event: &CircuitEventIngressV1,
        profile: &CircuitRuntimeProfileV1,
        resolution: &CircuitEffectResolutionV1,
        fence: &TaskFlowFence,
        now_ms: u64,
    ) -> Result<DurableCircuitExecutionReceiptV1, AgentdAutomationCircuitError> {
        self.require_identity(store, fence)?;
        let cancellation = self.cancellation.clone();
        let mut ports = self.ports.lock().await;
        let AgentdAutomationCircuitPortsV1 {
            decision,
            organ,
            wait,
            recovery: _,
        } = &mut *ports;
        store
            .resolve_durable_neural_circuit_effect_v1(
                run_id,
                candidate,
                event,
                profile,
                resolution,
                fence,
                now_ms,
                decision,
                organ,
                wait,
                &cancellation,
            )
            .await
            .map_err(Into::into)
    }

    pub async fn recover(
        &self,
        store: &AutomationStore,
        run_id: &str,
        candidate: &NeuralCircuitCandidateV1,
        event: &CircuitEventIngressV1,
        profile: &CircuitRuntimeProfileV1,
        fence: &TaskFlowFence,
        now_ms: u64,
    ) -> Result<Option<DurableCircuitExecutionReceiptV1>, AgentdAutomationCircuitError> {
        self.require_identity(store, fence)?;
        let mut ports = self.ports.lock().await;
        store
            .recover_durable_neural_circuit_activation_v1(
                run_id,
                candidate,
                event,
                profile,
                fence,
                now_ms,
                &mut ports.recovery,
            )
            .await
            .map_err(Into::into)
    }

    pub async fn settle_recovery(
        &self,
        store: &AutomationStore,
        run_id: &str,
        candidate: &NeuralCircuitCandidateV1,
        event: &CircuitEventIngressV1,
        profile: &CircuitRuntimeProfileV1,
        fence: &TaskFlowFence,
        now_ms: u64,
    ) -> Result<Option<DurableCircuitExecutionReceiptV1>, AgentdAutomationCircuitError> {
        self.require_identity(store, fence)?;
        let mut ports = self.ports.lock().await;
        store
            .settle_durable_neural_circuit_recovery_v1(
                run_id,
                candidate,
                event,
                profile,
                fence,
                now_ms,
                &mut ports.recovery,
            )
            .await
            .map_err(Into::into)
    }

    pub async fn snapshot(
        &self,
        store: &AutomationStore,
        run_id: &str,
    ) -> Result<Option<DurableCircuitSnapshotV1>, AgentdAutomationCircuitError> {
        if store.owner_agent_id() != &self.owner_agent_id {
            return Err(AgentdAutomationCircuitError::GenerationFenced);
        }
        store
            .durable_neural_circuit_snapshot_v1(run_id)
            .await
            .map_err(Into::into)
    }

    fn require_identity(
        &self,
        store: &AutomationStore,
        fence: &TaskFlowFence,
    ) -> Result<(), AgentdAutomationCircuitError> {
        if store.owner_agent_id() != &self.owner_agent_id
            || fence.owner_agent_id != self.owner_agent_id
            || fence.owner_id != self.owner_id
            || fence.generation != self.spawn_generation
        {
            return Err(AgentdAutomationCircuitError::GenerationFenced);
        }
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use std::sync::atomic::AtomicUsize;

    use codex_hepta_automation::CircuitEdgeV1;
    use codex_hepta_automation::CircuitNodeRoleV1;
    use codex_hepta_automation::CircuitNodeV1;
    use codex_hepta_automation::CircuitRuntimeOutcomeV1;
    use codex_hepta_automation::CircuitTerminalStateV1;
    use codex_hepta_automation::CircuitWaitStateV1;
    use codex_hepta_automation::DurableCircuitCommitStatusV1;
    use codex_hepta_automation::DurableCircuitRunStateV1;
    use codex_hepta_automation::run_neural_circuit_v1;
    use codex_hepta_contracts::Sha256Digest;
    use codex_hepta_fleet::AgentManifest;
    use codex_hepta_fleet::FleetRegistry;
    use codex_hepta_fleet::ResourceBudget;
    use codex_hepta_fleet::WorkspaceBinding;
    use codex_hepta_paths::HeptaFleetRoot;

    use super::*;

    const AGENT_ID: &str = "018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12";
    const THREAD_ID: &str = "019153a4-3088-7e03-a56a-9b1964f75ddd";
    const OWNER_ID: &str = "agentd-automation-circuit";

    fn digest(value: impl AsRef<[u8]>) -> Sha256Digest {
        Sha256Digest::for_bytes(value.as_ref())
    }

    fn candidate() -> NeuralCircuitCandidateV1 {
        let mut wait = CircuitNodeV1::new("wait", CircuitNodeRoleV1::WaitJoin);
        wait.wait_timeout_ms = Some(1_000);
        NeuralCircuitCandidateV1::new(
            "agentd-product-circuit",
            1,
            None,
            "observe",
            vec![
                CircuitNodeV1::new("observe", CircuitNodeRoleV1::Observe),
                wait,
                CircuitNodeV1::new("success", CircuitNodeRoleV1::ExitSuccess),
            ],
            vec![
                CircuitEdgeV1::new("observe", "wait"),
                CircuitEdgeV1::new("wait", "success"),
            ],
            Vec::new(),
            digest("route-policy"),
            digest("parameter-bundle"),
            digest("resource-profile"),
        )
        .expect("candidate")
    }

    fn event() -> CircuitEventIngressV1 {
        CircuitEventIngressV1::new("agentd-circuit-event", digest("payload"), None)
            .expect("event")
    }

    fn fence() -> TaskFlowFence {
        TaskFlowFence::new(
            AgentId::parse(AGENT_ID).expect("agent"),
            OWNER_ID,
            1,
            7,
            "agentd-circuit-fence",
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

    struct PendingThenReady {
        calls: Arc<AtomicUsize>,
    }

    impl CircuitWaitJoinPortV1 for PendingThenReady {
        fn wait(
            &mut self,
            _request: &CircuitWaitRequestV1,
        ) -> Result<CircuitWaitReceiptV1, NeuralCircuitRuntimeError> {
            let call = self.calls.fetch_add(1, Ordering::SeqCst);
            Ok(CircuitWaitReceiptV1 {
                state: if call == 0 {
                    CircuitWaitStateV1::Pending
                } else {
                    CircuitWaitStateV1::Ready
                },
                observation_digest: digest(format!("wait-{call}")),
                cost_units: 1,
            })
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
                observation_digest: digest("ready"),
                cost_units: 1,
            })
        }
    }

    struct LostAfterContact {
        calls: Arc<AtomicUsize>,
    }

    impl CircuitWaitJoinPortV1 for LostAfterContact {
        fn wait(
            &mut self,
            _request: &CircuitWaitRequestV1,
        ) -> Result<CircuitWaitReceiptV1, NeuralCircuitRuntimeError> {
            self.calls.fetch_add(1, Ordering::SeqCst);
            Err(NeuralCircuitRuntimeError::Port(
                "owner call completed but receipt was lost".to_string(),
            ))
        }
    }

    struct RecoveryObservation {
        outcome: Option<CircuitRuntimeOutcomeV1>,
    }

    impl CircuitRuntimeRecoveryObserverV1 for RecoveryObservation {
        fn observe(
            &mut self,
            _request: &CircuitRuntimeRecoveryRequestV1,
        ) -> Result<Option<CircuitRuntimeRecoveredOutcomeV1>, NeuralCircuitRuntimeError> {
            Ok(self
                .outcome
                .take()
                .map(|outcome| CircuitRuntimeRecoveredOutcomeV1 {
                    outcome,
                    evidence_digest: digest("identity-bound-owner-recovery"),
                }))
        }
    }

    async fn store() -> (tempfile::TempDir, AutomationStore) {
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
        (temp, store)
    }

    #[tokio::test]
    async fn named_agentd_host_resumes_wait_on_the_existing_durable_owner() {
        let (_temp, store) = store().await;
        let calls = Arc::new(AtomicUsize::new(0));
        let host = AgentdAutomationCircuitHostV1::new(
            AgentId::parse(AGENT_ID).expect("agent"),
            OWNER_ID,
            7,
            AgentdAutomationCircuitPortsV1::new(
                UnusedDecision,
                UnusedOrgan,
                PendingThenReady {
                    calls: Arc::clone(&calls),
                },
                RecoveryObservation { outcome: None },
            ),
        )
        .expect("host");
        let candidate = candidate();
        let event = event();
        let profile = CircuitRuntimeProfileV1::default();
        let first = host
            .execute(
                &store,
                "run-agentd-wait",
                THREAD_ID,
                &candidate,
                &event,
                &profile,
                &fence(),
                10,
            )
            .await
            .expect("first activation");
        assert_eq!(first.state, DurableCircuitRunStateV1::Waiting);
        let terminal = host
            .resume_wait(
                &store,
                "run-agentd-wait",
                &candidate,
                &event,
                &profile,
                &fence(),
                20,
            )
            .await
            .expect("resume");
        assert_eq!(terminal.state, DurableCircuitRunStateV1::Terminal);
        assert!(matches!(
            terminal.outcome,
            CircuitRuntimeOutcomeV1::Terminal(ref receipt)
                if receipt.state == CircuitTerminalStateV1::Succeeded
        ));
        assert_eq!(calls.load(Ordering::SeqCst), 2);
        store.close().await;
    }

    #[tokio::test]
    async fn owner_call_without_receipt_recovers_without_calling_the_owner_twice() {
        let (_temp, store) = store().await;
        let candidate = candidate();
        let event = event();
        let profile = CircuitRuntimeProfileV1::default();
        let recovered = run_neural_circuit_v1(
            &candidate,
            &event,
            &profile,
            &mut UnusedDecision,
            &mut UnusedOrgan,
            &mut ReadyWait,
            &codex_hepta_automation::NeverCancelled,
        )
        .expect("authoritative recovered outcome");
        let calls = Arc::new(AtomicUsize::new(0));
        let host = AgentdAutomationCircuitHostV1::new(
            AgentId::parse(AGENT_ID).expect("agent"),
            OWNER_ID,
            7,
            AgentdAutomationCircuitPortsV1::new(
                UnusedDecision,
                UnusedOrgan,
                LostAfterContact {
                    calls: Arc::clone(&calls),
                },
                RecoveryObservation {
                    outcome: Some(recovered),
                },
            ),
        )
        .expect("host");
        assert!(matches!(
            host.execute(
                &store,
                "run-owner-loss",
                THREAD_ID,
                &candidate,
                &event,
                &profile,
                &fence(),
                10,
            )
            .await,
            Err(AgentdAutomationCircuitError::Durable(
                DurableNeuralCircuitError::Runtime(NeuralCircuitRuntimeError::Port(_))
            ))
        ));
        assert_eq!(calls.load(Ordering::SeqCst), 1);
        let snapshot = host
            .snapshot(&store, "run-owner-loss")
            .await
            .expect("snapshot")
            .expect("run");
        assert_eq!(snapshot.state, DurableCircuitRunStateV1::Executing);
        let receipt = host
            .recover(
                &store,
                "run-owner-loss",
                &candidate,
                &event,
                &profile,
                &fence(),
                20,
            )
            .await
            .expect("recover")
            .expect("receipt");
        assert_eq!(receipt.status, DurableCircuitCommitStatusV1::Recovered);
        assert_eq!(receipt.state, DurableCircuitRunStateV1::Terminal);
        assert_eq!(calls.load(Ordering::SeqCst), 1);
        store.close().await;
    }
}
