// Original lifecycle/storage owner shared by the Full and Native source roots.
use crate::AgentdError;
use crate::AgentdEventKind;
use crate::AgentdIdentity;
use crate::EventBuffer;
use codex_hepta_agent_protocol::DrainSnapshot;
use codex_hepta_cognitive_store::DurableCognitiveStore as CognitiveStore;
use codex_hepta_fleet::AgentLifecycle;
use codex_hepta_fleet::FleetRegistry;
use std::sync::Arc;
use std::sync::Mutex;

#[cfg(target_os = "linux")]
#[path = "native_cpu_state.rs"]
mod native_cpu;

/// One original lifecycle/storage core, composed with its actual process activities.
/// The control peer cannot select a runtime profile.
pub(crate) struct AgentdStateCore<P: AgentdRuntimeProfile> {
    #[cfg(target_os = "linux")]
    pub(crate) native_cpu_root: std::sync::OnceLock<Arc<crate::AgentdRootAuthoritySession>>,
    #[cfg(target_os = "linux")]
    pub(crate) native_cpu_ingress:
        std::sync::OnceLock<Arc<crate::native_cpu_ingress::NativeCpuIngress>>,
    pub(crate) production_operations: std::sync::OnceLock<Arc<crate::AgentdProductionWriterHost>>,
    identity: AgentdIdentity,
    registry: FleetRegistry,
    runtime: Mutex<RuntimeState>,
    events: Mutex<EventBuffer>,
    cognitive: Mutex<Option<Arc<CognitiveStore>>>,
    owners: P,
}

impl<P: AgentdRuntimeProfile> std::ops::Deref for AgentdStateCore<P> {
    type Target = P;
    fn deref(&self) -> &Self::Target {
        &self.owners
    }
}

impl<P: AgentdRuntimeProfile> std::ops::DerefMut for AgentdStateCore<P> {
    fn deref_mut(&mut self) -> &mut Self::Target {
        &mut self.owners
    }
}

pub(crate) trait AgentdRuntimeProfile: Send + Sync + 'static {
    fn begin_drain(&self, reason: &str) -> Result<(), AgentdError>;
    fn request_turn_drain(&self);
    fn running_turns(&self) -> Result<u32, AgentdError>;
    fn turns_drained(&self) -> bool;
    fn fence_turns(&self);
}

/// CPU work belongs to the original production writer. This process owns no
/// assistant-turn admission API, prompt pipeline or App Server owner.
#[cfg(target_os = "linux")]
pub(crate) struct NativeCpuRuntimeOwners;
#[cfg(target_os = "linux")]
impl AgentdRuntimeProfile for NativeCpuRuntimeOwners {
    fn begin_drain(&self, _reason: &str) -> Result<(), AgentdError> {
        Ok(())
    }
    fn request_turn_drain(&self) {}
    fn running_turns(&self) -> Result<u32, AgentdError> {
        Ok(0)
    }
    fn turns_drained(&self) -> bool {
        true
    }
    fn fence_turns(&self) {}
}

struct RuntimeState {
    current_generation: u64,
    lifecycle: AgentLifecycle,
    app_server_ready: bool,
    notes_organ_ready: bool,
    native_cpu_ready: bool,
    critical_stores_ready: bool,
    revocation_ready: bool,
    required_ports_ready: bool,
    admission_open: bool,
    fenced: bool,
}

impl<P: AgentdRuntimeProfile> AgentdStateCore<P> {
    fn with_runtime_owners(
        identity: AgentdIdentity,
        registry: FleetRegistry,
        event_capacity: usize,
        owners: P,
    ) -> Result<Self, AgentdError> {
        let mut events = EventBuffer::new(event_capacity)?;
        events.push(AgentdEventKind::Bootstrapped);
        events.push(AgentdEventKind::Lifecycle {
            lifecycle: AgentLifecycle::Starting,
            generation: identity.spawn_generation,
        });
        Ok(Self {
            #[cfg(target_os = "linux")]
            native_cpu_root: std::sync::OnceLock::new(),
            #[cfg(target_os = "linux")]
            native_cpu_ingress: std::sync::OnceLock::new(),
            production_operations: std::sync::OnceLock::new(),
            runtime: Mutex::new(RuntimeState {
                current_generation: identity.spawn_generation,
                lifecycle: AgentLifecycle::Starting,
                app_server_ready: false,
                notes_organ_ready: false,
                native_cpu_ready: false,
                critical_stores_ready: false,
                revocation_ready: false,
                required_ports_ready: false,
                admission_open: false,
                fenced: false,
            }),
            identity,
            registry,
            events: Mutex::new(events),
            cognitive: Mutex::new(None),
            owners,
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

    pub(crate) fn attach_production_operations(
        &self,
        host: Arc<crate::AgentdProductionWriterHost>,
    ) -> Result<(), AgentdError> {
        if host.writer().authority().agent_id != self.identity.agent_id {
            return Err(AgentdError::GenerationFenced(
                "production operation host authority does not match agentd identity".to_string(),
            ));
        }
        self.production_operations.set(host).map_err(|_| {
            AgentdError::Protocol(
                "production operation host was attached more than once".to_string(),
            )
        })
    }

    pub(crate) fn identity(&self) -> &AgentdIdentity {
        &self.identity
    }

    pub(crate) fn current_generation(&self) -> Result<u64, AgentdError> {
        self.refresh_generation()?;
        Ok(self
            .runtime
            .lock()
            .map_err(poisoned_state)?
            .current_generation)
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
                runtime.admission_open = false;
            }
            if matches!(
                runtime.lifecycle,
                AgentLifecycle::Draining | AgentLifecycle::Stopped | AgentLifecycle::Failed
            ) {
                runtime.app_server_ready = false;
                runtime.notes_organ_ready = false;
                runtime.native_cpu_ready = false;
                runtime.required_ports_ready = false;
            }
            if runtime.lifecycle == AgentLifecycle::Running
                && (runtime.app_server_ready
                    || runtime.notes_organ_ready
                    || runtime.native_cpu_ready)
                && runtime.critical_stores_ready
                && runtime.revocation_ready
                && runtime.required_ports_ready
                && !runtime.fenced
            {
                runtime.admission_open = true;
            }
            self.events
                .lock()
                .map_err(poisoned_state)?
                .push(AgentdEventKind::Lifecycle {
                    lifecycle: record.lifecycle.lifecycle,
                    generation: record.lifecycle.generation,
                });
            if runtime.lifecycle == AgentLifecycle::Draining {
                self.owners.begin_drain("supervisor_draining")?;
            }
        }
        Ok(())
    }

    /// Freeze owner-local startup prerequisites under this generation. The
    /// default Agentd composition has zero production effect authority, so a
    /// current zero-authority revocation baseline is sufficient here; any
    /// effect-authorized composition must replace it before opening admission.
    pub(crate) fn mark_runtime_prerequisites_ready(&self) -> Result<(), AgentdError> {
        let critical_stores_ready = self.cognitive.lock().map_err(poisoned_state)?.is_some();
        let mut runtime = self.runtime.lock().map_err(poisoned_state)?;
        runtime.critical_stores_ready = critical_stores_ready;
        runtime.revocation_ready = true;
        Ok(())
    }

    pub(crate) fn mark_draining(&self) -> Result<(), AgentdError> {
        let mut runtime = self.runtime.lock().map_err(poisoned_state)?;
        runtime.app_server_ready = false;
        runtime.notes_organ_ready = false;
        runtime.native_cpu_ready = false;
        runtime.required_ports_ready = false;
        runtime.admission_open = false;
        self.owners.request_turn_drain();
        self.events
            .lock()
            .map_err(poisoned_state)?
            .push(AgentdEventKind::Draining);
        drop(runtime);
        self.owners.begin_drain("agentd_shutdown")?;
        Ok(())
    }

    pub(crate) fn drain_snapshot(
        &self,
        automation_blockers: u32,
    ) -> Result<DrainSnapshot, AgentdError> {
        self.refresh_generation()?;
        let runtime = self.runtime.lock().map_err(poisoned_state)?;
        let running_turns = self.owners.running_turns()?;
        Ok(DrainSnapshot {
            admission_closed: runtime.lifecycle == AgentLifecycle::Draining
                && !runtime.app_server_ready
                && !runtime.fenced,
            running_turns,
            drained: runtime.lifecycle == AgentLifecycle::Draining
                && !runtime.fenced
                && self.owners.turns_drained()
                && running_turns == 0
                && automation_blockers == 0,
            lifecycle: runtime.lifecycle,
            fenced: runtime.fenced,
        })
    }

    pub(crate) fn mark_fenced(&self) {
        if let Ok(mut runtime) = self.runtime.lock() {
            runtime.app_server_ready = false;
            runtime.notes_organ_ready = false;
            runtime.native_cpu_ready = false;
            runtime.required_ports_ready = false;
            runtime.admission_open = false;
            runtime.fenced = true;
        }
        if let Ok(mut events) = self.events.lock() {
            events.push(AgentdEventKind::GenerationFenced);
        }
        self.owners.fence_turns();
    }

    pub(crate) fn is_fenced(&self) -> Result<bool, AgentdError> {
        Ok(self.runtime.lock().map_err(poisoned_state)?.fenced)
    }
}
#[cfg(target_os = "linux")]
impl AgentdStateCore<NativeCpuRuntimeOwners> {
    pub(crate) fn new_native_cpu(
        identity: AgentdIdentity,
        registry: FleetRegistry,
        event_capacity: usize,
    ) -> Result<Self, AgentdError> {
        Self::with_runtime_owners(identity, registry, event_capacity, NativeCpuRuntimeOwners)
    }
}

fn poisoned_state<T>(_error: std::sync::PoisonError<T>) -> AgentdError {
    AgentdError::Protocol("agentd control state mutex is poisoned".to_string())
}
