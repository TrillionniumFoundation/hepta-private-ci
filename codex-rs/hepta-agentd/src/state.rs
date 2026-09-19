use std::fs::File;
use std::fs::OpenOptions;
use std::io::Read;
use std::io::Write;
use std::path::Path;
use std::path::PathBuf;
use std::sync::Arc;
use std::sync::Mutex;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_automation::AutomationStore;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_fleet::AgentLifecycle;
use codex_hepta_fleet::FleetRegistry;
use codex_hepta_memory::CognitiveStore;

use crate::AgentRunCoordinator;
use crate::AgentRunError;
use crate::AgentdError;
use crate::AgentdEventKind;
use crate::AgentdIdentity;
use crate::CancellationDisposition;
use crate::ContextAttachment;
use crate::EventBuffer;
use crate::RunReceipt;
use crate::RunRecoveryState;
use crate::RunSnapshot;
use crate::RuntimeComposition;

const RUN_STATE_FILE: &str = "agentd-run-lifecycle-v1.json";
const MAX_RUN_STATE_BYTES: u64 = 4 * 1024 * 1024;
const RUN_CANCELLATION_ACK_TIMEOUT_MS: u64 = 5_000;

#[path = "state_control.rs"]
mod control;

pub(crate) struct AgentdState {
    pub(crate) cognitive_ranker: std::sync::OnceLock<Arc<crate::PinnedCognitiveRanker>>,
    pub(crate) authbus: std::sync::OnceLock<Arc<crate::authbus_ingress::TextIngress>>,
    identity: AgentdIdentity,
    registry: FleetRegistry,
    runtime: Mutex<RuntimeState>,
    run_coordinator: Mutex<AgentRunCoordinator>,
    run_state_path: PathBuf,
    events: Mutex<EventBuffer>,
    automation: Mutex<Option<AutomationStore>>,
    cognitive: Mutex<Option<Arc<CognitiveStore>>>,
}

struct RuntimeState {
    current_generation: u64,
    lifecycle: AgentLifecycle,
    app_server_ready: bool,
    draining: bool,
    fenced: bool,
}

impl AgentdState {
    pub(crate) fn new(
        identity: AgentdIdentity,
        registry: FleetRegistry,
        event_capacity: usize,
    ) -> Result<Self, AgentdError> {
        let mut events = EventBuffer::new(event_capacity)?;
        events.push(AgentdEventKind::Bootstrapped);
        events.push(AgentdEventKind::Lifecycle {
            lifecycle: AgentLifecycle::Starting,
            generation: identity.spawn_generation,
        });

        let run_state_path = identity.run_root.join(RUN_STATE_FILE);
        let run_coordinator =
            load_run_coordinator(&run_state_path, run_composition(&identity), now_ms()?)?;

        Ok(Self {
            authbus: std::sync::OnceLock::new(),
            cognitive_ranker: std::sync::OnceLock::new(),
            runtime: Mutex::new(RuntimeState {
                current_generation: identity.spawn_generation,
                lifecycle: AgentLifecycle::Starting,
                app_server_ready: false,
                draining: false,
                fenced: false,
            }),
            run_coordinator: Mutex::new(run_coordinator),
            run_state_path,
            identity,
            registry,
            events: Mutex::new(events),
            automation: Mutex::new(None),
            cognitive: Mutex::new(None),
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
        *automation = Some(store);
        Ok(())
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
            if runtime.lifecycle == AgentLifecycle::Draining {
                runtime.draining = true;
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
            || runtime.draining
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
        if runtime.draining || runtime.fenced {
            return Ok(());
        }
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
        let mut runtime = self.runtime.lock().map_err(poisoned_state)?;
        runtime.app_server_ready = false;
        if !runtime.draining {
            runtime.draining = true;
            self.events
                .lock()
                .map_err(poisoned_state)?
                .push(AgentdEventKind::Draining);
        }
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

    pub(crate) fn is_draining(&self) -> Result<bool, AgentdError> {
        Ok(self.runtime.lock().map_err(poisoned_state)?.draining)
    }

    pub(crate) fn automation_admission_ready(&self) -> Result<bool, AgentdError> {
        self.refresh_generation()?;
        let runtime = self.runtime.lock().map_err(poisoned_state)?;
        Ok(runtime.lifecycle == AgentLifecycle::Running
            && runtime.app_server_ready
            && !runtime.draining
            && !runtime.fenced)
    }

    fn mutate_runs<T>(
        &self,
        operation: impl FnOnce(&mut AgentRunCoordinator) -> Result<T, AgentRunError>,
    ) -> Result<T, AgentdError> {
        let mut current = self.run_coordinator.lock().map_err(poisoned_state)?;
        let before = current.recovery_state();
        let mut next = current.clone();
        let result = operation(&mut next).map_err(run_error)?;
        if next.recovery_state() != before {
            // Durability is the linearization point for lifecycle metadata.
            // A failed write/sync/rename must never publish a state transition
            // that a restarted owner cannot recover.
            persist_run_state(&self.run_state_path, &next)?;
            *current = next;
        }
        Ok(result)
    }

    pub(crate) fn run_start(
        &self,
        now_ms: u64,
        snapshot: RunSnapshot,
    ) -> Result<RunReceipt, AgentdError> {
        self.mutate_runs(|coordinator| coordinator.start_run(now_ms, snapshot))
    }

    pub(crate) fn run_attach_context(
        &self,
        now_ms: u64,
        expected_revision: u64,
        attachment: ContextAttachment,
    ) -> Result<RunReceipt, AgentdError> {
        self.mutate_runs(|coordinator| {
            coordinator.attach_context(now_ms, expected_revision, attachment)
        })
    }

    pub(crate) fn run_mark_dispatched(
        &self,
        now_ms: u64,
        run_id: &str,
        expected_revision: u64,
    ) -> Result<RunReceipt, AgentdError> {
        self.mutate_runs(|coordinator| {
            coordinator.mark_dispatched(now_ms, run_id, expected_revision)
        })
    }

    pub(crate) fn run_cancel(
        &self,
        now_ms: u64,
        run_id: &str,
        expected_revision: u64,
        reason: &str,
    ) -> Result<(CancellationDisposition, RunReceipt), AgentdError> {
        self.mutate_runs(|coordinator| {
            coordinator.cancel_run(now_ms, run_id, expected_revision, reason)
        })
    }

    pub(crate) fn run_observe_terminal(
        &self,
        run_id: &str,
        expected_revision: u64,
        phase: crate::RunPhase,
        terminal_observed: bool,
    ) -> Result<RunReceipt, AgentdError> {
        self.mutate_runs(|coordinator| {
            coordinator.observe_terminal(run_id, expected_revision, phase, terminal_observed)
        })
    }

    pub(crate) fn run_status(&self, run_id: &str) -> Result<Option<RunReceipt>, AgentdError> {
        let coordinator = self.run_coordinator.lock().map_err(poisoned_state)?;
        Ok(coordinator.run(run_id))
    }

    pub(crate) fn run_remove_closed(
        &self,
        run_id: &str,
        expected_revision: u64,
    ) -> Result<RunReceipt, AgentdError> {
        self.mutate_runs(|coordinator| coordinator.remove_closed_run(run_id, expected_revision))
    }

    pub(crate) fn enforce_run_deadlines(&self, now_ms: u64) -> Result<usize, AgentdError> {
        self.mutate_runs(|coordinator| {
            coordinator
                .enforce_deadlines(now_ms)
                .map(|changed| changed.len())
        })
    }

    pub(crate) fn begin_run_drain(&self, reason: &str) -> Result<usize, AgentdError> {
        self.mutate_runs(|coordinator| coordinator.begin_drain(reason).map(|changed| changed.len()))
    }

    pub(crate) fn mark_unobserved_runs_indeterminate(&self) -> Result<usize, AgentdError> {
        self.mutate_runs(|coordinator| {
            coordinator
                .mark_unobserved_external_indeterminate()
                .map(|changed| changed.len())
        })
    }

    pub(crate) fn run_drain_complete(&self) -> Result<bool, AgentdError> {
        let coordinator = self.run_coordinator.lock().map_err(poisoned_state)?;
        Ok(coordinator.active_run_count() == 0)
    }

    pub(crate) fn pending_external_runs(&self) -> Result<usize, AgentdError> {
        let coordinator = self.run_coordinator.lock().map_err(poisoned_state)?;
        Ok(coordinator.pending_external_run_count())
    }
}

fn run_composition(identity: &AgentdIdentity) -> RuntimeComposition {
    let configuration_material = format!(
        "agentd-runtime-v2\0{}\0{}\0{}\0{}\0{:?}\0cancel_ack_ms={}",
        identity.agent_id,
        identity.workspace.display(),
        identity.home_root.display(),
        identity.run_root.display(),
        identity.resources,
        RUN_CANCELLATION_ACK_TIMEOUT_MS,
    );
    let ports_material = format!(
        "agentd-ports-v1\0{}\0{}",
        identity.control_socket.display(),
        identity.app_server_socket.display(),
    );
    RuntimeComposition {
        agent_id: identity.agent_id.to_string(),
        supervisor_generation: identity.spawn_generation,
        agentd_generation: identity.spawn_generation,
        configuration_digest: Sha256Digest::for_bytes(configuration_material.as_bytes())
            .as_str()
            .to_string(),
        ports_digest: Sha256Digest::for_bytes(ports_material.as_bytes())
            .as_str()
            .to_string(),
        cancellation_ack_timeout_ms: RUN_CANCELLATION_ACK_TIMEOUT_MS,
    }
}

fn load_run_coordinator(
    path: &Path,
    composition: RuntimeComposition,
    now_ms: u64,
) -> Result<AgentRunCoordinator, AgentdError> {
    let mut file = match File::open(path) {
        Ok(file) => file,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => {
            return AgentRunCoordinator::compose_runtime(composition).map_err(run_error);
        }
        Err(error) => return Err(error.into()),
    };
    let mut bytes = Vec::new();
    file.by_ref()
        .take(MAX_RUN_STATE_BYTES + 1)
        .read_to_end(&mut bytes)?;
    if bytes.len() as u64 > MAX_RUN_STATE_BYTES {
        return Err(AgentdError::Protocol(
            "agentd run lifecycle state exceeded its bounded size".to_string(),
        ));
    }
    let recovery: RunRecoveryState = serde_json::from_slice(&bytes)?;
    AgentRunCoordinator::restore_runtime(composition, recovery, now_ms).map_err(run_error)
}

fn persist_run_state(path: &Path, coordinator: &AgentRunCoordinator) -> Result<(), AgentdError> {
    let bytes = serde_json::to_vec(&coordinator.recovery_state())?;
    if bytes.len() as u64 > MAX_RUN_STATE_BYTES {
        return Err(AgentdError::Protocol(
            "agentd run lifecycle state exceeded its bounded size".to_string(),
        ));
    }
    let temporary = path.with_extension("json.tmp");
    let mut options = OpenOptions::new();
    options.create(true).truncate(true).write(true);
    let mut file = options.open(&temporary)?;
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        file.set_permissions(std::fs::Permissions::from_mode(0o600))?;
    }
    file.write_all(&bytes)?;
    file.sync_all()?;
    drop(file);
    std::fs::rename(&temporary, path)?;
    #[cfg(unix)]
    if let Some(parent) = path.parent() {
        File::open(parent)?.sync_all()?;
    }
    Ok(())
}

fn now_ms() -> Result<u64, AgentdError> {
    let millis = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|error| AgentdError::Protocol(error.to_string()))?
        .as_millis();
    u64::try_from(millis)
        .map_err(|_| AgentdError::Protocol("system clock exceeds u64 milliseconds".to_string()))
}

fn run_error(error: AgentRunError) -> AgentdError {
    AgentdError::Protocol(format!("run lifecycle: {error}"))
}

fn poisoned_state<T>(_error: std::sync::PoisonError<T>) -> AgentdError {
    AgentdError::Protocol("agentd control state mutex is poisoned".to_string())
}

#[cfg(test)]
#[path = "state_isolation_tests.rs"]
mod isolation_tests;
