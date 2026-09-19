use std::collections::BTreeSet;
use std::sync::Arc;
use std::sync::Mutex;

use codex_hepta_automation::AutomationStore;
use codex_hepta_control_plane::RuntimeModuleAbiV1;
use codex_hepta_control_plane::RuntimeModuleRegistryV1;
use codex_hepta_control_plane::RuntimeModuleStateClassV1;
use codex_hepta_control_plane::RuntimeTopologySnapshotV1;
use codex_hepta_fleet::AgentLifecycle;
use codex_hepta_fleet::FleetRegistry;
use codex_hepta_memory::CognitiveStore;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use crate::AgentdError;
use crate::AgentdEventKind;
use crate::AgentdIdentity;
use crate::AgentdOperationsHost;
use crate::CancellationDisposition;
use crate::ContextAttachment;
use crate::EventBuffer;
use crate::RunDispatchBinding;
use crate::RunExecutionBinding;
use crate::RunPhase;
use crate::RunReceipt;
use crate::RunSnapshot;
use crate::RunTerminalObservation;
use crate::run_ledger::RunLedger;

#[path = "state_control.rs"]
mod control;

pub(crate) struct AgentdState {
    pub(crate) cognitive_ranker: std::sync::OnceLock<Arc<crate::PinnedCognitiveRanker>>,
    pub(crate) authbus: std::sync::OnceLock<Arc<crate::authbus_ingress::TextIngress>>,
    pub(crate) objective_ingress:
        std::sync::OnceLock<Arc<crate::objective_ingress::ObjectiveIngressHost>>,
    identity: AgentdIdentity,
    registry: FleetRegistry,
    runtime: Mutex<RuntimeState>,
    runs: Mutex<RunLedger>,
    events: Mutex<EventBuffer>,
    automation: Mutex<Option<AutomationStore>>,
    automation_operations: std::sync::OnceLock<Arc<AgentdOperationsHost>>,
    cognitive: Mutex<Option<Arc<CognitiveStore>>>,
    runtime_modules: Mutex<RuntimeModuleRegistryV1>,
}

struct RuntimeState {
    current_generation: u64,
    lifecycle: AgentLifecycle,
    app_server_ready: bool,
    fenced: bool,
}

impl AgentdState {
    pub(crate) fn new(
        identity: AgentdIdentity,
        registry: FleetRegistry,
        event_capacity: usize,
    ) -> Result<Self, AgentdError> {
        let runs = RunLedger::open(&identity)?;
        let mut events = EventBuffer::new(event_capacity)?;
        events.push(AgentdEventKind::Bootstrapped);
        events.push(AgentdEventKind::Lifecycle {
            lifecycle: AgentLifecycle::Starting,
            generation: identity.spawn_generation,
        });
        Ok(Self {
            authbus: std::sync::OnceLock::new(),
            objective_ingress: std::sync::OnceLock::new(),
            cognitive_ranker: std::sync::OnceLock::new(),
            runtime: Mutex::new(RuntimeState {
                current_generation: identity.spawn_generation,
                lifecycle: AgentLifecycle::Starting,
                app_server_ready: false,
                fenced: false,
            }),
            identity,
            registry,
            runs: Mutex::new(runs),
            events: Mutex::new(events),
            automation: Mutex::new(None),
            automation_operations: std::sync::OnceLock::new(),
            cognitive: Mutex::new(None),
            runtime_modules: Mutex::new(RuntimeModuleRegistryV1::new()),
        })
    }

    pub(crate) fn attach_cognitive_store(
        &self,
        store: Arc<CognitiveStore>,
    ) -> Result<(), AgentdError> {
        if store.owner_agent_id() != &self.identity.agent_id {
            return Err(AgentdError::GenerationFenced(
                "cognitive store owner does not match agentd identity".to_string(),
            ));
        }
        let mut cognitive = self.cognitive.lock().map_err(poisoned_state)?;
        if cognitive.is_some() {
            return Err(AgentdError::Protocol(
                "cognitive store was attached more than once".to_string(),
            ));
        }
        self.activate_builtin_runtime_module(
            "cognitive.store",
            "cognitive-platform",
            RuntimeModuleStateClassV1::Stateful,
            &["knowledge_fact_ledger", "memory_ledger"],
            &[],
        )?;
        *cognitive = Some(store);
        Ok(())
    }

    pub(crate) fn attach_automation_store(
        &self,
        store: AutomationStore,
    ) -> Result<(), AgentdError> {
        if store.owner_agent_id() != &self.identity.agent_id {
            return Err(AgentdError::GenerationFenced(
                "automation store owner does not match agentd identity".to_string(),
            ));
        }
        let mut automation = self.automation.lock().map_err(poisoned_state)?;
        if automation.is_some() {
            return Err(AgentdError::Protocol(
                "automation store was attached more than once".to_string(),
            ));
        }
        self.activate_builtin_runtime_module(
            "automation.taskflow",
            "automation-platform",
            RuntimeModuleStateClassV1::Stateful,
            &["automation_occurrence", "automation_schedule"],
            &[],
        )?;
        *automation = Some(store);
        Ok(())
    }

    pub(crate) fn attach_automation_operations(
        &self,
        host: Arc<AgentdOperationsHost>,
    ) -> Result<(), AgentdError> {
        if host.generation().get() != self.identity.spawn_generation {
            return Err(AgentdError::GenerationFenced(
                "automation operations host generation does not match agentd process generation"
                    .to_string(),
            ));
        }
        self.activate_builtin_runtime_module(
            "kernel.operations",
            "durability-kernel",
            RuntimeModuleStateClassV1::Stateful,
            &["cross_owner_outbox", "operation_ledger"],
            &["external_effect_dispatch"],
        )?;
        self.automation_operations.set(host).map_err(|_| {
            AgentdError::Protocol(
                "automation operations host was attached more than once".to_string(),
            )
        })
    }

    pub(crate) fn attach_authbus(
        &self,
        host: Arc<crate::authbus_ingress::TextIngress>,
    ) -> Result<(), AgentdError> {
        if self.authbus.get().is_some() {
            return Err(AgentdError::Protocol("AuthBus host already attached".to_string()));
        }
        self.activate_builtin_runtime_module(
            "auth.authbus",
            "identity-access",
            RuntimeModuleStateClassV1::Stateful,
            &[],
            &[],
        )?;
        self.authbus
            .set(host)
            .map_err(|_| AgentdError::Protocol("AuthBus host already attached".to_string()))
    }

    pub(crate) fn attach_objective_ingress(
        &self,
        host: Arc<crate::objective_ingress::ObjectiveIngressHost>,
    ) -> Result<(), AgentdError> {
        if self.objective_ingress.get().is_some() {
            return Err(AgentdError::Protocol(
                "Objective ingress host already attached".to_string(),
            ));
        }
        self.activate_builtin_runtime_module(
            "objective.compiler",
            "intelligence-platform",
            RuntimeModuleStateClassV1::Stateless,
            &[],
            &[],
        )?;
        self.objective_ingress.set(host).map_err(|_| {
            AgentdError::Protocol("Objective ingress host already attached".to_string())
        })
    }

    pub(crate) fn runtime_topology_snapshot(
        &self,
    ) -> Result<RuntimeTopologySnapshotV1, AgentdError> {
        Ok(self
            .runtime_modules
            .lock()
            .map_err(poisoned_state)?
            .snapshot())
    }

    fn activate_builtin_runtime_module(
        &self,
        module_id: &str,
        owner_id: &str,
        state_class: RuntimeModuleStateClassV1,
        authoritative_domains: &[&str],
        effect_scope: &[&str],
    ) -> Result<(), AgentdError> {
        let module_id = StableId::new(module_id)
            .map_err(|error| AgentdError::Protocol(error.to_string()))?;
        let owner_id = StableId::new(owner_id)
            .map_err(|error| AgentdError::Protocol(error.to_string()))?;
        let generation = Generation::new(self.identity.spawn_generation)
            .map_err(|error| AgentdError::Protocol(error.to_string()))?;
        let authoritative_domains = authoritative_domains
            .iter()
            .map(|value| StableId::new(*value).map_err(|error| AgentdError::Protocol(error.to_string())))
            .collect::<Result<BTreeSet<_>, _>>()?;
        let effect_scope = effect_scope
            .iter()
            .map(|value| StableId::new(*value).map_err(|error| AgentdError::Protocol(error.to_string())))
            .collect::<Result<BTreeSet<_>, _>>()?;
        let implementation_digest = Digest32::of_bytes(
            format!("hepta.compiled-runtime-module.v1:{}", module_id.as_str()).as_bytes(),
        );
        let abi = RuntimeModuleAbiV1 {
            module_id: module_id.clone(),
            owner_id,
            generation,
            implementation_digest,
            predecessor_generation: None,
            rollback_predecessor_digest: Digest32::ZERO,
            state_class,
            input_ports: Vec::new(),
            output_ports: Vec::new(),
            authoritative_domains,
            effect_scope,
        };
        let mut modules = self.runtime_modules.lock().map_err(poisoned_state)?;
        modules
            .register_candidate(abi)
            .map_err(|error| AgentdError::Protocol(format!("runtime module registration failed: {error}")))?;
        modules
            .activate_bootstrap(&module_id, generation)
            .map_err(|error| AgentdError::Protocol(format!("runtime module activation failed: {error}")))?;
        Ok(())
    }

    pub(crate) fn automation_operations(&self) -> Option<Arc<AgentdOperationsHost>> {
        self.automation_operations.get().cloned()
    }

    pub(crate) fn mark_automation_unavailable(&self) -> Result<(), AgentdError> {
        self.automation.lock().map_err(poisoned_state)?.take();
        Ok(())
    }

    pub(crate) fn automation_is_available(&self) -> Result<bool, AgentdError> {
        Ok(self.automation.lock().map_err(poisoned_state)?.is_some())
    }

    pub(crate) fn identity(&self) -> &AgentdIdentity {
        &self.identity
    }

    pub(crate) fn refresh_generation(&self) -> Result<(), AgentdError> {
        // Registration/startup retains fleet-wide validation. Serving an
        // already admitted generation must not scan or depend on peer stores.
        let record = self
            .registry
            .load_agent(&self.identity.agent_id)
            .map_err(|_| {
                self.mark_fenced();
                AgentdError::GenerationFenced(format!(
                    "agent {} control record is unavailable or invalid",
                    self.identity.agent_id
                ))
            })?;
        if record.layout.home_root() != self.identity.home_root
            || record.layout.run_root() != self.identity.run_root
            || record.layout.cognitive_root() != self.identity.layout.cognitive_root()
            || record.layout.automation_root() != self.identity.layout.automation_root()
            || record.manifest.workspace.as_path() != self.identity.workspace
            || record.manifest.resources != self.identity.resources
        {
            return Err(AgentdError::GenerationFenced(
                "registered agent roots or resource budget changed while agentd was running"
                    .to_string(),
            ));
        }
        let distance = record
            .lifecycle
            .generation
            .checked_sub(self.identity.spawn_generation);
        let accepted = matches!(
            (record.lifecycle.lifecycle, distance),
            (AgentLifecycle::Starting, Some(0))
                | (AgentLifecycle::Running, Some(1))
                | (AgentLifecycle::Draining, Some(2))
        );
        if !accepted {
            return Err(AgentdError::GenerationFenced(format!(
                "agent {} spawn generation {} cannot serve {:?} generation {}",
                self.identity.agent_id,
                self.identity.spawn_generation,
                record.lifecycle.lifecycle,
                record.lifecycle.generation
            )));
        }

        let mut runtime = self.runtime.lock().map_err(poisoned_state)?;
        if runtime.current_generation != record.lifecycle.generation
            || runtime.lifecycle != record.lifecycle.lifecycle
        {
            runtime.current_generation = record.lifecycle.generation;
            runtime.lifecycle = record.lifecycle.lifecycle;
            if runtime.lifecycle != AgentLifecycle::Running {
                runtime.app_server_ready = false;
            }
            self.events
                .lock()
                .map_err(poisoned_state)?
                .push(AgentdEventKind::Lifecycle {
                    lifecycle: record.lifecycle.lifecycle,
                    generation: record.lifecycle.generation,
                });
        }
        Ok(())
    }

    /// Return the current fleet lifecycle generation after refreshing the
    /// process fence. This is distinct from `identity.spawn_generation`: the
    /// latter identifies the process launch, while this value is the current
    /// supervisor lifecycle generation used as a host-bound epoch witness.
    #[cfg(feature = "qualification-cognitive-write")]
    pub(crate) fn qualification_turn_authority(&self) -> Result<u64, AgentdError> {
        self.refresh_generation()?;
        let runtime = self.runtime.lock().map_err(poisoned_state)?;
        if runtime.lifecycle != AgentLifecycle::Running
            || !runtime.app_server_ready
            || runtime.fenced
        {
            return Err(AgentdError::GenerationFenced(
                "agentd qualification writer is unavailable until the running App Server is ready"
                    .to_string(),
            ));
        }
        Ok(runtime.current_generation)
    }

    pub(crate) fn mark_app_server_ready(&self) -> Result<(), AgentdError> {
        let mut runtime = self.runtime.lock().map_err(poisoned_state)?;
        if !runtime.app_server_ready {
            runtime.app_server_ready = true;
            self.events
                .lock()
                .map_err(poisoned_state)?
                .push(AgentdEventKind::AppServerReady);
        }
        Ok(())
    }

    pub(crate) fn mark_draining(&self) -> Result<(), AgentdError> {
        // Keep the runtime guard until the durable run ledger has installed
        // its drain fence. A concurrent admission that already acquired the
        // same runtime guard linearizes before drain; every later admission
        // observes app_server_ready=false.
        let mut runtime = self.runtime.lock().map_err(poisoned_state)?;
        runtime.app_server_ready = false;
        self.runs
            .lock()
            .map_err(poisoned_state)?
            .transact(|coordinator| {
                coordinator.begin_drain();
                Ok(())
            })?;
        drop(runtime);
        self.events
            .lock()
            .map_err(poisoned_state)?
            .push(AgentdEventKind::Draining);
        Ok(())
    }

    pub(crate) fn mark_fenced(&self) {
        if let Ok(mut runtime) = self.runtime.lock() {
            runtime.app_server_ready = false;
            runtime.fenced = true;
        }
        if let Ok(mut events) = self.events.lock() {
            events.push(AgentdEventKind::GenerationFenced);
        }
    }

    pub(crate) fn is_fenced(&self) -> Result<bool, AgentdError> {
        Ok(self.runtime.lock().map_err(poisoned_state)?.fenced)
    }

    pub(crate) fn automation_admission_ready(&self) -> Result<bool, AgentdError> {
        self.refresh_generation()?;
        let runtime = self.runtime.lock().map_err(poisoned_state)?;
        Ok(runtime.lifecycle == AgentLifecycle::Running
            && runtime.app_server_ready
            && !runtime.fenced)
    }

    /// Rehydrate a durable product RunStart while Agentd is still in its
    /// non-serving startup phase. This is the only bypass around the normal
    /// Running+ready admission guard and exists solely to migrate/reconcile
    /// owner-durable RunStart facts into the single Agentd lifecycle ledger.
    pub(crate) fn recover_run_start(
        &self,
        now_ms: u64,
        snapshot: RunSnapshot,
    ) -> Result<RunReceipt, AgentdError> {
        self.refresh_generation()?;
        {
            let runtime = self.runtime.lock().map_err(poisoned_state)?;
            if runtime.lifecycle != AgentLifecycle::Starting
                || runtime.app_server_ready
                || runtime.fenced
            {
                return Err(AgentdError::Protocol(
                    "run recovery is allowed only before Agentd begins serving".to_string(),
                ));
            }
        }
        self.runs
            .lock()
            .map_err(poisoned_state)?
            .transact(|coordinator| coordinator.start_run(now_ms, snapshot))
    }

    pub(crate) fn run_start(
        &self,
        now_ms: u64,
        snapshot: RunSnapshot,
    ) -> Result<RunReceipt, AgentdError> {
        let runtime = self.run_execution_guard()?;
        if snapshot.authority_epoch != runtime.current_generation {
            return Err(AgentdError::GenerationFenced(format!(
                "run authority epoch {} does not match current Agentd lifecycle generation {}",
                snapshot.authority_epoch, runtime.current_generation
            )));
        }
        self.runs
            .lock()
            .map_err(poisoned_state)?
            .transact(|coordinator| coordinator.start_run(now_ms, snapshot))
    }

    pub(crate) fn run_attach_context(
        &self,
        now_ms: u64,
        expected_revision: u64,
        attachment: ContextAttachment,
    ) -> Result<RunReceipt, AgentdError> {
        let _runtime = self.run_execution_guard()?;
        self.runs
            .lock()
            .map_err(poisoned_state)?
            .transact(|coordinator| {
                coordinator.attach_context(now_ms, expected_revision, attachment)
            })
    }

    pub(crate) fn run_mark_dispatched(
        &self,
        now_ms: u64,
        run_id: &str,
        expected_revision: u64,
        binding: RunDispatchBinding,
    ) -> Result<RunReceipt, AgentdError> {
        let _runtime = self.run_execution_guard()?;
        self.runs
            .lock()
            .map_err(poisoned_state)?
            .transact(|coordinator| {
                coordinator.mark_dispatched(now_ms, run_id, expected_revision, binding)
            })
    }

    pub(crate) fn run_bind_execution(
        &self,
        run_id: &str,
        expected_revision: u64,
        binding: RunExecutionBinding,
    ) -> Result<RunReceipt, AgentdError> {
        self.require_run_reconciliation_ready()?;
        self.runs
            .lock()
            .map_err(poisoned_state)?
            .transact(|coordinator| coordinator.bind_execution(run_id, expected_revision, binding))
    }

    pub(crate) fn run_execution_binding(
        &self,
        run_id: &str,
    ) -> Result<Option<RunExecutionBinding>, AgentdError> {
        self.refresh_generation()?;
        Ok(self
            .runs
            .lock()
            .map_err(poisoned_state)?
            .coordinator()
            .execution_binding(run_id))
    }

    pub(crate) fn run_cancel(
        &self,
        now_ms: u64,
        run_id: &str,
        expected_revision: u64,
        reason: String,
    ) -> Result<(CancellationDisposition, RunReceipt), AgentdError> {
        self.require_run_reconciliation_ready()?;
        self.runs
            .lock()
            .map_err(poisoned_state)?
            .transact(|coordinator| {
                coordinator.cancel_run(now_ms, run_id, expected_revision, reason)
            })
    }

    pub(crate) fn run_observe_terminal(
        &self,
        run_id: &str,
        expected_revision: u64,
        phase: RunPhase,
        observation: Option<RunTerminalObservation>,
    ) -> Result<RunReceipt, AgentdError> {
        self.require_run_reconciliation_ready()?;
        self.runs
            .lock()
            .map_err(poisoned_state)?
            .transact(|coordinator| {
                coordinator.observe_terminal(run_id, expected_revision, phase, observation)
            })
    }

    pub(crate) fn run_status(&self, run_id: &str) -> Result<Option<RunReceipt>, AgentdError> {
        self.refresh_generation()?;
        Ok(self
            .runs
            .lock()
            .map_err(poisoned_state)?
            .coordinator()
            .run(run_id))
    }

    pub(crate) fn run_remove_closed(
        &self,
        run_id: &str,
        expected_revision: u64,
    ) -> Result<RunReceipt, AgentdError> {
        self.require_run_reconciliation_ready()?;
        self.runs
            .lock()
            .map_err(poisoned_state)?
            .transact(|coordinator| coordinator.remove_closed_run(run_id, expected_revision))
    }

    pub(crate) fn expire_run_deadlines(&self, now_ms: u64) -> Result<Vec<RunReceipt>, AgentdError> {
        self.runs
            .lock()
            .map_err(poisoned_state)?
            .transact(|coordinator| coordinator.expire_deadlines(now_ms))
    }

    pub(crate) fn active_run_count(&self) -> Result<usize, AgentdError> {
        Ok(self
            .runs
            .lock()
            .map_err(poisoned_state)?
            .coordinator()
            .active_run_count())
    }

    pub(crate) fn mark_unfinished_runs_for_shutdown(&self) -> Result<Vec<RunReceipt>, AgentdError> {
        self.runs
            .lock()
            .map_err(poisoned_state)?
            .transact(|coordinator| coordinator.mark_unfinished_for_shutdown())
    }

    fn run_execution_guard(&self) -> Result<std::sync::MutexGuard<'_, RuntimeState>, AgentdError> {
        self.refresh_generation()?;
        let runtime = self.runtime.lock().map_err(poisoned_state)?;
        if runtime.lifecycle != AgentLifecycle::Running
            || !runtime.app_server_ready
            || runtime.fenced
        {
            return Err(AgentdError::Protocol(
                "run lifecycle admission is unavailable unless this generation is running and ready"
                    .to_string(),
            ));
        }
        Ok(runtime)
    }

    fn require_run_reconciliation_ready(&self) -> Result<(), AgentdError> {
        self.refresh_generation()?;
        let runtime = self.runtime.lock().map_err(poisoned_state)?;
        if runtime.fenced
            || !matches!(
                runtime.lifecycle,
                AgentLifecycle::Running | AgentLifecycle::Draining
            )
        {
            return Err(AgentdError::Protocol(
                "run lifecycle reconciliation requires a running or draining unfenced generation"
                    .to_string(),
            ));
        }
        Ok(())
    }
}

fn poisoned_state<T>(_error: std::sync::PoisonError<T>) -> AgentdError {
    AgentdError::Protocol("agentd control state mutex is poisoned".to_string())
}

#[cfg(test)]
#[path = "state_isolation_tests.rs"]
mod isolation_tests;
